#!/usr/bin/env python3
"""Recopie iron-nest-mcp/ammo.json dans la constante AMMO de iron-nest-core.js.

Les pages HTML s'ouvrent en file:// et ne peuvent pas lire le JSON : le cœur JS en
embarque donc une copie. À relancer après chaque modification de ammo.json
(tests/core.test.js échoue tant que les deux diffèrent).
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    shells = json.loads((ROOT / "iron-nest-mcp" / "ammo.json").read_text(encoding="utf-8"))["shells"]
    body = ",\n".join(f"    {name}: {json.dumps(shell, ensure_ascii=False)}" for name, shell in shells.items())
    core = ROOT / "iron-nest-core.js"
    src = core.read_text(encoding="utf-8")
    new, n = re.subn(r"const AMMO = \{\n.*?\n  \};", lambda _: "const AMMO = {\n" + body + "\n  };", src, count=1, flags=re.S)
    if n != 1:
        sys.exit("bloc « const AMMO = {…};» introuvable dans iron-nest-core.js")
    if new == src:
        print("AMMO déjà à jour")
        return
    core.write_text(new, encoding="utf-8")
    print("AMMO synchronisé depuis ammo.json")


if __name__ == "__main__":
    main()
