import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from v8_installer import hardware, payload, protocol
from v8_installer.plan import Disk, GIB, MIB, PlanError, automatic


@pytest.fixture
def plan():
    disk = Disk('/dev/vdb', 40*GIB, 512, 'fixture', 'Fixture', 'gpt', [], [(MIB,40*GIB-2*MIB)])
    value = automatic(disk,'wipe','x86_64')
    value.hardware = {'cpu':'intel','virtual':False,'gpus':[]}
    return value


def test_unknown_protocol_and_malformed_input_never_echo_credentials():
    runner = Path(__file__).resolve().parents[1]/'run.py'
    for request in ('{private-password', json.dumps({'version':999,'credentials':{'password':'private-password'}})):
        result = subprocess.run([sys.executable,'-I',str(runner),'--rpc'],input=request,text=True,capture_output=True)
        assert result.returncode == 1
        assert 'private-password' not in result.stdout+result.stderr
        event = json.loads(result.stdout)
        assert event['version']==1 and event['type']=='error'


def test_plan_uses_fresh_discovery_and_is_authoritative(plan, monkeypatch):
    monkeypatch.setattr(protocol,'discover',lambda:[plan.disk])
    monkeypatch.setattr(hardware,'detect',lambda:copy.deepcopy(plan.hardware))
    result=protocol.make_plan({'disk':plan.disk.path,'mode':'wipe','kernel':'linux','username':'alice'})
    assert result.disk is plan.disk and result.username=='alice'
    assert result.confirmation.endswith(result.fingerprint[:8])
    with pytest.raises(PlanError):protocol.make_plan({'disk':'/dev/invented','mode':'wipe','kernel':'linux'})


def test_auto_graphics_uses_580_or_nouveau_for_older_nvidia(plan, monkeypatch):
    monkeypatch.setattr(protocol, 'discover', lambda: [plan.disk])
    old = {'cpu':'intel', 'virtual':False, 'gpus':[{'vendor':'10de', 'device':'1b80', 'supported':False}]}
    monkeypatch.setattr(hardware, 'detect', lambda: copy.deepcopy(old))
    options = {'disk':plan.disk.path, 'mode':'wipe', 'kernel':'linux', 'graphics':'auto'}
    assert protocol.make_plan(options).graphics == 'nouveau'
    assert protocol.make_plan({**options, 'cachyos':True}).graphics == 'nvidia-580'


def test_wrong_confirmation_cannot_create_a_session_or_start_install(plan, monkeypatch, tmp_path):
    monkeypatch.setattr(protocol,'environment',lambda:None)
    monkeypatch.setattr(protocol,'revalidate',lambda p:None)
    monkeypatch.setattr(hardware,'detect',lambda:plan.hardware)
    monkeypatch.setattr(protocol,'REPORTS',tmp_path/'reports')
    called=[]
    monkeypatch.setattr(protocol,'execute',lambda *a,**kw:called.append(True))
    request={'version':1,'action':'install','plan':json.loads(plan.json()),'confirmation':'wrong','credentials':{'password':'private-password'}}
    with pytest.raises(PlanError,match='confirmation'):protocol.dispatch(request,lambda *a:None)
    assert not called and not (tmp_path/"reports").exists()


def test_log_filters_python_and_child_output(tmp_path):
    # Exercise fd redirection in a subprocess so pytest's own capture is untouched.
    root=Path(__file__).resolve().parents[1]
    script='''import os,subprocess,sys
sys.path.insert(0,sys.argv[1])
from pathlib import Path
from v8_installer.protocol import execution_log
with execution_log(Path(sys.argv[2]), ['private-password']):
 print('private-password', flush=True)
 subprocess.run([sys.executable,'-c',"print('private-password')"], check=True)
print('protocol survives')
'''
    log=tmp_path/'execution.log'
    result=subprocess.run([sys.executable,'-I','-c',script,str(root),str(log)],capture_output=True,text=True,check=True)
    assert result.stdout.strip()=='protocol survives'
    assert 'private-password' not in log.read_text()
    assert log.read_text().count('[REDACTED]')==2
    assert log.stat().st_mode & 0o777 == 0o600


def test_progress_is_real_and_install_failures_are_redacted(plan,monkeypatch,tmp_path):
    monkeypatch.setattr(protocol,'environment',lambda:None)
    monkeypatch.setattr(protocol,'revalidate',lambda p:None)
    monkeypatch.setattr(hardware,'detect',lambda:plan.hardware)
    monkeypatch.setattr(protocol,'REPORTS',tmp_path/'reports')
    def execute(*args,callback,**kwargs):
        callback([{'phase':'preflight','state':'started'}])
        raise PlanError('failed private-password')
    monkeypatch.setattr(protocol,'execute',execute)
    events=[]
    result=protocol.dispatch({'version':1,'action':'install','plan':json.loads(plan.json()),'confirmation':plan.confirmation,'credentials':{'password':'private-password'}},lambda *e:events.append(e))
    assert result['status']=='failed' and result['rescan_required']
    assert 'private-password' not in json.dumps(result)+json.dumps(events)
    assert any(e[0]=='progress' for e in events)
