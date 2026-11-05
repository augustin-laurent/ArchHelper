import base64
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('package_release',ROOT/'scripts/package-release.py')
release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)


def stage_fixture(tmp_path):
    stage=tmp_path/'stage';(stage/'engine').mkdir(parents=True)
    (stage/'arch-install').write_text('#!/bin/sh\nprintf "DEMO-BINARY-EXECUTED %s\\n" "$*"\n')
    (stage/'arch-install').chmod(0o755)
    (stage/'engine/run.py').write_text('raise SystemExit("Demo must not run the engine")\n')
    return stage


def test_release_requires_compiled_interface_and_complete_engine(tmp_path):
    with pytest.raises(RuntimeError,match='complete'):
        release.package(tmp_path,tmp_path/'stage',tmp_path/'out')


def test_sources_and_hashes_describe_files_without_a_desktop_archive(tmp_path):
    repo=tmp_path/'repo';repo.mkdir()
    (repo/'LICENSE').write_text('GPL')
    (repo/'install.sh').write_bytes((ROOT/'install.sh').read_bytes())
    subprocess.run(['git','init',str(repo)],check=True,capture_output=True)
    subprocess.run(['git','-C',str(repo),'add','.'],check=True)
    subprocess.run(['git','-C',str(repo),'-c','user.name=Test','-c','user.email=test@example.invalid','commit','-m','fixture'],check=True,capture_output=True)
    (repo/'new-source.py').write_text('new source')
    subprocess.run(['git','-C',str(repo),'add','new-source.py'],check=True)
    out=tmp_path/'out';installer=release.package(repo,stage_fixture(tmp_path),out)
    hashes={name:digest for digest,name in (line.split() for line in (out/'SHA256SUMS').read_text().splitlines())}
    assert hashes['install.sh']==hashlib.sha256(installer.read_bytes()).hexdigest()
    assert not list(out.glob('*-x86_64.tar.gz'))
    with tarfile.open(out/'arch-installer-0.2.0-preview1-sources.tar.gz') as sources:
        assert 'arch-installer/new-source.py' in sources.getnames()
        assert not any('/.git/' in n for n in sources.getnames())
    report=json.loads((out/'build-inputs.json').read_text())
    assert report['source_dirty'] and 'Build only' in report['validation']
    (repo/'.env').write_text('PRIVATE=must-not-be-published')
    with pytest.raises(RuntimeError,match='Untracked'):
        release.package(repo,stage_fixture(tmp_path/'other'),out)


def test_launcher_rejects_wrong_machine_before_any_execution(tmp_path):
    uname=tmp_path/'uname';uname.write_text('#!/bin/sh\necho Darwin\n');uname.chmod(0o755)
    result=subprocess.run(['bash',str(ROOT/'install.sh')],env={'PATH':str(tmp_path)+':/usr/bin:/bin'},capture_output=True,text=True)
    assert result.returncode!=0 and 'Linux x86-64' in result.stderr


def run_demo(installer,tmp_path):
    tools=tmp_path/'tools';tools.mkdir();(tools/'python').symlink_to(sys.executable)
    curl=tools/'curl';curl.write_text('#!/bin/sh\necho NETWORK-MUST-NOT-BE-USED >&2\nexit 99\n');curl.chmod(0o755)
    temp=tmp_path/'temp';temp.mkdir()
    env=dict(os.environ,PATH=str(tools)+':/usr/bin:/bin',TMPDIR=str(temp))
    result=subprocess.run(['bash',str(installer),'--demo','--lang','en'],env=env,text=True,capture_output=True)
    assert not list(temp.iterdir())
    assert 'NETWORK-MUST-NOT-BE-USED' not in result.stderr
    return result


def test_single_script_runs_without_archive_network_or_engine(tmp_path):
    installer=release.build_script(ROOT/'install.sh',stage_fixture(tmp_path),tmp_path/'install.sh')
    subprocess.run(['bash','-n',str(installer)],check=True)
    result=run_demo(installer,tmp_path)
    assert result.returncode==0 and 'DEMO-BINARY-EXECUTED --demo --lang en' in result.stdout


@pytest.mark.parametrize('unsafe',['checksum','symlink','traversal'])
def test_embedded_corruption_and_unsafe_members_stop_before_execution(tmp_path,unsafe):
    installer=release.build_script(ROOT/'install.sh',stage_fixture(tmp_path),tmp_path/'install.sh')
    header,encoded=installer.read_bytes().split(b'\n__ARCH_INSTALL_BUNDLE__\n',1)
    old=base64.b64decode(encoded)
    if unsafe=='checksum':
        data=b'corrupted'
    else:
        buffer=io.BytesIO()
        with tarfile.open(fileobj=buffer,mode='w:gz') as archive:
            name='installer/escape' if unsafe=='symlink' else 'installer/../../outside'
            member=tarfile.TarInfo(name)
            if unsafe=='symlink':member.type=tarfile.SYMTYPE;member.linkname=str(tmp_path)
            archive.addfile(member)
        data=buffer.getvalue()
        header=header.replace(hashlib.sha256(old).hexdigest().encode(),hashlib.sha256(data).hexdigest().encode())
    installer.write_bytes(header+b'\n__ARCH_INSTALL_BUNDLE__\n'+base64.encodebytes(data))
    result=run_demo(installer,tmp_path)
    assert result.returncode!=0 and 'DEMO-BINARY-EXECUTED' not in result.stdout
    assert ('checksum mismatch' if unsafe=='checksum' else 'Unsafe embedded') in result.stderr
    assert not (tmp_path/'outside').exists()


@pytest.mark.parametrize('args',[['--lang'],['--lang','xx'],['--archive'],['--unknown']])
def test_launcher_rejects_invalid_options(args):
    result=subprocess.run(['bash',str(ROOT/'install.sh'),*args],capture_output=True,text=True)
    assert result.returncode==2 and 'Usage:' in result.stderr
