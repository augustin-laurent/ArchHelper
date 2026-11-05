"""Read-only Linux block discovery. No archinstall import, mounts or writes here."""
import hashlib
import json
from pathlib import Path
import re
import stat
import subprocess

from .i18n import t
from .plan import Disk, Partition, MIB, PlanError


def command(*args):
    return subprocess.check_output(args, text=True)


def descendants(node):
    yield node
    for child in node.get("children", []):
        yield from descendants(child)


def blocked_reasons(node):
    reasons = []
    if node.get("ro"):
        reasons.append(t("disk.readonly"))
    for child in descendants(node):
        for mount in child.get("mountpoints") or []:
            if mount:
                reasons.append(t("disk.usedBy") % (child["path"], mount))
        name = Path(child["path"]).name
        if any((Path("/sys/class/block") / name / "holders").glob("*")):
            reasons.append(t("disk.holder") % child["path"])
        if child is not node and child.get("type") not in ("part",):
            reasons.append(t("disk.active") % (child["path"], child.get("type")))
    return sorted(set(reasons))


def discover(*, loop_backing=None):
    import parted
    data = json.loads(command("lsblk", "--json", "--bytes", "--paths", "--output",
                              "PATH,TYPE,SIZE,LOG-SEC,MODEL,SERIAL,WWN,PTTYPE,PTUUID,FSTYPE,UUID,PARTUUID,RO,MOUNTPOINTS"))
    result = []
    for n in data["blockdevices"]:
        path = n["path"]
        if n["type"] != "disk":
            if not loop_backing or n["type"] != "loop":
                continue
            actual = command("losetup", "--noheadings", "--output", "BACK-FILE", path).strip()
            if Path(actual).resolve() != Path(loop_backing).resolve():
                continue
        if not re.fullmatch(r"/dev/(?:sd[a-z]+|vd[a-z]+|nvme\d+n\d+|mmcblk\d+|loop\d+)", path):
            continue
        node_stat = Path(path).stat()
        if not stat.S_ISBLK(node_stat.st_mode):
            continue
        dev = parted.getDevice(path)
        sector = dev.sectorSize
        parts, free = [], []
        table = n.get("pttype") or ""
        if table:
            disk = parted.Disk(dev)
            infos = {c["path"]: c for c in descendants(n)}
            for p in disk.partitions:
                if p.number < 1:
                    continue
                info = infos.get(p.path, {})
                fs = info.get("fstype") or (p.fileSystem.type if p.fileSystem else "")
                parts.append(Partition(p.geometry.start * sector, p.geometry.length * sector,
                                       fs=fs, path=p.path, uuid=info.get("uuid") or "",
                                       partuuid=info.get("partuuid") or "",
                                       esp=bool(p.getFlag(parted.PARTITION_ESP))))
            free = [(g.start * sector, g.length * sector) for g in disk.getFreeSpaceRegions()
                    if g.length * sector >= MIB]
        else:
            free = [(MIB, dev.length * sector - 2 * MIB)]
        identity = json.dumps({k: n.get(k) for k in ("serial", "wwn", "ptuuid")}, sort_keys=True)
        # udev may change node permissions/ctime during a read-only probe.
        identity += f";rdev={node_stat.st_rdev};inode={node_stat.st_ino};size={n['size']};sector={sector}"
        result.append(Disk(path, int(n["size"]), sector, identity, (n.get("model") or t("disk.virtual")).strip(),
                           table, parts, free, blocked_reasons(n)))
    return result


def revalidate(plan, *, loop_backing=None):
    current = next((d for d in discover(loop_backing=loop_backing) if d.path == plan.disk.path), None)
    if not current or current.blocked or current.fingerprint != plan.disk.fingerprint:
        raise PlanError(t("disk.changed"))
    plan.validate()
    return current
