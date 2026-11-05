"""Protocol 1: one request on stdin, JSONL events on stdout, no shell evaluation."""
from contextlib import contextmanager
from dataclasses import asdict
import copy
import json
import os
from pathlib import Path
import platform
import shutil
import socket
import sys
import threading
import urllib.request
import uuid

from . import adapter, desktop, hardware, payload
from .disks import discover, revalidate
from .install import Credentials, atomic, decode, execute
from .plan import InstallPlan, Partition, PlanError, automatic
from .review import summary

VERSION = 1
REPORTS = Path("/var/log/v8-installer")


def environment():
    adapter.contract()
    if platform.system() != "Linux" or platform.machine() != "x86_64" or os.geteuid() != 0:
        raise PlanError("Run as root from the official Arch x86-64 installation ISO")
    if not Path("/run/archiso").is_dir() or not Path("/sys/firmware/efi").is_dir():
        raise PlanError("An official Arch live ISO booted in UEFI mode is required")
    for path in Path("/sys/firmware/efi/efivars").glob("SecureBoot-*"):
        if path.read_bytes()[4:5] == b"\x01":
            raise PlanError("Disable Secure Boot before installation")
    required = ("pacman", "pacman-conf", "pacman-key", "pacstrap", "arch-chroot", "repo-add", "lsblk", "cryptsetup", "mkfs.btrfs", "mkfs.fat", "systemd-detect-virt")
    missing = [name for name in required if not shutil.which(name)]
    if missing:
        raise PlanError("Missing live dependencies: " + ", ".join(missing))


def network():
    try:
        with urllib.request.urlopen("https://archlinux.org/", timeout=10) as response:
            ok = response.status == 200
    except (OSError, TimeoutError, ValueError):
        ok = False
    return {"online": ok, "hostname": socket.gethostname(), "iwctl": bool(shutil.which("iwctl"))}


def make_plan(raw):
    disk = next((d for d in discover() if d.path == raw["disk"]), None)
    if not disk:
        raise PlanError("Disk not found; rescan")
    mode = raw["mode"]
    if mode == "manual":
        plan = InstallPlan(disk, mode, [Partition(**row) for row in raw["partitions"]], "x86_64", raw["kernel"])
    else:
        plan = automatic(disk, mode, "x86_64")
    for key in ("kernel", "username", "hostname", "locale", "keyboard", "xkb", "timezone", "uki", "luks", "plymouth", "desktop", "network", "snapshots", "bluetooth", "zram", "root_enabled", "swap_gib", "swap_location", "extra_packages", "cachyos"):
        if key in raw:
            setattr(plan, key, raw[key])
    plan.hardware = hardware.detect()
    nvidia = [g for g in plan.hardware["gpus"] if g["vendor"] == "10de"]
    plan.graphics = raw.get("graphics", "auto")
    if plan.graphics == "auto":
        if nvidia:
            plan.graphics = ('nvidia' if all(g['supported'] for g in nvidia) else
                             'nvidia-580' if plan.cachyos and all(hardware.supports_580(g) for g in nvidia) else 'nouveau')
        else:
            plan.graphics = 'vm' if plan.hardware['virtual'] else 'mesa'
    plan.validate()
    hardware.validate(plan)
    return plan


@contextmanager
def execution_log(path, secrets):
    """Capture Python AND subprocess output; filter credentials before persistence."""
    sys.stdout.flush()
    sys.stderr.flush()
    saved = [os.dup(1), os.dup(2)]
    readfd, writefd = os.pipe()
    with path.open("wb") as log:
        os.fchmod(log.fileno(), 0o600)
        def drain():
            with os.fdopen(readfd, "rb") as stream:
                for line in stream:
                    for secret in secrets:
                        if secret:
                            line = line.replace(secret.encode(), b"[REDACTED]")
                    log.write(line)
                    log.flush()
        thread = threading.Thread(target=drain, daemon=True)
        thread.start()
        os.dup2(writefd, 1)
        os.dup2(writefd, 2)
        os.close(writefd)
        try:
            yield
        finally:
            sys.stdout.flush()
            sys.stderr.flush()
            for dest, fd in enumerate(saved, 1):
                os.dup2(fd, dest)
                os.close(fd)
            thread.join()


def dispatch(request, emit):
    if type(request.get("version")) is not int or request["version"] != VERSION:
        raise PlanError("Unsupported protocol version")
    action = request.get("action")
    if action == "network":
        return network()
    environment()
    if action == "checks":
        value = payload.manifest()
        return {"compatible": True, "release": value["release"], "hardware": hardware.detect(), "network": network()}
    if action == "discover":
        return {"disks": [asdict(d) for d in discover()], "hardware": hardware.detect()}
    if action == "packages":
        enabled = request.get('cachyos', False)
        if type(enabled) is not bool:
            raise PlanError('Invalid CachyOS repository selection')
        return {"packages": payload.catalog(enabled)}
    if action == "plan":
        plan = make_plan(request["options"])
        payload.resolve(plan, desktop.profile(plan.desktop))
        return {"plan": json.loads(plan.json()), "summary": summary(plan), "confirmation": plan.confirmation}
    if action not in ("preflight", "install", "export"):
        raise PlanError("Unknown protocol action")
    plan = decode(copy.deepcopy(request["plan"]))
    plan.validate()
    hardware.validate(plan, current=hardware.detect())
    revalidate(plan)
    if action == "preflight":
        desktop.profile(plan.desktop)
        if not network()["online"]:
            raise PlanError("No HTTPS connectivity; configure the live network first")
        return {"ready": True}
    if action == "install":
        credentials = Credentials(**request["credentials"])
        credentials.validate(plan)
        if request.get("confirmation") != plan.confirmation:
            raise PlanError("Exact disk and plan confirmation required")
    REPORTS.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory = REPORTS / str(uuid.uuid4())
    directory.mkdir(mode=0o700)
    atomic(directory / "plan.json", json.loads(plan.json()))
    if action == "export":
        return {"report": str(directory)}
    emit("report", {"report": str(directory)})
    try:
        def progress(rows):
            emit("progress", {"steps": rows})
        with execution_log(directory / "execution.log", [credentials.password, credentials.root_password, credentials.luks_password]):
            execute(plan, credentials, request["confirmation"], directory, callback=progress)
    except BaseException as error:
        message = str(error) if isinstance(error, PlanError) else type(error).__name__
        for secret in (credentials.password, credentials.root_password, credentials.luks_password):
            if secret:
                message = message.replace(secret, "[REDACTED]")
        result = {"status": "failed", "error": message, "report": str(directory), "rescan_required": True}
        atomic(directory / "result.json", result)
        emit("failed", result)
        return result
    result = {"status": "completed", "report": str(directory)}
    atomic(directory / "result.json", result)
    return result


def main():
    with os.fdopen(os.dup(1), "w", buffering=1) as output:
        def emit(kind, data):
            output.write(json.dumps({"version": VERSION, "type": kind, "data": data}, ensure_ascii=False) + "\n")
        try:
            raw = sys.stdin.buffer.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise PlanError("Request too large")
            result = dispatch(json.loads(raw), emit)
            emit("result", result)
            return 1 if result.get("status") == "failed" else 0
        except BaseException as error:
            emit("error", {"error": str(error) if isinstance(error, PlanError) else type(error).__name__})
            return 1
