# IRON NEST FCS — serveur MCP

Serveur [Model Context Protocol](https://modelcontextprotocol.io) en stdio JSON-RPC 2.0 (UTF-8), sans dépendance (Python ≥ 3.10). La table des obus est lue dans `ammo.json`, à garder à côté de `server.py`.

## Outils exposés

| Tool | Rôle |
|------|------|
| `iron_nest_solve_mission` | Briefing multi-cibles → charges, élévation, ToF, munitions, tubes, tirs groupés, double tube, plan texte |
| `iron_nest_firing_solution` | Une cible (azimut, km, type) ; azimut négatif accepté, distance hors 0–30 km signalée en erreur |
| `iron_nest_pick_shell` | Meilleure munition pour un type de cible (HE si doute) |
| `iron_nest_ballistics` | Élévation + temps de vol ; erreur si la charge ne porte pas jusqu'à la distance |
| `iron_nest_list_ammo` | Catalogue des obus (`ammo.json`) : dégâts, rayon, coût, confirmé wiki ou hypothèse |
| `iron_nest_grid_shot` | Deux cases A1–T10 (subdivisions décimales) → vecteur, distance, azimut, charges |
| `iron_nest_grid_mission` | Plusieurs cases cibles depuis une case Nest |
| `iron_nest_triangulate` | Position d'une cible : 2 azimuts, azimut + distance, ou 2 distances |
| `iron_nest_multi_kill` | Tirs groupés (plusieurs cibles dans un rayon) et paires double tube d'un briefing |

Types de cible reconnus : `unknown`, `infantry`, `vehicle`, `artillery`, `bunker`, `nest`, `smoke`, `illum` (un texte libre est classé automatiquement).

## Brancher dans Claude Desktop

Fichier `claude_desktop_config.json` (voir `claude_desktop_config.fragment.json`) :

```json
{
  "mcpServers": {
    "iron-nest-fcs": {
      "command": "python3",
      "args": ["/chemin/absolu/vers/iron-nest-mcp/server.py"]
    }
  }
}
```

Cursor / autres clients MCP : même bloc `command` + `args`, transport stdio. Sous Windows, `python` à la place de `python3` selon l'installation ; les échanges restent en UTF-8 quelle que soit la page de code de la console.

## Test manuel

```bash
python3 server.py <<'EOF'
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"0"}}}
{"jsonrpc":"2.0","id":2,"method":"tools/list"}
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"iron_nest_solve_mission","arguments":{"brief":"Azimut 55.3 distance 12.7\nAzimut 54.2 distance 9.7 Iron nest enemis\nAzimut 52.3 distance 2.7 bunker\nAzimut 51.3 distance 22.7 infantry","charge_mode":"max","ammo_pref":"auto"}}}
EOF
```

Tests automatiques : `python3 -m unittest discover -s tests -v` depuis la racine du dépôt.

Formules jeu : élévation = 12 × km / charges ; ToF = km / v_eff ; v_eff C1–C6 = 0.21 0.31 0.41 0.50 0.60 0.70 ; portée max = 5 km × charges.
