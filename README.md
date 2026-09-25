# Iron Nest Calculator

Calculateurs et outils pour **IRON NEST: Heavy Turret Simulator**.

## Fichiers

| Fichier | Description |
|---------|-------------|
| `iron-nest-grid.html` | Calculateur principal : grille A1–T10, triangulation, raccourcis, multi-cibles, points de chute, sessions, SAFE/UNSAFE |
| `iron-nest-fcs.html` | Solution de tir (FCS) multi-cibles / munitions à partir d'un briefing texte |
| `iron-nest-core.js` | Cœur de calcul partagé par les deux pages (à garder dans le même dossier) |
| `iron-nest-mcp/` | Serveur MCP (Model Context Protocol) pour agents, et `ammo.json`, la table des obus |
| `tests/` | Tests Python et Node sur les mêmes cas (`tests/vectors.json`) |
| `tools/sync_ammo.py` | Recopie `ammo.json` dans `iron-nest-core.js` |

## Utilisation

Ouvrir `iron-nest-grid.html` ou `iron-nest-fcs.html` dans un navigateur (double-clic ou serveur local). `iron-nest-core.js` doit rester à côté des pages.

### Conventions

- **Azimut** : 0° = Nord, sens horaire (90° = Est).
- **Grille** : colonnes A→T d'ouest en est, lignes 1→10 du sud au nord (ligne 1 en bas), 1 km par case. La subdivision `sx:sy` compte les centaines de mètres depuis le coin sud-ouest de la case, au 0.1 près (10 m) : `B2 1:2`, `A1 0.1:0.7`.
- **Briefing FCS** : une cible par ligne, `Azimut 55.3 distance 12.7 bunker`. Distance en km, ou en mètres avec `m` (`2700 m`). Sans unité, une valeur ≥ 100 est lue en mètres ; entre 30 et 100 elle est refusée (ambiguë). Les lignes hors portée sont affichées en erreur, pas ignorées.
- **Balistique** : élévation = 12 × km / charges ; ToF = km / v_eff (C1–C6 : 0.21 0.31 0.41 0.50 0.60 0.70 km/s) ; portée max = 5 km × charges (30 km en C6).
- **Tubes** : alternés Gauche / Droite dans l'ordre de tir (priorité Nest ennemi → bunker → artillerie → véhicule → infanterie → inconnu, puis distance).

### Fonctionnalités (grille)

- Coordonnées grille avec subdivisions décimales (`A1 0.1:0.7`)
- Triangulation (2 azimuts, az + dist, 2 distances), tir calculé depuis le canon choisi
- Raccourcis nommés (Nest, observateurs, références, cibles, alliés)
- Carte : clic = placer / sélectionner, glisser = déplacer (souris et tactile), points de chute multiples
- Tableau de bord cibles : assignation, tubes G/D, état, efficacité obus, SAFE/UNSAFE (alliés, observateurs et Nest dans le rayon)
- Sessions navigateur (sauver / charger / reset)

### Munitions

Une seule table : `iron-nest-mcp/ammo.json`. Les valeurs `confirmed` viennent du wiki (HE, HCHE, AP, STAR, SMOKE) ; les autres obus sont des hypothèses, avec un coût inconnu (`null`). STAR, SMOKE, TEAR GAS et WP font 0 dégât : toujours SAFE pour les amis, jamais proposés en tir groupé. Les chimiques (PHGN, CYAN) ne sont proposés qu'avec la préférence « chimiques ».

Après une modification de `ammo.json`, lancer `python3 tools/sync_ammo.py` pour mettre à jour la copie embarquée dans `iron-nest-core.js` (les pages ouvertes en `file://` ne peuvent pas lire le JSON). Le test Node échoue tant que les deux diffèrent.

## Tests

Sans dépendance, lancés par GitHub Actions à chaque push et pull request :

```bash
python3 -m unittest discover -s tests -v   # serveur MCP + table des obus
node --test tests/core.test.js             # cœur JS des pages
```

Les deux suites vérifient les mêmes cas (`tests/vectors.json`), ce qui garantit que le serveur MCP et les pages donnent les mêmes résultats.

## Licence

Outil communautaire non officiel — non affilié aux développeurs du jeu.
