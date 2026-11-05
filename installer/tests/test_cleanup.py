from pathlib import Path
from types import SimpleNamespace
from v8_installer import install


def test_cleanup_closes_only_the_target_partition(monkeypatch):
    monkeypatch.setattr(Path, 'exists', lambda self: True)
    calls=[]
    root=SimpleNamespace(dev_path=Path('/dev/vdb2'),is_root=lambda:True)
    config=SimpleNamespace(device_modifications=[SimpleNamespace(partitions=[root])])
    for active,should_close in (('/dev/vda2',False),('/dev/vdb2',True)):
        calls.clear()
        def run(args,**kwargs):
            calls.append(args)
            return SimpleNamespace(returncode=0,stdout='  device: '+active+'\n')
        monkeypatch.setattr(install.subprocess,'run',run)
        install.close_target_mapping(config)
        assert (['cryptsetup','close','root'] in calls)==should_close
