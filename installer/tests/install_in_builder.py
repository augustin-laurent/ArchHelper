"""Full installation, inside the disposable live root, to a fresh loop file.

No user-supplied devices. Move /var/tmp/v8-installed-uki.img out of the live
root after this test; never include the test image in a release SquashFS.
"""
import json
import os
import platform
from pathlib import Path
import subprocess
import sys
import uuid
bundle = Path(os.environ["ARCHHELPER_BUNDLE"]).resolve()
sys.path.insert(0, str(bundle / "engine"))
from v8_installer.disks import discover
from v8_installer.plan import automatic, GIB
from v8_installer.install import execute, Credentials

assert os.geteuid() == 0 and Path("/run/archiso").is_dir()
luks = os.environ.get("V8_TEST_LUKS") == "1"
image = Path("/var/tmp/v8-installed-luks.img" if luks else "/var/tmp/v8-installed-uki.img")
with image.open("xb") as f:
    f.truncate(40 * GIB)
device = subprocess.check_output(["losetup", "--find", "--show", "--partscan", str(image)], text=True).strip()
assert device.startswith("/dev/loop")
backing = subprocess.check_output(["losetup", "--noheadings", "--output", "BACK-FILE", device], text=True).strip()
try:
    disk = next(d for d in discover(loop_backing=backing) if d.path == device)
    plan = automatic(disk, "wipe", platform.machine())
    from v8_installer import hardware
    plan.hardware = hardware.detect()
    plan.graphics = "nvidia" if any(g["vendor"] == "10de" for g in plan.hardware["gpus"]) else "vm" if plan.hardware["virtual"] else "mesa"
    plan.username, plan.hostname = "v8test", "v8-installed"
    plan.keyboard, plan.locale, plan.timezone = "us", "en_US.UTF-8", "UTC"
    plan.luks, plan.uki = luks, not luks
    plan.validate()
    report = Path("/var/log/v8-installer") / ("full-native-" + str(uuid.uuid4()))
    assert not report.exists(), "A failed run needs a fresh disk and a fresh report"
    journal = execute(plan, Credentials("v8testvm123", "v8luksvm123" if luks else ""), plan.confirmation, report, loop_backing=backing)
    assert all(row["state"] == "completed" for row in journal.steps)
    print("V8_FULL_INSTALL=" + json.dumps({"status": "completed", "uki": plan.uki, "luks": plan.luks, "report": str(report)}))
finally:
    subprocess.run(["losetup", "--detach", device], check=True)
