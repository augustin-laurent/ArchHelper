"""Read-only PCI detection and explicit target configuration (never the live GPU)."""
import json
from pathlib import Path
import subprocess

from . import boot
from .plan import PlanError

TABLE = Path(__file__).with_name("nvidia-gpus.json")
LEGACY_TABLE = Path(__file__).with_name("nvidia-580.ids")


def supported_580():
    return {item for line in LEGACY_TABLE.read_text().splitlines()
            if not line.startswith('#') for item in line.split()}


def supports_580(gpu):
    ids = supported_580()
    device = gpu['device']
    if device in ids:
        return True
    return f"{device}:{gpu.get('subsystem_vendor', '')}:{gpu.get('subsystem_device', '')}" in ids


def detect(sysfs=Path("/sys/bus/pci/devices"), cpuinfo=Path("/proc/cpuinfo"), *, virtual=None):
    supported = json.loads(TABLE.read_text())["devices"]
    if virtual is None:
        result = subprocess.run(["systemd-detect-virt", "--vm"], capture_output=True, text=True)
        virtual = result.returncode == 0
    text = cpuinfo.read_text()
    cpu = "intel" if "GenuineIntel" in text else "amd" if "AuthenticAMD" in text else "other"
    gpus = []
    for device in sorted(sysfs.iterdir()):
        try:
            if not (device / "class").read_text().strip().startswith("0x03"):
                continue
            vendor = (device / "vendor").read_text().strip().removeprefix("0x")
            chip = (device / "device").read_text().strip().removeprefix("0x")
            def subsystem(name):
                path = device / name
                return path.read_text().strip().removeprefix('0x') if path.is_file() else ''
            name = supported.get(chip, "NVIDIA " + chip) if vendor == "10de" else {"8086": "Intel", "1002": "AMD", "1af4": "Virtio"}.get(vendor, vendor + ":" + chip)
            gpus.append({"pci": device.name, "vendor": vendor, "device": chip,
                         "subsystem_vendor": subsystem('subsystem_vendor'),
                         "subsystem_device": subsystem('subsystem_device'),
                         "driver": (device / "driver/module").resolve().name if (device / "driver/module").exists() else "",
                         "name": name, "supported": vendor != "10de" or chip in supported})
        except FileNotFoundError:
            continue
    return {"cpu": cpu, "virtual": bool(virtual), "gpus": gpus}


def validate(plan, *, current=None):
    if plan.graphics not in ("mesa", "nvidia", "nvidia-580", "nouveau", "vm"):
        raise PlanError("Unsupported graphics profile")
    if current is not None and plan.hardware != current:
        raise PlanError("Hardware changed; scan and review a new plan")
    nvidia = [g for g in plan.hardware.get("gpus", []) if g["vendor"] == "10de"]
    if plan.graphics == "nvidia" and any(not g["supported"] for g in nvidia):
        raise PlanError("NVIDIA before Turing or unknown PCI ID: unsupported in this release")
    if plan.graphics in ("nvidia", "nvidia-580", "nouveau") and not nvidia:
        raise PlanError("No supported NVIDIA GPU detected")
    if plan.graphics == 'nvidia-580':
        if not getattr(plan, 'cachyos', False):
            raise PlanError('NVIDIA 580 requires the CachyOS repository')
        if any(not supports_580(g) for g in nvidia):
            raise PlanError('NVIDIA 580 is not qualified for this GPU; choose another driver')
    if nvidia and plan.graphics not in ("nvidia", "nvidia-580", "nouveau"):
        raise PlanError("Select the NVIDIA profile for this hardware")
    if plan.graphics == "vm" and not plan.hardware.get("virtual"):
        raise PlanError("VM rendering is available only in a detected virtual machine")


def packages(plan):
    result = []
    cpu = plan.hardware.get("cpu")
    if cpu in ("intel", "amd"):
        result.append(cpu + "-ucode")
    vendors = {g["vendor"] for g in plan.hardware.get("gpus", [])}
    if "8086" in vendors:
        result += ["vulkan-intel", "intel-media-driver"]
    if "1002" in vendors:
        result += ["vulkan-radeon", "libva-mesa-driver"]
    if plan.graphics == "nvidia":
        # Official prebuilt modules exist for Arch's standard and LTS kernels.
        # Other kernels need DKMS and the matching headers.
        module = {"linux": "nvidia-open", "linux-lts": "nvidia-open-lts"}.get(plan.kernel, "nvidia-open-dkms")
        result += [module, "nvidia-utils", "nvidia-prime", "egl-wayland", "libva-nvidia-driver"]
        if module == "nvidia-open-dkms":
            result.append(plan.kernel + "-headers")
    if plan.graphics == 'nvidia-580':
        result += ['nvidia-580xx-dkms', 'nvidia-580xx-utils', 'nvidia-prime',
                   'egl-wayland', 'libva-nvidia-driver', plan.kernel + '-headers']
    return result


def modules(plan):
    if plan.graphics not in ("nvidia", "nvidia-580"):
        return []
    # Integrated GPU first on hybrid systems; don't force NVIDIA as compositor.
    drivers = {g.get("driver") for g in plan.hardware.get("gpus", [])}
    result = [name for name in ("i915", "xe", "amdgpu") if name in drivers]
    return result + ["nvidia", "nvidia_modeset", "nvidia_uvm", "nvidia_drm"]


def configure(root, plan):
    env = "export TERMINAL=foot\nexport EDITOR=nvim\nexport QT_QPA_PLATFORM='wayland;xcb'\nexport MOZ_ENABLE_WAYLAND=1\n"
    if plan.graphics == "vm":
        env += "export AQ_NO_MODIFIERS=1\nexport WLR_RENDERER_ALLOW_SOFTWARE=1\n"
        if getattr(plan, 'desktop', 'hyprland') in ('hyprland', 'niri', 'sway', 'river', 'labwc', 'wayfire', 'lxqt', 'weston'):
            boot.write(root, "/etc/sddm.conf.d/15-wayland-vm.conf",
                       "[General]\nGreeterEnvironment=QT_QUICK_BACKEND=software\n")
    if plan.graphics in ("nvidia", "nvidia-580"):
        boot.write(root, "/etc/modprobe.d/installer-nvidia.conf", "options nvidia_drm modeset=1\n")
        # UWSM imports this for the session. PRIME offload stays opt-in.
        if len(plan.hardware.get("gpus", [])) == 1:
            env += "export LIBVA_DRIVER_NAME=nvidia\nexport __GLX_VENDOR_LIBRARY_NAME=nvidia\n"
    if getattr(plan, "desktop", "hyprland") == "hyprland":
        boot.write(root, "/usr/share/uwsm/env.d/10-installer", env)
