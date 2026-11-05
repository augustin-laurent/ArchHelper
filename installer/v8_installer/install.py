"""Ordered execution with an atomic journal; never resumes a destructive phase."""
from dataclasses import dataclass, field
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import time
import uuid

from . import adapter, boot, desktop, hardware, payload
from .i18n import t
from .disks import revalidate
from .plan import InstallPlan, Disk, Partition, PlanError

TARGET = Path("/mnt/v8-target")


@dataclass(repr=False)
class Credentials:
    password: str = field(repr=False)
    luks_password: str = field(default="", repr=False)
    root_password: str = field(default="", repr=False)

    def validate(self, plan):
        required = [self.password]
        if plan.luks:
            required.append(self.luks_password)
        if plan.root_enabled and plan.username != 'root':
            required.append(self.root_password)
        for value in required:
            if not value or any(c in value for c in "\0\r\n"):
                raise PlanError(t("install.passwordMin"))


def decode(raw):
    obj = json.loads(raw) if isinstance(raw, str) else raw
    disk = obj.pop("disk")
    disk["partitions"] = [Partition(**p) for p in disk["partitions"]]
    return InstallPlan(disk=Disk(**disk), partitions=[Partition(**p) for p in obj.pop("partitions")], **obj)


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w") as out:
        os.chmod(tmp, 0o600)
        out.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        out.flush()
        os.fsync(out.fileno())
    tmp.replace(path)
    fd = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class Journal:
    def __init__(self, directory, phases=(), callback=None):
        self.callback = callback
        self.directory = directory
        if (directory / "journal.json").exists():
            raise PlanError(t("journal.noReplay"))
        self.steps = [{"phase": name, "state": "planned"} for name in phases]

    def save(self):
        atomic(self.directory / "journal.json", {"steps": self.steps})
        if self.callback:
            try:
                self.callback(self.steps)
            except BrokenPipeError:
                self.callback = None

    @contextmanager
    def phase(self, name):
        row = next((s for s in self.steps if s["phase"] == name), None)
        if row is None:
            row = {"phase": name, "state": "planned"}
            self.steps.append(row)
        if row["state"] != "planned":
            raise PlanError(t("journal.phaseNoReplay"))
        row.update(state="started", time=time.time())
        self.save()
        try:
            yield
        except BaseException as err:
            row["state"] = "failed"
            # No exception values: external processes could include private data.
            row["error"] = type(err).__name__
            self.save()
            raise
        else:
            row["state"] = "completed"
            self.save()


def configure_firewall(root):
    # A chroot shares the live network. Write target policy files directly;
    # never call a firewall command that might reload rules in the live kernel.
    content = (root / "etc/default/ufw").read_text()
    for key, value in {"IPV6": "yes", "DEFAULT_INPUT_POLICY": '"DROP"',
                       "DEFAULT_OUTPUT_POLICY": '"ACCEPT"', "DEFAULT_FORWARD_POLICY": '"DROP"'}.items():
        content, count = re.subn(r"^" + key + r"=.*$", key + "=" + value, content, flags=re.M)
        if count != 1:
            raise PlanError(t("install.ufwFormat") % key)
    boot.write(root, "/etc/default/ufw", content)
    boot.write(root, "/etc/ufw/ufw.conf", "ENABLED=yes\nLOGLEVEL=low\n")


def configure_keyboard(root, plan):
    from .keyboards import split as split_xkb
    layout, variant = split_xkb(plan.xkb)
    boot.write(root, "/etc/vconsole.conf", f"KEYMAP={plan.keyboard}\n")
    # SDDM uses Xorg by default and does not read the console keymap.
    boot.write(root, "/etc/X11/xorg.conf.d/00-keyboard.conf",
               'Section "InputClass"\n    Identifier "system-keyboard"\n'
               '    MatchIsKeyboard "on"\n'
               f'    Option "XkbLayout" "{layout}"\n'
               f'    Option "XkbVariant" "{variant}"\nEndSection\n')
    if desktop.profile(getattr(plan, 'desktop', 'none'))['display_manager'] == 'sddm':
        # Xorg's InputClass alone does not set the core keyboard used by the
        # SDDM greeter on all systems. Apply the chosen map after X starts.
        boot.write(root, '/etc/sddm/Xsetup',
                   '#!/bin/sh\n'
                   '[ ! -x /usr/share/sddm/scripts/Xsetup ] || /usr/share/sddm/scripts/Xsetup\n'
                   f'exec /usr/bin/setxkbmap -layout {shlex.quote(layout)} -variant {shlex.quote(variant)}\n',
                   mode=0o755)
        boot.write(root, '/etc/sddm.conf.d/30-keyboard.conf',
                   '[X11]\nDisplayCommand=/etc/sddm/Xsetup\n')
    boot.write(root, '/etc/environment.d/60-keyboard.conf',
               f'XKB_DEFAULT_LAYOUT={layout}\nXKB_DEFAULT_VARIANT={variant}\n')
    # environment.d only reaches services started by the user manager. PAM's
    # environment is also inherited by display-manager-launched sessions.
    env_path = root / 'etc/environment'
    existing = env_path.read_text().splitlines() if env_path.is_file() else []
    existing = [line for line in existing if not re.match(r'^\s*(?:XKB_DEFAULT_LAYOUT|XKB_DEFAULT_VARIANT)\s*=', line)]
    boot.write(root, '/etc/environment', '\n'.join(existing + [
        f'XKB_DEFAULT_LAYOUT={layout}', f'XKB_DEFAULT_VARIANT={variant}', '']))
    if getattr(plan, 'desktop', '') == 'plasma':
        boot.write(root, '/etc/skel/.config/kxkbrc',
                   f'[Layout]\nUse=true\nLayoutList={layout}\nVariantList={variant}\n')
    if getattr(plan, 'desktop', '') == 'gnome':
        source = layout + ('+' + variant if variant else '')
        boot.write(root, '/etc/dconf/db/local.d/00-archhelper-keyboard',
                   f"[org/gnome/desktop/input-sources]\nsources=[('xkb', '{source}')]\n")
        for name in ('user', 'gdm'):
            path = root / 'etc/dconf/profile' / name
            lines = path.read_text().splitlines() if path.is_file() else ['user-db:user']
            if name == 'gdm' and 'system-db:gdm' not in lines:
                lines.append('system-db:gdm')
            if 'system-db:local' not in lines:
                lines.append('system-db:local')
            boot.write(root, '/etc/dconf/profile/' + name, '\n'.join(lines) + '\n')


def configure_swap(inst, plan):
    if not plan.swap_gib:
        return
    home = next((p for p in plan.partitions if p.mount == '/home' and p.action != 'delete'), None)
    directory = '/home/.archhelper-swap' if plan.swap_location == 'home' else '/swap'
    filesystem = home.fs if plan.swap_location == 'home' and home else 'btrfs'
    if filesystem == 'btrfs':
        # A nested subvolume keeps the active swapfile out of snapshots.
        inst.arch_chroot('btrfs subvolume create ' + directory)
        inst.arch_chroot(f'btrfs filesystem mkswapfile --size {plan.swap_gib}G {directory}/swapfile')
    else:
        inst.arch_chroot('mkdir -m 700 ' + directory)
        # Fully write ext4 swap blocks; preallocated unwritten extents are not
        # accepted as swap on every kernel/filesystem combination.
        inst.arch_chroot(f'dd if=/dev/zero of={directory}/swapfile bs=1M count={plan.swap_gib * 1024} status=none conv=fsync')
        inst.arch_chroot('chmod 600 ' + directory + '/swapfile')
        inst.arch_chroot('mkswap ' + directory + '/swapfile')
    fstab = inst.target / 'etc/fstab'
    with fstab.open('a') as output:
        output.write(f'\n{directory}/swapfile none swap defaults,pri=10 0 0\n')


def configure_timeshift(inst):
    """Configure scheduled Btrfs snapshots on the installed root filesystem."""
    root = inst.target
    try:
        settings = json.loads((root / 'etc/timeshift/default.json').read_text())
        uuid = subprocess.check_output(
            ['findmnt', '--noheadings', '--output', 'UUID', '--target', str(root)],
            text=True).strip()
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        raise PlanError('Unable to configure Timeshift for the root filesystem') from exc
    if not isinstance(settings, dict) or not re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', uuid):
        raise PlanError('Unable to determine the Timeshift Btrfs filesystem UUID')
    settings.update({'backup_device_uuid': uuid, 'do_first_run': 'false',
                     'btrfs_mode': 'true', 'schedule_daily': 'true', 'count_daily': '5',
                     'schedule_hourly': 'false', 'schedule_weekly': 'false',
                     'schedule_monthly': 'false', 'schedule_boot': 'false',
                     'include_btrfs_home': 'false', 'include_btrfs_home_for_backup': 'false',
                     'include_btrfs_home_for_restore': 'false'})
    boot.write(root, '/etc/timeshift/timeshift.json', json.dumps(settings, indent=2) + '\n')
    # Timeshift evaluates its own schedule; the timer only invokes that check.
    boot.write(root, '/etc/systemd/system/archhelper-timeshift.service',
               '[Unit]\nDescription=Check Timeshift snapshot schedule\n'
               '[Service]\nType=oneshot\nExecStart=/usr/bin/timeshift --check --scripted\n')
    boot.write(root, '/etc/systemd/system/archhelper-timeshift.timer',
               '[Unit]\nDescription=Check Timeshift snapshot schedule hourly\n'
               '[Timer]\nOnCalendar=hourly\nPersistent=true\n'
               '[Install]\nWantedBy=timers.target\n')
    inst.enable_service('archhelper-timeshift.timer')


def configure_optional_services(inst, plan):
    """Mask unselected daemons even when desktop dependencies install them."""
    root = inst.target
    masked = []
    if plan.network != 'networkmanager':
        masked.append('NetworkManager.service')
    if plan.network != 'networkd':
        masked += ['systemd-networkd.service', 'systemd-networkd.socket']
    if not plan.bluetooth:
        masked.append('bluetooth.service')
    for name in masked:
        path = root / 'etc/systemd/system' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.unlink(missing_ok=True)
        path.symlink_to('/dev/null')
    if plan.network == 'networkmanager':
        inst.enable_service('NetworkManager')
    elif plan.network == 'networkd':
        boot.write(root, '/etc/systemd/network/20-wired.network',
                   '[Match]\nName=en* eth*\n\n[Network]\nDHCP=yes\n')
        inst.enable_service('systemd-networkd')
    if plan.bluetooth:
        inst.enable_service('bluetooth')


def configure_locale(inst, locale):
    """Enable an existing UTF-8 entry, including one already uncommented."""
    # glibc ships C.UTF-8 precompiled; it intentionally has no locale.gen row.
    if locale.lower().replace('-', '') == 'c.utf8':
        boot.write(inst.target, '/etc/locale.conf', 'LANG=C.UTF-8\n')
        return
    def parts(name):
        base, _, modifier = name.partition('@')
        base = base.split('.', 1)[0]
        modifier = modifier.split('.', 1)[0]
        return base, modifier

    target = inst.target
    locale_gen = target / 'etc/locale.gen'
    lines = locale_gen.read_text().splitlines(keepends=True)
    requested = parts(locale)
    for index, line in enumerate(lines):
        content = line.lstrip()
        if content.startswith('#'):
            content = content[1:].lstrip()
        fields = content.split()
        if len(fields) >= 2 and fields[1].upper() == 'UTF-8' and parts(fields[0]) == requested:
            if line.lstrip().startswith('#'):
                lines[index] = content
                locale_gen.write_text(''.join(lines))
            break
    else:
        raise PlanError(t('install.localeFailed'))
    inst.arch_chroot('locale-gen')
    base, modifier = requested
    boot.write(target, '/etc/locale.conf', f'LANG={base}.UTF-8' + (f'@{modifier}' if modifier else '') + '\n')


def configure_target(inst, plan, credentials):
    from archinstall.lib.models.users import User, Password
    root = inst.target
    hardware.configure(root, plan)
    inst.set_hostname(plan.hostname)
    configure_locale(inst, plan.locale)
    if not inst.set_timezone(plan.timezone):
        raise PlanError(t("install.localeFailed"))
    configure_keyboard(root, plan)
    if plan.desktop == 'gnome':
        inst.arch_chroot('dconf update')
    if plan.username != 'root':
        inst.create_users(User(plan.username, Password(credentials.password), True, ["audio", "video"]))
    if plan.root_enabled:
        root_password = credentials.password if plan.username == 'root' else credentials.root_password
        subprocess.run(['arch-chroot', str(root), 'chpasswd'], input='root:' + root_password + '\n', text=True, check=True)
    else:
        inst.arch_chroot("passwd -l root")
    # Verify each intended login is usable; upstream can return False on failure.
    shadow = {line.split(':', 1)[0]: line.split(':')[1] for line in (root / 'etc/shadow').read_text().splitlines()}
    for name in {plan.username} | ({'root'} if plan.root_enabled else set()):
        password_hash = shadow.get(name, '')
        if not password_hash or password_hash.startswith(('!', '*')):
            raise PlanError(t("install.userLocked"))
    login = desktop.profile(plan.desktop)
    if login['display_manager'] == 'sddm':
        inst.arch_chroot("chown -R sddm:sddm /var/lib/sddm")
        inst.arch_chroot("chmod 750 /var/lib/sddm")
    if login['service']:
        inst.enable_service(login['service'])
    for service in ("systemd-resolved", "ufw", "systemd-timesyncd"):
        inst.enable_service(service)
    configure_optional_services(inst, plan)
    if plan.zram:
        boot.write(root, "/etc/systemd/zram-generator.conf", "[zram0]\nzram-size = min(ram / 2, 4096)\n")
    inst.arch_chroot("systemctl set-default " + ("multi-user.target" if plan.desktop == "none" else "graphical.target"))
    for name in ("sshd.service", "sshd.socket"):
        path = root / "etc/systemd/system" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.unlink(missing_ok=True)
        path.symlink_to("/dev/null")
    generator = root / "etc/systemd/system-generators/systemd-ssh-generator"
    generator.parent.mkdir(parents=True, exist_ok=True)
    generator.unlink(missing_ok=True)
    generator.symlink_to("/dev/null")
    # ALARM base files can contain bootstrap identities; never retain them.
    if any(line.startswith("alarm:") for line in (root / "etc/passwd").read_text().splitlines()):
        inst.arch_chroot("userdel -r alarm")
    configure_firewall(root)
    inst.genfstab()
    configure_swap(inst, plan)
    inst.enable_periodic_trim()
    # The dedicated @snapshots mount already exists: create-config would collide.
    if plan.snapshots == "snapper":
        template_path = root / "usr/share/snapper/config-templates/default"
        if not template_path.exists():
            template_path = root / "etc/snapper/config-templates/default"
        template = template_path.read_text()
        template = re.sub(r'^SUBVOLUME=.*$', 'SUBVOLUME="/"', template, flags=re.M)
        template = re.sub(r'^FSTYPE=.*$', 'FSTYPE="btrfs"', template, flags=re.M)
        boot.write(root, "/etc/snapper/configs/root", template)
        boot.write(root, "/etc/conf.d/snapper", 'SNAPPER_CONFIGS="root"\n')
        inst.enable_service(["snapper-timeline.timer", "snapper-cleanup.timer"])
    elif plan.snapshots == "timeshift":
        configure_timeshift(inst)
    boot.write(root, "/var/lib/v8/schema.json", json.dumps({"system_schema": 1, "release": plan.release}) + "\n")


def close_target_mapping(config):
    """Never close a mapping on a different partition during failure cleanup."""
    if config is None or not Path("/dev/mapper/root").exists():
        return
    root = next((p for p in config.device_modifications[0].partitions if p.is_root()), None)
    if root is None or root.dev_path is None:
        return
    result = subprocess.run(["cryptsetup", "status", "root"], capture_output=True, text=True,
                            env=dict(os.environ, LC_ALL="C"))
    device = re.search(r"^\s*device:\s+(\S+)\s*$", result.stdout, re.M)
    if result.returncode == 0 and device and Path(device[1]).resolve() == Path(root.dev_path).resolve():
        subprocess.run(["cryptsetup", "close", "root"], check=True)


def execute(plan, credentials, confirmation, directory, *, loop_backing=None, callback=None):
    # Package/bootstrap directories must stay readable by normal target users.
    # Only journals and credential-free reports get explicit private modes.
    os.umask(0o022)
    journal = Journal(directory, ("preflight", "partition-format", "mount", "base-packages",
                                  "desktop-packages", "configuration", "boot", "verification"), callback)
    with open("/run/v8-installer.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if os.geteuid() != 0 or platform.system() != "Linux" or not Path("/sys/firmware/efi").exists():
            raise PlanError(t("install.requireRootUefi"))
        if platform.machine() != plan.architecture:
            raise PlanError(t("install.archMismatch"))
        plan.validate()
        credentials.validate(plan)
        if confirmation != plan.confirmation:
            raise PlanError(t("install.confirmationRequired"))
        if TARGET.is_symlink() or os.path.ismount(TARGET) or (TARGET.exists() and any(TARGET.iterdir())):
            raise PlanError(t("install.targetNotEmpty"))
        with journal.phase("preflight"):
            adapter.contract()
            manifest = desktop.profile(plan.desktop)
            if manifest.get("architecture") != plan.architecture:
                raise PlanError(t("install.payloadArch"))
            for variable in Path("/sys/firmware/efi/efivars").glob("SecureBoot-*"):
                if variable.read_bytes()[4:5] == b"\x01":
                    raise PlanError(t("install.secureBootOn"))
            if plan.luks and Path("/dev/mapper/root").exists():
                raise PlanError(t("install.rootMapped"))
            hardware.validate(plan, current=hardware.detect())
            remote, pacman_conf = payload.prepare(plan, manifest, directory)
            revalidate(plan, loop_backing=loop_backing)
            esp = next(p for p in plan.partitions if p.mount == "/efi")
            if esp.action == "keep":
                probe = Path("/run/v8-esp-preflight")
                if probe.is_symlink() or os.path.ismount(probe) or (probe.exists() and any(probe.iterdir())):
                    raise PlanError(t("install.espProbeBusy"))
                probe.mkdir(mode=0o700, exist_ok=True)
                subprocess.run(["mount", "-o", "ro,nosuid,nodev,noexec", esp.path, str(probe)], check=True)
                try:
                    if shutil.disk_usage(probe).free < 768 * 1024 ** 2:
                        raise PlanError(t("install.espSharedSpace"))
                finally:
                    subprocess.run(["umount", str(probe)], check=True)
            config = adapter.layout(plan, credentials.luks_password)
            revalidate(plan, loop_backing=loop_backing)
            atomic(directory / "plan.json", json.loads(plan.json()))
        # Lock our executor, not the block device: udev must read new metadata.
        try:
            with journal.phase("partition-format"):
                revalidate(plan, loop_backing=loop_backing)
                adapter.format_disk(config)
            inst = adapter.installer(TARGET, config, remote, plan.kernel, pacman_conf=pacman_conf)
            with journal.phase("mount"):
                inst.mount_ordered_layout()
            with journal.phase("base-packages"):
                inst.minimal_installation(mkinitcpio=False, locale_config=None)
            with journal.phase("desktop-packages"):
                desktop.configure(TARGET, plan)
            with journal.phase("configuration"):
                configure_target(inst, plan, credentials)
            with journal.phase("boot"):
                root_part = next(p for p in config.device_modifications[0].partitions if p.is_root())
                boot.configure(inst, plan, root_part)
            with journal.phase("verification"):
                inst.arch_chroot("pacman -Dk")
                desktop.verify(TARGET, plan)
                if plan.snapshots == "snapper":
                    inst.arch_chroot("snapper --no-dbus -c root create --read-only --description v8-initial")
                kernel_names = subprocess.check_output(["arch-chroot", str(TARGET), "pacman", "-Qq"], text=True).splitlines()
                from .plan import KERNELS
                if set(kernel_names) & set(sum((list(v) for v in KERNELS.values()), [])) != {plan.kernel}:
                    raise PlanError(t("install.kernelsDiff"))
                for name in ("sshd.service", "sshd.socket"):
                    if (TARGET / "etc/systemd/system" / name).readlink() != Path("/dev/null"):
                        raise PlanError(t("install.sshNotOff"))
                # Native package hooks already rebuilt caches. Avoid repeating
                # these expensive first-boot jobs under VM CPU emulation.
                inst.arch_chroot("/usr/lib/systemd/systemd-update-done")
                versions = subprocess.check_output(["arch-chroot", str(TARGET), "pacman", "-Q"], text=True)
                boot.write(TARGET, "/var/lib/v8-installer/packages.txt", versions)
                atomic(TARGET / "var/lib/v8-installer/plan.json", json.loads(plan.json()))
            atomic(TARGET / "var/lib/v8-installer/journal.json", {"steps": journal.steps})
            shutil.copy2(directory / "target-pacman.conf", TARGET / "etc/pacman.conf")
            shutil.copy2("/etc/pacman.d/mirrorlist", TARGET / "etc/pacman.d/mirrorlist")
        finally:
            # Unmount only our fixed target tree; never unmount an arbitrary disk.
            if os.path.ismount(TARGET):
                subprocess.run(["gpgconf", "--homedir", str(TARGET / "etc/pacman.d/gnupg"), "--kill", "all"], check=False)
                subprocess.run(["arch-chroot", str(TARGET), "gpgconf", "--homedir", "/etc/pacman.d/gnupg", "--kill", "all"], check=False)
                subprocess.run(["umount", "--recursive", str(TARGET)], check=True)
            if plan.luks:
                close_target_mapping(config)
        atomic(TARGET.parent / ("v8-last-result.json"), {"status": "completed", "report": str(directory)})
        return journal
