package main

import (
	"archive/tar"
	"bufio"
	"bytes"
	"compress/gzip"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
	"time"

	tea "charm.land/bubbletea/v2"
)

type partition struct {
	Start    int64  `json:"start"`
	Size     int64  `json:"size"`
	Action   string `json:"action"`
	FS       string `json:"fs"`
	Mount    string `json:"mount"`
	Path     string `json:"path"`
	UUID     string `json:"uuid"`
	PartUUID string `json:"partuuid"`
	ESP      bool   `json:"esp"`
}
type disk struct {
	Path       string      `json:"path"`
	Size       int64       `json:"size"`
	Model      string      `json:"model"`
	Partitions []partition `json:"partitions"`
	Blocked    []string    `json:"blocked"`
}
type options struct {
	Desktop       string      `json:"desktop"`
	Disk          string      `json:"disk"`
	Mode          string      `json:"mode"`
	Kernel        string      `json:"kernel"`
	Username      string      `json:"username"`
	Hostname      string      `json:"hostname"`
	Locale        string      `json:"locale"`
	Keyboard      string      `json:"keyboard"`
	XKB           string      `json:"xkb"`
	Timezone      string      `json:"timezone"`
	UKI           bool        `json:"uki"`
	LUKS          bool        `json:"luks"`
	Plymouth      bool        `json:"plymouth"`
	Graphics      string      `json:"graphics"`
	Network       string      `json:"network"`
	Snapshots     string      `json:"snapshots"`
	Bluetooth     bool        `json:"bluetooth"`
	ZRAM          bool        `json:"zram"`
	RootEnabled   bool        `json:"root_enabled"`
	SwapGiB       int         `json:"swap_gib"`
	SwapLocation  string      `json:"swap_location"`
	ExtraPackages []string    `json:"extra_packages"`
	CachyOS       bool        `json:"cachyos"`
	Partitions    []partition `json:"partitions"`
}
type phase struct {
	Phase string `json:"phase"`
	State string `json:"state"`
}
type response struct {
	Disks        []disk          `json:"disks"`
	Packages     []string        `json:"packages"`
	Plan         json.RawMessage `json:"plan"`
	Summary      string          `json:"summary"`
	Confirmation string          `json:"confirmation"`
	Report       string          `json:"report"`
	Error        string          `json:"error"`
	Status       string          `json:"status"`
	Online       bool            `json:"online"`
	Compatible   bool            `json:"compatible"`
	Steps        []phase         `json:"steps"`
	Hardware     struct {
		CPU     string `json:"cpu"`
		Virtual bool   `json:"virtual"`
		GPUs    []struct {
			Name      string `json:"name"`
			Supported bool   `json:"supported"`
		} `json:"gpus"`
	} `json:"hardware"`
	Network struct {
		Online bool `json:"online"`
	} `json:"network"`
}
type event struct {
	Version int      `json:"version"`
	Type    string   `json:"type"`
	Data    response `json:"data"`
}
type rpcMsg struct {
	action string
	event  event
}
type externalMsg struct{ err error }
type exportMsg struct {
	path string
	err  error
}

func waitEvent(ch <-chan rpcMsg) tea.Cmd {
	return func() tea.Msg {
		msg, ok := <-ch
		if !ok {
			return nil
		}
		return msg
	}
}

func rpc(engine, lang, action string, request map[string]any, ch chan<- rpcMsg) {
	defer close(ch)
	request["version"], request["action"] = 1, action
	body, err := json.Marshal(request)
	if err != nil {
		ch <- rpcMsg{action, event{1, "error", response{Error: "Invalid request"}}}
		return
	}
	ctx := context.Background()
	if action != "install" {
		var cancel context.CancelFunc
		timeout := 90 * time.Second
		if action == "packages" || action == "plan" {
			timeout = 5 * time.Minute
		}
		ctx, cancel = context.WithTimeout(ctx, timeout)
		defer cancel()
	}
	cmd := exec.CommandContext(ctx, "python", "-I", engine, "--rpc")
	cmd.Env = append(os.Environ(), "V8_LANG="+lang)
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	cmd.Stdin = bytes.NewReader(body)
	cmd.Stderr = io.Discard
	stdout, err := cmd.StdoutPipe()
	if err == nil {
		err = cmd.Start()
	}
	if err != nil {
		ch <- rpcMsg{action, event{1, "error", response{Error: "Cannot start Python backend"}}}
		return
	}
	scanner := bufio.NewScanner(stdout)
	scanner.Buffer(make([]byte, 4096), 2*1024*1024)
	terminal := false
	for scanner.Scan() {
		var ev event
		if json.Unmarshal(scanner.Bytes(), &ev) != nil || ev.Version != 1 {
			continue
		}
		terminal = terminal || ev.Type == "result" || ev.Type == "error"
		ch <- rpcMsg{action, ev}
	}
	err = cmd.Wait()
	clear(body)
	if !terminal {
		ch <- rpcMsg{action, event{1, "error", response{Error: fmt.Sprintf("Backend stopped without a result (exit: %v). Rescan before retrying.", err)}}}
	}
}

func exportReport(directory, destination string) error {
	out, err := os.OpenFile(destination, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if err != nil {
		return err
	}
	ok := false
	defer func() {
		out.Close()
		if !ok {
			os.Remove(destination)
		}
	}()
	zip := gzip.NewWriter(out)
	archive := tar.NewWriter(zip)
	for _, name := range []string{"plan.json", "journal.json", "result.json", "execution.log", "transaction.json"} {
		path := filepath.Join(directory, name)
		info, err := os.Lstat(path)
		if os.IsNotExist(err) {
			continue
		}
		if err != nil {
			return err
		}
		if !info.Mode().IsRegular() {
			return fmt.Errorf("unexpected report entry")
		}
		header, err := tar.FileInfoHeader(info, "")
		if err != nil {
			return err
		}
		header.Name = name
		header.Mode = 0600
		if err = archive.WriteHeader(header); err != nil {
			return err
		}
		file, err := os.Open(path)
		if err != nil {
			return err
		}
		_, err = io.Copy(archive, file)
		file.Close()
		if err != nil {
			return err
		}
	}
	if err = archive.Close(); err != nil {
		return err
	}
	if err = zip.Close(); err != nil {
		return err
	}
	if err = out.Sync(); err != nil {
		return err
	}
	ok = true
	return nil
}
