"""Destructive integration tests exclusively on fresh loop files in the builder.

Run in either build chroot or the disposable live VM: PYTHONPATH=... python this-file.
Does not accept a block-device argument. Every loop device is allocated here.
"""
import copy
import hashlib
import json
import os
import platform
from pathlib import Path
import subprocess
import tempfile
import time

from v8_installer import adapter
from v8_installer.disks import discover, revalidate
from v8_installer.plan import automatic, GIB, MIB, Partition, PlanError

BASE = Path("/build/v8-installer-tests")
assert os.geteuid() == 0 and (Path("/input/work/omarchy").is_dir() or Path("/run/archiso").is_dir())
BASE.mkdir(parents=True, exist_ok=True)


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while data := f.read(MIB):
            h.update(data)
    return h.hexdigest()


def attach(file, size):
    with file.open("xb") as f:
        f.truncate(size)
    dev = run("losetup", "--find", "--show", "--partscan", str(file))
    assert dev.startswith("/dev/loop")
    backing = run("losetup", "--noheadings", "--output", "BACK-FILE", dev)
    return dev, backing


def scan(backing, dev):
    run("udevadm", "settle")
    return next(d for d in discover(loop_backing=backing) if d.path == dev)


def execute_layout(plan, backing):
    plan.validate()
    revalidate(plan, loop_backing=backing)
    config = adapter.layout(plan, "test-luks-password" if plan.luks else "")
    revalidate(plan, loop_backing=backing)
    adapter.format_disk(config)
    return config


results = []
with tempfile.TemporaryDirectory(prefix="run-", dir=BASE) as folder:
    folder = Path(folder)
    neighbor, _ = attach(folder / "neighbor.img", 16 * MIB)
    subprocess.run(["dd", "if=/dev/urandom", f"of={neighbor}", "bs=1M", "count=16", "status=none"], check=True)
    neighbor_hash = digest(neighbor)
    devices = [neighbor]
    try:
        for mode in ("wipe", "alongside", "manual", "manual-shared-esp", "luks"):
            dev, backing = attach(folder / (mode + ".img"), 40 * GIB)
            devices.append(dev)
            before = {}
            if mode in ("alongside", "manual"):
                run("parted", "-s", dev, "mklabel", "gpt", "mkpart", "data1", "ext4", "1MiB", "129MiB",
                    "mkpart", "temporary", "ext4", "256MiB", "384MiB", "mkpart", "data3", "ext4", "512MiB", "640MiB", "rm", "2")
                run("udevadm", "settle")
                for n in (1, 3):
                    run("mkfs.ext4", "-F", f"{dev}p{n}")
                    before[f"{dev}p{n}"] = digest(f"{dev}p{n}")
            if mode == "manual-shared-esp":
                run("parted", "-s", dev, "mklabel", "gpt", "mkpart", "esp", "fat32", "1MiB", "4097MiB",
                    "set", "1", "esp", "on", "mkpart", "old-root", "ext4", "4097MiB", "100%")
                run("udevadm", "settle")
                run("mkfs.fat", "-F32", dev + "p1")
                run("mkfs.ext4", "-F", dev + "p2")
                run("mmd", "-i", dev + "p1", "::/EFI", "::/EFI/Microsoft")
                sentinel = folder / "microsoft-sentinel"
                sentinel.write_text("existing OS must survive\n")
                run("mcopy", "-i", dev + "p1", str(sentinel), "::/EFI/Microsoft/keep.txt")
                before[dev + "p1"] = digest(dev + "p1")
            disk = scan(backing, dev)
            plan = automatic(disk, "alongside" if mode in ("alongside", "manual") else "wipe", platform.machine())
            if mode == "manual":
                plan.mode = "manual"
                # Explicitly delete data3 and create an unmounted ext4 replacement.
                old = next(p for p in plan.partitions if p.path.endswith("p3"))
                old.action = "delete"
                plan.partitions.append(Partition(old.start, old.size, "create", "ext4"))
                before.pop(old.path)
            if mode == "manual-shared-esp":
                plan.mode = "manual"
                plan.partitions = copy.deepcopy(disk.partitions)
                plan.partitions[0].mount = "/efi"
                plan.partitions[1].mount = "/"
                plan.partitions[1].fs = "btrfs"
                plan.partitions[1].action = "format"
            if mode == "luks":
                plan.luks = True
            config = execute_layout(plan, backing)
            root = next(p for p in config.device_modifications[0].partitions if p.is_root())
            assert str(root.dev_path).startswith(dev + "p") and root.partuuid
            if mode == "alongside":
                assert str(root.dev_path) == dev + "p4", root.dev_path
            inst = adapter.installer(Path("/mnt/v8-layout-test"), config, ["base"], plan.kernel)
            try:
                inst.mount_ordered_layout()
                for name in ("home", ".snapshots", "var/log", "var/cache/pacman/pkg", "efi"):
                    assert os.path.ismount(inst.target / name), name
            finally:
                subprocess.run(["umount", "-R", str(inst.target)], check=True)
                if plan.luks:
                    run("cryptsetup", "close", "root")
            if mode == "luks":
                assert json.loads(run("cryptsetup", "luksDump", "--dump-json-metadata", str(root.dev_path)))["keyslots"]
            for path, value in before.items():
                assert digest(path) == value, "preserved partition changed: " + path
            assert digest(neighbor) == neighbor_hash, "neighbor disk changed"
            # Any post-format plan is stale and must not be replayed.
            try:
                revalidate(plan, loop_backing=backing)
            except PlanError:
                pass
            else:
                raise AssertionError("Stale plan accepted")
            results.append({"mode": mode, "status": "passed", "root_partition": Path(root.dev_path).name,
                            "preserved_partitions": len(before), "neighbor_unchanged": True})
            run("losetup", "--detach", dev)
            devices.remove(dev)
    finally:
        for dev in reversed(devices):
            subprocess.run(["losetup", "--detach", dev], check=False)
print("V8_DISK_RESULTS=" + json.dumps(results))
