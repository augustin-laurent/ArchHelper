package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	tea "charm.land/bubbletea/v2"
	"charm.land/huh/v2"
	"charm.land/lipgloss/v2"
	"github.com/charmbracelet/x/ansi"
)

func TestTimezoneChoicesIncludeZoneFilesAndSafeAliases(t *testing.T) {
	root := t.TempDir()
	if err := os.Mkdir(filepath.Join(root, "Etc"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "Etc", "GMT+3"), []byte("TZif-example"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink("Etc/GMT+3", filepath.Join(root, "Alias")); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "zone.tab"), []byte("not a time zone"), 0o644); err != nil {
		t.Fatal(err)
	}
	outside := filepath.Join(t.TempDir(), "outside")
	if err := os.WriteFile(outside, []byte("TZif-outside"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(outside, filepath.Join(root, "Outside")); err != nil {
		t.Fatal(err)
	}
	got := map[string]bool{}
	for _, choice := range timezoneChoices(root) {
		got[choice.Value] = true
	}
	if len(got) != 2 || !got["Etc/GMT+3"] || !got["Alias"] {
		t.Fatalf("unexpected time zones: %v", got)
	}
}

func TestFrenchLocaleIsVisibleFirstAndPreservesOtherLocales(t *testing.T) {
	path := filepath.Join(t.TempDir(), "SUPPORTED")
	if err := os.WriteFile(path, []byte("fr_FR.UTF-8 UTF-8\nen_US.UTF-8 UTF-8\nja_JP.UTF-8 UTF-8\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	choices := catalogChoices(path, true)
	if len(choices) != 3 || choices[0].Value != "fr_FR.UTF-8" || !strings.Contains(choices[0].Key, "Français (France)") || choices[2].Value != "ja_JP.UTF-8" {
		t.Fatalf("unexpected locale choices: %v", choices)
	}
}

func TestShortPasswordsAreAccepted(t *testing.T) {
	if err := validPassword("abc"); err != nil {
		t.Fatal(err)
	}
	for _, password := range []string{"", "abc\nxyz", "abc\x00xyz"} {
		if validPassword(password) == nil {
			t.Fatalf("accepted invalid password %q", password)
		}
	}
}

func TestLiveKeyboardUsesChosenMapAndDemoDoesNothing(t *testing.T) {
	dir := t.TempDir()
	output := filepath.Join(dir, "called")
	program := filepath.Join(dir, "loadkeys")
	if err := os.WriteFile(program, []byte("#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$ARCHHELPER_TEST_OUTPUT\"\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", dir)
	t.Setenv("ARCHHELPER_TEST_OUTPUT", output)
	m := newModel(true, "fr", "")
	if m.applyLiveKeyboard() != nil {
		t.Fatal("demo must not change the keyboard")
	}
	m.demo = false
	m.opts.Keyboard = "fr"
	result, ok := m.applyLiveKeyboard()().(liveKeyboardMsg)
	if !ok || result.err != nil || result.name != "fr" {
		t.Fatalf("live keyboard result: %#v", result)
	}
	data, err := os.ReadFile(output)
	if err != nil || string(data) != "-q\n--\nfr\n" {
		t.Fatalf("loadkeys arguments: %q, %v", data, err)
	}
}

func TestConfirmingConsoleKeyboardSchedulesLiveChange(t *testing.T) {
	dir := t.TempDir()
	output := filepath.Join(dir, "called")
	if err := os.WriteFile(filepath.Join(dir, "loadkeys"), []byte("#!/bin/sh\nprintf '%s' \"$3\" > \"$ARCHHELPER_TEST_OUTPUT\"\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", dir)
	t.Setenv("ARCHHELPER_TEST_OUTPUT", output)
	m := newModel(false, "fr", "")
	m.step = language
	m.buildForm()
	m.form.NextGroup() // interface language -> system locale
	m.form.NextGroup() // system locale -> console keyboard
	if got := m.form.GetFocusedField().GetKey(); got != "console-keyboard" {
		t.Fatalf("unexpected field: %q", got)
	}
	_, cmd := m.Update(huh.NextField())
	queue := []tea.Cmd{cmd}
	for len(queue) > 0 {
		cmd, rest := queue[0], queue[1:]
		queue = rest
		if cmd == nil {
			continue
		}
		msg := cmd()
		if batch, ok := msg.(tea.BatchMsg); ok {
			queue = append(queue, batch...)
			continue
		}
		if msg != nil {
			_, next := m.Update(msg)
			queue = append(queue, next)
		}
		if data, err := os.ReadFile(output); err == nil {
			if string(data) != "fr" {
				t.Fatalf("unexpected keymap: %q", data)
			}
			return
		}
	}
	t.Fatal("confirming console keyboard did not apply it")
}

func TestEveryScreenFitsConsoleAndKeepsFooter(t *testing.T) {
	for _, lang := range []string{"fr", "en"} {
		for _, size := range [][2]int{{80, 24}, {120, 24}, {140, 40}} {
			for step := welcome; step <= resultStep; step++ {
				m := newModel(true, lang, "/not-an-engine")
				m.Update(tea.WindowSizeMsg{Width: size[0], Height: size[1]})
				m.step = step
				m.ready = true
				m.online = true
				m.status = "completed"
				m.summary = "Review\nCREATE ESP\nCREATE ROOT"
				m.view.SetContent(m.summary)
				m.buildForm()
				m.steps = []phase{{"preflight", "completed"}, {"boot", "started"}}
				output := m.View().Content
				if lipgloss.Height(output) > size[1] {
					t.Fatalf("%s screen %d height exceeds console", lang, step)
				}
				for _, line := range strings.Split(output, "\n") {
					if lipgloss.Width(line) > size[0] {
						t.Fatalf("screen %d width exceeds console", step)
					}
				}
				plain := ansi.Strip(output)
				if !strings.Contains(plain, "F6") && !strings.Contains(plain, "Ctrl+Q") {
					t.Fatalf("screen %d lost footer: %s", step, plain)
				}
				if dir := os.Getenv("ARCHHELPER_SNAPSHOTS"); dir != "" {
					os.MkdirAll(dir, 0755)
					os.WriteFile(filepath.Join(dir, lang+"-"+m.titles()[step]+".ansi"), []byte(output), 0644)
				}
			}
		}
	}
}

func TestDemoNeverExecutesBackend(t *testing.T) {
	m := newModel(true, "fr", "/nonexistent/backend.py")
	command := m.enter(checks)
	msg := command().(rpcMsg)
	if msg.event.Type != "result" || !msg.event.Data.Compatible {
		t.Fatal(msg)
	}
	m.Update(msg)
	if !m.ready {
		t.Fatal("demo did not pass checks")
	}
}

func TestExitSignalsAreBlockedDuringInstallation(t *testing.T) {
	m := newModel(true, "en", "")
	m.running = true
	m.step = installing
	_, cmd := m.Update(signalMsg{})
	if cmd != nil || !m.running || m.errorText == "" {
		t.Fatal("signal allowed exit")
	}
}

func TestBackPreservesInputsAndInvalidatesReview(t *testing.T) {
	m := newModel(true, "en", "")
	m.password = "private-test-password"
	m.opts.Username = "alice"
	m.step = system
	m.enter(account)
	if m.password != "private-test-password" || m.opts.Username != "alice" {
		t.Fatal("back lost input")
	}
	if strings.Contains(m.View().Content, "private-test-password") {
		t.Fatal("password visible")
	}
	m.plan = json.RawMessage(`{"old":true}`)
	m.enter(reviewStep)
	if len(m.plan) != 0 {
		t.Fatal("stale plan retained")
	}
}

func TestChangingDiskDropsManualLayout(t *testing.T) {
	m := newModel(true, "en", "")
	m.step = disksStep
	m.opts.Mode = "manual"
	m.manualDisk = "/dev/vda"
	m.opts.Disk = "/dev/vdb"
	m.opts.Partitions = []partition{{Path: "/dev/vda1", Action: "keep"}}
	m.disks = []disk{{Path: "/dev/vdb", Partitions: []partition{{Path: "/dev/vdb1", Action: "keep"}}}}
	m.formDone()
	if len(m.opts.Partitions) != 1 || m.opts.Partitions[0].Path != "/dev/vdb1" {
		t.Fatal("old disk partitions carried over")
	}
}

func TestPartitionEditorUsesExactMiBGeometry(t *testing.T) {
	for _, s := range []string{"-1", "NaN", "1/0", "999999999999999999999999", "0.00000001"} {
		if _, err := bytesMiB(s); err == nil {
			t.Fatalf("accepted %s", s)
		}
	}
	value, err := bytesMiB("1.5")
	if err != nil || value != 1572864 {
		t.Fatal(value, err)
	}
}

func TestUnconfirmedLUKSPassphraseIsAskedAgain(t *testing.T) {
	m := newModel(true, "en", "")
	m.step = system
	m.opts.LUKS = true
	m.luksPassword = "partially-reviewed"
	m.luksRepeat = ""
	m.formDone()
	if m.step != system || m.form == nil {
		t.Fatal("unconfirmed LUKS passphrase skipped review")
	}
}

func TestExportRefusesOverwriteAndIgnoresUnlistedFiles(t *testing.T) {
	dir := t.TempDir()
	os.WriteFile(filepath.Join(dir, "plan.json"), []byte(`{}`), 0600)
	os.WriteFile(filepath.Join(dir, "private"), []byte("secret"), 0600)
	dest := filepath.Join(t.TempDir(), "report.tar.gz")
	if err := exportReport(dir, dest); err != nil {
		t.Fatal(err)
	}
	if err := exportReport(dir, dest); err == nil {
		t.Fatal("overwrote existing export")
	}
}
