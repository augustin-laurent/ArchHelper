"""Serializable installation intent. Credentials never belong in this module."""
from dataclasses import asdict, dataclass, field
import hashlib
import json
import re
from pathlib import Path

from .i18n import t

MIB = 1024 ** 2
GIB = 1024 ** 3
SUBVOLUMES = {"@": "/", "@home": "/home", "@snapshots": "/.snapshots",
              "@log": "/var/log", "@pkg": "/var/cache/pacman/pkg"}
KERNELS = {"aarch64": ("linux-aarch64",),
           "x86_64": ("linux", "linux-lts", "linux-zen", "linux-hardened", "linux-cachyos")}


class PlanError(ValueError):
    pass


@dataclass
class Partition:
    start: int
    size: int
    action: str = "keep"
    fs: str = ""
    mount: str = ""
    path: str = ""
    uuid: str = ""
    partuuid: str = ""
    esp: bool = False

    @property
    def end(self):
        return self.start + self.size


@dataclass
class Disk:
    path: str
    size: int
    sector: int
    identity: str
    model: str
    table: str
    partitions: list[Partition]
    free: list[tuple[int, int]]
    blocked: list[str] = field(default_factory=list)

    @property
    def fingerprint(self):
        # Busy state participates in the comparison immediately before writing.
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()


@dataclass
class InstallPlan:
    disk: Disk
    mode: str
    partitions: list[Partition]
    architecture: str
    kernel: str
    hostname: str = "archlinux"
    username: str = "user"
    locale: str = "fr_FR.UTF-8"
    keyboard: str = "fr"
    xkb: str = "fr"
    timezone: str = "Europe/Paris"
    bootloader: str = "systemd-boot"
    uki: bool = True
    luks: bool = False
    secure_boot: bool = False
    tpm2: bool = False
    plymouth: bool = True
    schema_version: int = 1
    release: str = "0.2.0-preview1"
    hardware: dict = field(default_factory=dict)
    graphics: str = "mesa"
    desktop: str = "hyprland"
    network: str = "networkmanager"
    snapshots: str = "snapper"
    bluetooth: bool = False
    zram: bool = False
    root_enabled: bool = False
    swap_gib: int = 0
    swap_location: str = "root"
    extra_packages: list[str] = field(default_factory=list)
    cachyos: bool = False

    def json(self):
        return json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n"

    @property
    def fingerprint(self):
        return hashlib.sha256(self.json().encode()).hexdigest()

    @property
    def confirmation(self):
        return f"INSTALLER {self.disk.path} {self.fingerprint[:8]}"

    def validate(self):
        from .desktop import profile
        profile(self.desktop)
        d = self.disk
        if type(d.size) is not int or type(d.sector) is not int or d.sector not in (512, 4096):
            raise PlanError(t("plan.geometry"))
        if any(type(getattr(self, k)) is not bool for k in ("uki", "luks", "secure_boot", "tpm2", "plymouth", "bluetooth", "zram", "root_enabled", "cachyos")):
            raise PlanError(t("plan.explicitBooleans"))
        if self.network not in ("networkmanager", "networkd", "none") or self.snapshots not in ("snapper", "timeshift", "none"):
            raise PlanError("Unsupported network or snapshot selection")
        if type(self.swap_gib) is not int or not 0 <= self.swap_gib <= 1024:
            raise PlanError("Invalid swap file size")
        if self.swap_location not in ('root', 'home'):
            raise PlanError('Unsupported swap location')
        if (not isinstance(self.extra_packages, list) or len(self.extra_packages) > 512 or
                any(not isinstance(p, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9@_.+\-]*', p) for p in self.extra_packages) or
                len(set(self.extra_packages)) != len(self.extra_packages)):
            raise PlanError("Invalid additional package selection")
        if d.blocked:
            raise PlanError(t("plan.protected") % "; ".join(d.blocked))
        if self.schema_version != 1 or self.mode not in ("wipe", "alongside", "manual"):
            raise PlanError(t("plan.unknownVersionOrMode"))
        if self.kernel not in KERNELS.get(self.architecture, ()):
            raise PlanError(t("plan.kernelArchMismatch"))
        if self.kernel == 'linux-cachyos' and not self.cachyos:
            raise PlanError('The CachyOS kernel requires the CachyOS repository')
        if self.bootloader != "systemd-boot" or self.secure_boot or self.tpm2:
            raise PlanError(t("plan.pendingQualification"))
        if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,30}", self.username) or self.username in ("preview", "alarm", "sddm", "nobody"):
            raise PlanError(t("plan.invalidUsername"))
        if self.username == "root" and (not self.root_enabled or self.desktop != "none"):
            raise PlanError("Root-only installation requires an enabled root account and the console profile")
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", self.hostname):
            raise PlanError(t("plan.invalidHostname"))
        supported = Path('/usr/share/i18n/SUPPORTED')
        locales = {parts[0] for line in supported.read_text().splitlines() if len(parts := line.split()) == 2 and parts[1] == 'UTF-8'} if supported.is_file() else set()
        if self.locale not in locales:
            raise PlanError(t("plan.unsupportedLocale"))
        from .keyboards import validate as validate_keyboard
        validate_keyboard(self.keyboard, self.xkb)
        zoneinfo = Path('/usr/share/zoneinfo')
        zone = zoneinfo / self.timezone
        if not re.fullmatch(r'[A-Za-z0-9_+.-]+(?:/[A-Za-z0-9_+.-]+)*', self.timezone) or not zone.is_file() or not zone.resolve().is_relative_to(zoneinfo.resolve()):
            raise PlanError(t("plan.unsupportedTimezone"))
        if self.mode != "wipe" and d.table != "gpt" and not (self.mode == "manual" and not d.table and not d.partitions):
            raise PlanError(t("plan.gptRequired"))
        original = {p.path: p for p in d.partitions}
        seen = set()
        active = []
        mounts = set()
        for p in self.partitions:
            if type(p.start) is not int or type(p.size) is not int or type(p.esp) is not bool:
                raise PlanError(t("plan.integerGeometry"))
            if p.action not in ("keep", "create", "format", "delete"):
                raise PlanError(t("plan.unknownAction"))
            if p.action == "create":
                if p.path:
                    raise PlanError(t("plan.pathOnNew"))
                if p.start % MIB or p.size % MIB:
                    raise PlanError(t("plan.mibAligned"))
            else:
                old = original.get(p.path)
                if not old or p.path in seen or (p.start, p.size, p.uuid, p.partuuid) != (old.start, old.size, old.uuid, old.partuuid):
                    raise PlanError(t("plan.existingUnknown"))
                seen.add(p.path)
                if p.action == "keep" and (p.fs != old.fs or p.esp != old.esp):
                    raise PlanError(t("plan.keepInconsistent"))
            if p.action == "delete":
                if p.mount:
                    raise PlanError(t("plan.mountedDelete"))
                continue
            # Existing exact geometries come from libparted (including the last
            # usable GPT sector); only new partitions require our 1 MiB margin.
            margin = MIB if p.action == "create" else d.sector
            if p.start < margin or p.size <= 0 or p.end > d.size - margin or p.start % d.sector or p.size % d.sector:
                raise PlanError(t("plan.outOfBounds"))
            if p.mount and p.mount not in ("/", "/efi", "/home", "/srv"):
                raise PlanError(t("plan.mountWhitelist"))
            if p.mount in mounts and p.mount:
                raise PlanError(t("plan.duplicateMount"))
            if p.mount:
                mounts.add(p.mount)
            if (p.mount or p.action in ("create", "format")) and p.fs not in ("btrfs", "ext4", "fat32", "vfat"):
                raise PlanError(t("plan.unsupportedFs"))
            if p.esp and p.mount not in ("", "/efi"):
                raise PlanError(t("plan.espData"))
            active.append(p)
        if self.mode != "wipe" and seen != set(original):
            raise PlanError(t("plan.allPartitionsPresent"))
        if self.mode == "wipe" and any(p.action != "create" for p in self.partitions):
            raise PlanError(t("plan.wipeFullLayout"))
        if self.mode == "alongside":
            for p in self.partitions:
                if p.path and (p.action != "keep" or p.mount):
                    raise PlanError(t("plan.alongsideKeepsAll"))
                if p.action == "create" and not any(p.start >= a and p.end <= a + n for a, n in d.free):
                    raise PlanError(t("plan.outsideFree"))
        ordered = sorted(active, key=lambda p: p.start)
        if any(a.end > b.start for a, b in zip(ordered, ordered[1:])):
            raise PlanError(t("plan.overlap"))
        roots = [p for p in active if p.mount == "/"]
        esps = [p for p in active if p.mount == "/efi"]
        if len(roots) != 1 or len(esps) != 1:
            raise PlanError(t("plan.oneRootOneEsp"))
        root, esp = roots[0], esps[0]
        if root.fs != "btrfs" or root.action not in ("create", "format") or root.size < 20 * GIB:
            raise PlanError(t("plan.rootNeedsNewBtrfs"))
        home = next((p for p in active if p.mount == '/home'), None)
        swap_partition = home if self.swap_location == 'home' and home else root
        if self.swap_gib and swap_partition.action == 'keep':
            raise PlanError('Swap cannot be placed on a preserved home partition')
        reserve = 20 if swap_partition is root else 2
        if self.swap_gib and swap_partition.size < (self.swap_gib + reserve) * GIB:
            raise PlanError(f'Swap size must leave at least {reserve} GiB on its filesystem')
        if esp.fs not in ("fat32", "vfat") or not esp.esp or esp.size < GIB:
            raise PlanError(t("plan.espNeedsFat32"))
        if any(p.mount == "/home" and p.fs not in ("ext4", "btrfs") for p in active):
            raise PlanError(t("plan.homeFs"))
        return self


def automatic(disk, mode, architecture):
    import copy
    if mode == "wipe":
        start, length = MIB, ((disk.size - 2 * MIB) // MIB) * MIB
        parts = []
    elif mode == "alongside":
        ranges = [(a, n) for a, n in disk.free if n >= 24 * GIB]
        if not ranges:
            raise PlanError(t("plan.noFreeSpace"))
        start, length = max(ranges, key=lambda x: x[1])
        parts = copy.deepcopy(disk.partitions)
    else:
        raise PlanError(t("plan.manualEditor"))
    end = ((start + length) // MIB) * MIB
    start = ((start + MIB - 1) // MIB) * MIB
    end = min(end, ((disk.size - MIB) // MIB) * MIB)
    parts += [Partition(start, 4 * GIB, "create", "fat32", "/efi", esp=True),
              Partition(start + 4 * GIB, end - start - 4 * GIB, "create", "btrfs", "/")]
    return InstallPlan(disk, mode, parts, architecture, KERNELS[architecture][0])
