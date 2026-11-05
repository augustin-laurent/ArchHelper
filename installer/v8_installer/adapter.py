"""Only bridge to archinstall 4.5's internal disk and installation API."""
from importlib.metadata import version
from pathlib import Path
import sys
from unittest.mock import patch

from .i18n import t
from .plan import SUBVOLUMES, PlanError


def contract():
    if version("archinstall") != "4.5" or sys.version_info[:2] != (3, 14):
        raise PlanError(t("adapter.unsupportedApi"))


def layout(plan, luks_password=""):
    contract()
    import parted
    # Upstream's singleton otherwise probes/mounts every existing Btrfs volume.
    # Import it empty, then populate only the confirmed target without mounting.
    def no_loop_probe(path):
        raise parted.IOException("V8: unselected device")
    saved_enumerate, saved_get = parted.getAllDevices, parted.getDevice
    try:
        parted.getAllDevices = lambda: []
        parted.getDevice = no_loop_probe
        from archinstall.lib.disk.device_handler import device_handler
    finally:
        # pyparted wraps its module and does not support delattr used by patch.
        parted.getAllDevices, parted.getDevice = saved_enumerate, saved_get
    from archinstall.lib.disk.utils import get_lsblk_info, find_lsblk_info
    from archinstall.lib.models.device import (
        BDevice, _DeviceInfo, _PartitionInfo, DiskLayoutConfiguration, DiskLayoutType,
        DeviceModification, PartitionModification, PartitionType, ModificationStatus,
        FilesystemType, PartitionFlag, Size, SectorSize, Unit, SubvolumeModification,
        DiskEncryption, EncryptionType,
    )
    from archinstall.lib.models.users import Password
    dev = parted.getDevice(plan.disk.path)
    disk = parted.Disk(dev) if plan.disk.table else parted.freshDisk(dev, "gpt")
    info = _DeviceInfo.from_disk(disk)
    lsblk = get_lsblk_info(Path(plan.disk.path))
    existing = []
    for p in disk.partitions:
        if p.number < 1:
            continue
        block = find_lsblk_info(p.path, lsblk.children)
        if not block:
            raise PlanError(t("adapter.partitionMissing"))
        fs = next((q.fs for q in plan.disk.partitions if q.path == p.path), "")
        try:
            fs_type = FilesystemType("fat32" if fs == "vfat" else fs)
        except ValueError:
            fs_type = None
        existing.append(_PartitionInfo.from_partition(p, block, fs_type, []))
    device = BDevice(disk, info, existing)
    device_handler._devices = {Path(plan.disk.path): device}
    from archinstall.lib.models.device import PartitionTable
    device_handler._partition_table = PartitionTable.GPT
    mods = []
    for p in plan.partitions:
        fs = "fat32" if p.fs == "vfat" else p.fs
        try:
            fs_type = FilesystemType(fs)
        except ValueError:
            fs_type = None
        status = {"keep": ModificationStatus.EXIST, "create": ModificationStatus.CREATE,
                  "format": ModificationStatus.MODIFY, "delete": ModificationStatus.DELETE}[p.action]
        subs = []
        mount = Path(p.mount) if p.mount else None
        if p.mount == "/":
            subs = [SubvolumeModification(Path(name), Path(target)) for name, target in SUBVOLUMES.items()
                    if not any(q.mount == target and target != "/" for q in plan.partitions)]
            mount = None
        flags = [PartitionFlag.ESP, PartitionFlag.BOOT] if p.esp else []
        mods.append(PartitionModification(status, PartitionType.PRIMARY,
            Size(p.start, Unit.B, SectorSize(plan.disk.sector, Unit.B)),
            Size(p.size, Unit.B, SectorSize(plan.disk.sector, Unit.B)), fs_type, mount,
            ["compress=zstd", "noatime"] if fs == "btrfs" and p.mount else [], flags, subs,
            Path(p.path) if p.path else None, partuuid=p.partuuid or None, uuid=p.uuid or None))
    enc = None
    if plan.luks:
        if not luks_password:
            raise PlanError(t("adapter.luksPasswordMissing"))
        enc = DiskEncryption(EncryptionType.LUKS, Password(luks_password),
                             [m for m in mods if m.is_root()])
    return DiskLayoutConfiguration(DiskLayoutType.Manual,
        [DeviceModification(device, plan.mode == "wipe", mods)], disk_encryption=enc)


def format_disk(config):
    from archinstall.lib.disk.filesystem import FilesystemHandler
    from archinstall.lib.disk.device_handler import device_handler
    from archinstall.lib.models.device import ModificationStatus
    original = device_handler._setup_partition
    def setup(part, *args, **kwargs):
        original(part, *args, **kwargs)
        # 4.5 otherwise calls wipefs on a deleted device node after commit.
        if part.status == ModificationStatus.DELETE:
            part.dev_path = None
    with patch.object(device_handler, "_setup_partition", side_effect=setup):
        FilesystemHandler(config).perform_filesystem_operations()


def installer(target, config, packages, kernel, *, pacman_conf=None):
    from archinstall.lib.installer import Installer
    from archinstall.lib.command import SysCommand
    import shlex
    class V8Installer(Installer):
        # Ordinary arch-chroot also works inside the isolated builder. Upstream
        # 4.5's -S requires the outer host to run the exact new systemd API.
        def run_command(self, cmd, peek_output=False):
            return SysCommand(["arch-chroot", str(self.target), *shlex.split(cmd)], peek_output=peek_output)

        def _chroot_argv(self, *args):
            return ["arch-chroot", str(self.target), *args]
    inst = V8Installer(target, config, base_packages=list(packages), kernels=[kernel], silent=True)
    if pacman_conf is not None:
        import subprocess
        def strap(names):
            names = [names] if isinstance(names, str) else names
            # Seed the target with the trusted live keyring, including keys for
            # explicitly configured repositories used by the transaction.
            subprocess.run(["pacstrap", "-C", str(pacman_conf), str(target), *names,
                            "--noconfirm", "--needed"], check=True)
        inst.pacman.strap = strap
        inst.pacman.synced = True
    return inst
