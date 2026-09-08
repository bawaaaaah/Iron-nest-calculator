# IRON NEST FCS — serveur MCP

Serveur [Model Context Protocol](https://modelcontextprotocol.io) en stdio JSON-RPC 2.0, sans dépendance.

## Outils exposés

| Tool | Rôle |
|------|------|
| `iron_nest_solve_mission` | Briefing multi-cibles → charges, élévation, ToF, munitions, tubes, plan MCP |
| `iron_nest_firing_solution` | Une cible (azimut, km, type) |
| `iron_nest_pick_shell` | Meilleure munition (HE si doute) |
| `iron_nest_ballistics` | Élévation + temps de vol |
| `iron_nest_list_ammo` | Catalogue obus |

## Brancher dans Claude Desktop

Fichier `claude_desktop_config.json` :

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

Cursor / autres clients MCP : même bloc `command` + `args`, transport stdio.

## Test manuel

```bash
python3 server.py <<'EOF'
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"0"}}}
{"jsonrpc":"2.0","id":2,"method":"tools/list"}
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"iron_nest_solve_mission","arguments":{"brief":"Azimut 55.3 distance 12.7\nAzimut 54.2 distance 9.7 Iron nest enemis\nAzimut 52.3 distance 2.7 bunker\nAzimut 51.3 distance 22.7 infantry","charge_mode":"max","ammo_pref":"auto"}}}
EOF
```

Formules jeu : élévation = 12 × km / charges ; ToF = km / v_eff ; v_eff C1–C6 = 0.21 0.31 0.41 0.50 0.60 0.70 ; portée max = 5 km × charges.
