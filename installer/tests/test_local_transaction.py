"""Optional real pacman transaction using only existing local cached files."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest


def test_local_signed_package_roundtrip_in_user_namespace(tmp_path):
    required = ('unshare', 'pacman', 'pacman-key', 'pacman-conf', 'repo-add', 'gpg')
    if any(not shutil.which(name) for name in required):
        pytest.skip('Pacman and user namespaces are not available')
    probe = subprocess.run(['unshare', '--user', '--map-root-user', 'true'], capture_output=True)
    if probe.returncode:
        pytest.skip('Unprivileged user namespaces are unavailable')
    info = subprocess.run(['pacman', '-Si', 'amd-ucode'], capture_output=True, text=True)
    match = re.search(r'^Version\s*:\s*(\S+)', info.stdout, re.M)
    if not match:
        pytest.skip('amd-ucode is not present in the local sync database')
    name = f'amd-ucode-{match[1]}-any.pkg.tar.zst'
    cache = Path('/var/cache/pacman/pkg')
    required_files = [Path('/var/lib/pacman/sync/core.db'), cache/name, cache/(name+'.sig'),
                      Path('/etc/pacman.d/gnupg/pubring.gpg'), Path('/etc/pacman.d/gnupg/trustdb.gpg')]
    if not all(p.is_file() and os.access(p, os.R_OK) for p in required_files):
        pytest.skip('Signed package, repository database or public keyring not cached locally')
    script = r'''
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import os, shutil, subprocess, sys
sys.path.insert(0, sys.argv[1])
from v8_installer import payload
name = sys.argv[2]
with TemporaryDirectory(prefix='archhelper-transaction-', dir=sys.argv[3]) as tmp:
    root = Path(tmp)
    remote, report, tools, key, target_cache = (root/n for n in ('remote', 'report', 'tools', 'gnupg', 'target-cache'))
    for path in (remote, report, tools, key, target_cache): path.mkdir(mode=0o700)
    target = root/'target'
    (target/'var/lib/pacman').mkdir(parents=True)
    for filename in ('pubring.gpg', 'trustdb.gpg'): shutil.copy('/etc/pacman.d/gnupg/'+filename, key/filename)
    shutil.copy('/var/lib/pacman/sync/core.db', remote/'core.db')
    for filename in (name, name+'.sig'): shutil.copy('/var/cache/pacman/pkg/'+filename, remote/filename)
    wrapper = tools/'pacman-key'
    wrapper.write_text('#!/bin/sh\nexec /usr/bin/pacman-key --gpgdir "$ARCHHELPER_TEST_GPGDIR" "$@"\n')
    wrapper.chmod(0o755)
    os.environ.update(PATH=str(tools)+':'+os.environ['PATH'], ARCHHELPER_TEST_GPGDIR=str(key))
    conf = root/'source.conf'
    conf.write_text(f'[options]\nArchitecture = x86_64\nGPGDir = {key}\nSigLevel = Required DatabaseOptional\n[core]\nServer = file://{remote}\n')
    payload.CACHE = root/'cache'
    payload.target_packages = lambda plan, value: ['amd-ucode']
    def verify_fixture(plan, resolved): assert resolved == {'amd-ucode'}
    payload.validate_kernel_set = verify_fixture
    packages, local = payload._prepare(SimpleNamespace(), {}, report, conf)
    subprocess.run(['pacman', '--config', str(local), '--root', str(target), '--dbpath', str(target/'var/lib/pacman'),
                    '--cachedir', str(target_cache), '--logfile', str(root/'install.log'), '--gpgdir', str(key),
                    '-Sy', '--noconfirm', *packages], check=True)
    assert (target/'boot/amd-ucode.img').is_file()
    assert (report/'transaction.json').is_file()
    assert 'Server = file://' in (report/'target-pacman.conf').read_text()
'''
    engine = Path(__file__).resolve().parents[1]
    result = subprocess.run(['unshare', '--user', '--map-root-user', sys.executable, '-I', '-c', script,
                             str(engine), name, str(tmp_path)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
