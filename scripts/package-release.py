#!/usr/bin/env python3
"""Assemble one runnable Bash installer; the target never compiles Go."""
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile


def build_script(template, stage, destination):
    if not (stage/'arch-install').is_file() or not (stage/'engine/run.py').is_file():
        raise RuntimeError('A compiled interface and complete Python engine are required')
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode='w:gz') as archive:
        archive.add(stage/'arch-install', arcname='installer/arch-install')
        archive.add(stage/'engine', arcname='installer/engine',
                    filter=lambda info: None if '__pycache__' in Path(info.name).parts else info)
    packed = data.getvalue()
    content = template.read_text()
    placeholder = "readonly bundle_sha256='@BUNDLE_SHA256@'"
    if content.count(placeholder) != 1:
        raise RuntimeError('Invalid launcher template')
    content = content.replace(placeholder, "readonly bundle_sha256='" + hashlib.sha256(packed).hexdigest() + "'")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content.encode() + b'\n__ARCH_INSTALL_BUNDLE__\n' + base64.encodebytes(packed))
    destination.chmod(0o755)
    return destination


def package(root, stage, output, vendor=None):
    version = '0.2.0-preview1'
    def git(*args):
        return subprocess.check_output(['git','-c','safe.directory='+str(root),'-C',str(root),*args],text=True)
    if not (stage/'arch-install').is_file() or not (stage/'engine/run.py').is_file():
        raise RuntimeError('A compiled interface and complete Python engine are required')
    extra = git('ls-files','--others','--exclude-standard','-z').strip('\0')
    if extra:
        raise RuntimeError('Untracked files present: review and track sources before packaging')
    output.mkdir(parents=True, exist_ok=True)
    installer = build_script(root/'install.sh', stage, output/'install.sh')
    sources = output/f'arch-installer-{version}-sources.tar.gz'
    with tarfile.open(sources, 'w:gz') as archive:
        for name in git('ls-files','-z').split('\0'):
            path = root/name
            if name and path.is_file():
                archive.add(path, arcname='arch-installer/'+name)
        if vendor:
            archive.add(vendor, arcname='arch-installer/installer/tui/vendor')
    provenance = {'version': version, 'architecture': 'x86_64',
                  'source_commit': git('rev-parse','HEAD').strip(),
                  'source_dirty': bool(git('status','--porcelain')),
                  'validation': 'Build only. ISO installation, boot and each desktop session require qualification.',
                  'desktop_packages': 'Official Arch repositories only; resolved before disk writes.'}
    (output/'build-inputs.json').write_text(json.dumps(provenance, indent=2)+'\n')
    shutil.copy2(root/'LICENSE', output/'LICENSE')
    artifacts = [installer, sources, output/'build-inputs.json', output/'LICENSE']
    (output/'SHA256SUMS').write_text(''.join(hashlib.file_digest(p.open('rb'),'sha256').hexdigest()+'  '+p.name+'\n' for p in artifacts))
    return installer


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--vendor',type=Path)
    args = parser.parse_args()
    print(package(Path(__file__).resolve().parents[1], args.stage, args.output, args.vendor))
