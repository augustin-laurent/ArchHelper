# Qualification depuis l’ISO Arch officielle

## Ce qui constitue une validation

Les tests unitaires, les captures de l’interface et une compilation ne prouvent
pas qu’un système installé démarre. Consigner séparément les résultats suivants :

| Niveau | Vérification | État avant essais matériels |
|---|---|---|
| Unitaire | Plans, protections disque, protocole, secrets, détection PCI, paquets | Exécutable sans disque utilisateur |
| Interface | Français/anglais, 80×24 et grands terminaux, navigation, redimensionnement | Mode démo uniquement |
| Construction | Compilation du lanceur autonome et de son moteur dans Arch | À exécuter sur le constructeur |
| Disque | Effacement, espace libre, manuel, ESP partagée et LUKS2 | Effacement et LUKS2 testés en VM ; autres modes à qualifier |
| Démarrage | Installation depuis ISO, retrait ISO, démarrage du disque, SDDM et bureau | À qualifier en QEMU/UEFI |
| Matériel | Intel, AMD, NVIDIA moderne, hybride et réseau | À qualifier sur machines dédiées |

## Préparer une VM

Prendre une ISO officielle vérifiée, UEFI sans Secure Boot, 4 CPU, 8 Gio de RAM,
un disque virtuel **neuf** d’au moins 40 Gio et une carte graphique virtio.
Ne transmettre aucun disque physique. Utiliser un affichage accéléré si l’hôte
le permet. Le lanceur réclame Python 3.14 et archinstall 4.5 ; une autre version
doit échouer avant toute écriture disque, jusqu’à sa requalification.

Transférer le `install.sh` autonome construit dans la VM, démarrer le live,
connecter le réseau puis lancer `bash install.sh`. Aucune publication n’est
nécessaire. Le mode `--demo` n’est pas un test d’installation.

## Tests de partitions exclusivement sur fichiers créés par les tests

Depuis une VM live jetable contenant les sources et la release complète :

```sh
export PYTHONPATH=/chemin/archhelper/engine
python /chemin/sources/installer/tests/disks_in_builder.py
ARCHHELPER_BUNDLE=/chemin/archhelper python /chemin/sources/installer/tests/install_in_builder.py
```

Ces programmes n’acceptent pas de périphérique cible : ils créent leurs propres
fichiers et périphériques loop. Recommencer avec `V8_TEST_LUKS=1` dans une nouvelle
VM/session. Le journal seul ne permet jamais de reprendre un formatage.

## Scénarios d’acceptation

1. Installer en effacement, UKI actif ; retirer l’ISO et démarrer sur le disque.
2. Vérifier SDDM, la connexion utilisateur et le bureau choisi.
   Ouvrir terminal, menu, navigateur, fichiers et verrouillage.
3. Refaire avec LUKS2, puis avec UKI désactivé ; vérifier le déverrouillage et le
   démarrage après une mise à jour du noyau.
4. Tester espace libre, manuel et ESP conservée. Comparer les empreintes des
   partitions conservées et d’un disque voisin ; vérifier les fichiers Microsoft.
5. Changer un montage ou la géométrie après le résumé : le plan doit être refusé.
6. Couper le réseau pendant la préparation : aucun formatage ne doit commencer.
   Après préparation, la transaction doit utiliser exclusivement les archives locales.
7. Tester un lanceur modifié, une signature de paquet absente et une version
   archinstall incompatible : refus avant formatage.
8. Sur NVIDIA compatible, vérifier DKMS, les modules dans l’initramfs, le KMS,
   `nvidia-smi`, la session Wayland et une mise à jour NVIDIA sans mise à jour noyau.
   Sur hybride, vérifier le GPU intégré par défaut et `prime-run <application>`.
9. Vérifier les choix NVIDIA open, 580xx et Nouveau selon leurs listes de prise
   en charge, et l’absence de réglages de rendu VM sur PC physique. Tester Ethernet
   et la reconnexion Wi-Fi après redémarrage.
10. Exporter le rapport sur un support persistant. Rechercher les mots de passe
    choisis dans l’export : aucune occurrence ne doit être présente.

Enregistrer ISO et empreinte, versions de paquets, modèle de machine/GPU,
options choisies, résultat et rapports. Un échec matériel garde la release en
préversion ; ne pas remplacer « non testé » par « compatible ».

## Essais partiels du 5 novembre 2026

ISO `archlinux-2026.11.01-x86_64.iso`, SHA-256
`01bcdcf01af2f7d58f2794899c834770d25c9bfc945bd092b32bb66672a4a216`,
vérifiée contre le site Arch. QEMU x86-64 en émulation TCG, firmware UEFI,
4 CPU, 4 Gio de RAM et disque qcow2 jetable de 48 Gio ; aucun disque physique
transmis. Live : Python 3.14.9 et archinstall 4.5, sans réseau.

- Les actions réelles `checks` et `discover` réussissent : le disque virtuel est
  proposé et le support de transfert en lecture seule est protégé.
- Le moteur partitionne, formate et monte la racine Btrfs et ses sous-volumes,
  puis effectue le même essai avec LUKS2. Les montages sont ensuite démontés et
  le mapping chiffré fermé.
- Un swap Btrfs de 1 Gio est créé et activé dans la racine chiffrée, puis sous
  `/home`. Un autre essai crée et active un swap de 1 Gio sur `/home` ext4 séparé.
  Les commandes de création sont exécutées depuis le live avec les chemins de
  la cible traduits, puisque ces cibles ne contiennent pas encore les paquets.
- Dans une cible de test utilisant `/usr` du live, création d’un utilisateur sudo
  et activation de root, puis exercice de la branche de configuration root seul
  sur cette même cible, où l’utilisateur créé existait encore ; locale
  `sr_RS.UTF-8@latin`. Le pare-feu et l’activation de son service ont été simulés,
  car le paquet UFW n’était pas installé dans cette cible de test.
- Les paquets et le système complet n’ont pas été installés dans cette VM : les
  dépôts distants n’étaient pas accessibles. Le redémarrage sur disque, SDDM,
  CachyOS et les GPU physiques restent donc à qualifier.

## Installation connectée du 5 novembre 2026

Avec la même ISO, QEMU TCG/UEFI, 8 Gio de RAM et un disque virtuel jetable
de 48 Gio, une installation Hyprland sans CachyOS a terminé toutes les phases
du moteur et démarré sur le disque. Options : Btrfs, UKI, clavier et locale
français, NetworkManager, Bluetooth, Snapper, ZRAM et swap de 1 Gio, paquet
supplémentaire `htop`. Après démarrage, `swapon --show` indique le fichier de
swap de 1024 Mio et `/dev/zram0` actifs ; la connexion en console fonctionne
avec la disposition française.

Le premier démarrage affichait encore `us` dans SDDM malgré la configuration
Xorg française. Ajouter `setxkbmap fr` au script de démarrage X11 de SDDM,
puis relancer SDDM, a fait apparaître `fr` ; le mot de passe saisi en AZERTY
a ouvert Hyprland. L’installateur produit désormais son propre script de
démarrage SDDM et inclut `xorg-setxkbmap`. Ce correctif a été reproduit
manuellement dans la VM. Le script désormais généré par l’installateur a ensuite
été installé dans cette même VM, en retirant la modification manuelle. Après
trois redémarrages, la configuration X11 de SDDM indiquait respectivement `fr`,
`us`, puis `fr` avec la variante `bepo` ; la saisie du mot de passe selon chaque
disposition a ouvert la session Hyprland. La console utilisait respectivement
`fr`, `us`, puis `fr` (disposition de console choisie séparément). Ces essais
ont remplacé les fichiers clavier sur une installation existante ; ils ne
constituent pas trois installations complètes. La configuration utilisateur
Hyprland a aussi été adaptée à `kb_variant = "bepo"`, comme celle générée pour
une nouvelle installation : après un autre redémarrage et une connexion Bépo,
la saisie en session fonctionne et `hyprctl getoption input:kb_variant` renvoie
`bepo`. La configuration utilisateur a été adaptée manuellement pour cet essai.
Le même procédé a été répété avec `kb_layout = "us"` et une variante vide :
après redémarrage, `hyprctl getoption input:kb_layout` renvoie `us` et la
saisie QWERTY fonctionne dans le terminal. Pour cet essai de session, SDDM
était encore configuré en Bépo : les deux couches ont été vérifiées séparément.

Sur une copie jetable de la VM Btrfs, Timeshift a été installé puis configuré
par le même code que l’installateur. Son minuteur était actif ; la création et
la liste d’un instantané Btrfs ont réussi. Le lancement manuel du service de
contrôle planifié s’est terminé avec succès et a affecté l’étiquette quotidienne
à cet instantané ; le minuteur a redémarré avec le système. Cet essai a été
effectué sur un système existant, pas par une
nouvelle installation complète avec Timeshift sélectionné.

Une seconde VM UEFI jetable a installé le noyau `linux-cachyos`, avec le dépôt
CachyOS, un compte utilisateur et un mot de passe root, systemd-networkd,
sans Bluetooth, instantanés ni swap. Le premier essai a révélé que le miroir
refusait l’agent réseau Python par défaut ; un agent explicite a corrigé le
téléchargement, sans modifier la vérification de signature. L’installation
complète a ensuite réussi et démarré sur `7.3.1-1-cachyos` ; la connexion root
en console et l’état actif de systemd-networkd ont été vérifiés. Les GPU
physiques et les pilotes NVIDIA restent à qualifier sur matériel compatible.
La liste de validation du pilote propriétaire 580 provient désormais de la
liste NVIDIA 580.196.07 : elle couvre notamment la RTX 3090 et tient compte des
identifiants de sous-système lorsque NVIDIA restreint une entrée à un modèle
précis. Elle ne constitue pas une validation de fonctionnement sur GPU réel.
Le 5 novembre 2026, la résolution du paquet `linux-cachyos-headers` échouait
car sa dépendance `pahole>=1:1.32-2` n’était pas disponible dans les dépôts
activés. Cette incompatibilité doit donc être signalée avant la confirmation
lorsqu’un pilote DKMS nécessite ces en-têtes ; elle dépend de l’état des dépôts.
La résolution et l’installation des paquets NVIDIA 580 avec les en-têtes LTS ont
ensuite démarré dans la VM ; la compilation DKMS a été interrompue à la demande
de l’utilisateur et son résultat n’a pas été vérifié.

Le parcours de démonstration a également été rejoué dans des pseudo-terminaux
de 80 × 24 et 120 × 32 caractères, en français et en anglais, avec recherche
et sélection d’un paquet, récapitulatif et confirmation. Ces essais ne lancent
pas le moteur et ne remplacent pas les installations en VM ci-dessus.
En 80 × 24, la recherche de `Etc/GMT+3` et sa présence dans le récapitulatif
ont également été vérifiées en français et en anglais.
