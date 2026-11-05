#!/usr/bin/env python3
"""Fetch pinned inputs, and write the single isolated Linux builder config."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((ROOT / 'sources.lock.json').read_text())


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def download(url, dest, expected=None):
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and expected and hashlib.sha256(dest.read_bytes()).hexdigest() == expected:
        return
    tmp = dest.with_suffix(dest.suffix + '.part')
    try:
        with urllib.request.urlopen(url, timeout=120) as response, tmp.open('wb') as stream:
            shutil.copyfileobj(response, stream)
        if expected and hashlib.sha256(tmp.read_bytes()).hexdigest() != expected:
            raise RuntimeError('Checksum incorrect : ' + url)
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)


def source_path(root, relative):
    path = root / relative
    if not relative.startswith('work/') or '..' in Path(relative).parts or not path.resolve().is_relative_to((root / 'work').resolve()):
        raise ValueError('Chemin source hors du répertoire work')
    return path


def fetch(root=ROOT, sources=None):
    for row in sources if sources is not None else LOCK['sources']:
        path = source_path(root, row['path'])
        if path.exists() and not (path / '.git').exists() and any(path.iterdir()):
            raise RuntimeError('Répertoire source occupé : ' + str(path))
        if not (path / '.git').exists():
            path.mkdir(parents=True, exist_ok=True)
            run('git', 'init', str(path))
        if run('git', '-C', str(path), 'status', '--porcelain', '--untracked-files=no'):
            raise RuntimeError('Source modifiée : ' + str(path))
        run('git', '-C', str(path), 'fetch', '--depth=1', row['url'], row['commit'])
        run('git', '-C', str(path), 'checkout', '--detach', row['commit'])
        assert run('git', '-C', str(path), 'rev-parse', 'HEAD') == row['commit']
        if row.get('tag'):
            tag = row['tag']
            run('git', '-C', str(path), 'fetch', '--depth=1', row['url'], f'refs/tags/{tag}:refs/tags/{tag}')
            if run('git', '-C', str(path), 'rev-parse', f'{tag}^{{commit}}') != row['commit']:
                raise RuntimeError('Tag déplacé : ' + tag)
        print(row['path'] + ' @ ' + row['commit'], flush=True)


def config(root=ROOT):
    image = LOCK['ubuntu_builder']
    return f'''minimumLimaVersion: 2.2.1
vmType: qemu
arch: x86_64
cpus: 4
memory: 8GiB
disk: 65GiB
cpuType:
  x86_64: host
images:
  - location: {json.dumps(image['url'])}
    arch: x86_64
    digest: sha256:{image['sha256']}
mountType: 9p
mounts:
  - location: {json.dumps(str(root))}
    mountPoint: /input
    writable: false
  - location: {json.dumps(str(root / 'dist'))}
    mountPoint: /output
    writable: true
containerd:
  system: false
  user: false
portForwards:
  - guestPortRange: [1, 65535]
    ignore: true
provision:
  - mode: system
    script: |
      #!/bin/bash
      set -eu
      printf 'v8-isolated-builder-v1\\n' >/etc/v8-build-vm
'''


def prepare():
    fetch()
    base = ROOT / 'work/builder'
    bootstrap = LOCK['arch_bootstrap']
    archive = base / 'archlinux-bootstrap-2026.10.01-x86_64.tar.zst'
    download(bootstrap['url'], archive, bootstrap['sha256'])
    download(bootstrap['url'] + '.sig', archive.with_suffix(archive.suffix + '.sig'))
    lima = LOCK['lima']
    download(lima['url'], base / 'lima-linux.tar.gz', lima['sha256'])
    (ROOT / 'dist').mkdir(exist_ok=True)
    (base / 'v8-builder.yaml').write_text(config())


if __name__ == '__main__':
    prepare()
