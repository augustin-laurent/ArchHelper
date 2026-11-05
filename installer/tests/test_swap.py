from types import SimpleNamespace

from v8_installer.install import configure_swap


def test_swapfile_is_isolated_and_added_to_fstab(tmp_path):
    etc = tmp_path / 'etc'
    etc.mkdir()
    (etc / 'fstab').write_text('# generated\n')
    calls = []
    inst = SimpleNamespace(target=tmp_path, arch_chroot=calls.append)
    configure_swap(inst, SimpleNamespace(swap_gib=8, swap_location='root', partitions=[]))
    assert calls == ['btrfs subvolume create /swap', 'btrfs filesystem mkswapfile --size 8G /swap/swapfile']
    assert '/swap/swapfile none swap defaults,pri=10 0 0' in (etc / 'fstab').read_text()


def test_swap_on_separate_ext4_home(tmp_path):
    etc = tmp_path / 'etc'
    etc.mkdir()
    (etc / 'fstab').write_text('')
    calls = []
    inst = SimpleNamespace(target=tmp_path, arch_chroot=calls.append)
    home = SimpleNamespace(mount='/home', fs='ext4', action='format')
    configure_swap(inst, SimpleNamespace(swap_gib=4, swap_location='home', partitions=[home]))
    assert calls == ['mkdir -m 700 /home/.archhelper-swap', 'dd if=/dev/zero of=/home/.archhelper-swap/swapfile bs=1M count=4096 status=none conv=fsync',
                     'chmod 600 /home/.archhelper-swap/swapfile', 'mkswap /home/.archhelper-swap/swapfile']
    assert '/home/.archhelper-swap/swapfile none swap' in (etc / 'fstab').read_text()


def test_swap_disabled_makes_no_changes(tmp_path):
    calls = []
    configure_swap(SimpleNamespace(target=tmp_path, arch_chroot=calls.append), SimpleNamespace(swap_gib=0))
    assert calls == []
