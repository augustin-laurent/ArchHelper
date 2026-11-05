# First release — patched runtime and helper pass

This updates the v8 architecture after the decision to keep Omarchy’s patched runtime for the first release. The source baseline remains exactly `v4.5.0-rc1`, commit `03ff1eff3812933f7088484533784d2f63eaf19a`. No upstream script was executed and no system package or configuration was installed or changed.

## 1. First-release decisions

**Use the pinned Quickshell patch, with upstream Qt packages.** The inspected compatibility fix is in Quickshell’s QML loader, not in Qt’s source. Keep `OmarchyLoadPatch`, the existing `Color` API and the pinned loader patch in the first release; postpone the port to an unpatched Quickshell runtime. This avoids a simultaneous runtime migration and distribution migration.

Build and sign this package ourselves as `v8-quickshell`; do not add Omarchy’s repository. It provides the `quickshell` capability and conflicts with the upstream `quickshell`/`quickshell-git` packages because they own the same executables and QML modules. Other Qt consumers continue to use upstream Qt.

| Item | First-release selection |
|---|---|
| Upstream Quickshell source | `2b4501a282689792b62e94f3fb30d8f512324fe6` |
| Base recipe | `omarchy-pkgs` RC commit `bed2ea5a48400c02228c86dd4da9bc75487a24ee`, `pkgbuilds/quickshell/` |
| Package version | `0.3.2.r7.g2b4501a-1` |
| Loader patch | `load_qtquick_611.patch`, SHA-256 `23b65d205d825f11a1cd8501acbc6e50250d09a6ce607e2ff8b3cf5d438bd0ce` |
| Historical Qt build inputs recorded upstream | qt6-base `6.12.0-3`, qt6-declarative `6.12.0-1`, qt6-wayland `6.12.0-1`, for both architectures |
| Rebuild triggers | qt6-base, qt6-declarative, qt6-wayland; record actual complete build environment per architecture |
| Performed checks | Patch applicability against pinned source: passed without applying it. Draft PKGBUILD syntax: passed |
| Still unverified | Compilation, dependency resolution, QML loading, live session, x86-64/ARM64 runtime behavior |

The historical Qt versions above are provenance, not instructions to partially downgrade an Arch system. Rebuild and test the pinned patched runtime against the full supported Arch/ALARM transaction. The compatibility hook is a diagnostic; a successful hook alone does not prove every shell surface loads or provide an automatic rollback.

The reviewable draft is in [first-release-runtime/PKGBUILD](first-release-runtime/PKGBUILD), alongside the unchanged patch and a runtime lock file. It has not been built or published.

**Keep the internal Omarchy namespace during the first release.** Retain `omarchy-*`, plugin IDs, `/usr/share/omarchy`, package-owned `bin/` symlinks, `~/.config/omarchy` and `~/.local/state/omarchy` while adapting policy-sensitive commands. New v8 packages own these paths. This is unrelated to trusting or using the upstream repository. A renamed CLI can delegate to the existing router; wholesale renaming is deferred to a real migration.

This matters operationally: `env-bootstrap`, `omarchy-version` and `omarchy-update-available` treat a root other than `/usr/share/omarchy` as a development checkout. Setting `OMARCHY_PATH=/usr/share/v8` alone can produce `dev` version output and development Git checks. Production bootstrap must select a fixed packaged root and omit the development checkout override. Root-capable commands must select only trusted packaged code. Fresh v8 installations are in scope; co-installing the upstream Omarchy packages over the same paths is not supported.

## 2. What was inspected

The pass reads all **536 files in `bin/`**, their metadata and literal references. It also covers QML/JS, Hyprland defaults, UWSM/bash environment, user units, fixed shared assets and all **405 menu entries**, including `action`, `when`, `checked` and `disabled` fields.

| Decision | Helpers | Meaning |
|---|---:|---|
| Retain | 24 | Keep the mechanism and its behavior; packaging and runtime checks still required |
| Adapt | 298 | Adjust configuration, dependencies, owned paths, capabilities or callers |
| Replace | 53 | Replace the project-specific policy/entrypoint; reuse safe mechanisms inside it where useful |
| Feature module | 144 | Optional integration, not necessarily removable while its callers remain |
| Exclude from first public release | 17 | Development checkout tools, legacy upgrade, factory reset and vendor update guard/dev update |

This is a static coverage pass over every helper plus deeper reading of critical chains, not a line-by-line correctness or security review of all 536 programs. There are 3,145 reference records, 24 explicitly expanded dynamic-family records, and 281 fixed/prefix asset references; 218 of the asset records resolve to files, representing 172 distinct files. Conditional branches and strings can overestimate execution; runtime-generated names can still escape the analysis. None of these counts is an executable package allowlist.

The earlier count of 146 commands was only a literal scan of shell and Hyprland files. The broader conservative traversal reaches 233 helpers from shell roots, 236 from Hyprland roots, 146 from session-start roots and 380 from the full stock menu. These sets overlap and include optional branches; they must not be added together or presented as mandatory bootstrap dependencies.

Data files:

- [helpers-premiere-release.csv](helpers-premiere-release.csv): every helper, proposed owner, decision, callers, outgoing references, dependency hints and source hash.
- [helpers-premiere-release.json](helpers-premiere-release.json): equivalent structured inventory, method and limitations.
- [helpers-references.csv](helpers-references.csv): per-source reference evidence with line numbers; synthetic menu nodes use line offsets within their field string.
- [helpers-menu-actions.csv](helpers-menu-actions.csv): each menu field and its helper dependencies.
- [helpers-assets.csv](helpers-assets.csv): shared scripts/templates/config references, with unresolved prefixes identified.
- [helpers-dispatch-dynamique.csv](helpers-dispatch-dynamique.csv): explicitly reviewed dynamic helper families.
- [helpers-points-a-rebrancher.csv](helpers-points-a-rebrancher.csv): 347 references toward a replacement/exclusion candidate; each requires caller review, not an assumption that it runs.
- [helpers-preuves.json](helpers-preuves.json): 26 targeted source excerpts supporting the critical findings below.

## 3. Essential helper chains

| Area | Helpers to carry forward | Additional files and dependencies | Required first-release work |
|---|---|---|---|
| Environment and dispatch | `omarchy`, `omarchy-cmd-{present,missing}`, `omarchy-i18n` | `default/bash/env-bootstrap`, UWSM env/default, i18n catalogs, fonts, `/usr/bin` and package-owned helper symlinks | Fixed production root; preserve longest-prefix routing, metadata aliases, status codes and stdin/stdout contracts |
| Shell lifecycle and IPC | `omarchy-launch-shell`, `omarchy-shell`, `omarchy-restart-shell` | Patched Quickshell/qs, socat, timeout, systemd journal, Hyprland session environment | Preserve timeouts, display/socket selection, bounded relaunch and refusal to restart a live locker |
| Menu/bar/dock | `omarchy-menu`, `omarchy-menu-{select,input,images,plugin}`, `omarchy-bar`, `omarchy-dock` | Menu JSONC, `Menu.qml`, `MenuModel.js`, manifests, image/tempfile handshakes | Port actions and guards together; cancel is not success; keep provider refresh and selection protocols |
| Launching and settings editors | `omarchy-launch-{terminal,tui,editor,config-editor,browser,webapp}`, `omarchy-launch-floating-terminal-with-presentation`, `omarchy-cmd-terminal-cwd` | UWSM, xdg-terminal-exec, xdg-utils, a real terminal/browser/editor; `omarchy-restart-gum`, `omarchy-show-{logo,done}` | Preserve argument boundaries and detached session launch; seed defaults that are actually installed |
| Lock and suspend | `omarchy-system-{lock,sleep-lock,sleep-monitor,wake}`, `omarchy-hyprland-session-locked`, relevant lid/monitor helpers | PAM services, lock QML, polkit backend, dbus-monitor, systemd-inhibit, logind drop-in, user sleep-lock unit | Install password PAM before advertising lock; preserve secure-lock acknowledgement and the inhibitor deadline |
| Notifications and OSD | `omarchy-notification-{send,dismiss,wait,time,battery,weather}`, `omarchy-osd` | Shell notification service, i18n, clock/battery/weather services | Startup wait, timeout and action semantics; notify on real failures without making optional services mandatory |
| Theme initialization and switching | `omarchy-theme-{set,dir,color,osc,set-templates,bg-set,bg-switcher,bg-cache}`, `omarchy-theme-set-*`, relevant restart helpers | `themes/`, `default/themed/`, current theme/background state, GTK/font defaults and OWE | Seed valid state on install; retain staging/locks/trust checks; keep or gate every retint helper called by the arrays |
| Windows/workspaces/monitors | `omarchy-hyprland-*`, `omarchy-hw-{display,laptop,external-monitors,recover-internal-monitor}`, monitor watch | Lua defaults, user overrides, Hyprland socket, recovery unit, layout/toggle state | Preserve reload coordination and hotplug/clamshell behavior; native titlebars remain an independent optional dependency |
| Audio/network/power/input | `omarchy-audio-*`, brightness helpers, `omarchy-network-*`, power-profile helpers, `omarchy-input-method`, setup keyboard/input | PipeWire/WirePlumber, NetworkManager/resolved, BlueZ, brightness/DDC tools, fcitx5 and user units when selected | Capability-aware controls; preserve selected backend and user configuration; no unrelated root system setup at login |
| Capture/clipboard | `omarchy-capture-*`, `omarchy-clipboard-*`, relevant menu helpers | `shell/plugins/clipboard/capture.sh`, wl-clipboard, region picker, screenshot/OCR/recording backends | Choose actual capture tools per profile; helper names alone do not install Omasnap or Monologue |
| User state/hooks | `omarchy-done`, `omarchy-state`, `omarchy-hook`, `omarchy-hook-install`, toggle probes | State directories and hook files with their intended ownership | Preserve path/name checks and completion semantics; execute user hooks only as the user |
| Diagnostics | local debug/stats helpers | journal, inxi or other explicitly selected tools | Keep useful local diagnostics; do not send logs to upstream services automatically |

First-release assembly defaults can remain close to the RC: Foot, Chromium and **official Neovim**, without `omarchy-nvim`/LazyVim. `omarchy-launch-editor` currently falls back to `nvim`; shipping no editor would break configuration editing unless that fallback is changed. These are dependencies of the assembled desktop/profile, not of the Quickshell runtime itself.

## 4. Findings that require concrete changes

### H1 — The shared terminal wrapper is part of the core

`omarchy-launch-floating-terminal-with-presentation` has 165 distinct source callers in this conservative graph. It sources `omarchy-restart-gum` and invokes `omarchy-show-logo` and `omarchy-show-done` inside the terminal. Removing the sourceable helper because it looks like a cosmetic restart command breaks this path. Keep the wrapper chain and its assets; test command success, error, Ctrl-C, no TTY, and paths containing spaces. [Source](https://github.com/omacom/omarchy/blob/03ff1eff3812933f7088484533784d2f63eaf19a/bin/omarchy-launch-floating-terminal-with-presentation).

### H2 — PAM, not just a lock command, is required

The QML lock service uses `omarchy-lock-password` and optionally `omarchy-lock-fingerprint`. `omarchy-apply-lock` currently creates the PAM files and installs fingerprint recovery pieces. Extract/adapt that setup into the project’s owned authentication integration. Do not defer it to a first-run routine that may fail or be omitted. Preserve the suspend monitor and its bounded secure-lock check; its failure report does not itself stop logind from eventually suspending. [PAM publisher](https://github.com/omacom/omarchy/blob/03ff1eff3812933f7088484533784d2f63eaf19a/bin/omarchy-apply-lock), [sleep-lock contract](https://github.com/omacom/omarchy/blob/03ff1eff3812933f7088484533784d2f63eaf19a/bin/omarchy-system-sleep-lock).

### H3 — OWE is not yet optional in the unchanged startup path

`instaldopsx xl/user/first-run/enable-user-units.sh` unconditionally enables `owed.service` and installs `/usr/share/owe/10-owe-sync`; failure makes that first-run step fail and keeps the first-run completion marker unset. For a low-delta first release, **include OWE and owe-lockfeed in the default desktop assembly**. They remain separate packages, but removing them from this assembly is only supported after those unit/hook/theme call sites have been made conditional and tested. This preserves the RC behavior while the core fork is brought up. [Source](https://github.com/omacom/omarchy/blob/03ff1eff3812933f7088484533784d2f63eaf19a/install/user/first-run/enable-user-units.sh).

### H4 — Theme switching includes unconditional adapter calls

`visible_theme_commands` and `other_theme_commands` name terminal, GTK, editor, agent and keyboard retint helpers. Keep the lightweight adapters even if the corresponding apps are absent, or explicitly filter the call list. Absence of an optional app should return a successful “nothing to do”; a real failure should remain visible. Do not install all agent/editor applications merely to satisfy these adapter names. [Source](https://github.com/omacom/omarchy/blob/03ff1eff3812933f7088484533784d2f63eaf19a/bin/omarchy-theme-set#L529).

### H5 — Runtime libraries live under `install/`

`omarchy-theme-set-browser` sources `install/helpers/browser-policy.sh`. Other paths use `install/helpers/pacman.sh`, rekey/setup libraries and user setup leaves. Excluding the entire `install/` directory from runtime packaging would break shared helpers. Carry only the required passive library/assets with a named owner; replace boot/provisioning entrypoints before dropping their libraries. Keep the browser policy writer’s fixed root-owned path and root/user separation if it remains enabled. [Source](https://github.com/omacom/omarchy/blob/03ff1eff3812933f7088484533784d2f63eaf19a/bin/omarchy-theme-set-browser#L6).

### H6 — Package probes differ from menu probes

Standalone `omarchy-pkg-present`/`missing` use exact-name `pacman -Q`, while the generated menu guard snapshot resolves package `provides`. With a package named `v8-quickshell` providing `quickshell`, an exact-name probe can disagree with dependency resolution and the menu. Adapt the shared probes and install post-checks to one provides-aware contract; preserve zero/one meaning and test real errors separately from absence. Do not assume naming the capability in `provides` makes `pacman -Q quickshell` work. [Standalone probe](https://github.com/omacom/omarchy/blob/03ff1eff3812933f7088484533784d2f63eaf19a/bin/omarchy-pkg-present), [menu guard code](https://github.com/omacom/omarchy/blob/03ff1eff3812933f7088484533784d2f63eaf19a/shell/plugins/menu/MenuModel.js).

### H7 — Stock version/update indicators would report the wrong product

`omarchy-version` queries `omarchy-dev`/`omarchy`; `omarchy-update-available` looks for those packages too. Replace their metadata selection for v8. Channel readers in `GUARD_READERS` and checked menu fields must change together with the update command. Keep reusable locking, free-space, cache-pruning and inhibition mechanisms; replacing product policy does not require rewriting those mechanisms. [Version](https://github.com/omacom/omarchy/blob/03ff1eff3812933f7088484533784d2f63eaf19a/bin/omarchy-version), [indicator](https://github.com/omacom/omarchy/blob/03ff1eff3812933f7088484533784d2f63eaf19a/bin/omarchy-update-available).

### H8 — First-run/provisioning must be reduced, not replayed wholesale

The stock first-run invokes user finalization, installs agent/fingerprint hooks, enables units and schedules update notices. User finalization also provisions developer/agent defaults and runs `install/user/all.sh`. Extract the actual prerequisites: directories, valid theme/current state, XDG defaults, session units and a clear welcome/recovery result. Do not import the whole system installer or mark every historical migration complete as a substitute for v8 schema initialization. [First-run](https://github.com/omacom/omarchy/blob/03ff1eff3812933f7088484533784d2f63eaf19a/bin/omarchy-provision-first-run), [user finalization](https://github.com/omacom/omarchy/blob/03ff1eff3812933f7088484533784d2f63eaf19a/bin/omarchy-provision-user).

### H9 — The RC login-keyring policy assumes a different login flow

`install/login/sddm.sh` removes GNOME keyring PAM lines; the user default-keyring script seeds a default keyring configuration. Our first release keeps graphical authentication independent from LUKS/TPM unlock. Adapt keyring integration to that selected login flow rather than replaying the edits automatically. Test login, network secrets and secret-portal access under both encrypted and unencrypted installation modes. [SDDM setup](https://github.com/omacom/omarchy/blob/03ff1eff3812933f7088484533784d2f63eaf19a/install/login/sddm.sh), [keyring defaults](https://github.com/omacom/omarchy/blob/03ff1eff3812933f7088484533784d2f63eaf19a/install/user/default-keyring.sh).

### H10 — Reset/boot/AUR actions need their own replacements

Replace `omarchy-refresh-limine`, `omarchy-snapshot`, drive-password/rekey and Plymouth-writing paths with the selected backend contracts. Retain useful selectors/probes where possible. Replace yay add/update flows with interactive paru review. Explicit refresh must validate its relative path and retain backups; whole-home `cp -af /etc/skel/. ~/` is not a versioned migration. Remove vendor raw-pacman guard hooks together with their command. Unsupported actions must be absent/disabled with a clear reason, never fake success. [Limine refresh](https://github.com/omacom/omarchy/blob/03ff1eff3812933f7088484533784d2f63eaf19a/bin/omarchy-refresh-limine), [config refresh](https://github.com/omacom/omarchy/blob/03ff1eff3812933f7088484533784d2f63eaf19a/bin/omarchy-refresh-config), [AUR helper](https://github.com/omacom/omarchy/blob/03ff1eff3812933f7088484533784d2f63eaf19a/bin/omarchy-pkg-aur-add).

## 5. Dynamic dispatch and menu completeness

Keep these families together or adapt the dispatch before splitting them:

| Dispatcher | Dynamically selected helpers |
|---|---|
| `omarchy` | Metadata routes and aliases; enumerate installed commands without depending on every development helper |
| `omarchy-bar` | `omarchy-installed-service-{dropbox,tailscale}` |
| `omarchy-menu-plugin` | `omarchy-plugin-*` operations selected by argument |
| `omarchy-agent-usage-update` | `omarchy-agent-usage-*` collectors |
| `omarchy-default-dictation`, `omarchy-dictation`, `omarchy-dictation-use` | Installation and control adapters for selected dictation backend |
| `omarchy-toggle-input-device` | `omarchy-hw-touchpad` / `omarchy-hw-touchscreen` |
| `Menu.qml` providers | Font, power-profile and language enumeration plus constructed selection actions |

The 592 menu fields include **191 fields referencing at least one replacement, excluded or feature-module helper**. This means they need a routing/gating decision, not that 191 menu items are bugs. An action may be correct while its `checked` reader still invokes a removed vendor channel. `GUARD_READERS` caches those readers separately and must stay aligned. Guards are shell code too, and their package-probe fast paths can differ from the standalone executables.

The `module` classification is a feature boundary, not permission to delete a script. For example, the core theme dispatcher may still need an app’s retint adapter while the app itself is optional. Required adapters belong in the base helper package or get an explicit capability check. Package build validation must fail on an ungated known missing helper; a compatibility stub that always exits zero is not a replacement for an implemented system action.

## 6. Packaging without a package per helper family

| Package | Responsibility |
|---|---|
| `v8-quickshell` | Patched native runtime; conflicts with other Quickshell runtime packages |
| `v8-desktop-cli` | Base user helpers, theme/launch/menu/settings mechanisms, safe probes and required compatibility adapters |
| `v8-defaults` / `v8-themes` | Passive shared scripts, template/config/font data and theme inputs; do not depend on the CLI they supply data to |
| `v8-system-tools` | Project version/update/package-policy entrypoints, delegating migration/AUR/boot work to their owners |
| `v8-migrations`, `v8-aur-policy`, `v8-snapshots`, `v8-boot-core` | Existing separate responsibilities from the specification; desktop invokes capabilities, does not hard-depend on a bootloader |
| `v8-shell-extras` initially | Optional agent/app/dictation helpers; split further only if actual dependencies or independent releases justify it |
| Installer/platform packages | Root-side apply/provision/hardware operations; not replayed by the desktop user at login |

The inventory’s `component` column is a logical responsibility; it does not require an extra Arch package for each label. `target_package` proposes the coarser packaging above. Ownership must be adjusted at extraction time so shared files have exactly one owner and no dependency cycle.

Minimum generic external programs to check include bash, coreutils, util-linux, procps-ng, psmisc, findutils, gawk, grep, sed, jq, socat, gum, systemd, D-Bus, GLib/XDG tools, UWSM, Hyprland and the selected terminal/editor/browser. Per-helper `package_hints` are text-based hints, not a resolved package dependency graph: words can occur in strings or optional branches. Native Qt modules, PAM service files and D-Bus services need separate checks; `command -v` cannot establish that they work.

## 7. Implementation order and release gates

1. **Runtime/data foundation:** build the draft patched runtime in disposable x86-64 and ARM64 environments; stage fixed roots, symlinks, fonts and QML imports. Validate all shell surfaces against the exact resulting Qt/runtime package set.
2. **Bootstrap and authentication:** extract first-run, seed theme state and defaults, install password PAM and user units. Validate first login and second login without loops, sudo prompts or developer setup side effects.
3. **Base desktop:** bring up launch/menu/bar/dock/notifications/workspaces/audio/network/input and theme switching. Retain adapters or gate their callers. Verify missing optional apps do not break core actions.
4. **Policy-sensitive actions:** connect project version/update, paru, migrations, snapshots, Plymouth and selected boot backend. Remove vendor/dev/factory-reset actions and their guard readers/hooks together.
5. **Integration closure:** test the default feature profile and the explicitly supported optional profiles. Scan the staged package tree for missing referenced binaries/assets, then exercise dynamic dispatch and session behavior in VMs.

Focused upstream test sources to adapt include `shell-launch-test.sh`, `sleep-lock-test.sh`, `notifications-test.sh`, `menu-guards-test.sh`, `menu-guards-parallel-test.sh`, `theme-set-retint-order-test.sh`, `refresh-config-test.sh`, `input-method-test.sh`, `systemd-test.sh` and `owe-lock-test.sh`. These have **not** been run here. Add fixtures for `v8-quickshell` providing `quickshell`, no optional editor/agent packages, canceled actions and a fresh account with no existing state.

Release acceptance must cover: no missing-helper error on retained routes; correct cancellation/error status; lock-before-suspend and restart-while-locked; no mandatory Limine/yay/vendor repository; no root execution of user configuration; no automatic SSH activation; theme switching with absent optional apps; no unresolved `.service`, PAM or QML import dependency. An update must verify the runtime after Qt changes rather than relying on the source patch applying.

The helper pass and draft recipe make the work concrete and traceable. They do not yet produce a working first-release ISO: helper porting, native builds and session/VM validation remain to be implemented.
