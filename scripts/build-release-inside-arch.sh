#!/usr/bin/env bash
# Only in a disposable builder, inputs read-only and output under /output.
set -euo pipefail
[[ $(id -u) == 0 && $(uname -m) == x86_64 && -d /input/installer && -d /output ]]
[[ -f /.dockerenv || $(cat /etc/v8-build-vm 2>/dev/null) == v8-isolated-builder-v1 ]]
[[ ! -e /build/release ]] || { echo 'Use a fresh build root.' >&2; exit 1; }
pacman -Syu --noconfirm --needed go python archinstall python-pytest python-pytest-asyncio git xkeyboard-config
export PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/input/installer
python -c 'from v8_installer.adapter import contract; contract()'
python -m pytest -q -p no:cacheprovider /input/installer/tests /input/tests | tee /output/python-tests.txt
unset PYTHONPATH
mkdir -p /build/release/engine /build/tui
cp -a /input/installer/tui/. /build/tui/
cd /build/tui
go test ./... | tee /output/go-tests.txt
go vet ./...
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -buildvcs=false -trimpath -o /build/release/arch-install .
go mod vendor
cp -a /input/installer/v8_installer /build/release/engine/
if [[ -f /usr/share/xkeyboard-config-2/rules/evdev.xml ]]; then
  cp /usr/share/xkeyboard-config-2/rules/evdev.xml /build/release/engine/v8_installer/xkb-evdev.xml
else
  cp /usr/share/X11/xkb/rules/evdev.xml /build/release/engine/v8_installer/xkb-evdev.xml
fi
cp /input/installer/run.py /build/release/engine/
python /input/scripts/package-release.py --stage /build/release --output /output --vendor /build/tui/vendor
