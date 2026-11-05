import json
from types import SimpleNamespace

import pytest

from v8_installer.install import configure_optional_services, configure_timeshift
from v8_installer.plan import PlanError


@pytest.mark.parametrize('network,bluetooth,masked,enabled', [
    ('none', False, {'NetworkManager.service', 'systemd-networkd.service', 'systemd-networkd.socket', 'bluetooth.service'}, set()),
    ('networkd', True, {'NetworkManager.service'}, {'systemd-networkd', 'bluetooth'}),
    ('networkmanager', False, {'systemd-networkd.service', 'systemd-networkd.socket', 'bluetooth.service'}, {'NetworkManager'}),
])
def test_disabled_services_are_masked_even_if_packages_are_installed(tmp_path, network, bluetooth, masked, enabled):
    calls = []
    inst = SimpleNamespace(target=tmp_path, enable_service=calls.append)
    configure_optional_services(inst, SimpleNamespace(network=network, bluetooth=bluetooth))
    units = tmp_path / 'etc/systemd/system'
    actual = {p.name for p in units.iterdir()} if units.exists() else set()
    assert actual == masked and set(calls) == enabled
    assert all((units / name).readlink().as_posix() == '/dev/null' for name in masked)
    assert (tmp_path / 'etc/systemd/network/20-wired.network').exists() == (network == 'networkd')


def test_timeshift_uses_root_filesystem_and_enables_daily_snapshots(tmp_path, monkeypatch):
    template = tmp_path / 'etc/timeshift/default.json'
    template.parent.mkdir(parents=True)
    template.write_text(json.dumps({'backup_device_uuid': '', 'btrfs_mode': 'false',
                                    'do_first_run': 'true', 'schedule_daily': 'false',
                                    'include_btrfs_home': 'false'}))
    calls = []
    inst = SimpleNamespace(target=tmp_path, enable_service=calls.append)
    monkeypatch.setattr('v8_installer.install.subprocess.check_output',
                        lambda *args, **kwargs: '12345678-1234-1234-1234-123456789abc\n')
    configure_timeshift(inst)
    settings = json.loads((template.parent / 'timeshift.json').read_text())
    assert settings['backup_device_uuid'] == '12345678-1234-1234-1234-123456789abc'
    assert settings['btrfs_mode'] == 'true' and settings['schedule_daily'] == 'true'
    assert settings['count_daily'] == '5' and settings['include_btrfs_home'] == 'false'
    assert all(settings['schedule_' + period] == 'false' for period in ('hourly', 'weekly', 'monthly', 'boot'))
    assert calls == ['archhelper-timeshift.timer']
    assert '--check --scripted' in (tmp_path / 'etc/systemd/system/archhelper-timeshift.service').read_text()


def test_timeshift_refuses_unknown_filesystem_uuid(tmp_path, monkeypatch):
    template = tmp_path / 'etc/timeshift/default.json'
    template.parent.mkdir(parents=True)
    template.write_text('{}')
    monkeypatch.setattr('v8_installer.install.subprocess.check_output', lambda *args, **kwargs: 'invalid')
    with pytest.raises(PlanError, match='UUID'):
        configure_timeshift(SimpleNamespace(target=tmp_path))
    assert not (template.parent / 'timeshift.json').exists()
