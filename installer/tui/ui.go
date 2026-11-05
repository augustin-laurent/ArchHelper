package main

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	"charm.land/bubbles/v2/spinner"
	"charm.land/bubbles/v2/viewport"
	tea "charm.land/bubbletea/v2"
	"charm.land/huh/v2"
	"charm.land/lipgloss/v2"
)

const (
	welcome = iota
	checks
	networkStep
	language
	disksStep
	account
	system
	packagesStep
	reviewStep
	installing
	resultStep
)

type model struct {
	demo                                                                    bool
	lang, engine                                                            string
	width, height, step                                                     int
	opts                                                                    options
	password, repeat, luksPassword, luksRepeat, confirmation                string
	rootPassword, rootRepeat                                                string
	swapSize                                                                string
	manualDisk, hardwareText                                                string
	form                                                                    *huh.Form
	spin                                                                    spinner.Model
	view                                                                    viewport.Model
	disks                                                                   []disk
	packages                                                                []string
	plan                                                                    json.RawMessage
	summary, expected, report, status, errorText                            string
	ready, online, busy, running, showLog, confirming, rebooting, exporting bool
	events                                                                  <-chan rpcMsg
	steps                                                                   []phase
	manual                                                                  bool
	editor                                                                  bool
	row                                                                     int
	edit                                                                    partition
	startMiB, sizeMiB, editAction, editFS, editMount                        string
	editESP                                                                 bool
	exportPath                                                              string
}

type liveKeyboardMsg struct {
	name string
	err  error
}

func (m *model) applyLiveKeyboard() tea.Cmd {
	if m.demo {
		return nil
	}
	name := m.opts.Keyboard
	return func() tea.Msg {
		cmd := exec.Command("loadkeys", "-q", "--", name)
		cmd.Stdin = os.Stdin
		return liveKeyboardMsg{name: name, err: cmd.Run()}
	}
}

func newModel(demo bool, lang, engine string) *model {
	s := spinner.New()
	s.Spinner = spinner.Line
	s.Style = lipgloss.NewStyle().Foreground(lipgloss.Color("#c9df83"))
	return &model{demo: demo, lang: lang, engine: engine, width: 80, height: 24, swapSize: "0", spin: s, view: viewport.New(viewport.WithWidth(52), viewport.WithHeight(12)), opts: options{Mode: "wipe", Kernel: "linux", Username: "user", Desktop: "hyprland", Hostname: "archlinux", Locale: "fr_FR.UTF-8", Keyboard: "fr", XKB: "fr", Timezone: "Europe/Paris", UKI: true, Plymouth: true, Graphics: "auto", Network: "networkmanager", Snapshots: "snapper", SwapLocation: "root", ExtraPackages: []string{}}}
}
func (m *model) tr(fr, en string) string {
	if m.lang == "en" {
		return en
	}
	return fr
}
func (m *model) Init() tea.Cmd { return m.spin.Tick }
func (m *model) filtering() bool {
	if m.form == nil {
		return false
	}
	field, ok := m.form.GetFocusedField().(interface{ GetFiltering() bool })
	return ok && field.GetFiltering()
}
func (m *model) titles() []string {
	return []string{m.tr("Bienvenue", "Welcome"), m.tr("Vérifications", "Checks"), m.tr("Connexion", "Network"), m.tr("Langue et clavier", "Language"), m.tr("Disque", "Disk"), m.tr("Compte", "Account"), m.tr("Système et pilotes", "System & drivers"), m.tr("Paquets", "Packages"), m.tr("Récapitulatif", "Review"), m.tr("Installation", "Installation"), m.tr("Terminé", "Result")}
}
func (m *model) contentWidth() int {
	if m.width >= 100 {
		return max(35, m.width-35)
	}
	return max(30, m.width-6)
}
func (m *model) bodyHeight() int { return max(5, m.height-10) }
func (m *model) call(action string, request map[string]any) tea.Cmd {
	m.busy = true
	m.errorText = ""
	ch := make(chan rpcMsg, 32)
	m.events = ch
	if m.demo {
		go demoRPC(action, m.lang, request, ch)
	} else {
		go rpc(m.engine, m.lang, action, request, ch)
	}
	return waitEvent(ch)
}
func (m *model) enter(step int) tea.Cmd {
	m.step = step
	m.errorText = ""
	m.form = nil
	m.confirming = false
	m.showLog = false
	switch step {
	case checks:
		m.ready = false
		return m.call("checks", map[string]any{})
	case networkStep:
		return m.call("network", map[string]any{})
	case disksStep:
		if len(m.disks) == 0 {
			return m.call("discover", map[string]any{})
		}
	case packagesStep:
		return m.call("packages", map[string]any{"cachyos": m.opts.CachyOS})
	case reviewStep:
		m.plan = nil
		m.summary = ""
		return m.call("plan", map[string]any{"options": m.opts})
	}
	return m.buildForm()
}
func (m *model) next() tea.Cmd {
	if m.busy || m.running {
		return nil
	}
	switch m.step {
	case welcome:
		return m.enter(checks)
	case checks:
		if !m.ready {
			return m.enter(checks)
		}
	case networkStep:
		if !m.online {
			return m.call("network", map[string]any{})
		}
	case disksStep:
		if m.opts.Disk == "" {
			return nil
		}
	case packagesStep:
		if len(m.packages) == 0 {
			return m.call("packages", map[string]any{"cachyos": m.opts.CachyOS})
		}
	case reviewStep:
		if len(m.plan) == 0 {
			return nil
		}
		m.confirming = true
		return m.buildForm()
	case resultStep:
		if m.status == "failed" {
			m.plan = nil
			m.disks = nil
			m.opts.Partitions = nil
			m.manual = false
			return m.enter(disksStep)
		}
		return tea.Quit
	}
	return m.enter(m.step + 1)
}

func (m *model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch v := msg.(type) {
	case tea.WindowSizeMsg:
		m.width, m.height = v.Width, v.Height
		m.view.SetWidth(m.contentWidth())
		m.view.SetHeight(m.bodyHeight())
		if m.form != nil {
			m.form.WithWidth(m.contentWidth()).WithHeight(m.bodyHeight())
		}
		return m, nil
	case spinner.TickMsg:
		var cmd tea.Cmd
		m.spin, cmd = m.spin.Update(v)
		return m, cmd
	case signalMsg:
		if m.running {
			m.errorText = m.tr("Écriture en cours : sortie bloquée.", "Disk writes in progress: exit blocked.")
			return m, nil
		}
		return m, tea.Quit
	case externalMsg:
		if v.err != nil {
			m.errorText = m.tr("La commande externe a échoué.", "External command failed.")
		}
		return m, m.call("network", map[string]any{})
	case liveKeyboardMsg:
		if v.err != nil {
			m.errorText = m.tr("Impossible d'appliquer le clavier du live : ", "Could not apply the live keyboard: ") + v.name
		} else {
			m.errorText = ""
		}
		return m, nil
	case exportMsg:
		m.busy = false
		if v.err != nil {
			m.errorText = v.err.Error()
		} else {
			m.errorText = m.tr("Rapport exporté : ", "Report exported: ") + v.path
		}
		return m, nil
	case rpcMsg:
		e := v.event
		if e.Type == "report" {
			m.report = e.Data.Report
			return m, waitEvent(m.events)
		}
		if e.Type == "progress" {
			m.steps = e.Data.Steps
			return m, waitEvent(m.events)
		}
		if e.Type == "failed" {
			m.errorText = e.Data.Error
			m.report = e.Data.Report
			return m, waitEvent(m.events)
		}
		m.busy = false
		if e.Type == "error" {
			m.errorText = e.Data.Error
			if m.running {
				m.running = false
				m.status = "failed"
				m.step = resultStep
			}
			return m, nil
		}
		switch v.action {
		case "checks":
			m.ready = e.Data.Compatible
			m.hardwareText = "CPU: " + e.Data.Hardware.CPU
			for _, g := range e.Data.Hardware.GPUs {
				m.hardwareText += "\nGPU: " + g.Name
				if !g.Supported {
					m.hardwareText += m.tr(" (NVIDIA open non pris en charge)", " (NVIDIA open unsupported)")
				}
			}
		case "network":
			m.online = e.Data.Online
		case "discover":
			m.disks = e.Data.Disks
			m.plan = nil
			m.opts.Partitions = nil
			found := false
			for _, d := range m.disks {
				if d.Path == m.opts.Disk && len(d.Blocked) == 0 {
					found = true
				}
			}
			if !found {
				m.opts.Disk = ""
			}
			return m, m.buildForm()
		case "packages":
			m.packages = e.Data.Packages
			return m, m.buildForm()
		case "plan":
			m.plan = e.Data.Plan
			m.summary = e.Data.Summary
			m.expected = e.Data.Confirmation
			m.view.SetContent(m.summary)
			m.view.GotoTop()
		case "preflight":
			m.step = installing
			m.running = true
			m.form = nil
			credentials := map[string]string{"password": m.password, "luks_password": m.luksPassword, "root_password": m.rootPassword}
			request := map[string]any{"plan": m.plan, "credentials": credentials, "confirmation": m.confirmation}
			m.password, m.repeat, m.luksPassword, m.luksRepeat, m.rootPassword, m.rootRepeat = "", "", "", "", "", ""
			return m, m.call("install", request)
		case "install":
			m.running = false
			m.step = resultStep
			m.status = e.Data.Status
			m.report = e.Data.Report
			if e.Data.Error != "" {
				m.errorText = e.Data.Error
			}
			m.form = nil
		case "export":
			m.report = e.Data.Report
			if m.demo {
				m.errorText = m.tr("Démo : aucun rapport écrit.", "Demo: no report written.")
			} else {
				m.exporting = true
				return m, m.buildForm()
			}
		}
		return m, nil
	case tea.KeyPressMsg:
		key := v.String()
		if key == "ctrl+c" || key == "ctrl+q" || key == "ctrl+z" {
			if m.running || m.busy {
				m.errorText = m.tr("Opération en cours ; patiente.", "Operation in progress; please wait.")
				return m, nil
			}
			return m, tea.Quit
		}
		if m.running {
			if key == "f6" {
				m.showLog = !m.showLog
				return m, m.loadLog()
			}
			if m.showLog {
				var cmd tea.Cmd
				m.view, cmd = m.view.Update(msg)
				return m, cmd
			}
			return m, nil
		}
		if m.busy {
			return m, nil
		}
		if key == "esc" && !m.filtering() {
			m.errorText = ""
			if m.showLog {
				m.showLog = false
				return m, nil
			}
			if m.exporting || m.rebooting || m.confirming {
				m.exporting = false
				m.rebooting = false
				m.confirming = false
				m.form = nil
				return m, nil
			}
			if m.editor {
				m.editor = false
				return m, nil
			}
			if m.manual {
				m.manual = false
				return m, m.buildForm()
			}
			if m.step > 0 && m.step < installing {
				return m, m.enter(m.step - 1)
			}
			return m, nil
		}
		if m.step == networkStep && key == "f2" {
			if m.demo {
				m.online = true
				return m, nil
			}
			return m, tea.ExecProcess(exec.Command("iwctl"), func(err error) tea.Msg { return externalMsg{err} })
		}
		if key == "f5" {
			if m.step == networkStep {
				return m, m.call("network", map[string]any{})
			}
			if m.step == disksStep {
				m.manual = false
				m.editor = false
				return m, m.call("discover", map[string]any{})
			}
			if m.step == packagesStep {
				return m, m.call("packages", map[string]any{"cachyos": m.opts.CachyOS})
			}
		}
		if m.step == resultStep && key == "r" && m.status == "completed" {
			if m.demo {
				m.errorText = m.tr("Démo : aucun redémarrage.", "Demo: reboot disabled.")
				return m, nil
			}
			m.rebooting = true
			return m, m.buildForm()
		}
		if key == "f6" && (m.step == reviewStep || m.step == resultStep) {
			if m.report != "" {
				m.exporting = true
				return m, m.buildForm()
			}
			if len(m.plan) > 0 {
				return m, m.call("export", map[string]any{"plan": m.plan})
			}
		}
		if key == "f7" && m.step == resultStep {
			m.showLog = !m.showLog
			return m, m.loadLog()
		}
		if m.manual && !m.editor {
			return m, m.manualKey(key)
		}
		if m.form == nil {
			if key == "enter" || key == "f10" {
				return m, m.next()
			}
			if m.step == reviewStep || m.showLog {
				var cmd tea.Cmd
				m.view, cmd = m.view.Update(msg)
				return m, cmd
			}
			return m, nil
		}
	}
	if m.form != nil && !m.busy {
		previousField := m.form.GetFocusedField().GetKey()
		updated, cmd := m.form.Update(msg)
		if f, ok := updated.(*huh.Form); ok {
			m.form = f
		}
		if m.form.State == huh.StateCompleted {
			return m, m.formDone()
		}
		if m.step == language && previousField == "console-keyboard" && m.form.GetFocusedField().GetKey() != previousField {
			return m, tea.Batch(cmd, m.applyLiveKeyboard())
		}
		return m, cmd
	}
	return m, nil
}

func (m *model) loadLog() tea.Cmd {
	if !m.showLog {
		return nil
	}
	content := m.tr("Aucun journal disponible.", "No log available.")
	if m.demo {
		content = "DEMO: no commands executed\nAll eight simulated phases completed."
	} else if m.report != "" {
		if data, err := os.ReadFile(filepath.Join(m.report, "execution.log")); err == nil {
			if len(data) > 64000 {
				data = data[len(data)-64000:]
			}
			content = string(data)
		}
	}
	m.view.SetContent(content)
	m.view.GotoBottom()
	return nil
}

func (m *model) View() tea.View {
	accent := lipgloss.NewStyle().Foreground(lipgloss.Color("#c9df83")).Bold(true)
	muted := lipgloss.NewStyle().Foreground(lipgloss.Color("#93a99a"))
	warning := lipgloss.NewStyle().Foreground(lipgloss.Color("#f0aa83"))
	if os.Getenv("TERM") == "linux" {
		accent = lipgloss.NewStyle().Foreground(lipgloss.Color("10")).Bold(true)
		muted = lipgloss.NewStyle().Foreground(lipgloss.Color("7"))
		warning = lipgloss.NewStyle().Foreground(lipgloss.Color("11"))
	}
	badge := "ARCH LINUX / UEFI"
	if m.demo {
		badge = "DEMO / NO DISK ACCESS"
	}
	header := accent.Render("A R C H H E L P E R") + "   " + muted.Render(m.tr("INSTALLATION", "INSTALLER")+"  /  "+badge)
	titles := m.titles()
	title := fmt.Sprintf("%02d  /  %02d     %s", m.step+1, len(titles), titles[m.step])
	body := ""
	switch {
	case m.exporting || m.rebooting || m.editor || m.confirming:
		if m.form != nil {
			body = m.form.View()
		}
	case m.showLog:
		body = m.view.View()
	case m.manual:
		body = m.manualView()
	case m.form != nil:
		body = m.form.View()
	default:
		switch m.step {
		case welcome:
			mark := accent.Render("     /\\\n    /  \\\n   / /\\ \\\n  / /  \\ \\\n /_/    \\_\\")
			intro := accent.Render(m.tr("Un système qui te ressemble.", "A system that feels like yours.")) + "\n\n" + m.tr("Choisis ton disque, ton environnement et tes outils.\nPrépare une installation Arch à ta mesure.\n\nExamine toutes les modifications avant\nde confirmer l'installation.", "Choose your disk, environment and tools.\nPrepare an Arch installation of your own.\n\nReview every change before confirming\nthe installation.") + "\n\n" + accent.Render(m.tr("ENTRÉE  →  Commencer", "ENTER  →  Begin"))
			body = lipgloss.JoinHorizontal(lipgloss.Top, lipgloss.NewStyle().Width(16).Render(mark), intro)
		case checks:
			body = m.tr("ISO Arch officielle · x86-64 · UEFI\nPython 3.14 · archinstall 4.5\nBureaux des dépôts officiels Arch\n\n", "Official Arch ISO · x86-64 · UEFI\nPython 3.14 · archinstall 4.5\nDesktops from official Arch repositories\n\n")
			if m.ready {
				body += m.tr("[OK] Prêt. Entrée pour continuer.", "[OK] Ready. Enter to continue.") + "\n\n" + m.hardwareText
			} else {
				body += m.tr("Les vérifications doivent réussir pour continuer.", "Checks must pass before continuing.")
			}
		case networkStep:
			state := m.tr("Hors ligne", "Offline")
			if m.online {
				state = m.tr("Connecté", "Online")
			}
			body = accent.Render(state) + "\n\n" + m.tr("Ethernet : configuration automatique du live.\nWi-Fi : F2 ouvre iwctl ; taper exit pour revenir.\nF5 relance le diagnostic HTTPS.\n\nLe réseau du système installé sera choisi plus loin.", "Ethernet: use the live automatic configuration.\nWi-Fi: F2 opens iwctl; type exit to return.\nF5 repeats the HTTPS connectivity check.\n\nChoose networking for the installed system later.")
		case disksStep:
			body = m.tr("Aucun disque disponible. F5 : rescanner.", "No disk available. F5: rescan.")
		case reviewStep:
			body = m.view.View()
		case installing:
			done := 0
			var lines []string
			for _, p := range m.steps {
				prefix := "[ ]"
				if p.State == "completed" {
					prefix = "[+]"
					done++
				}
				if p.State == "started" {
					prefix = m.spin.View()
				}
				if p.State == "failed" {
					prefix = "[!]"
				}
				lines = append(lines, prefix+" "+m.phaseName(p.Phase))
			}
			body = strings.Join(lines, "\n") + fmt.Sprintf("\n\n%d / 8 %s", done, m.tr("étapes terminées", "steps completed"))
		case resultStep:
			if m.status == "completed" {
				body = accent.Render(m.tr("Arch Linux est installé.", "Arch Linux is installed.")) + "\n\n" + m.tr("Retire l'ISO lors du redémarrage.\nConnecte-toi avec le compte créé.\n\nChoisis la session Wayland installée.\n\nR : redémarrer   Entrée : quitter", "Remove the ISO when rebooting.\nSign in with your new account.\n\nChoose the installed Wayland session.\n\nR: reboot   Enter: quit")
			} else {
				body = warning.Render(m.tr("Installation interrompue.", "Installation interrupted.")) + "\n\n" + m.tr("Exporte le rapport avant d'éteindre le live.\nUne nouvelle tentative exige un nouveau plan.\n\nEntrée : rescanner les disques", "Export the report before shutting down the live.\nA new attempt requires a fresh plan.\n\nEnter: rescan disks")
			}
			if m.report != "" {
				body += "\n\n" + m.report
			}
		}
	}
	if m.busy && !m.running {
		body = m.spin.View() + " " + m.tr("Vérification en cours…", "Checking…") + "\n\n" + body
	}
	body = lipgloss.NewStyle().Width(m.contentWidth()).Height(m.bodyHeight()).MaxHeight(m.bodyHeight()).Render(body)
	if m.width >= 100 && m.step != welcome {
		var nav []string
		for i, t := range titles {
			marker := "·"
			if i < m.step {
				marker = "✓"
			}
			line := fmt.Sprintf(" %s  %02d  %s", marker, i+1, t)
			if i == m.step {
				line = accent.Render(fmt.Sprintf(" ›  %02d  %s", i+1, t))
			} else {
				line = muted.Render(line)
			}
			nav = append(nav, lipgloss.NewStyle().MaxWidth(27).Render(line))
		}
		label := muted.Render(m.tr("  PARCOURS", "  YOUR PROGRESS")) + "\n" + muted.Render("  ──────────────────────")
		sidebar := lipgloss.NewStyle().Width(29).Render(label + "\n" + strings.Join(nav, "\n"))
		body = lipgloss.JoinHorizontal(lipgloss.Top, sidebar, body)
	}
	help := m.tr("Tab : champ   Entrée : valider   Échap : retour   Ctrl+Q : quitter", "Tab: field   Enter: accept   Esc: back   Ctrl+Q: quit")
	if m.step == reviewStep {
		help = m.tr("PgUp/PgDn : lire   Entrée : confirmer   F6 : exporter   Échap : retour", "PgUp/PgDn: read   Enter: confirm   F6: export   Esc: back")
	}
	if m.step == resultStep {
		help = m.tr("F6 : exporter le rapport   F7 : journal   R : redémarrer", "F6: export report   F7: log   R: reboot")
	}
	if m.running {
		help = m.tr("F6 : journal   La sortie est bloquée pendant l'installation.", "F6: log   Exit is blocked during installation.")
	}
	errorLine := ""
	if m.errorText != "" {
		errorLine = warning.Render(m.errorText)
	}
	content := header + "\n" + muted.Render(strings.Repeat("─", max(1, m.width-4))) + "\n" + accent.Render(title) + "\n\n" + body + "\n" + lipgloss.NewStyle().Width(max(1, m.width-4)).MaxHeight(2).Render(errorLine) + "\n" + muted.Render(help)
	base := lipgloss.NewStyle().Padding(1, 2).MaxWidth(m.width).MaxHeight(m.height).Foreground(lipgloss.Color("#e4e8de")).Background(lipgloss.Color("#14201c"))
	if os.Getenv("TERM") == "linux" {
		base = base.Foreground(lipgloss.Color("7")).Background(lipgloss.Color("0"))
	}
	v := tea.NewView(base.Render(content))
	v.AltScreen = true
	return v
}

func (m *model) phaseName(p string) string {
	fr := map[string]string{"preflight": "Préparation et téléchargement", "partition-format": "Partitionnement et formatage", "mount": "Montage", "base-packages": "Installation d'Arch", "desktop-packages": "Configuration du bureau", "configuration": "Comptes et services", "boot": "Démarrage UEFI", "verification": "Vérifications finales"}
	en := map[string]string{"preflight": "Preparation and downloads", "partition-format": "Partitioning and formatting", "mount": "Mounting", "base-packages": "Arch installation", "desktop-packages": "Desktop configuration", "configuration": "Accounts and services", "boot": "UEFI boot", "verification": "Final checks"}
	return m.tr(fr[p], en[p])
}
