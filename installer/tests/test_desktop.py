from pathlib import Path
from types import SimpleNamespace

import pytest
from v8_installer import desktop
from v8_installer.plan import Disk, GIB, MIB, PlanError, automatic
from v8_installer.review import summary


def test_desktop_changes_are_bound_to_confirmation_and_summary():
    disk=Disk('/dev/vdb',40*GIB,512,'fixture','Fixture','gpt',[],[(MIB,40*GIB-2*MIB)])
    plan=automatic(disk,'wipe','x86_64')
    before=plan.confirmation
    plan.desktop='plasma'
    assert plan.confirmation!=before
    assert 'KDE Plasma' in summary(plan) and 'plasma-login-manager' in summary(plan)
    plan.desktop='invented'
    with pytest.raises(PlanError,match='desktop'):plan.validate()


@pytest.mark.parametrize('name',desktop.PROFILES)
def test_profile_is_isolated_and_contains_no_custom_desktop(name):
    value=desktop.profile(name)
    packages=value['target_packages']
    forbidden=('omarchy','archhelper','quickshell','omacontrol')
    assert not any(any(word in package for word in forbidden) for package in packages)
    assert not set(packages)&{'owe','owe-lockfeed','v8-quickshell'}
    managers=set(packages)&{'sddm','gdm','plasma-login-manager','cosmic-greeter'}
    assert managers==({value['display_manager']} if value['display_manager'] else set())
    assert ('uwsm' in packages)==(name=='hyprland')
    if name=='none':assert not value['session'] and 'pipewire' not in packages


def install_fixture(root,name):
    plan=SimpleNamespace(desktop=name,keyboard='fr',username='alice',plymouth=True)
    value=desktop.profile(name)
    if value['session']:
        session=root/'usr/share/wayland-sessions'/value['session']
        session.parent.mkdir(parents=True)
        session.write_text('[Desktop Entry]\nExec=uwsm start -- hyprland.desktop\n')
    if name=='hyprland':
        sample=root/'usr/share/hypr/hyprland.lua';sample.parent.mkdir(parents=True)
        sample.write_text('-- upstream look\nlocal terminal = "kitty"\nlocal fileManager = "dolphin"\nlocal menu = "hyprlauncher"\n')
    if name=='river':
        sample=root/'usr/share/river-classic/example/init';sample.parent.mkdir(parents=True)
        sample.write_text('#!/bin/sh\nriverctl map normal Super Return spawn foot\n')
    return plan


@pytest.mark.parametrize('name',desktop.PROFILES)
def test_configure_uses_only_the_chosen_login_manager(tmp_path,name):
    plan=install_fixture(tmp_path,name)
    desktop.configure(tmp_path,plan)
    assert (tmp_path/'etc/sddm.conf.d/20-wayland.conf').exists()==(desktop.profile(name)['display_manager']=='sddm')
    if name=='hyprland':
        text=(tmp_path/'etc/skel/.config/hypr/hyprland.lua').read_text()
        assert '-- upstream look' in text and 'uwsm finalize' in text
        assert 'uwsm app -- foot' in text and 'kb_layout = "fr", kb_variant = ""' in text
        assert 'omarchy' not in text
        assert 'hyprland-uwsm.desktop' in (tmp_path/'var/lib/sddm/state.conf').read_text()
    if name=='river':assert (tmp_path/'etc/skel/.config/river/init').stat().st_mode&0o111
    assert (tmp_path/'etc/resolv.conf').readlink()==Path('/run/systemd/resolve/stub-resolv.conf')


def test_hyprland_refuses_unmanaged_session_and_missing_upstream_config(tmp_path):
    plan=install_fixture(tmp_path,'hyprland')
    session=tmp_path/'usr/share/wayland-sessions/hyprland-uwsm.desktop'
    session.write_text('[Desktop Entry]\nExec=Hyprland\n')
    with pytest.raises(PlanError,match='UWSM'):desktop.configure(tmp_path,plan)
    session.write_text('[Desktop Entry]\nExec=uwsm start -- hyprland.desktop\n')
    (tmp_path/'usr/share/hypr/hyprland.lua').unlink()
    with pytest.raises(PlanError,match='configuration'):desktop.configure(tmp_path,plan)


def test_wrong_enabled_login_manager_fails_verification(tmp_path):
    plan=install_fixture(tmp_path,'plasma')
    alias=tmp_path/'etc/systemd/system/display-manager.service'
    alias.parent.mkdir(parents=True);alias.symlink_to('/usr/lib/systemd/system/sddm.service')
    with pytest.raises(PlanError,match='login manager'):desktop.verify(tmp_path,plan)
    alias.unlink();alias.symlink_to('/usr/lib/systemd/system/plasmalogin.service')
    desktop.verify(tmp_path,plan)
