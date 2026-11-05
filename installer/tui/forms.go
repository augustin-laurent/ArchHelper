package main

import (
	"errors"
	"fmt"
	"math/big"
	"os"
	"os/exec"
	"regexp"
	"strconv"
	"strings"

	tea "charm.land/bubbletea/v2"
	"charm.land/huh/v2"
	"charm.land/lipgloss/v2"
)

func theme(dark bool) *huh.Styles {
	t := huh.ThemeBase(dark)
	blue, purple, muted := "#c9df83", "#e4ad78", "#93a99a"
	if os.Getenv("TERM") == "linux" {
		blue, purple, muted = "10", "11", "7"
	}
	t.Focused.Title = t.Focused.Title.Foreground(lipgloss.Color(blue))
	t.Focused.Base = lipgloss.NewStyle().PaddingLeft(1).BorderLeft(true).BorderStyle(lipgloss.NormalBorder()).BorderForeground(lipgloss.Color(blue))
	t.Focused.SelectSelector = t.Focused.SelectSelector.Foreground(lipgloss.Color(purple))
	t.Focused.Description = t.Focused.Description.Foreground(lipgloss.Color(muted))
	t.Focused.FocusedButton = t.Focused.FocusedButton.Background(lipgloss.Color(blue)).Foreground(lipgloss.Color("0"))
	t.Blurred.Title = t.Blurred.Title.Foreground(lipgloss.Color(muted))
	t.Focused.NextIndicator = t.Focused.NextIndicator.SetString(">")
	t.Focused.PrevIndicator = t.Focused.PrevIndicator.SetString("<")
	return t
}
func (m *model) buildForm() tea.Cmd {
	m.form = nil
	var fields []huh.Field
	switch {
	case m.exporting:
		if m.exportPath == "" {
			m.exportPath = "/tmp/arch-install-report.tar.gz"
		}
		fields = []huh.Field{huh.NewInput().Title(m.tr("Destination du rapport (.tar.gz)", "Report destination (.tar.gz)")).Description(m.tr("Choisis un support persistant. Un fichier existant ne sera pas écrasé.", "Choose persistent storage. Existing files will not be overwritten.")).Value(&m.exportPath)}
	case m.rebooting:
		fields = []huh.Field{huh.NewConfirm().Title(m.tr("Redémarrer maintenant ?", "Reboot now?")).Affirmative(m.tr("Redémarrer", "Reboot")).Negative(m.tr("Rester ici", "Stay here")).Value(&m.ready)}
		m.ready = false
	case m.confirming:
		m.confirmation = ""
		m.ready = false
		fields = []huh.Field{huh.NewConfirm().Title(m.tr("Appliquer les modifications et installer ?", "Apply changes and install?")).Description(m.tr("Les opérations sur les disques indiquées dans le récapitulatif seront exécutées.", "The disk operations shown in the review will be performed.")).Affirmative(m.tr("Installer", "Install")).Negative(m.tr("Annuler", "Cancel")).Value(&m.ready)}
	case m.editor:
		fields = []huh.Field{
			huh.NewSelect[string]().Title(m.tr("Action", "Action")).Options(huh.NewOption("KEEP", "keep"), huh.NewOption("FORMAT", "format"), huh.NewOption("DELETE", "delete"), huh.NewOption("CREATE", "create")).Value(&m.editAction),
			huh.NewInput().Title(m.tr("Début (MiB)", "Start (MiB)")).Value(&m.startMiB).Validate(validMiB),
			huh.NewInput().Title(m.tr("Taille (MiB)", "Size (MiB)")).Value(&m.sizeMiB).Validate(validMiB),
			huh.NewSelect[string]().Title(m.tr("Système de fichiers", "Filesystem")).Options(huh.NewOption(m.tr("Original", "Original"), "original"), huh.NewOption("Btrfs", "btrfs"), huh.NewOption("ext4", "ext4"), huh.NewOption("FAT32", "fat32")).Value(&m.editFS),
			huh.NewSelect[string]().Title(m.tr("Montage", "Mount")).Options(huh.NewOption("-", ""), huh.NewOption("/", "/"), huh.NewOption("/efi", "/efi"), huh.NewOption("/home", "/home"), huh.NewOption("/srv", "/srv")).Value(&m.editMount),
			huh.NewConfirm().Title("ESP").Value(&m.editESP),
		}
	default:
		switch m.step {
		case language:
			fields = []huh.Field{
				huh.NewSelect[string]().Title(m.tr("Langue de l'interface", "Interface language")).Options(huh.NewOption("Français", "fr"), huh.NewOption("English", "en")).Value(&m.lang),
				huh.NewSelect[string]().Title(m.tr("Langue du système", "System locale")).Description(m.tr("/ pour rechercher", "/ to search")).Options(catalogChoices("/usr/share/i18n/SUPPORTED", true)...).Value(&m.opts.Locale),
				huh.NewSelect[string]().Key("console-keyboard").Title(m.tr("Clavier de la console", "Console keyboard")).Description(m.tr("/ pour rechercher. Appliqué dès validation ; choisis aussi le clavier graphique.", "/ to search. Applied when confirmed; also choose the graphical layout.")).Options(keyboardChoices()...).Value(&m.opts.Keyboard),
				huh.NewSelect[string]().Title(m.tr("Clavier graphique et SDDM", "Graphical and SDDM keyboard")).Description(m.tr("/ pour rechercher une disposition ou variante.", "/ to search layouts and variants.")).Options(graphicalKeyboardChoices(m.engine)...).Value(&m.opts.XKB),
				huh.NewSelect[string]().Title(m.tr("Fuseau horaire", "Time zone")).Description(m.tr("/ pour rechercher", "/ to search")).Options(timezoneChoices("/usr/share/zoneinfo")...).Value(&m.opts.Timezone),
			}
		case disksStep:
			choices := []huh.Option[string]{}
			for _, d := range m.disks {
				if len(d.Blocked) == 0 {
					choices = append(choices, huh.NewOption(fmt.Sprintf("%s  %.0f GiB  %s", d.Path, float64(d.Size)/(1<<30), d.Model), d.Path))
				}
			}
			if len(choices) == 0 {
				return nil
			}
			fields = []huh.Field{
				huh.NewSelect[string]().Title(m.tr("Disque cible", "Target disk")).Description(m.tr("Les supports occupés et le média live sont exclus. F5 : rescanner.", "Busy devices and live media are excluded. F5: rescan.")).Options(choices...).Value(&m.opts.Disk),
				huh.NewSelect[string]().Title(m.tr("Partitionnement", "Partitioning")).Options(huh.NewOption(m.tr("Effacer tout le disque", "Erase entire disk"), "wipe"), huh.NewOption(m.tr("Utiliser l'espace non alloué", "Use unallocated space"), "alongside"), huh.NewOption(m.tr("Éditeur manuel", "Manual editor"), "manual")).Value(&m.opts.Mode),
			}
		case account:
			fields = []huh.Field{
				huh.NewInput().Title(m.tr("Utilisateur administrateur", "Administrator username")).Description(m.tr("Saisir root pour une installation en console sans autre utilisateur.", "Enter root for a console-only installation without another user.")).Value(&m.opts.Username).Validate(func(s string) error {
					if !regexp.MustCompile(`^[a-z_][a-z0-9_-]{0,30}$`).MatchString(s) {
						return errors.New(m.tr("Nom Unix invalide.", "Invalid Unix username."))
					}
					return nil
				}),
				huh.NewInput().Title(m.tr("Nom de la machine", "Hostname")).Value(&m.opts.Hostname),
				huh.NewInput().Title(m.tr("Mot de passe", "Password")).EchoMode(huh.EchoModePassword).Value(&m.password).Validate(validPassword),
				huh.NewInput().Title(m.tr("Confirmer le mot de passe", "Confirm password")).EchoMode(huh.EchoModePassword).Value(&m.repeat).Validate(func(s string) error {
					if s != m.password {
						return errors.New(m.tr("Les mots de passe diffèrent.", "Passwords do not match."))
					}
					return nil
				}),
				huh.NewInput().Title(m.tr("Mot de passe root facultatif", "Optional root password")).Description(m.tr("Laisser vide pour verrouiller root. Ignoré si l'utilisateur est root.", "Leave empty to lock root. Ignored when the user is root.")).EchoMode(huh.EchoModePassword).Value(&m.rootPassword).Validate(func(s string) error {
					if s != "" && m.opts.Username != "root" {
						return validPassword(s)
					}
					return nil
				}),
				huh.NewInput().Title(m.tr("Confirmer le mot de passe root", "Confirm root password")).EchoMode(huh.EchoModePassword).Value(&m.rootRepeat).Validate(func(s string) error {
					if m.opts.Username != "root" && s != m.rootPassword {
						return errors.New(m.tr("Les mots de passe diffèrent.", "Passwords do not match."))
					}
					return nil
				}),
			}
		case system:
			fields = []huh.Field{
				huh.NewSelect[string]().Title(m.tr("Bureau Wayland", "Wayland desktop")).Description(m.tr("Un seul profil, avec son écran de connexion adapté. Sans thème personnalisé.", "One profile with its matching login manager. No custom desktop theme.")).Options(
					huh.NewOption("Hyprland + SDDM + UWSM", "hyprland"),
					huh.NewOption("KDE Plasma + Plasma Login Manager", "plasma"),
					huh.NewOption("GNOME + GDM", "gnome"),
					huh.NewOption("Niri + SDDM", "niri"),
					huh.NewOption("Sway + SDDM", "sway"),
					huh.NewOption("River Classic + SDDM", "river"),
					huh.NewOption("Labwc + SDDM", "labwc"),
					huh.NewOption("Wayfire + SDDM", "wayfire"),
					huh.NewOption("COSMIC + COSMIC Greeter", "cosmic"),
					huh.NewOption("LXQt Wayland / Labwc + SDDM", "lxqt"),
					huh.NewOption("Weston + SDDM", "weston"),
					huh.NewOption(m.tr("Aucun bureau (console)", "No desktop (console)"), "none"),
				).Value(&m.opts.Desktop).Validate(func(s string) error {
					if m.opts.Username == "root" && s != "none" {
						return errors.New(m.tr("Root seul nécessite le profil console.", "Root-only requires the console profile."))
					}
					return nil
				}),
				huh.NewConfirm().Title(m.tr("Activer le dépôt CachyOS", "Enable CachyOS repository")).Description(m.tr("Ajoute CachyOS et multilib ; vérifie le trousseau de signatures.", "Adds CachyOS and multilib; verifies the signing keyring.")).Value(&m.opts.CachyOS),
				huh.NewSelect[string]().Title(m.tr("Noyau", "Kernel")).Options(huh.NewOption("Linux", "linux"), huh.NewOption("Linux LTS", "linux-lts"), huh.NewOption("Linux Zen", "linux-zen"), huh.NewOption("Linux Hardened", "linux-hardened"), huh.NewOption("Linux CachyOS", "linux-cachyos")).Value(&m.opts.Kernel).Validate(func(s string) error {
					if s == "linux-cachyos" && !m.opts.CachyOS {
						return errors.New(m.tr("Active d'abord le dépôt CachyOS.", "Enable the CachyOS repository first."))
					}
					return nil
				}),
				huh.NewSelect[string]().Title(m.tr("Pilotes graphiques", "Graphics drivers")).Description(m.tr("580 propriétaire : dépôt CachyOS et GPU compatibles requis. DKMS si nécessaire.", "Proprietary 580: CachyOS repository and supported GPU required. DKMS when needed.")).Options(huh.NewOption(m.tr("Détection automatique", "Automatic detection"), "auto"), huh.NewOption("Intel / AMD (Mesa)", "mesa"), huh.NewOption("NVIDIA open + utils", "nvidia"), huh.NewOption(m.tr("NVIDIA 580 propriétaire (CachyOS)", "NVIDIA 580 proprietary (CachyOS)"), "nvidia-580"), huh.NewOption("Nouveau (Mesa)", "nouveau"), huh.NewOption(m.tr("Machine virtuelle", "Virtual machine"), "vm")).Value(&m.opts.Graphics),
				huh.NewConfirm().Title("UKI").Value(&m.opts.UKI), huh.NewConfirm().Title("Plymouth").Value(&m.opts.Plymouth),
				huh.NewConfirm().Title(m.tr("Chiffrer la racine avec LUKS2", "Encrypt root with LUKS2")).Value(&m.opts.LUKS),
				huh.NewSelect[string]().Title(m.tr("Gestion du réseau", "Network management")).Description(m.tr("systemd-networkd configure Ethernet en DHCP ; le Wi-Fi nécessite une configuration supplémentaire.", "systemd-networkd configures Ethernet using DHCP; Wi-Fi requires additional setup.")).Options(huh.NewOption("NetworkManager", "networkmanager"), huh.NewOption("systemd-networkd", "networkd"), huh.NewOption(m.tr("Aucun", "None"), "none")).Value(&m.opts.Network),
				huh.NewSelect[string]().Title(m.tr("Instantanés", "Snapshots")).Options(huh.NewOption("Snapper", "snapper"), huh.NewOption("Timeshift", "timeshift"), huh.NewOption(m.tr("Aucun", "None"), "none")).Value(&m.opts.Snapshots),
				huh.NewConfirm().Title("Bluetooth").Value(&m.opts.Bluetooth),
				huh.NewConfirm().Title("ZRAM").Description(m.tr("Swap compressé en mémoire, jusqu'à 4 Gio.", "Compressed memory swap, up to 4 GiB.")).Value(&m.opts.ZRAM),
				huh.NewInput().Title(m.tr("Swap sur disque (Gio)", "Disk swap (GiB)")).Description(m.tr("0 désactive le swap sur disque.", "0 disables disk swap.")).Value(&m.swapSize).Validate(func(s string) error {
					value, err := strconv.Atoi(s)
					if err != nil || value < 0 || value > 1024 {
						return errors.New(m.tr("Entier entre 0 et 1024 requis.", "Enter an integer from 0 to 1024."))
					}
					return nil
				}),
				huh.NewSelect[string]().Title(m.tr("Emplacement du swap", "Swap location")).Description(m.tr("Une partition /home séparée n'est pas chiffrée par LUKS racine.", "A separate /home partition is not encrypted by root LUKS.")).Options(huh.NewOption(m.tr("Racine (/swap)", "Root (/swap)"), "root"), huh.NewOption("/home", "home")).Value(&m.opts.SwapLocation),
			}
		case packagesStep:
			if len(m.packages) == 0 {
				return nil
			}
			choices := make([]huh.Option[string], 0, len(m.packages))
			for _, p := range m.packages {
				choices = append(choices, huh.NewOption(p, p))
			}
			fields = []huh.Field{huh.NewMultiSelect[string]().Title(m.tr("Paquets supplémentaires", "Additional packages")).Description(m.tr("/ : rechercher · Espace : sélectionner · Entrée : continuer", "/: search · Space: select · Enter: continue")).Options(choices...).Filterable(true).Value(&m.opts.ExtraPackages)}
		}
	}
	if len(fields) == 0 {
		return nil
	}
	// One field per group keeps all controls visible even in an 80x24 console.
	groups := make([]*huh.Group, 0, len(fields))
	for _, f := range fields {
		groups = append(groups, huh.NewGroup(f))
	}
	m.form = huh.NewForm(groups...).WithTheme(huh.ThemeFunc(theme)).WithWidth(m.contentWidth()).WithHeight(m.bodyHeight()).WithShowHelp(false)
	return m.form.Init()
}

func validPassword(s string) error {
	if s == "" || strings.ContainsAny(s, "\x00\r\n") {
		return errors.New("Password required; no newline or NUL")
	}
	return nil
}
func bytesMiB(s string) (int64, error) {
	r, ok := new(big.Rat).SetString(s)
	if !ok || r.Sign() < 0 {
		return 0, errors.New("Invalid MiB value")
	}
	r.Mul(r, big.NewRat(1<<20, 1))
	if !r.IsInt() || !r.Num().IsInt64() {
		return 0, errors.New("MiB must represent an exact byte count")
	}
	return r.Num().Int64(), nil
}
func validMiB(s string) error { _, err := bytesMiB(s); return err }

func (m *model) formDone() tea.Cmd {
	m.form = nil
	if m.exporting {
		m.exporting = false
		if m.demo {
			m.errorText = m.tr("Démo : aucune écriture.", "Demo: no files written.")
			return nil
		}
		m.busy = true
		src, dest := m.report, m.exportPath
		return func() tea.Msg { return exportMsg{dest, exportReport(src, dest)} }
	}
	if m.rebooting {
		m.rebooting = false
		if m.ready {
			return tea.ExecProcess(exec.Command("systemctl", "reboot"), func(err error) tea.Msg { return exportMsg{err: err} })
		}
		return nil
	}
	if m.confirming {
		m.confirming = false
		if m.ready {
			m.confirmation = m.expected
			return m.call("preflight", map[string]any{"plan": m.plan})
		}
		return nil
	}
	if m.editor {
		if (m.edit.Path == "") != (m.editAction == "create") {
			m.errorText = m.tr("Une partition existante ne peut pas devenir une création.", "Existing partitions cannot become new creations.")
			return m.buildForm()
		}
		m.edit.Start, _ = bytesMiB(m.startMiB)
		m.edit.Size, _ = bytesMiB(m.sizeMiB)
		m.edit.Action = m.editAction
		m.edit.Mount = m.editMount
		m.edit.ESP = m.editESP
		if m.editFS != "original" {
			m.edit.FS = m.editFS
		}
		if m.row == len(m.opts.Partitions) {
			m.opts.Partitions = append(m.opts.Partitions, m.edit)
		} else {
			m.opts.Partitions[m.row] = m.edit
		}
		m.editor = false
		return nil
	}
	if m.step == disksStep {
		if m.manualDisk != m.opts.Disk {
			m.opts.Partitions = nil
			m.manualDisk = m.opts.Disk
		}
		if m.opts.Mode == "manual" {
			if len(m.opts.Partitions) == 0 {
				for _, d := range m.disks {
					if d.Path == m.opts.Disk {
						m.opts.Partitions = append([]partition(nil), d.Partitions...)
					}
				}
			}
			m.manual = true
			m.row = 0
			return nil
		}
	}
	if m.step == account {
		m.opts.RootEnabled = m.opts.Username == "root" || m.rootPassword != ""
		if m.opts.Username == "root" {
			m.rootPassword, m.rootRepeat = "", ""
		}
	}
	if m.step == packagesStep && m.opts.ExtraPackages == nil {
		m.opts.ExtraPackages = []string{}
	}
	if m.step == system {
		m.opts.SwapGiB, _ = strconv.Atoi(m.swapSize)
	}
	if m.step == system && m.opts.LUKS && (m.luksPassword == "" || m.luksRepeat != m.luksPassword) {
		m.form = huh.NewForm(huh.NewGroup(huh.NewInput().Title(m.tr("Phrase secrète LUKS2", "LUKS2 passphrase")).EchoMode(huh.EchoModePassword).Value(&m.luksPassword).Validate(validPassword)), huh.NewGroup(huh.NewInput().Title(m.tr("Confirmer LUKS2", "Confirm LUKS2")).EchoMode(huh.EchoModePassword).Value(&m.luksRepeat).Validate(func(s string) error {
			if s != m.luksPassword {
				return errors.New("Passphrases do not match")
			}
			return nil
		}))).WithTheme(huh.ThemeFunc(theme)).WithWidth(m.contentWidth()).WithHeight(m.bodyHeight()).WithShowHelp(false)
		return m.form.Init()
	}
	if !m.opts.LUKS {
		m.luksPassword, m.luksRepeat = "", ""
	}
	return m.next()
}

func (m *model) manualKey(k string) tea.Cmd {
	switch k {
	case "up", "k":
		m.row = max(0, m.row-1)
	case "down", "j":
		m.row = min(max(0, len(m.opts.Partitions)-1), m.row+1)
	case "n":
		m.row = len(m.opts.Partitions)
		m.edit = partition{Action: "create", FS: "btrfs"}
		return m.editForm()
	case "enter", "e":
		if m.row < len(m.opts.Partitions) {
			m.edit = m.opts.Partitions[m.row]
			return m.editForm()
		}
	case "d":
		if m.row < len(m.opts.Partitions) {
			if m.opts.Partitions[m.row].Path != "" {
				m.opts.Partitions[m.row].Action = "delete"
				m.opts.Partitions[m.row].Mount = ""
			} else {
				m.opts.Partitions = append(m.opts.Partitions[:m.row], m.opts.Partitions[m.row+1:]...)
				m.row = max(0, m.row-1)
			}
		}
	case "s", "f10":
		m.manual = false
		return m.enter(account)
	}
	return nil
}
func (m *model) editForm() tea.Cmd {
	m.editor = true
	m.startMiB = strconv.FormatFloat(float64(m.edit.Start)/(1<<20), 'f', -1, 64)
	m.sizeMiB = strconv.FormatFloat(float64(m.edit.Size)/(1<<20), 'f', -1, 64)
	m.editAction, m.editFS, m.editMount, m.editESP = m.edit.Action, m.edit.FS, m.edit.Mount, m.edit.ESP
	if m.editFS != "btrfs" && m.editFS != "ext4" && m.editFS != "fat32" {
		m.editFS = "original"
	}
	return m.buildForm()
}
func (m *model) manualView() string {
	lines := []string{m.tr("PARTITIONS — modifications proposées", "PARTITIONS — proposed changes"), ""}
	start := max(0, m.row-max(1, m.bodyHeight()-6)/2)
	for i := start; i < len(m.opts.Partitions) && len(lines) < m.bodyHeight()-3; i++ {
		p := m.opts.Partitions[i]
		marker := " "
		if i == m.row {
			marker = ">"
		}
		name := p.Path
		if name == "" {
			name = "new"
		}
		lines = append(lines, fmt.Sprintf("%s %s %s %.2fG %s %s", marker, name, strings.ToUpper(p.Action), float64(p.Size)/(1<<30), p.FS, p.Mount))
	}
	lines = append(lines, "", m.tr("N : créer  E : éditer  D : supprimer", "N: create  E: edit  D: delete"), m.tr("S : continuer  Échap : retour  F5 : rescanner", "S: continue  Esc: back  F5: rescan"))
	return strings.Join(lines, "\n")
}
