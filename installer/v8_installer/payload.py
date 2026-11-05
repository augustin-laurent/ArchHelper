"""Download and verify an official Arch package transaction before disk writes."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import urllib.request
from contextlib import contextmanager

from . import desktop, hardware
from .plan import PlanError

CACHE = Path('/run/arch-installer-packages')
CACHY_KEY = '882DCFE48E2051D48E2562ABF3B607488DB35A47'
CACHY_PACKAGE = 'https://mirror.cachyos.org/repo/x86_64/cachyos/cachyos-keyring-20240331-1-any.pkg.tar.zst'
PACMAN_CONF = Path('/etc/pacman.conf')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def manifest():
    # The profile is bundled with the engine, with no external desktop payload.
    return desktop.profile()


def target_packages(plan, value):
    optional = {'networkmanager': ['networkmanager'], 'networkd': [], 'none': []}[getattr(plan, 'network', 'networkmanager')]
    optional += {'snapper': ['snapper', 'snap-pac'], 'timeshift': ['timeshift'], 'none': []}[getattr(plan, 'snapshots', 'snapper')]
    optional += ['bluez', 'bluez-utils'] if getattr(plan, 'bluetooth', False) else []
    optional += ['zram-generator'] if getattr(plan, 'zram', False) else []
    optional += ['cachyos-keyring'] if getattr(plan, 'cachyos', False) else []
    remote = sorted(set(value['target_packages'] + hardware.packages(plan) + optional + getattr(plan, 'extra_packages', []) +
                        ['base', 'sudo', 'linux-firmware', 'mkinitcpio', plan.kernel,
                         'btrfs-progs', 'dosfstools', 'systemd-ukify'] + (['plymouth'] if plan.plymouth else [])))
    if any(not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9@_.+\-]*', p) for p in remote):
        raise PlanError('Invalid target package name')
    return remote


def _query(args):
    try:
        result = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=dict(os.environ, LC_ALL='C'), timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PlanError('Package preparation failed: ' + type(exc).__name__) from exc
    if result.returncode:
        raise PlanError('Package resolution failed: ' + (result.stderr.strip() or result.stdout.strip() or 'pacman error')[-4000:])
    return result.stdout


def _download(url, dest):
    # The official mirror rejects Python's default urllib user agent (HTTP 403).
    request = urllib.request.Request(url, headers={'User-Agent': 'archhelper-installer/1.0'})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read(16 * 1024 * 1024 + 1)
    if len(data) > 16 * 1024 * 1024:
        raise PlanError('CachyOS keyring download is too large')
    dest.write_bytes(data)


def bootstrap_cachyos(directory):
    """Install the upstream keyring only after verifying the pinned master key.

    This changes the ephemeral Arch live keyring/package database; no target disk
    is touched. The keyring is subsequently included in the target transaction.
    """
    _query(['pacman-key', '--recv-keys', CACHY_KEY, '--keyserver', 'hkps://keyserver.ubuntu.com'])
    _query(['pacman-key', '--lsign-key', CACHY_KEY])
    archive = Path(directory) / 'cachyos-keyring.pkg.tar.zst'
    signature = Path(str(archive) + '.sig')
    try:
        _download(CACHY_PACKAGE, archive)
        _download(CACHY_PACKAGE + '.sig', signature)
    except (OSError, ValueError) as exc:
        raise PlanError('Unable to download the signed CachyOS keyring') from exc
    gpgdir = _query(['pacman-conf', 'GPGDir']).strip()
    status = _query(['gpg', '--homedir', gpgdir, '--batch', '--status-fd', '1', '--verify', str(signature), str(archive)])
    valid = [line.split()[2:] for line in status.splitlines() if line.startswith('[GNUPG:] VALIDSIG ')]
    if not any(CACHY_KEY in row for row in valid):
        raise PlanError('CachyOS keyring signature does not match the pinned master key')
    _query(['pacman', '-U', '--needed', '--noconfirm', str(archive)])
    _query(['pacman-key', '--populate', 'cachyos'])


@contextmanager
def sources(directory, enabled):
    if not enabled:
        yield None
        return
    bootstrap_cachyos(directory)
    original = PACMAN_CONF.read_text()
    names = _query(['pacman-conf', '--repo-list']).splitlines()
    config = Path(directory) / 'sources.conf'
    if 'cachyos' not in names:
        original += '\n[cachyos]\nSigLevel = Required DatabaseOptional\nServer = https://mirror.cachyos.org/repo/x86_64/cachyos\n'
    # CachyOS's 580xx userspace currently requires multilib dependencies.
    if 'multilib' not in names:
        original += '\n[multilib]\nInclude = /etc/pacman.d/mirrorlist\n'
    config.write_text(original)
    yield config


def _database(directory, config=None):
    # pacman may drop download privileges to its dedicated alpm user. The
    # private TemporaryDirectory default (0700) would prevent that user from
    # traversing to its download directory before any transaction can resolve.
    os.chmod(directory, 0o755)
    db, cache = (Path(directory) / name for name in ('db', 'cache'))
    (db / 'local').mkdir(parents=True)
    cache.mkdir()
    db.chmod(0o755)
    cache.chmod(0o755)
    args = ['pacman', '--dbpath', str(db), '--cachedir', str(cache), '--logfile', str(Path(directory) / 'pacman.log')]
    if config:
        args += ['--config', str(config)]
    _query([*args, '-Sy', '--noconfirm'])
    return args


def catalog(cachyos=False):
    """List package names from freshly synchronized active repositories."""
    with tempfile.TemporaryDirectory(prefix='archhelper-packages-') as directory:
        with sources(directory, cachyos) as config:
            args = _database(directory, config)
            return sorted(set(_query([*args, '-Slq']).splitlines()))


def resolve(plan, value):
    """Resolve the complete target transaction before the destructive confirmation."""
    remote = target_packages(plan, value)
    with tempfile.TemporaryDirectory(prefix='archhelper-resolve-') as directory:
        with sources(directory, getattr(plan, 'cachyos', False)) as config:
            args = _database(directory, config)
            resolved = set(_query([*args, '-Sp', '--noconfirm', '--print-format', '%n', *remote]).splitlines())
        validate_kernel_set(plan, resolved)


def validate_kernel_set(plan, resolved):
    from .plan import KERNELS
    known_kernels = {name for names in KERNELS.values() for name in names}
    if resolved & known_kernels != {plan.kernel}:
        raise PlanError('Package selection would install additional or missing kernels')


def prepare(plan, value, directory):
    """Resolve in an empty database and retain signed packages before formatting."""
    with tempfile.TemporaryDirectory(prefix='archhelper-sources-') as temporary:
        with sources(temporary, getattr(plan, 'cachyos', False)) as config:
            return _prepare(plan, value, directory, config)


def _prepare(plan, value, directory, source_config):
    public = CACHE / directory.name
    public.mkdir(parents=True, exist_ok=True, mode=0o755)
    db, cache = (public / n for n in ('pacman-db', 'packages'))
    for path in (db / 'local', cache):
        path.mkdir(parents=True, exist_ok=True)
    remote = target_packages(plan, value)
    conf_args = ['--config', str(source_config)] if source_config else []
    repo_names = subprocess.check_output(['pacman-conf', *conf_args, '--repo-list'], text=True).splitlines()
    if not repo_names:
        raise PlanError('No active repositories are configured')
    # Resolve Include files while the live is intact. Preserve a self-contained
    # configuration so target upgrades do not depend on live-only mirrorlists.
    target_conf = subprocess.check_output(['pacman-conf', *conf_args], text=True)
    if '[options]' not in target_conf or any('[' + name + ']' not in target_conf for name in repo_names):
        raise PlanError('Unable to capture active repository configuration')
    (directory / 'target-pacman.conf').write_text(target_conf)
    args = ['pacman', '--dbpath', str(db), '--cachedir', str(cache), '--logfile', str(directory / 'pacman.log')]
    if source_config:
        args += ['--config', str(source_config)]
    env = dict(os.environ, LC_ALL='C')
    subprocess.run([*args, '-Sy', '--noconfirm'], check=True, env=env)
    # Re-resolve against the freshly synchronized databases immediately before
    # download: repositories may have changed since the review was displayed.
    result = subprocess.run([*args, '-Sp', '--noconfirm', '--print-format', '%n', *remote],
                            check=True, env=env, text=True, stdout=subprocess.PIPE)
    validate_kernel_set(plan, set(result.stdout.splitlines()))
    subprocess.run([*args, '-Sw', '--noconfirm', *remote], check=True, env=env)
    archives = sorted(p for p in cache.glob('*.pkg.tar.*') if not p.name.endswith('.sig'))
    if not archives:
        raise PlanError('Empty package transaction')
    for archive in archives:
        sig = archive.with_name(archive.name + '.sig')
        if not sig.is_file():
            raise PlanError('Missing official package signature: ' + archive.name)
        subprocess.run(['pacman-key', '--verify', str(sig), str(archive)], check=True)
    subprocess.run(['repo-add', str(cache / 'official-cache.db.tar.gz'), *map(str, archives)], check=True)
    conf = directory / 'pacman.conf'
    conf.write_text(f'[options]\nArchitecture = x86_64\nSigLevel = Required DatabaseOptional\nLocalFileSigLevel = Required\n[official-cache]\nServer = file://{cache}\n')
    (directory / 'transaction.json').write_text(json.dumps({p.name: digest(p) for p in archives}, indent=2) + '\n')
    return remote, conf
