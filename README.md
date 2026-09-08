# Iron Nest Calculator

Calculateurs et outils pour **IRON NEST: Heavy Turret Simulator**.

## Fichiers

| Fichier | Description |
|---------|-------------|
| `iron-nest-grid.html` | Calculateur principal : grille A1–T10, triangulation, raccourcis, multi-cibles, points de chute, sessions, alliés SAFE/UNSAFE |
| `iron-nest-fcs.html` | Solution de tir (FCS) multi-cibles / munitions |
| `iron-nest-mcp/` | Serveur MCP (Model Context Protocol) pour agents |

## Utilisation

Ouvrir `iron-nest-grid.html` dans un navigateur (double-clic ou serveur local).

### Fonctionnalités (grille)

- Coordonnées grille avec subdivisions décimales (`A1 0.1:0.7`)
- Triangulation (2 azimuts, az+dist, 2 distances)
- Raccourcis nommés (Nest, obs, cibles, alliés)
- Clic carte : placer / déplacer points, points de chute multiples
- Tableau de bord cibles : tubes G/D, efficacité obus, SAFE/UNSAFE
- Sessions navigateur (sauver / charger / reset)
- Référence munitions alignée wiki (HE, HCHE, AP, STAR, SMOKE, …)

### Munitions (wiki v1.0)

STAR et SMOKE = 0 dégât → toujours SAFE pour les alliés.

## Licence

Outil communautaire non officiel — non affilié aux développeurs du jeu.
