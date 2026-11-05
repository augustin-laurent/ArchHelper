#!/usr/bin/env python3
"""Build a target-only desktop payload from pinned inputs; never modifies the host."""
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

INPUT = Path(os.environ.get("V8_INPUT", "/input"))
ROOT = Path(os.environ.get("ARCHHELPER_PAYLOAD", "/build/release/payload")) / "rootfs"
SOURCE = INPUT / "work/omarchy"
OMACONTROL_SOURCE = INPUT / "work/omacontrol"
LOCK = json.loads((INPUT / "sources.lock.json").read_text())
for row in LOCK["sources"]:
    path = INPUT / row["path"]
    actual = subprocess.check_output(["git", "-c", "safe.directory=" + str(path), "-C", str(path), "rev-parse", "HEAD"], text=True).strip()
    assert actual == row["commit"], row["path"]
assert not ROOT.exists(), "Use a fresh payload output directory"
ROOT.mkdir(parents=True)

def write(path, text, mode=0o644):
    target = ROOT / path.lstrip("/")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    target.chmod(mode)

def link(path, target):
    dest = ROOT / path.lstrip("/")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.symlink_to(target)

desktop = ROOT / 'usr/share/omarchy'
desktop.mkdir(parents=True)
for directory in ['shell', 'default', 'config', 'themes']:
    shutil.copytree(SOURCE / directory, desktop / directory, symlinks=True)
shutil.copy2(SOURCE / 'LICENSE', desktop / 'LICENSE')
# The OmaControl window ships as a regular plugin of the image; its git metadata stays out of it.
shutil.copytree(OMACONTROL_SOURCE, desktop / 'shell' / 'plugins' / 'omacontrol',
                symlinks=True, ignore=shutil.ignore_patterns('.git'))
decisions = {row['command']: row['decision'] for row in csv.DictReader(
    (INPUT / 'config/helper-decisions.csv').open())}
blocked = []
for src in sorted((SOURCE / 'bin').iterdir()):
    if not src.is_file():
        continue
    name = src.name
    unsafe = decisions.get(name) in ('replace', 'exclude') or name.startswith((
        'omarchy-install-', 'omarchy-setup-', 'omarchy-provision-',
        'omarchy-update', 'omarchy-pkg-', 'omarchy-migrate',
        'omarchy-dev-', 'omarchy-refresh-', 'omarchy-reset',
        'omarchy-snapshot', 'omarchy-bootloader', 'omarchy-kernel',
    ))
    if unsafe:
        blocked.append(name)
        write('/usr/bin/' + name, '#!/bin/bash\nprintf "%s\\n" "This helper is not supported by this ArchHelper release." >&2\nexit 69\n', 0o755)
    else:
        target = ROOT / 'usr/bin' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
        target.chmod(0o755)
    link('/usr/share/omarchy/bin/' + name, '/usr/bin/' + name)
write('/usr/share/v8-preview/disabled-helpers.json', json.dumps(blocked, indent=2) + '\n')
write('/usr/bin/omarchy-version', '#!/bin/bash\ncat /usr/share/omarchy/version\n', 0o755)
write('/usr/bin/omarchy-system-logout', '#!/bin/bash\nexec uwsm stop\n', 0o755)

write('/usr/share/omarchy/default/omarchy/omarchy-menu.jsonc', json.dumps({
    'root': {'label': 'ArchHelper'},
    'root.apps': {'label': 'Applications', 'provider': 'apps'},
    'root.terminal': {'label': 'Terminal', 'action': 'uwsm app -- foot'},
    'root.browser': {'label': 'Browser', 'action': 'uwsm app -- chromium'},
    'root.files': {'label': 'Files', 'action': 'uwsm app -- nautilus'},
    'root.lock': {'label': 'Lock', 'action': 'omarchy-system-lock'},
    'root.logout': {'label': 'Log out', 'action': 'uwsm stop'},
    'root.reboot': {'label': 'Restart', 'action': 'systemctl reboot'},
    'root.shutdown': {'label': 'Shut down', 'action': 'systemctl poweroff'},
}, indent=2) + '\n')
write('/etc/profile.d/v8-preview.sh', 'export OMARCHY_PATH=/usr/share/omarchy\n')
write('/usr/share/v8-preview/sessions/v8-preview.desktop', "[Desktop Entry]\nName=ArchHelper\nExec=uwsm start -g -1 -e -D Hyprland hyprland.desktop\nTryExec=uwsm\nType=Application\n")
write('/etc/sddm.conf.d/10-archhelper.conf', "[General]\nDisplayServer=x11\n[Theme]\nCurrent=v8-preview\n[Wayland]\nSessionDir=/usr/share/v8-preview/sessions\n")
shutil.copytree(SOURCE / 'default/sddm/omarchy', ROOT / 'usr/share/sddm/themes/v8-preview')
write('/etc/systemd/user/v8-shell.service', "[Unit]\nDescription=ArchHelper desktop shell\nPartOf=graphical-session.target\nAfter=graphical-session.target\n[Service]\nExecStart=/usr/bin/omarchy-launch-shell\nRestart=on-failure\nRestartSec=2\n")
link('/etc/systemd/user/graphical-session.target.wants/owed.service', '/usr/lib/systemd/user/owed.service')
link('/etc/resolv.conf', '/run/systemd/resolve/stub-resolv.conf')
write('/etc/plymouth/plymouthd.conf', '[Daemon]\nTheme=bgrt\nShowDelay=0\n')

shell_config = json.loads((SOURCE / 'config/omarchy/shell.json').read_text())
for side, widgets in shell_config['bar']['layout'].items():
    shell_config['bar']['layout'][side] = [w for w in widgets if w['id'] not in (
        'omarchy.system-update', 'omarchy.agents', 'omarchy.weather', 'omarchy.elsewhen',
    )]
# The OmaControl gear: the plugin's own window; its manifest asks for the right section.
shell_config['bar']['layout']['right'].append({'id': 'io.github.twiking.omacontrol'})
shell_config['dock']['pinned'] = ['org.gnome.Nautilus', 'chromium', 'foot']
shell_config['idle'] = {'screensaver': 0, 'lock': 0}
write('/usr/share/omarchy/config/omarchy/shell.json', json.dumps(shell_config, indent=2) + '\n')
write('/etc/skel/.config/hypr/hyprland.lua', '''dofile('/usr/share/omarchy/default/hypr/bootstrap.lua')
require('default.hypr.helpers')
require('default.hypr.looknfeel')
require('default.hypr.input')
require('default.hypr.monitor-workspaces')
require('default.hypr.bindings.tiling')
hl.monitor({ output = '', mode = 'preferred', position = 'auto', scale = 1 })
o.bind('SUPER + RETURN', 'Terminal', 'uwsm app -- foot')
o.bind('SUPER + SPACE', 'Menu', { menu = 'root' })
o.bind('SUPER + B', 'Browser', 'uwsm app -- chromium')
o.bind('SUPER + E', 'Files', 'uwsm app -- nautilus')
o.bind('SUPER + ESCAPE', 'Lock', 'omarchy-system-lock')
hl.on('hyprland.start', function()
  hl.exec_cmd('uwsm finalize')
  hl.exec_cmd('systemctl --user start v8-shell.service')
end)
''')
for directory in ['foot', 'gtk-3.0', 'gtk-4.0', 'fontconfig', 'omarchy']:
    if (SOURCE / 'config' / directory).is_dir():
        shutil.copytree(SOURCE / 'config' / directory, ROOT / 'etc/skel/.config' / directory, dirs_exist_ok=True, symlinks=True)
write('/etc/skel/.config/omarchy/shell.json', json.dumps(shell_config, indent=2) + '\n')
write('/etc/skel/.bashrc', '. /etc/profile.d/v8-preview.sh\n')
fonts = ROOT / 'usr/share/fonts/v8-preview'
shutil.copytree(SOURCE / 'default/fonts/omarchy', fonts)
shutil.copytree(SOURCE / 'etc/xkb', ROOT / 'etc/xkb')
packages = """base linux-firmware mkinitcpio archlinux-keyring bash sudo less neovim jq gum git python python-gobject
networkmanager systemd-resolvconf ufw iptables sddm xorg-server hyprland uwsm libnewt
xdg-desktop-portal-hyprland xdg-desktop-portal-gtk xdg-utils xdg-user-dirs xdg-terminal-exec
foot chromium nautilus pipewire pipewire-pulse pipewire-alsa wireplumber polkit inotify-tools
plymouth qt6-5compat qt6-imageformats noto-fonts noto-fonts-emoji ttf-jetbrains-mono-nerd
adwaita-icon-theme mesa mesa-utils libnotify wl-clipboard grim slurp imagemagick bluez
bluez-utils upower power-profiles-daemon brightnessctl pciutils util-linux procps-ng socat curl wget unzip
snapper snap-pac btrfs-progs dosfstools systemd-ukify""".split()
repo = Path(os.environ.get('V8_REPO', '/build/repo'))
local_packages, provides, dependencies = [], set(), set()
for name in ('v8-quickshell', 'owe', 'owe-lockfeed'):
    archives = list(repo.glob(name + '-[0-9]*.pkg.tar.*'))
    archives = [p for p in archives if not p.name.endswith('.sig')]
    assert len(archives) == 1, (name, archives)
    source = archives[0]
    metadata = subprocess.check_output(['bsdtar', '-xOf', str(source), '.PKGINFO'], text=True)
    for line in metadata.splitlines():
        if line.startswith(('depend = ', 'provides = ', 'pkgname = ')):
            key, val = line.split(' = ', 1)
            val = __import__('re').split(r'[<>=]', val)[0]
            (dependencies if key == 'depend' else provides).add(val)
    dest = ROOT.parent / 'packages' / source.name
    dest.parent.mkdir(exist_ok=True)
    shutil.copy2(source, dest)
    local_packages.append({'name': name, 'file': source.name, 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()})
packages = sorted(set(packages) | (dependencies - provides))
# Soname dependencies are resolved by pacman's providers; release packages use normal names.
assert all('.so' not in p for p in packages), 'Resolve soname dependencies explicitly in the recipe'
files = []
for file in sorted(ROOT.rglob('*')):
    name = '/' + str(file.relative_to(ROOT))
    if file.is_symlink():
        files.append({'path': name, 'link': str(file.readlink())})
    elif file.is_file():
        files.append({'path': name, 'sha256': hashlib.sha256(file.read_bytes()).hexdigest()})
qt = {}
for name in ('qt6-base', 'qt6-declarative', 'qt6-wayland'):
    qt[name] = subprocess.check_output(['pacman', '-Q', name], text=True).split()[1]
manifest = {'schema_version': 2, 'architecture': 'x86_64', 'release': '0.2.0-preview1',
            'target_packages': packages, 'files': files, 'local_packages': local_packages,
            'qt_versions': qt, 'sources': LOCK['sources']}
(ROOT.parent / 'payload.json').write_text(json.dumps(manifest, indent=2) + '\n')
print('Desktop payload:', ROOT.parent)
