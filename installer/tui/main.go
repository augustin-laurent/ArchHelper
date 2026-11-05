package main

import (
	"flag"
	"fmt"
	"os"
	"os/signal"
	"path/filepath"
	"syscall"

	tea "charm.land/bubbletea/v2"
)

var version = "0.2.0-preview1"

type signalMsg struct{}

func main() {
	demo := flag.Bool("demo", false, "Simulated hardware and installation; never starts the backend")
	lang := flag.String("lang", "fr", "Interface language: fr or en")
	engine := flag.String("engine", "", "Backend run.py (default: relative to the release binary)")
	showVersion := flag.Bool("version", false, "Print version")
	flag.Parse()
	if *showVersion {
		fmt.Println(version)
		return
	}
	if *lang != "fr" && *lang != "en" {
		fmt.Fprintln(os.Stderr, "--lang: fr or en")
		os.Exit(2)
	}
	if !*demo && os.Geteuid() != 0 {
		fmt.Fprintln(os.Stderr, "Run from the Arch live ISO as root, or use --demo.")
		os.Exit(1)
	}
	if *engine == "" {
		exe, err := os.Executable()
		if err != nil {
			panic(err)
		}
		*engine = filepath.Join(filepath.Dir(exe), "engine", "run.py")
	}
	m := newModel(*demo, *lang, *engine)
	p := tea.NewProgram(m, tea.WithoutSignalHandler())
	signals := make(chan os.Signal, 1)
	signal.Notify(signals, syscall.SIGINT, syscall.SIGTERM, syscall.SIGHUP)
	defer signal.Stop(signals)
	go func() {
		for range signals {
			p.Send(signalMsg{})
		}
	}()
	if _, err := p.Run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
