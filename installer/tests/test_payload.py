from pathlib import Path
from types import SimpleNamespace

import pytest
from v8_installer import desktop, payload
from v8_installer.plan import PlanError


def transaction(tmp_path, monkeypatch, *, signed=True, repos='core\nextra\n'):
    monkeypatch.setattr(payload, 'CACHE', tmp_path/'cache')
    calls=[]
    def output(args, **kw):
        calls.append(args)
        if '--repo-list' in args:
            return repos
        return '[options]\n' + ''.join('[' + repo + ']\nServer = https://example.invalid/' + repo + '\n' for repo in repos.splitlines())
    def run(args, **kw):
        calls.append(args)
        if '-Sw' in args:
            cache=Path(args[args.index('--cachedir')+1])
            (cache/'base-1-1-any.pkg.tar.zst').write_bytes(b'archive')
            if signed:
                (cache/'base-1-1-any.pkg.tar.zst.sig').write_bytes(b'signature')
        return SimpleNamespace(returncode=0, stdout='linux\n' if '-Sp' in args else '')
    monkeypatch.setattr(payload.subprocess, 'check_output', output)
    monkeypatch.setattr(payload.subprocess, 'run', run)
    plan=SimpleNamespace(hardware={}, graphics='mesa', kernel='linux', plymouth=True)
    report=tmp_path/'session';report.mkdir()
    return plan, report, calls


def test_fresh_database_requires_signatures_and_has_no_unsigned_local_repository(tmp_path,monkeypatch):
    plan,report,calls=transaction(tmp_path,monkeypatch)
    remote,conf=payload.prepare(plan,desktop.profile('plasma'),report)
    assert '--dbpath' in next(c for c in calls if '-Sw' in c)
    verify=next(i for i,c in enumerate(calls) if c[0]=='pacman-key')
    repo=next(i for i,c in enumerate(calls) if c[0]=='repo-add')
    assert verify<repo and 'Server = file://' in conf.read_text()
    assert 'plasma-login-manager' in remote and 'sddm' not in remote
    assert 'SigLevel = Required' in conf.read_text()
    assert 'Optional\nServer' not in conf.read_text()
    assert '[extra]' in (report / 'target-pacman.conf').read_text()
    assert not any('-Si' in c for c in calls) # no custom Qt build to match


def test_missing_signature_stops_before_repository_is_created(tmp_path,monkeypatch):
    plan,report,calls=transaction(tmp_path,monkeypatch,signed=False)
    with pytest.raises(PlanError,match='signature'):
        payload.prepare(plan,desktop.profile(),report)
    assert not any(c[0]=='repo-add' for c in calls)


def test_active_additional_repositories_still_require_package_signatures(tmp_path,monkeypatch):
    plan,report,calls=transaction(tmp_path,monkeypatch,repos='core\ncustom\n')
    payload.prepare(plan,desktop.profile(),report)
    assert any(c[0] == 'pacman-key' and '--verify' in c for c in calls)


@pytest.mark.parametrize('network,snapshots,bluetooth,zram,expected,absent', [
    ('none', 'none', False, False, set(), {'networkmanager', 'snapper', 'timeshift', 'bluez', 'zram-generator'}),
    ('networkd', 'timeshift', True, True, {'timeshift', 'bluez', 'bluez-utils', 'zram-generator'}, {'networkmanager', 'snapper'}),
    ('networkmanager', 'snapper', False, False, {'networkmanager', 'snapper', 'snap-pac'}, {'timeshift', 'bluez', 'zram-generator'}),
])
def test_optional_packages_follow_plan(tmp_path, monkeypatch, network, snapshots, bluetooth, zram, expected, absent):
    plan, report, _ = transaction(tmp_path, monkeypatch)
    plan.network, plan.snapshots, plan.bluetooth, plan.zram = network, snapshots, bluetooth, zram
    remote, _ = payload.prepare(plan, desktop.profile('none'), report)
    assert expected <= set(remote)
    assert not absent & set(remote)


def test_catalog_and_resolution_use_isolated_database(monkeypatch):
    calls = []
    def query(args):
        calls.append(args)
        if '-Slq' in args:
            return 'git\nvim\ngit\n'
        if '-Sp' in args:
            return 'base\nlinux\ngit\n'
        return ''
    monkeypatch.setattr(payload, '_query', query)
    assert payload.catalog() == ['git', 'vim']
    plan = SimpleNamespace(hardware={}, graphics='mesa', kernel='linux', plymouth=False, extra_packages=['git'])
    payload.resolve(plan, desktop.profile('none'))
    assert all('--dbpath' in c for c in calls)
    assert 'git' in next(c for c in calls if '-Sp' in c)


def test_temporary_database_is_traversable_by_pacman_download_user(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    monkeypatch.setattr(payload, '_query', lambda args: '')
    payload._database(tmp_path)
    assert tmp_path.stat().st_mode & 0o777 == 0o755
    assert (tmp_path/'db').stat().st_mode & 0o777 == 0o755
    assert (tmp_path/'cache').stat().st_mode & 0o777 == 0o755


def test_resolution_rejects_additional_kernel(monkeypatch):
    monkeypatch.setattr(payload, '_query', lambda args: 'linux\nlinux-lts\n' if '-Sp' in args else '')
    plan = SimpleNamespace(hardware={}, graphics='mesa', kernel='linux', plymouth=False, extra_packages=['linux-lts'])
    with pytest.raises(PlanError, match='kernels'):
        payload.resolve(plan, desktop.profile('none'))


def test_preparation_rechecks_kernel_before_package_download(tmp_path, monkeypatch):
    plan, report, calls = transaction(tmp_path, monkeypatch)
    original = payload.subprocess.run
    def changed(args, **kwargs):
        if '-Sp' in args:
            calls.append(args)
            return SimpleNamespace(returncode=0, stdout='linux\nlinux-lts\n')
        return original(args, **kwargs)
    monkeypatch.setattr(payload.subprocess, 'run', changed)
    with pytest.raises(PlanError, match='kernels'):
        payload.prepare(plan, desktop.profile('none'), report)
    assert not any('-Sw' in c for c in calls)


def test_cachyos_bootstrap_verifies_pinned_signer_before_install(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(payload, '_download', lambda url, dest: dest.write_bytes(b'test'))
    def query(args):
        calls.append(args)
        if args[:2] == ['pacman-conf', 'GPGDir']:
            return '/tmp/gnupg\n'
        if args[0] == 'gpg':
            return '[GNUPG:] VALIDSIG ' + payload.CACHY_KEY + ' 0 0 0 0 0 0 0 0 ' + payload.CACHY_KEY + '\n'
        return ''
    monkeypatch.setattr(payload, '_query', query)
    payload.bootstrap_cachyos(tmp_path)
    assert next(i for i, c in enumerate(calls) if c[0] == 'gpg') < next(i for i, c in enumerate(calls) if c[:2] == ['pacman', '-U'])
    assert ['pacman-key', '--populate', 'cachyos'] in calls


def test_cachyos_download_identifies_the_installer(tmp_path, monkeypatch):
    import io
    requests = []
    def open_url(request, **kwargs):
        requests.append(request)
        return io.BytesIO(b'keyring')
    monkeypatch.setattr(payload.urllib.request, 'urlopen', open_url)
    dest = tmp_path / 'keyring'
    payload._download(payload.CACHY_PACKAGE, dest)
    assert dest.read_bytes() == b'keyring'
    assert requests[0].get_header('User-agent') == 'archhelper-installer/1.0'


def test_cachyos_bootstrap_refuses_unexpected_signer(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(payload, '_download', lambda url, dest: dest.write_bytes(b'test'))
    def query(args):
        calls.append(args)
        return '[GNUPG:] VALIDSIG ' + 'A' * 40 + ' 0 0 0\n' if args[0] == 'gpg' else '/tmp/gnupg\n'
    monkeypatch.setattr(payload, '_query', query)
    with pytest.raises(PlanError, match='pinned master'):
        payload.bootstrap_cachyos(tmp_path)
    assert not any(c[:2] == ['pacman', '-U'] for c in calls)


def test_cachyos_sources_only_when_enabled(tmp_path, monkeypatch):
    original = tmp_path / 'original.conf'
    original.write_text('[options]\n[core]\nServer = https://arch.invalid\n')
    monkeypatch.setattr(payload, 'PACMAN_CONF', original)
    calls = []
    monkeypatch.setattr(payload, 'bootstrap_cachyos', lambda directory: calls.append(directory))
    monkeypatch.setattr(payload, '_query', lambda args: 'core\n')
    with payload.sources(tmp_path, False) as config:
        assert config is None and not calls
    with payload.sources(tmp_path, True) as config:
        assert '[cachyos]' in config.read_text() and '[multilib]' in config.read_text() and calls
    plan = SimpleNamespace(hardware={}, graphics='mesa', kernel='linux-cachyos', plymouth=False, cachyos=True)
    assert 'cachyos-keyring' in payload.target_packages(plan, desktop.profile('none'))
