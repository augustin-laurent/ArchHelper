#!/usr/bin/env bash
# Single-file installer for the official Arch ISO. The release build embeds its
# precompiled terminal interface and Python engine below the end marker.
set -euo pipefail
readonly version=0.2.0-preview1
readonly bundle_sha256='@BUNDLE_SHA256@'
demo=0
lang=fr
usage() {
  echo 'Usage: bash install.sh [--demo] [--lang fr|en]'
  echo 'Official Arch ISO, Linux x86-64, UEFI, root and Internet required.'
  echo 'Demo: no backend, network or disk access. No separate archive required.'
}
while (( $# )); do
  case $1 in
    --demo) demo=1; shift ;;
    --lang)
      [[ $# -ge 2 && ( $2 == fr || $2 == en ) ]] || { usage >&2; exit 2; }
      lang=$2; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    --version) echo "$version"; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done
[[ $(uname -s) == Linux && $(uname -m) == x86_64 ]] || { echo 'Linux x86-64 required' >&2; exit 1; }
for tool in python mktemp; do
  command -v "$tool" >/dev/null || { echo "Missing: $tool" >&2; exit 1; }
done
[[ $bundle_sha256 != '@BUNDLE_SHA256@' ]] || {
  echo 'This source template is not the assembled installer. Build it with make script.' >&2
  exit 1
}
if (( ! demo )); then
  [[ $(id -u) == 0 && -d /run/archiso && -d /sys/firmware/efi ]] || {
    echo 'Boot the official Arch x86-64 ISO in UEFI mode and run as root.' >&2; exit 1;
  }
  python - <<'PY'
from pathlib import Path
from importlib.metadata import version, PackageNotFoundError
import sys
try:
    qualified = sys.version_info[:2] == (3, 14) and version('archinstall') == '4.5'
except PackageNotFoundError:
    qualified = False
if not qualified:
    raise SystemExit('This preview requires Python 3.14 and archinstall 4.5. No live libraries were replaced.')
for p in Path('/sys/firmware/efi/efivars').glob('SecureBoot-*'):
    if p.read_bytes()[4:5] == b'\x01':
        raise SystemExit('Disable Secure Boot first.')
PY
  for tool in curl pacman pacman-key pacman-conf pacstrap arch-chroot repo-add lsblk cryptsetup mkfs.btrfs mkfs.fat systemd-detect-virt; do
    command -v "$tool" >/dev/null || { echo "Missing live dependency: $tool" >&2; exit 1; }
  done
  if ! curl --fail --silent --show-error --connect-timeout 10 --max-time 20 https://archlinux.org/ -o /dev/null; then
    echo 'Connect Ethernet, or use iwctl: device list; station DEVICE scan; station DEVICE connect SSID' >&2
    if command -v iwctl >/dev/null; then iwctl; else exit 1; fi
    curl --fail --silent --show-error --max-time 20 https://archlinux.org/ -o /dev/null
  fi
fi
temp_root=${TMPDIR:-/run}
(( ! demo )) || temp_root=${TMPDIR:-/tmp}
stage=$(mktemp -d "$temp_root/arch-install.XXXXXXXX")
trap 'rm -rf -- "$stage"' EXIT
python - "$0" "$stage" "$bundle_sha256" <<'PY'
import base64, hashlib, io, sys, tarfile
from pathlib import Path, PurePosixPath
script, stage, expected = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
try:
    body = script.read_bytes().split(b'\n__ARCH_INSTALL_BUNDLE__\n', 1)[1]
    data = base64.b64decode(b''.join(body.split()), validate=True)
except (IndexError, ValueError):
    raise SystemExit('Missing or invalid embedded installer')
if hashlib.sha256(data).hexdigest() != expected:
    raise SystemExit('Embedded installer checksum mismatch')
with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
    members = archive.getmembers()
    for member in members:
        path = PurePosixPath(member.name)
        if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] != 'installer' or not (member.isfile() or member.isdir()):
            raise SystemExit('Unsafe embedded installer member')
    archive.extractall(stage, members=members, filter='data')
if not (stage/'installer/arch-install').is_file() or not (stage/'installer/engine/run.py').is_file():
    raise SystemExit('Incomplete embedded installer')
PY
if (( demo )); then
  "$stage/installer/arch-install" --demo --lang "$lang"
else
  # Keep the engine in live RAM until reboot if the terminal closes mid-install.
  trap - EXIT
  "$stage/installer/arch-install" --lang "$lang"
fi
exit "$?"
