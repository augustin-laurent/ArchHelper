package main

import (
	"encoding/json"
	"fmt"
	"time"
)

var phases = []string{"preflight", "partition-format", "mount", "base-packages", "desktop-packages", "configuration", "boot", "verification"}

func demoRPC(action, lang string, request map[string]any, ch chan<- rpcMsg) {
	defer close(ch)
	send := func(kind string, r response) { ch <- rpcMsg{action, event{1, kind, r}} }
	switch action {
	case "checks":
		r := response{Compatible: true}
		r.Hardware.CPU = "intel (demo)"
		r.Hardware.Virtual = true
		send("result", r)
	case "network":
		send("result", response{Online: true})
	case "discover":
		send("result", response{Disks: []disk{{Path: "/dev/nvme0n1", Size: 512 * 1024 * 1024 * 1024, Model: "Demo NVMe - virtual fixture", Partitions: []partition{}}, {Path: "/dev/sda", Size: 64 * 1024 * 1024 * 1024, Model: "Arch installation media", Blocked: []string{"Live media"}}}})
	case "packages":
		send("result", response{Packages: []string{"firefox", "git", "htop", "vim"}})
	case "plan":
		opts := request["options"].(options)
		if opts.Mode == "manual" && len(opts.Partitions) == 0 {
			send("error", response{Error: "Demo: add root and ESP partitions in the editor"})
			return
		}
		raw, _ := json.Marshal(opts)
		notice := "This is a fictional preview. Real plans are validated\nand bound to their backend-generated fingerprint."
		heading := "SIMULATION / NO DISK ACCESS"
		if lang == "fr" {
			heading = "SIMULATION / AUCUN ACCÈS DISQUE"
			notice = "Aperçu fictif. Les vrais plans sont validés par le moteur\net liés à leur empreinte de confirmation."
		}
		diskTitle, systemTitle, serviceTitle := "DISK / PARTITIONS", "SYSTEM", "SERVICES / SOFTWARE"
		if lang == "fr" {
			diskTitle, systemTitle, serviceTitle = "DISQUE / PARTITIONS", "SYSTÈME", "SERVICES / LOGICIELS"
		}
		send("result", response{Plan: raw, Confirmation: "DEMO " + opts.Disk, Summary: fmt.Sprintf("%s\n\n01  %s\n%s  ·  512 GiB\nMode: %s\n  CREATE  ESP    ·  4 GiB\n    FAT32  →  /efi\n  CREATE  ROOT   ·  508 GiB\n    Btrfs  →  /\n\n02  %s\n%s  ·  %s\nGPU: %s\nUKI=%t  ·  LUKS2=%t\n%s@%s  ·  %s\nConsole: %s  ·  XKB: %s\n%s\n\n03  %s\nNetwork: %s  ·  Snapshots: %s\nBluetooth: %t  ·  ZRAM: %t\nSwap: %d GiB (%s)\nCachyOS: %t\nPackages: %v\n\n%s", heading, diskTitle, opts.Disk, opts.Mode, systemTitle, opts.Kernel, opts.Desktop, opts.Graphics, opts.UKI, opts.LUKS, opts.Username, opts.Hostname, opts.Locale, opts.Keyboard, opts.XKB, opts.Timezone, serviceTitle, opts.Network, opts.Snapshots, opts.Bluetooth, opts.ZRAM, opts.SwapGiB, opts.SwapLocation, opts.CachyOS, opts.ExtraPackages, notice)})
	case "preflight":
		send("result", response{})
	case "install":
		steps := make([]phase, len(phases))
		for i, p := range phases {
			steps[i] = phase{p, "planned"}
		}
		for i := range steps {
			steps[i].State = "started"
			send("progress", response{Steps: append([]phase(nil), steps...)})
			time.Sleep(450 * time.Millisecond)
			steps[i].State = "completed"
			send("progress", response{Steps: append([]phase(nil), steps...)})
		}
		send("result", response{Status: "completed"})
	case "export":
		send("result", response{})
	}
}
