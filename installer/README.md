# Moteur ArchHelper et interface terminal

Le binaire Go `arch-install` est l’entrée de l’interface. Le moteur Python est privé
au protocole local et reste l’unique propriétaire des validations et opérations
de disque ; aucun partitionnement n’est implémenté en Go ou en Bash.

## Organisation de la release

```text
install.sh                  # script autonome assemblé
  installer/arch-install    # interface intégrée
  installer/engine/run.py   # moteur intégré
  installer/engine/v8_installer/
```

Les profils de bureau décrivent les paquets officiels à résoudre dans les dépôts
actifs ; ils n’embarquent ni compte ni base pacman du live.

## Protocole local v1

Go démarre `python -I engine/run.py --rpc`, transmet une requête JSON sur stdin
puis ferme le tube. Stdout est réservé aux événements JSON Lines, chacun portant
`version: 1`, `type` et `data`. Les sorties des commandes d’installation sont
capturées séparément et filtrées avant leur écriture dans le journal privé.

| Action | Entrée complémentaire | Résultat |
|---|---|---|
| `checks` | aucune | Compatibilité du live, intégrité du payload, matériel et réseau |
| `network` | aucune | Connectivité HTTPS et disponibilité d’iwctl |
| `discover` | aucune | Disques découverts en lecture seule et matériel |
| `packages` | aucune | Catalogue des paquets des dépôts actifs, synchronisé dans une base temporaire |
| `plan` | `options` | Plan normalisé, transaction résolue, résumé et confirmation liée au plan |
| `preflight` | `plan` | Revalidation du live, matériel, disque, payload et réseau |
| `export` | `plan` | Rapport privé avec plan sans secrets |
| `install` | `plan`, `credentials`, `confirmation` | Phases réelles, résultat et chemin du rapport |

`plan` accepte disque, mode, partitions manuelles, compte/machine, locale,
claviers console et graphique, fuseau, noyau, UKI/LUKS/Plymouth, profils graphique,
réseau et instantanés, Bluetooth, ZRAM, swap et paquets supplémentaires. Le moteur redécouvre
le disque ; l’interface ne fournit pas d’identité de disque faisant autorité.
Le plan retourné doit être retransmis intact à la confirmation. Un changement
des options déclenche sa reconstruction.

Types d’événements : `report`, `progress`, `failed`, `result` et `error`.
Les lignes de progression portent les phases `planned/started/completed/failed`.
Les erreurs externes exposent leur classe, pas leur contenu potentiellement privé.
Un protocole inconnu ou un message mal formé échoue sans réémettre la requête.

## Transaction et arrêt

Avant formatage, les paquets sont résolus contre une base vide, leurs signatures
sont vérifiées et une transaction locale est préparée dans le live. Le journal
reste privé ; les archives ne contiennent aucun secret. Tous les paquets restent
soumis à des signatures obligatoires et sont vérifiés avec le trousseau du live.

Un verrou empêche deux installations concurrentes. Les protections et contrôles
d’identité sont réutilisés juste avant les écritures. Les erreurs déclenchent le
démontage de la cible et la fermeture du mapping LUKS créé par l’installateur.
La fermeture du canal d’interface ne doit pas interrompre une opération disque.
Un arrêt brutal ou une panne impose un nouveau scan et un nouveau plan.

L’interface ne lance pas le moteur en mode `--demo`. Les tests physiques et les
tests loop restent distincts des tests de présentation et du protocole.
