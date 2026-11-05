# Choix des outils

Le parcours retenu est une application terminal plein écran, lancée par un
petit script depuis l’ISO officielle. Le moteur disque reste archinstall.

| Outil | Usage pertinent | Choix pour ArchHelper |
|---|---|---|
| [Bubble Tea](https://github.com/charmbracelet/bubbletea) | Application terminal à états, événements et opérations asynchrones | Interface principale en Go |
| [Bubbles](https://github.com/charmbracelet/bubbles) | Défilement, indicateurs d’activité et composants | Journal et progression |
| [Huh](https://github.com/charmbracelet/huh) | Formulaires intégrés à Bubble Tea | Champs, sélections, validations et mots de passe |
| [Lip Gloss](https://github.com/charmbracelet/lipgloss) | Mise en page et styles du terminal | Tokyo Night et adaptation de la console |
| [Gum](https://github.com/charmbracelet/gum) | Choix et prompts composables dans un script | Excellent pour un assistant séquentiel ; pas nécessaire au nouveau lanceur |
| [Textual](https://github.com/Textualize/textual) | Application terminal Python et styles TCSS | Ancienne interface remplacée ; dépendance transitive d’archinstall |
| [prompt_toolkit](https://github.com/prompt-toolkit/python-prompt-toolkit) | Saisie et applications interactives Python | Alternative possible, non ajoutée |
| [Dialog / Whiptail](https://invisible-island.net/dialog/) | Boîtes de dialogue curses classiques | Compatibilité intéressante, pas de seconde interface à maintenir |
| [fzf](https://github.com/junegunn/fzf) | Recherche approximative et sélection de listes | Redondant avec les champs intégrés |
| [Calamares](https://github.com/calamares/calamares) | Installateur graphique pour distributions | Nécessite un environnement graphique, hors du parcours ISO officiel |
| [archinstall](https://github.com/archlinux/archinstall) | Partitionnement, installation de base et configuration | Moteur unique, adaptateur 4.5 conservé |
| [iwctl](https://man.archlinux.org/man/iwctl.1.en) | Connexion Wi-Fi du live | Ouverture interactive sans secret dans les arguments |
| [Reflector](https://man.archlinux.org/man/reflector.1.en) | Sélection des miroirs Arch | Outil facultatif avant lancement ; la liste du live est conservée |
| [VHS](https://github.com/charmbracelet/vhs) | Captures et démonstrations terminal reproductibles | Scénario de démonstration fourni, dépendance de développement |

Le programme Go ne crée pas de partitions. Le protocole local transmet les
intentions au moteur Python, qui produit le plan, son empreinte et le résumé.
Les couleurs riches sont facultatives : la console Linux utilise une palette
16 couleurs et le parcours n’exige aucune icône de police spéciale.
