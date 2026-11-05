.PHONY: build check test test-python test-go tui script clean
PYTHON ?= python3
GO ?= go
build:
	./v8 build
check:
	./v8 check
tui:
	mkdir -p dist
	cd installer/tui && CGO_ENABLED=0 $(GO) build -buildvcs=false -trimpath -o ../../dist/arch-install .
test: test-python test-go
test-python:
	PYTHONPATH=installer $(PYTHON) -m pytest -q installer/tests tests
test-go:
	cd installer/tui && $(GO) test -race ./... && $(GO) vet ./...
clean:
	./v8 clean

script: tui
	mkdir -p dist/stage/engine
	cp dist/arch-install dist/stage/arch-install
	cp -r installer/v8_installer dist/stage/engine/
	@if [ -f /usr/share/xkeyboard-config-2/rules/evdev.xml ]; then cp /usr/share/xkeyboard-config-2/rules/evdev.xml dist/stage/engine/v8_installer/xkb-evdev.xml; else cp /usr/share/X11/xkb/rules/evdev.xml dist/stage/engine/v8_installer/xkb-evdev.xml; fi
	cp installer/run.py dist/stage/engine/
	$(PYTHON) -c 'import importlib.util; from pathlib import Path; s=importlib.util.spec_from_file_location("package_release", "scripts/package-release.py"); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); m.build_script(Path("install.sh"),Path("dist/stage"),Path("dist/install.sh"))'
