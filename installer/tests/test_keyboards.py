from types import SimpleNamespace

import pytest

from v8_installer.install import configure_keyboard
from v8_installer.keyboards import validate
from v8_installer.plan import PlanError
from v8_installer import desktop


@pytest.mark.parametrize('console,xkb', [('fr', 'fr'), ('us', 'us'), ('fr', 'fr:bepo')])
def test_keyboard_layouts_and_variants_apply_to_console_and_greeter(tmp_path, console, xkb):
    validate(console, xkb)
    configure_keyboard(tmp_path, SimpleNamespace(keyboard=console, xkb=xkb))
    layout, _, variant = xkb.partition(':')
    assert (tmp_path / 'etc/vconsole.conf').read_text() == f'KEYMAP={console}\n'
    xorg = (tmp_path / 'etc/X11/xorg.conf.d/00-keyboard.conf').read_text()
    assert f'Option "XkbLayout" "{layout}"' in xorg
    assert f'Option "XkbVariant" "{variant}"' in xorg
    assert f'XKB_DEFAULT_VARIANT={variant}' in (tmp_path / 'etc/environment.d/60-keyboard.conf').read_text()
    assert f'XKB_DEFAULT_LAYOUT={layout}' in (tmp_path / 'etc/environment').read_text()


def test_plasma_layout_is_inherited_by_new_users(tmp_path):
    configure_keyboard(tmp_path, SimpleNamespace(keyboard='fr', xkb='fr:bepo', desktop='plasma'))
    config = (tmp_path / 'etc/skel/.config/kxkbrc').read_text()
    assert 'Use=true' in config and 'LayoutList=fr' in config and 'VariantList=bepo' in config


@pytest.mark.parametrize('xkb,expected', [('fr', "-layout fr -variant ''"),
                                           ('us', "-layout us -variant ''"),
                                           ('fr:bepo', '-layout fr -variant bepo')])
def test_sddm_initializes_the_core_keyboard(tmp_path, xkb, expected):
    configure_keyboard(tmp_path, SimpleNamespace(keyboard='fr', xkb=xkb, desktop='hyprland'))
    script = tmp_path / 'etc/sddm/Xsetup'
    assert expected in script.read_text()
    assert script.stat().st_mode & 0o111
    assert 'DisplayCommand=/etc/sddm/Xsetup' in (tmp_path / 'etc/sddm.conf.d/30-keyboard.conf').read_text()
    assert 'xorg-setxkbmap' in desktop.profile('hyprland')['target_packages']


def test_gnome_layout_applies_to_user_and_greeter_without_locking_it(tmp_path):
    configure_keyboard(tmp_path, SimpleNamespace(keyboard='fr', xkb='fr:bepo', desktop='gnome'))
    config = (tmp_path / 'etc/dconf/db/local.d/00-archhelper-keyboard').read_text()
    assert "sources=[('xkb', 'fr+bepo')]" in config
    assert 'system-db:local' in (tmp_path / 'etc/dconf/profile/user').read_text()
    assert 'system-db:local' in (tmp_path / 'etc/dconf/profile/gdm').read_text()
    assert not (tmp_path / 'etc/dconf/db/local.d/locks').exists()


def test_existing_environment_is_preserved_and_xkb_values_replaced(tmp_path):
    env = tmp_path / 'etc/environment'
    env.parent.mkdir(parents=True)
    env.write_text('LANG=fr_FR.UTF-8\nXKB_DEFAULT_LAYOUT=us\n')
    configure_keyboard(tmp_path, SimpleNamespace(keyboard='fr', xkb='fr'))
    assert env.read_text() == 'LANG=fr_FR.UTF-8\nXKB_DEFAULT_LAYOUT=fr\nXKB_DEFAULT_VARIANT=\n'


def test_rejects_untrusted_keyboard_values():
    with pytest.raises(PlanError):
        validate('fr', 'fr:evil\nINJECT=1')
