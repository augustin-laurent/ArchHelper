# ArchHelper 0.2.0-preview1

Nouvel installateur plein écran depuis l’ISO Arch officielle : Bubble Tea, Huh,
Lip Gloss, thème Tokyo Night et moteur archinstall 4.5.

- Installation complète Arch + Hyprland/Quickshell/OmaControl.
- Effacement, espace non alloué et éditeur manuel ; LUKS2 facultatif.
- Détection Intel/AMD/VM et NVIDIA Turing ou ultérieur via table PCI épinglée.
- Transaction de paquets préparée avant le formatage ; compatibilité Qt vérifiée.
- Journaux privés, export des rapports et mode `--demo` sans accès aux disques.

Préversion à qualifier avec le protocole `docs/VALIDATION_ARCHISO.md` avant
publication. Une compilation ou un test simulé ne démontre pas un démarrage
réussi ni la compatibilité d’un GPU physique.

Prérequis : ISO Arch x86-64 UEFI, Python 3.14, archinstall 4.5, Secure Boot
désactivé et Internet. Aucun support BIOS, ARM, NVIDIA antérieur à Turing ou AUR.

Les paquets officiels Arch conservent leurs signatures. Les paquets spécifiques
ArchHelper sont vérifiés par les SHA-256 de cette release ; ils ne disposent pas
encore d’une signature indépendante du canal GitHub HTTPS.
