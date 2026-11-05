"""One mkinitcpio pipeline, with firmware-readable publication on the ESP."""
import json
from pathlib import Path
import shutil
import subprocess
import os
import hashlib
import sys


def write(root, path, content, mode=0o644):
    dest = root / path.lstrip("/")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_symlink():
        dest.unlink()
    dest.write_text(content)
    dest.chmod(mode)


def configure(installation, plan, root_partition):
    root = installation.target
    luks_uuid = ""
    if plan.luks:
        luks_uuid = subprocess.check_output(["cryptsetup", "luksUUID", str(root_partition.dev_path)], text=True).strip()
        params = [f"rd.luks.name={luks_uuid}=root", "root=/dev/mapper/root"]
    else:
        params = [f"root=PARTUUID={root_partition.partuuid}"]
    params += ["rootflags=subvol=@", "rw"]
    if plan.plymouth:
        params += ["quiet", "splash"]
    serial = "ttyAMA0" if plan.architecture == "aarch64" else "ttyS0"
    params += ["console=tty0"]
    if plan.hardware.get("virtual"):
        params += [f"console={serial},115200"]
    write(root, "/etc/kernel/cmdline", " ".join(params) + "\n")
    hooks = ["base", "systemd", "autodetect", "modconf", "kms", "keyboard", "sd-vconsole", "block"]
    if plan.architecture == "x86_64":
        hooks.insert(3, "microcode")
    if plan.plymouth:
        hooks.insert(6, "plymouth")
    if plan.luks:
        hooks += ["sd-encrypt"]
    hooks += ["filesystems", "fsck"]
    modules = "virtio_pci virtio_blk virtio_scsi virtio_gpu xhci_pci usbhid" if plan.architecture == "aarch64" else ""
    from .hardware import modules as gpu_modules
    modules = " ".join(filter(None, [modules, *gpu_modules(plan)]))
    write(root, "/etc/mkinitcpio.conf", f'MODULES=({modules})\nBINARIES=()\nFILES=()\nHOOKS=({" ".join(hooks)})\nCOMPRESSION="gzip"\n')
    image = "/boot/Image" if plan.architecture == "aarch64" else f"/boot/vmlinuz-{plan.kernel}"
    write(root, "/etc/v8-boot.json", json.dumps({"kernel_image": image, "uki": plan.uki,
          "kernel": plan.kernel, "architecture": plan.architecture}, indent=2) + "\n")
    prepare(root)
    # Keep this helper independent of Textual/archinstall on installed systems.
    write(root, "/usr/lib/v8/boot_sync.py", Path(__file__).read_text())
    write(root, "/usr/bin/v8-boot-sync", '#!/usr/bin/python -I\nimport runpy, sys\nsys.argv = ["v8-boot-sync", "--sync"]\nrunpy.run_path("/usr/lib/v8/boot_sync.py", run_name="__main__")\n', 0o755)
    write(root, "/usr/bin/v8-boot-prepare", '#!/usr/bin/python -I\nimport runpy, sys\nsys.argv = ["v8-boot-prepare", "--prepare"]\nrunpy.run_path("/usr/lib/v8/boot_sync.py", run_name="__main__")\n', 0o755)
    (root / "etc/pacman.d/hooks/zz-v8-boot.hook").unlink(missing_ok=True)
    # ALARM's kernel owns a preset without backup=(). Restore ours after package
    # extraction, before upstream's 90-mkinitcpio-install hook executes.
    write(root, "/etc/pacman.d/hooks/89-v8-boot-prepare.hook", f'''[Trigger]
Operation = Install
Operation = Upgrade
Type = Package
Target = {plan.kernel}
Target = mkinitcpio
Target = nvidia-open-dkms
Target = nvidia-open
Target = nvidia-open-lts
Target = nvidia-580xx-dkms
Target = nvidia-580xx-utils
Target = nvidia-utils
[Action]
Description = Preparing the selected V8 initramfs preset
When = PostTransaction
Exec = /usr/bin/v8-boot-prepare
''')
    write(root, "/etc/pacman.d/hooks/zz-00-v8-boot.hook", f'''[Trigger]
Operation = Install
Operation = Upgrade
Type = Package
Target = {plan.kernel}
Target = mkinitcpio
Target = systemd
Target = systemd-ukify
Target = plymouth
Target = nvidia-open-dkms
Target = nvidia-open
Target = nvidia-open-lts
Target = nvidia-580xx-dkms
Target = nvidia-580xx-utils
Target = nvidia-utils
[Action]
Description = Publishing V8 boot files on the ESP
When = PostTransaction
Exec = /usr/bin/v8-boot-sync
''')
    installation.arch_chroot("mkinitcpio -P", peek_output=True)
    installation.arch_chroot("v8-boot-sync", peek_output=True)
    efi = root / "efi"
    fallback = "BOOTAA64.EFI" if plan.architecture == "aarch64" else "BOOTX64.EFI"
    old = efi / "EFI/BOOT" / fallback
    if old.exists():
        backup = efi / "EFI/v8/previous-fallback.efi"
        backup.parent.mkdir(parents=True, exist_ok=True)
        if not backup.exists():
            shutil.copy2(old, backup)
    # Removable fallback works even when the VM firmware cannot persist NVRAM.
    installation.arch_chroot("bootctl --esp-path=/efi --no-variables --graceful install", peek_output=True)
    verify_loader_files(root, plan.architecture)
    loader = efi / "loader/loader.conf"
    if not loader.exists():
        write(root, "/efi/loader/loader.conf", "default v8*\ntimeout 5\neditor no\n")
    return luks_uuid


def prepare(root=Path("/")):
    config = json.loads((root / "etc/v8-boot.json").read_text())
    kernel = config["kernel"]
    if kernel not in ("linux-aarch64", "linux", "linux-lts", "linux-zen", "linux-hardened", "linux-cachyos"):
        raise RuntimeError("Unrecognized kernel preset")
    image = config["kernel_image"]
    if image != ("/boot/Image" if kernel == "linux-aarch64" else f"/boot/vmlinuz-{kernel}"):
        raise RuntimeError("Unrecognized kernel image path")
    (root / "boot/v8").mkdir(parents=True, exist_ok=True)
    preset = f'ALL_config="/etc/mkinitcpio.conf"\nALL_kver="{image}"\nPRESETS=(default)\ndefault_image="/boot/v8/initramfs.img"\n'
    write(root, f"/etc/mkinitcpio.d/{kernel}.preset", preset)
    (root / "boot/v8/prepare.timestamp").touch()


def verify_loader_files(root, architecture):
    suffix = "aa64" if architecture == "aarch64" else "x64"
    fallback = "BOOTAA64.EFI" if architecture == "aarch64" else "BOOTX64.EFI"
    vendor = root / f"usr/lib/systemd/boot/efi/systemd-boot{suffix}.efi"
    expected = hashlib.sha256(vendor.read_bytes()).digest()
    for name in (f"EFI/systemd/systemd-boot{suffix}.efi", f"EFI/BOOT/{fallback}"):
        dest = root / "efi" / name
        if not dest.is_file() or hashlib.sha256(dest.read_bytes()).digest() != expected:
            raise RuntimeError("Installed bootloader differs from the verified vendor binary: " + name)


def publish():
    """Executed inside the target on install and subsequent kernel transactions."""
    config = json.loads(Path("/etc/v8-boot.json").read_text())
    efi = Path("/efi")
    if not os.path.ismount(efi):
        raise RuntimeError("ESP /efi is not mounted; boot publication refused")
    image = Path(config["kernel_image"])
    initrd = Path("/boot/v8/initramfs.img")
    if not image.is_file() or not initrd.is_file():
        raise RuntimeError("Kernel or initramfs missing")
    stamp = Path("/boot/v8/prepare.timestamp")
    if stamp.exists() and initrd.stat().st_mtime_ns <= stamp.stat().st_mtime_ns:
        raise RuntimeError("Initramfs was not regenerated after preset preparation; previous EFI entry preserved")
    minimum = image.stat().st_size + initrd.stat().st_size + 128 * 1024 ** 2
    if shutil.disk_usage(efi).free < minimum:
        raise RuntimeError("Insufficient free ESP space; previous boot files preserved")
    if config["uki"]:
        output = Path("/boot/v8/current.efi")
        subprocess.run(["ukify", "build", f"--linux={image}", f"--initrd={initrd}",
                        "--cmdline=@/etc/kernel/cmdline", f"--output={output}"], check=True)
        sources = [(output, "v8.efi")]
    else:
        sources = [(image, "vmlinuz"), (initrd, "initramfs.img")]
    digest = hashlib.sha256(Path("/etc/kernel/cmdline").read_bytes())
    for source, _ in sources:
        with source.open("rb") as stream:
            while chunk := stream.read(1024 ** 2):
                digest.update(chunk)
    generation = digest.hexdigest()
    base = efi / "EFI/v8/generations" / generation
    needed = sum(s.stat().st_size for s, _ in sources) + 64 * 1024 ** 2
    if shutil.disk_usage(efi).free < needed:
        raise RuntimeError("Insufficient ESP space for a complete new boot generation")
    for source, name in sources:
        dest = base / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".new")
        shutil.copyfile(source, tmp)
        with tmp.open("rb") as stream:
            os.fsync(stream.fileno())
        tmp.replace(dest)
    entry = efi / "loader/entries/v8.conf"
    entry.parent.mkdir(parents=True, exist_ok=True)
    if config["uki"]:
        content = f"title V8\nefi /EFI/v8/generations/{generation}/v8.efi\n"
    else:
        prefix = f"/EFI/v8/generations/{generation}"
        content = f"title V8\nlinux {prefix}/vmlinuz\ninitrd {prefix}/initramfs.img\noptions " + Path("/etc/kernel/cmdline").read_text().strip() + "\n"
    entry.with_suffix(".new").write_text(content)
    entry.with_suffix(".new").replace(entry)
    os.sync()
    # Only switch the menu after the complete set exists. Keep the preceding
    # files for diagnosis; this is not a claim of bootable root snapshots.
    previous = sorted((p for p in base.parent.iterdir() if p != base and p.is_dir()
                       and not p.is_symlink() and len(p.name) == 64
                       and all(c in "0123456789abcdef" for c in p.name)),
                      key=lambda p: p.stat().st_mtime, reverse=True)
    for old in previous[1:]:
        shutil.rmtree(old)
    suffix = "aa64" if config["architecture"] == "aarch64" else "x64"
    if (efi / f"EFI/systemd/systemd-boot{suffix}.efi").is_file():
        # Some bootctl versions report failure when an identical loader is
        # skipped. Graceful mode plus byte verification still catches failures.
        subprocess.run(["bootctl", "--esp-path=/efi", "--no-variables", "--graceful", "update"], check=True)
        verify_loader_files(Path("/"), config["architecture"])


def synchronize():
    # NVIDIA-only transactions do not necessarily trigger the upstream kernel
    # initramfs hook. Rebuild only if that hook has not already done the work.
    stamp = Path("/boot/v8/prepare.timestamp")
    image = Path("/boot/v8/initramfs.img")
    if not image.is_file() or (stamp.exists() and image.stat().st_mtime_ns <= stamp.stat().st_mtime_ns):
        subprocess.run(["mkinitcpio", "-P"], check=True)
    publish()


if __name__ == "__main__":
    if sys.argv[1:] == ["--prepare"]:
        prepare()
    elif sys.argv[1:] == ["--sync"]:
        synchronize()
    else:
        publish()
