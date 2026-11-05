package main

import (
	"bufio"
	"encoding/xml"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"

	"charm.land/huh/v2"
)

// Read the same system catalogs the installation backend validates.
func catalogChoices(path string, locale bool) []huh.Option[string] {
	values := map[string]bool{}
	if locale {
		values["fr_FR.UTF-8"], values["en_US.UTF-8"] = true, true
	} else {
		values["UTC"] = true
	}
	if f, err := os.Open(path); err == nil {
		defer f.Close()
		s := bufio.NewScanner(f)
		for s.Scan() {
			line := s.Text()
			if strings.HasPrefix(line, "#") {
				continue
			}
			fields := strings.Fields(line)
			if locale && len(fields) == 2 && fields[1] == "UTF-8" {
				values[fields[0]] = true
			} else if !locale && len(fields) >= 3 {
				values[fields[2]] = true
			}
		}
	}
	names := make([]string, 0, len(values))
	for name := range values {
		names = append(names, name)
	}
	sort.Strings(names)
	result := make([]huh.Option[string], 0, len(names))
	if locale {
		// Keep the defaults visible without scrolling through hundreds of locales.
		result = append(result,
			huh.NewOption("Français (France) — fr_FR.UTF-8", "fr_FR.UTF-8"),
			huh.NewOption("English (United States) — en_US.UTF-8", "en_US.UTF-8"))
	}
	for _, name := range names {
		if locale && (name == "fr_FR.UTF-8" || name == "en_US.UTF-8") {
			continue
		}
		result = append(result, huh.NewOption(name, name))
	}
	return result
}

// Include installed TZif zones and aliases, including Etc/* and regional
// aliases absent from zone.tab. Match the backend's path and containment rules.
func timezoneChoices(root string) []huh.Option[string] {
	values := map[string]bool{}
	root, err := filepath.EvalSymlinks(root)
	if err != nil {
		return nil
	}
	validName := regexp.MustCompile(`^[A-Za-z0-9_+.-]+(?:/[A-Za-z0-9_+.-]+)*$`)
	_ = filepath.WalkDir(root, func(path string, d fs.DirEntry, walkErr error) error {
		if walkErr != nil || d.IsDir() {
			return nil
		}
		name, err := filepath.Rel(root, path)
		if err != nil || !validName.MatchString(name) {
			return nil
		}
		resolved, err := filepath.EvalSymlinks(path)
		if err != nil {
			return nil
		}
		inside, err := filepath.Rel(root, resolved)
		if err != nil || inside == ".." || strings.HasPrefix(inside, ".."+string(filepath.Separator)) {
			return nil
		}
		f, err := os.Open(resolved)
		if err != nil {
			return nil
		}
		var magic [4]byte
		n, _ := f.Read(magic[:])
		f.Close()
		if n == len(magic) && string(magic[:]) == "TZif" {
			values[name] = true
		}
		return nil
	})
	names := make([]string, 0, len(values))
	for name := range values {
		names = append(names, name)
	}
	sort.Strings(names)
	result := make([]huh.Option[string], 0, len(names))
	for _, name := range names {
		result = append(result, huh.NewOption(name, name))
	}
	return result
}

func keyboardChoices() []huh.Option[string] {
	values := map[string]bool{"fr": true, "us": true}
	_ = filepath.WalkDir("/usr/share/kbd/keymaps", func(path string, d fs.DirEntry, err error) error {
		if err == nil && d.IsDir() && d.Name() == "include" {
			return filepath.SkipDir
		}
		if err == nil && !d.IsDir() && strings.Contains(d.Name(), ".map") {
			values[strings.SplitN(d.Name(), ".map", 2)[0]] = true
		}
		return nil
	})
	names := make([]string, 0, len(values))
	for name := range values {
		names = append(names, name)
	}
	sort.Strings(names)
	result := make([]huh.Option[string], 0, len(names))
	for _, name := range names {
		result = append(result, huh.NewOption(name, name))
	}
	return result
}

func graphicalKeyboardChoices(engine string) []huh.Option[string] {
	type config struct {
		Name        string `xml:"name"`
		Description string `xml:"description"`
	}
	var registry struct {
		Layouts []struct {
			Config   config `xml:"configItem"`
			Variants []struct {
				Config config `xml:"configItem"`
			} `xml:"variantList>variant"`
		} `xml:"layoutList>layout"`
	}
	var data []byte
	var err error
	for _, path := range []string{filepath.Join(filepath.Dir(engine), "v8_installer/xkb-evdev.xml"), "/usr/share/xkeyboard-config-2/rules/evdev.xml", "/usr/share/X11/xkb/rules/evdev.xml"} {
		data, err = os.ReadFile(path)
		if err == nil {
			break
		}
	}
	if err != nil || xml.Unmarshal(data, &registry) != nil {
		return []huh.Option[string]{huh.NewOption("fr", "fr"), huh.NewOption("us", "us")}
	}
	var result []huh.Option[string]
	for _, layout := range registry.Layouts {
		result = append(result, huh.NewOption(layout.Config.Description+" ("+layout.Config.Name+")", layout.Config.Name))
		for _, variant := range layout.Variants {
			value := layout.Config.Name + ":" + variant.Config.Name
			result = append(result, huh.NewOption(layout.Config.Description+" — "+variant.Config.Description+" ("+value+")", value))
		}
	}
	return result
}
