import copy
import json
from unittest.mock import patch
import pytest

from v8_installer.plan import Disk, Partition, automatic, PlanError, GIB, MIB
from v8_installer.install import Credentials, Journal, decode
from v8_installer.disks import revalidate, blocked_reasons


@pytest.fixture
def disk():
    return Disk("/dev/vdb", 40 * GIB, 512, "serial=V8_TEST", "Test disk", "gpt", [], [(MIB, 40 * GIB - 2 * MIB)])


def test_defaults_and_secret_free_roundtrip(disk):
    p = automatic(disk, "wipe", "aarch64").validate()
    assert p.kernel == "linux-aarch64" and p.uki and p.plymouth and not p.luks
    assert p.partitions[0].size == 4 * GIB
    assert decode(p.json()).json() == p.json()
    assert "password" not in p.json()
    assert "secret" not in repr(Credentials("secret-value", "luks-secret-value"))


@pytest.mark.parametrize("architecture, kernel", [("x86_64", "linux"), ("aarch64", "linux-aarch64")])
def test_one_default_kernel(disk, architecture, kernel):
    assert automatic(disk, "wipe", architecture).validate().kernel == kernel


def test_confirmation_binds_the_entire_plan(disk):
    p = automatic(disk, "wipe", "aarch64")
    original = p.confirmation
    p.luks = True
    assert p.confirmation != original


def test_extended_locale_and_timezone_and_reject_path_traversal(disk):
    p = automatic(disk, 'wipe', 'x86_64')
    p.locale, p.timezone = 'de_DE.UTF-8', 'Asia/Tokyo'
    p.validate()
    p.timezone = '../../etc/passwd'
    with pytest.raises(PlanError):
        p.validate()


def test_optional_choices_are_validated_and_bound_to_plan(disk):
    p = automatic(disk, 'wipe', 'x86_64')
    before = p.confirmation
    p.network, p.snapshots, p.bluetooth, p.zram = 'networkd', 'timeshift', True, True
    p.validate()
    assert p.confirmation != before
    p.snapshots = 'unknown'
    with pytest.raises(PlanError):
        p.validate()


def test_root_only_requires_console_and_valid_credentials(disk):
    p = automatic(disk, 'wipe', 'x86_64')
    p.username, p.root_enabled, p.desktop = 'root', True, 'none'
    p.validate()
    Credentials('root-password').validate(p)
    p.desktop = 'hyprland'
    with pytest.raises(PlanError, match='console'):
        p.validate()


def test_optional_root_password_is_required_and_never_serialized(disk):
    p = automatic(disk, 'wipe', 'x86_64')
    p.root_enabled = True
    with pytest.raises(PlanError):
        Credentials('user-password').validate(p)
    secret = Credentials('user-password', root_password='root-password')
    secret.validate(p)
    assert 'root-password' not in repr(secret) and 'root-password' not in p.json()


def test_swap_size_is_bounded_by_root_and_confirmation(disk):
    p = automatic(disk, 'wipe', 'x86_64')
    before = p.confirmation
    p.swap_gib = 4
    p.validate()
    assert p.confirmation != before
    p.swap_gib = 20
    with pytest.raises(PlanError, match='20 GiB'):
        p.validate()
    p.swap_gib = -1
    with pytest.raises(PlanError, match='swap'):
        p.validate()


@pytest.mark.parametrize('fs', ['btrfs', 'ext4'])
def test_swap_home_checks_the_home_partition_capacity(disk, fs):
    p = automatic(disk, 'wipe', 'x86_64')
    root = p.partitions[-1]
    root.size -= 8 * GIB
    p.partitions.append(Partition(root.end, 8 * GIB, 'create', fs, '/home'))
    p.swap_location, p.swap_gib = 'home', 4
    p.validate()
    p.swap_gib = 7
    with pytest.raises(PlanError, match='2 GiB'):
        p.validate()


def test_extra_packages_are_safe_and_bound_to_confirmation(disk):
    p = automatic(disk, 'wipe', 'x86_64')
    previous = p.confirmation
    p.extra_packages = ['firefox', 'git']
    p.validate()
    assert p.confirmation != previous
    p.extra_packages = ['--config=/tmp/evil']
    with pytest.raises(PlanError, match='package'):
        p.validate()


def test_cachyos_kernel_requires_explicit_repository(disk):
    p = automatic(disk, 'wipe', 'x86_64')
    p.kernel = 'linux-cachyos'
    with pytest.raises(PlanError, match='CachyOS repository'):
        p.validate()
    p.cachyos = True
    p.validate()


def test_alongside_preserves_original_and_uses_only_gap(disk):
    old = Partition(MIB, 8 * GIB, fs="ntfs", path="/dev/vdb1", uuid="original")
    disk.partitions = [old]
    disk.free = [(9 * GIB, 30 * GIB)]
    p = automatic(disk, "alongside", "aarch64").validate()
    assert p.partitions[0] == old and p.partitions[0] is not old
    p.partitions[0].action = "format"
    with pytest.raises(PlanError):
        p.validate()


def test_unaligned_gap_never_grows(disk):
    disk.free = [(GIB + 512, 30 * GIB)]
    p = automatic(disk, "alongside", "aarch64").validate()
    assert p.partitions[-1].end <= sum(disk.free[0])


@pytest.mark.parametrize("mutation", [
    lambda p: setattr(p.disk, "blocked", ["mounted /run/archiso"]),
    lambda p: setattr(p, "kernel", "linux-lts"),
    lambda p: setattr(p, "username", "root"),
    lambda p: setattr(p, "hostname", "x; reboot"),
    lambda p: setattr(p, "secure_boot", True),
    lambda p: setattr(p, "tpm2", True),
    lambda p: setattr(p, "bootloader", "grub"),
    lambda p: setattr(p.partitions[1], "start", MIB),
    lambda p: setattr(p.partitions[1], "mount", "/../../etc"),
    lambda p: setattr(p.partitions[1], "size", 10 * GIB),
    lambda p: setattr(p.partitions[0], "esp", False),
    lambda p: setattr(p.partitions[0], "size", 100 * MIB),
])
def test_invalid_combinations_fail_closed(disk, mutation):
    p = automatic(disk, "wipe", "aarch64")
    mutation(p)
    with pytest.raises(PlanError):
        p.validate()


def test_manual_esp_preserved_root_format_explicit(disk):
    p = automatic(disk, "wipe", "aarch64")
    for i, part in enumerate(p.partitions):
        part.path, part.action = f"/dev/vdb{i+1}", "keep"
        part.uuid, part.partuuid = f"uuid{i}", f"partuuid{i}"
    disk.partitions = copy.deepcopy(p.partitions)
    p.mode = "manual"
    p.partitions[1].action = "format"
    assert p.validate()
    assert p.partitions[0].action == "keep"
    p.partitions[1].action = "keep"
    with pytest.raises(PlanError, match="racine Btrfs neuve"):
        p.validate()


def test_missing_original_partition_rejected(disk):
    disk.partitions = [Partition(MIB, GIB, path="/dev/vdb1", fs="ext4")]
    disk.free = [(2 * GIB, 36 * GIB)]
    p = automatic(disk, "alongside", "aarch64")
    p.partitions.pop(0)
    with pytest.raises(PlanError, match="Toutes les partitions"):
        p.validate()


def test_changed_layout_or_mount_rejected(disk):
    p = automatic(disk, "wipe", "aarch64")
    changed = copy.deepcopy(disk)
    changed.identity += "replacement"
    with patch("v8_installer.disks.discover", return_value=[changed]):
        with pytest.raises(PlanError, match="changé"):
            revalidate(p)


def test_mount_and_swap_protect_whole_disk():
    n = {"path": "/dev/not-real", "children": [{"path": "/dev/not-real1", "type": "part", "mountpoints": ["/run/archiso/bootmnt"]}]}
    assert blocked_reasons(n)
    n["children"][0]["mountpoints"] = ["[SWAP]"]
    assert blocked_reasons(n)


def test_credentials_and_atomic_failure_journal(disk, tmp_path):
    p = automatic(disk, "wipe", "aarch64")
    Credentials("short").validate(p)
    with pytest.raises(PlanError):
        Credentials("").validate(p)
    p.root_enabled = True
    p.luks = True
    Credentials("a", "b", "c").validate(p)
    with pytest.raises(PlanError):
        Credentials("a", "b\n", "c").validate(p)
    journal = Journal(tmp_path)
    with pytest.raises(RuntimeError):
        with journal.phase("partition-format"):
            raise RuntimeError("private-string")
    content = (tmp_path / "journal.json").read_text()
    assert "private-string" not in content and '"failed"' in content
    assert (tmp_path / "journal.json").stat().st_mode & 0o777 == 0o600
    with pytest.raises(PlanError):
        with journal.phase("partition-format"):
            pass
    with pytest.raises(PlanError):
        Journal(tmp_path)


def test_manual_can_create_gpt_on_empty_disk(disk):
    disk.table = ""
    p = automatic(disk, "wipe", "aarch64")
    p.mode = "manual"
    assert p.validate()
