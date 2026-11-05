"""Vanilla Hyprland from Arch, with an SDDM login and a UWSM session."""
import re
from pathlib import Path

from . import boot
from .plan import PlanError

# Explicit package names from official Arch repositories; one desktop per plan.
BASE = "systemd-resolvconf ufw iptables dbus-broker-units neovim curl".split()
GRAPHICAL = "pipewire pipewire-pulse pipewire-alsa wireplumber polkit noto-fonts noto-fonts-emoji mesa xdg-utils xdg-user-dirs".split()
PROFILES = {
    'hyprland': dict(name='Hyprland', manager='sddm', service='sddm', session='hyprland-uwsm.desktop',
                    packages='hyprland uwsm sddm xorg-server xdg-desktop-portal-hyprland xdg-desktop-portal-gtk foot thunar fuzzel hyprpolkitagent wl-clipboard brightnessctl playerctl'),
    'plasma': dict(name='KDE Plasma', manager='plasma-login-manager', service='plasmalogin', session='plasma.desktop',
                   packages='plasma-meta plasma-login-manager konsole dolphin'),
    'gnome': dict(name='GNOME', manager='gdm', service='gdm', session='gnome.desktop',
                  packages='gnome-shell gnome-session gnome-control-center gnome-settings-daemon gnome-keyring gnome-backgrounds gdm nautilus gnome-console gnome-text-editor gvfs xdg-desktop-portal-gnome'),
    'niri': dict(name='Niri', manager='sddm', service='sddm', session='niri.desktop',
                 packages='niri sddm xorg-server xwayland-satellite xdg-desktop-portal-gnome xdg-desktop-portal-gtk alacritty fuzzel waybar mako polkit-gnome'),
    'sway': dict(name='Sway', manager='sddm', service='sddm', session='sway.desktop',
                 packages='sway sddm xorg-server foot wmenu swaybg swaylock swayidle i3status mako polkit-gnome xdg-desktop-portal-wlr xdg-desktop-portal-gtk'),
    'river': dict(name='River Classic', manager='sddm', service='sddm', session='river.desktop',
                  packages='river-classic sddm xorg-server foot fuzzel waybar mako polkit-gnome xdg-desktop-portal-wlr xdg-desktop-portal-gtk'),
    'labwc': dict(name='Labwc', manager='sddm', service='sddm', session='labwc.desktop',
                  packages='labwc sddm xorg-server foot bemenu mako polkit-gnome xdg-desktop-portal-wlr xdg-desktop-portal-gtk'),
    'wayfire': dict(name='Wayfire', manager='sddm', service='sddm', session='wayfire.desktop',
                    packages='wayfire wf-shell wcm sddm xorg-server foot mako polkit-gnome xdg-desktop-portal-wlr xdg-desktop-portal-gtk'),
    'cosmic': dict(name='COSMIC', manager='cosmic-greeter', service='cosmic-greeter', session='cosmic.desktop',
                   packages='cosmic-session cosmic-greeter cosmic-terminal cosmic-text-editor'),
    'lxqt': dict(name='LXQt (Wayland / Labwc)', manager='sddm', service='sddm', session='lxqt-wayland.desktop',
                 packages='lxqt-session lxqt-wayland-session lxqt-panel lxqt-config lxqt-runner lxqt-policykit lxqt-notificationd lxqt-powermanagement pcmanfm-qt qterminal labwc sddm xorg-server xdg-desktop-portal-lxqt'),
    'weston': dict(name='Weston', manager='sddm', service='sddm', session='weston.desktop',
                   packages='weston sddm xorg-server xdg-desktop-portal-gtk'),
    'none': dict(name='Console / TTY', manager='', service='', session='', packages=''),
}


def profile(desktop='hyprland'):
    if desktop not in PROFILES:
        raise PlanError('Unsupported desktop profile')
    value = PROFILES[desktop]
    packages = BASE + (GRAPHICAL if desktop != 'none' else []) + value['packages'].split()
    if value['manager'] == 'sddm':
        packages.append('xorg-setxkbmap')
    return {'schema_version': 3, 'architecture': 'x86_64', 'release': '0.2.0-preview1',
            'desktop': desktop, 'name': value['name'],
            'session': value['session'], 'display_manager': value['manager'],
            'service': value['service'], 'target_packages': sorted(set(packages))}


def _hyprland(root, plan):
    """Use the sample supplied by the installed package, matching its version.

    Keep upstream appearance and behavior; adapt apps, keyboard and session
    lifecycle. Refuse unexpected config formats instead of silently producing
    a broken session. Called before create_users so /etc/skel is copied once.
    """
    sample = root / 'usr/share/hypr/hyprland.lua'
    session = root / 'usr/share/wayland-sessions/hyprland-uwsm.desktop'
    if not sample.is_file() or not session.is_file():
        raise PlanError('The official Hyprland Lua configuration and UWSM session are required')
    entry = session.read_text()
    if not re.search(r'^Exec=uwsm start\b', entry, re.M):
        raise PlanError('The installed Hyprland session does not launch UWSM')
    config = sample.read_text()
    for key, value in {'terminal': 'uwsm app -- foot', 'fileManager': 'uwsm app -- thunar',
                       'menu': "fuzzel --launch-prefix='uwsm app --'"}.items():
        config, count = re.subn(r'^(\s*local\s+' + key + r'\s*=\s*)"[^"\n]*"',
                               lambda m: m[1] + '"' + value + '"', config, flags=re.M)
        if count != 1:
            raise PlanError('Unsupported upstream Hyprland sample: ' + key)
    from .keyboards import split as split_xkb
    layout, variant = split_xkb(getattr(plan, 'xkb', plan.keyboard))
    config += f'''\n-- Local keyboard and session integration; upstream appearance is preserved.
hl.config({{ input = {{ kb_layout = "{layout}", kb_variant = "{variant}" }} }})
hl.bind("SUPER + RETURN", hl.dsp.exec_cmd("uwsm app -- foot"))
hl.bind("SUPER + SPACE", hl.dsp.exec_cmd("fuzzel --launch-prefix='uwsm app --'"))
hl.bind("SUPER + SHIFT + M", hl.dsp.exec_cmd("uwsm stop"))
hl.on("hyprland.start", function()
    hl.exec_cmd("uwsm finalize")
    hl.exec_cmd("systemctl --user start hyprpolkitagent.service")
end)
'''
    boot.write(root, '/etc/skel/.config/hypr/hyprland.lua', config)


def configure(root, plan):
    value = profile(plan.desktop)
    if plan.desktop == 'hyprland':
        _hyprland(root, plan)
    elif plan.desktop == 'river':
        sample = root / 'usr/share/river-classic/example/init'
        if not sample.is_file():
            raise PlanError('The official River Classic example configuration is missing')
        boot.write(root, '/etc/skel/.config/river/init', sample.read_text(), mode=0o755)
    if value['session']:
        session = '/usr/share/wayland-sessions/' + value['session']
        if not (root / session.lstrip('/')).is_file():
            raise PlanError('Missing official Wayland session: ' + value['session'])
        if value['display_manager'] == 'sddm':
            boot.write(root, '/etc/sddm.conf.d/20-wayland.conf',
                       '[Users]\nHideUsers=root alarm\nRememberLastSession=true\n')
            boot.write(root, '/var/lib/sddm/state.conf',
                       f'[Last]\nUser={plan.username}\nSession={session}\n')
    boot.write(root, '/usr/share/arch-installer/README.txt',
               value['name'] + '\nLogin: ' + (value['display_manager'] or 'console') + '\n')
    if plan.plymouth:
        boot.write(root, '/etc/plymouth/plymouthd.conf', '[Daemon]\nTheme=bgrt\n')
    link = root / 'etc/resolv.conf'
    if link.is_symlink() or link.is_file():
        link.unlink()
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to('/run/systemd/resolve/stub-resolv.conf')


def verify(root, plan):
    value = profile(plan.desktop)
    if value['session'] and not (root / 'usr/share/wayland-sessions' / value['session']).is_file():
        raise PlanError('Installed Wayland session is missing')
    if value['service']:
        alias = root / 'etc/systemd/system/display-manager.service'
        if not alias.is_symlink() or alias.readlink().name != value['service'] + '.service':
            raise PlanError('The selected login manager is not enabled')
    if plan.desktop == 'hyprland':
        config = root / 'home' / plan.username / '.config/hypr/hyprland.lua'
        if not config.is_file():
            raise PlanError('Hyprland user configuration is missing')
