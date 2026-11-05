import copy
import json
from types import SimpleNamespace

import pytest
from v8_installer import hardware
from v8_installer.plan import PlanError


def fixture(tmp_path, ids):
    sysfs=tmp_path/'pci';sysfs.mkdir()
    for i,(vendor,device) in enumerate(ids):
        p=sysfs/f'0000:0{i}:00.0';p.mkdir()
        for name,value in {'class':'0x030000','vendor':'0x'+vendor,'device':'0x'+device}.items():(p/name).write_text(value)
    cpu=tmp_path/'cpuinfo';cpu.write_text('vendor_id : GenuineIntel\n')
    return hardware.detect(sysfs,cpu,virtual=False)


def test_modern_nvidia_hybrid_and_kernel_headers(tmp_path):
    data=fixture(tmp_path,[('8086','1234'),('10de','1e04')])
    data['gpus'][0]['driver']='i915'
    plan=SimpleNamespace(hardware=data,graphics='nvidia',kernel='linux-lts')
    hardware.validate(plan,current=copy.deepcopy(data))
    assert 'nvidia-open-lts' in hardware.packages(plan)
    assert 'linux-lts-headers' not in hardware.packages(plan)
    assert 'intel-ucode' in hardware.packages(plan)
    assert hardware.modules(plan)[0]=='i915'
    hardware.configure(tmp_path,plan)
    env=(tmp_path/'usr/share/uwsm/env.d/10-installer').read_text()
    assert '__GLX_VENDOR_LIBRARY_NAME' not in env # integrated compositor, explicit offload
    assert 'WLR_RENDERER_ALLOW_SOFTWARE' not in env


@pytest.mark.parametrize('kernel,module', [('linux', 'nvidia-open'), ('linux-lts', 'nvidia-open-lts'), ('linux-zen', 'nvidia-open-dkms')])
def test_nvidia_module_matches_kernel(tmp_path, kernel, module):
    data = fixture(tmp_path, [('10de', '1e04')])
    plan = SimpleNamespace(hardware=data, graphics='nvidia', kernel=kernel)
    hardware.validate(plan)
    packages = hardware.packages(plan)
    assert module in packages
    assert (kernel + '-headers' in packages) == (module == 'nvidia-open-dkms')


def test_nouveau_is_available_without_nvidia_proprietary_packages(tmp_path):
    data = fixture(tmp_path, [('10de', '1b80')])
    plan = SimpleNamespace(hardware=data, graphics='nouveau', kernel='linux')
    hardware.validate(plan)
    assert not any(p.startswith('nvidia') for p in hardware.packages(plan))
    assert hardware.modules(plan) == []


def test_proprietary_580_requires_cachyos_and_supported_hardware(tmp_path):
    data = fixture(tmp_path, [('10de', '1b80')])
    plan = SimpleNamespace(hardware=data, graphics='nvidia-580', kernel='linux-lts', cachyos=False)
    with pytest.raises(PlanError, match='CachyOS'):
        hardware.validate(plan)
    plan.cachyos = True
    hardware.validate(plan)
    packages = hardware.packages(plan)
    assert {'nvidia-580xx-dkms', 'nvidia-580xx-utils', 'linux-lts-headers'} <= set(packages)
    assert 'nvidia-open-dkms' not in packages and 'nvidia-utils' not in packages
    assert 'nvidia_drm' in hardware.modules(plan)
    hardware.configure(tmp_path, plan)
    assert (tmp_path/'etc/modprobe.d/installer-nvidia.conf').is_file()
    data['gpus'][0]['device'] = 'ffff'
    with pytest.raises(PlanError, match='not qualified'):
        hardware.validate(plan)


def test_580_table_is_curated_and_bundled():
    ids = hardware.supported_580()
    assert len(ids) > 1000 and {'1b80', '2204'} <= ids and 'ffff' not in ids


def test_580_support_includes_modern_cards_and_checks_subsystem():
    assert hardware.supports_580({'device': '2204'})  # GeForce RTX 3090
    assert hardware.supports_580({'device': '137a', 'subsystem_vendor': '17aa', 'subsystem_device': '2225'})
    assert not hardware.supports_580({'device': '137a', 'subsystem_vendor': '17aa', 'subsystem_device': 'ffff'})
    assert not hardware.supports_580({'device': '137a'})


def test_detected_subsystem_controls_proprietary_driver_choice(tmp_path):
    fixture(tmp_path, [('10de', '137a')])
    device = tmp_path / 'pci/0000:00:00.0'
    (device / 'subsystem_vendor').write_text('0x17aa\n')
    (device / 'subsystem_device').write_text('0x2225\n')
    detected = hardware.detect(tmp_path / 'pci', tmp_path / 'cpuinfo', virtual=False)
    plan = SimpleNamespace(hardware=detected, graphics='nvidia-580', cachyos=True)
    hardware.validate(plan)
    (device / 'subsystem_device').write_text('0xffff\n')
    plan.hardware = hardware.detect(tmp_path / 'pci', tmp_path / 'cpuinfo', virtual=False)
    with pytest.raises(PlanError, match='not qualified'):
        hardware.validate(plan)


@pytest.mark.parametrize('chip',['1b80','ffff'])
def test_legacy_and_unknown_nvidia_are_rejected(tmp_path,chip):
    data=fixture(tmp_path,[('10de',chip)])
    plan=SimpleNamespace(hardware=data,graphics='nvidia')
    with pytest.raises(PlanError,match='unsupported'):hardware.validate(plan)


def test_hardware_change_and_vm_override_rejected(tmp_path):
    data=fixture(tmp_path,[('1002','1234')])
    plan=SimpleNamespace(hardware=data,graphics='mesa')
    changed=copy.deepcopy(data);changed['cpu']='amd'
    with pytest.raises(PlanError,match='changed'):hardware.validate(plan,current=changed)
    plan.graphics='vm'
    with pytest.raises(PlanError,match='virtual'):hardware.validate(plan)


def test_table_has_pinned_upstream_and_real_devices():
    data=json.loads(hardware.TABLE.read_text())
    assert len(data['commit'])==40 and len(data['devices'])>200
    assert data['devices']['1e04']=='NVIDIA GeForce RTX 2080 Ti'


def test_vm_rendering_is_explicit_and_includes_the_greeter(tmp_path):
    plan=SimpleNamespace(hardware={'cpu':'intel','virtual':True,'gpus':[]},graphics='vm')
    hardware.validate(plan)
    hardware.configure(tmp_path,plan)
    assert 'WLR_RENDERER_ALLOW_SOFTWARE=1' in (tmp_path/'usr/share/uwsm/env.d/10-installer').read_text()
    assert 'QT_QUICK_BACKEND=software' in (tmp_path/'etc/sddm.conf.d/15-wayland-vm.conf').read_text()
