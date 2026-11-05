import json
from pathlib import Path
from unittest.mock import patch
import pytest
from v8_installer import boot


@pytest.mark.parametrize("uki", [False, True])
@pytest.mark.parametrize("architecture,image", [("aarch64", "/boot/Image"), ("x86_64", "/boot/vmlinuz-linux")])
def test_publish_complete_generation_and_keep_previous(tmp_path, uki, architecture, image):
    def mapped(path):
        return tmp_path / str(path).lstrip("/")
    for name, data in {image: b"kernel", "/boot/v8/initramfs.img": b"initrd",
                       "/etc/kernel/cmdline": b"root=PARTUUID=test rootflags=subvol=@ rw"}.items():
        dest = mapped(name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    mapped("/efi").mkdir()
    mapped("/etc/v8-boot.json").write_text(json.dumps({"kernel_image": image, "uki": uki, "architecture": architecture}))
    def ukify(args, **kwargs):
        if args[0] == "ukify":
            out = next(s.split("=", 1)[1] for s in args if s.startswith("--output="))
            Path(out).write_bytes(b"MZ-TEST-UKI" + mapped(image).read_bytes())
    with patch.object(boot, "Path", side_effect=mapped), patch.object(boot.os.path, "ismount", return_value=True), patch.object(boot.os, "sync"), patch.object(boot.subprocess, "run", side_effect=ukify):
        boot.publish()
        old_entry = mapped("/efi/loader/entries/v8.conf").read_text()
        mapped(image).write_bytes(b"new-kernel")
        boot.publish()
        new_entry = mapped("/efi/loader/entries/v8.conf").read_text()
        assert old_entry != new_entry
        assert len(list(mapped("/efi/EFI/v8/generations").iterdir())) == 2
        assert "options " in new_entry or uki


def test_non_uki_copy_failure_leaves_previous_entry(tmp_path):
    def mapped(path):
        return tmp_path / str(path).lstrip("/")
    for name in ("/boot/Image", "/boot/v8/initramfs.img", "/etc/kernel/cmdline"):
        dest = mapped(name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"test")
    mapped("/efi/loader/entries").mkdir(parents=True)
    mapped("/efi/loader/entries/v8.conf").write_text("previous-valid-entry")
    mapped("/etc/v8-boot.json").write_text(json.dumps({"kernel_image": "/boot/Image", "uki": False, "architecture": "aarch64"}))
    original = boot.shutil.copyfile
    def failing(src, dest):
        if src.name == "initramfs.img":
            raise OSError("simulated power loss")
        return original(src, dest)
    with patch.object(boot, "Path", side_effect=mapped), patch.object(boot.os.path, "ismount", return_value=True), patch.object(boot.shutil, "copyfile", side_effect=failing):
        with pytest.raises(OSError):
            boot.publish()
    assert mapped("/efi/loader/entries/v8.conf").read_text() == "previous-valid-entry"


@pytest.mark.parametrize("kernel,image", [("linux-aarch64", "/boot/Image"), ("linux", "/boot/vmlinuz-linux"), ("linux-lts", "/boot/vmlinuz-linux-lts"), ("linux-zen", "/boot/vmlinuz-linux-zen"), ("linux-hardened", "/boot/vmlinuz-linux-hardened")])
def test_prepare_restores_preset_overwritten_by_kernel(tmp_path, kernel, image):
    config = tmp_path / "etc/v8-boot.json"
    config.parent.mkdir()
    config.write_text(json.dumps({"kernel": kernel, "kernel_image": image}))
    boot.prepare(tmp_path)
    preset = tmp_path / f"etc/mkinitcpio.d/{kernel}.preset"
    assert 'PRESETS=(default)' in preset.read_text()
    preset.write_text('vendor preset replaced on upgrade')
    boot.prepare(tmp_path)
    assert 'default_image="/boot/v8/initramfs.img"' in preset.read_text()
    assert (tmp_path / "boot/v8/prepare.timestamp").exists()


@pytest.mark.parametrize("architecture,suffix,fallback", [("aarch64", "aa64", "AA64"), ("x86_64", "x64", "X64")])
def test_loader_verification_detects_missing_or_corrupt_copy(tmp_path, architecture, suffix, fallback):
    paths = (f"usr/lib/systemd/boot/efi/systemd-boot{suffix}.efi", f"efi/EFI/systemd/systemd-boot{suffix}.efi", f"efi/EFI/BOOT/BOOT{fallback}.EFI")
    for name in paths:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"verified-vendor-loader")
    boot.verify_loader_files(tmp_path, architecture)
    (tmp_path / paths[-1]).write_bytes(b"corrupt")
    with pytest.raises(RuntimeError):
        boot.verify_loader_files(tmp_path, architecture)


@pytest.mark.parametrize("architecture,kernel,serial", [("aarch64", "linux-aarch64", "ttyAMA0"), ("x86_64", "linux", "ttyS0")])
@pytest.mark.parametrize("luks,uki", [(False, True), (True, False)])
def test_configure_selected_architecture_and_encryption(tmp_path, architecture, kernel, serial, luks, uki):
    from types import SimpleNamespace
    calls = []
    inst = SimpleNamespace(target=tmp_path, arch_chroot=lambda command, **kw: calls.append(command))
    plan = SimpleNamespace(architecture=architecture, kernel=kernel, luks=luks, uki=uki, plymouth=True, hardware={"virtual": True}, graphics="vm")
    part = SimpleNamespace(partuuid="test-root", dev_path="/dev/fixture2")
    with patch.object(boot.subprocess, "check_output", return_value="luks-fixture\n"), patch.object(boot, "verify_loader_files"):
        boot.configure(inst, plan, part)
    cmdline = (tmp_path / "etc/kernel/cmdline").read_text()
    assert f"console={serial},115200" in cmdline
    assert ("rd.luks.name=luks-fixture=root" in cmdline) == luks
    hooks = (tmp_path / "etc/mkinitcpio.conf").read_text()
    assert ("microcode" in hooks) == (architecture == "x86_64")
    assert ("sd-encrypt" in hooks) == luks
    assert 'PRESETS=(default)' in (tmp_path / f"etc/mkinitcpio.d/{kernel}.preset").read_text()
    config = json.loads((tmp_path / 'etc/v8-boot.json').read_text())
    assert config['uki'] == uki and config['architecture'] == architecture
    assert calls[:2] == ['mkinitcpio -P', 'v8-boot-sync']
