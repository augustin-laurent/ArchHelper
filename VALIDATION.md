# Validation — installateur Arch ISO, 2 novembre 2026

> Rapport historique. Pour les essais QEMU et les limites actuelles du 5 novembre
> 2026, voir [la qualification ISO](docs/VALIDATION_ARCHISO.md).

Éléments effectivement exécutés sur cette branche :

- **70 tests Python réussis** (moteur, plans, protections, protocole, filtrage des
  secrets, matériel, payload, lanceur, extraction et fabrication des archives).
- **8 tests Go réussis avec `-race`**, dont 60 scénarios de dimensions/langues
  couvrant les dix écrans en français/anglais, 80×24, 120×24 et 140×40.
- `go vet`, compilation Linux x86-64 sans cgo, vérifications de syntaxe Bash et
  compilation de syntaxe Python réussies.
- Parcours complet réel dans un pseudo-terminal **français 120×32**, en mode
  démonstration, jusqu’à la confirmation et aux huit phases simulées.
- Parcours complet **anglais 80×24, `TERM=linux`, LUKS activé**, également simulé.
  Le test émule HPA (CSI backtick), absent de la table de commandes de pyte 0.8.2.
- Cinq captures de chaque parcours produites par le test terminal ; aucune
  commande moteur ni aucun accès disque n’est lancé par le mode démo.

Les tests Python utilisent Python 3.14.8, archinstall 4.5 et pyparted 3.13.0 dans
un environnement de développement dédié. Les tests de géométrie et du protocole
ne formatent aucun disque. Go est épinglé à 1.27.3 pour cette compilation.

## Ce qui reste à qualifier

Le moteur Docker n’était pas accessible avec les droits de cette session et
aucun QEMU/KVM disponible n’a servi à lancer une installation. La première construction complète a réussi sur GitHub pour le commit
`962db5f` : Quickshell, OWE, le payload et les archives ont été produits
([rapport de construction](https://github.com/augustin-laurent/ArchHelper/actions/runs/41497612807)).
Les recettes des composants graphiques sont inchangées ; la reconstruction des
derniers correctifs est suivie dans le workflow de la branche.

Les scénarios de partitionnement sur fichiers loop, l’installation depuis l’ISO
officielle, le démarrage du disque, la session graphique et les GPU physiques
Intel/AMD/NVIDIA/hybrides restent à qualifier selon
[le protocole d’acceptation](docs/VALIDATION_ARCHISO.md). Le scénario VHS est
fourni mais n’a pas été exécuté ici ; les captures ont utilisé le test PTY/pyte.

Le canal public [augustin-laurent/archhelper-releases](https://github.com/augustin-laurent/archhelper-releases)
est créé et documenté. Aucune archive installable n’y est encore publiée. Le
script de publication prépare une release brouillon après construction ; le
lanceur distant ne sera utilisable qu’après publication des archives correspondantes.

Les archives spécifiques du projet ne sont pas signées indépendamment du canal
GitHub HTTPS ; leurs empreintes sont vérifiées. Les paquets officiels Arch
restent soumis à leurs signatures. Les résultats historiques Textual/ARM64 dans
`docs/validation/` ne qualifient pas cette version.
