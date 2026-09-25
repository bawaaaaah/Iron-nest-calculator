"""Tests du serveur MCP (stdlib uniquement) : python3 -m unittest discover -s tests -v"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "iron-nest-mcp" / "server.py"
sys.path.insert(0, str(SERVER.parent))
sys.dont_write_bytecode = True

import server  # noqa: E402

VECTORS = json.loads((ROOT / "tests" / "vectors.json").read_text(encoding="utf-8"))
AMMO = json.loads((ROOT / "iron-nest-mcp" / "ammo.json").read_text(encoding="utf-8"))["shells"]


class TestVectors(unittest.TestCase):
    """Mêmes attentes que tests/core.test.js (implémentation JS)."""

    def test_parse_brief(self):
        for case in VECTORS["parse_brief"]:
            with self.subTest(text=case["text"]):
                got = server.parse_brief(case["text"])
                self.assertEqual(len(got), len(case["expect"]), got)
                for t, exp in zip(got, case["expect"], strict=True):
                    for key, value in exp.items():
                        if key == "error":
                            self.assertEqual(bool(t.get("error")), value, t)
                        elif isinstance(value, float) or key in ("az", "km"):
                            self.assertAlmostEqual(t[key], value, places=6)
                        else:
                            self.assertEqual(t[key], value)

    def test_classify_and_kinds(self):
        for text, kind in VECTORS["classify"]:
            self.assertEqual(server.classify(text), kind, text)
        for text, kind in VECTORS["normalize_kind"]:
            self.assertEqual(server.normalize_kind(text), kind, text)

    def test_pick_shell(self):
        for kind, pref, clustered, shell in VECTORS["pick_shell"]:
            self.assertEqual(server.pick_shell(kind, pref, clustered), shell, (kind, pref, clustered))

    def test_min_charge(self):
        for km, charge in VECTORS["min_charge"]:
            self.assertEqual(server.min_charge(km), charge, km)

    def test_ballistics(self):
        for case in VECTORS["ballistics"]:
            with self.subTest(case=case):
                got = server.ballistics(case["km"], case["charges"])
                self.assertEqual("error" in got, bool(case.get("error")), got)
                if "charge" in case:
                    self.assertEqual(got["charge"], case["charge"])
                    self.assertAlmostEqual(got["elevation_deg"], case["elev"], places=2)
                    self.assertAlmostEqual(got["tof_s"], case["tof"], places=1)

    def test_parse_cell(self):
        for text, exp in VECTORS["parse_cell"]:
            with self.subTest(text=text):
                got = server.parse_cell(text)
                if exp is None:
                    self.assertIsNone(got)
                else:
                    self.assertEqual((got["token"], got["x_m"], got["y_m"]), (exp["token"], exp["x"], exp["y"]))

    def test_cell_of(self):
        for x, y, token in VECTORS["cell_of"]:
            self.assertEqual(server.cell_of(x, y)["token"], token, (x, y))

    def test_multi_kill(self):
        for case in VECTORS["multi_kill"]:
            with self.subTest(brief=case["brief"], pref=case["pref"]):
                targets = server.parse_brief(case["brief"])
                for i, t in enumerate(targets, 1):
                    t["id"] = i
                plans = server.multi_kill_plans(targets, case["pref"])
                for p in plans:
                    self.assertGreater(server.SHELLS[p["shell"]]["dmg"], 0, p)
                    if case["pref"] != "chem":
                        self.assertFalse(server.SHELLS[p["shell"]]["chem"], p)
                if case["top"] is None:
                    self.assertEqual(plans, [])
                else:
                    self.assertEqual((plans[0]["shell"], plans[0]["covers"]), (case["top"]["shell"], case["top"]["covers"]))

    def test_solve(self):
        for case in VECTORS["solve"]:
            with self.subTest(brief=case["brief"], mode=case["mode"]):
                res = server.solve_mission(case["brief"], case["mode"], case["pref"])
                by_id = {str(s["id"]): s for s in res["solutions"]}
                if "fire_order" in case:
                    self.assertEqual(res["fire_order"], case["fire_order"])
                for field in ("tubes", "shells", "charges"):
                    key = {"tubes": "tube", "shells": "shell", "charges": "charge"}[field]
                    for tid, value in case.get(field, {}).items():
                        self.assertEqual(by_id[tid][key], value, (field, tid))
                for tid in case.get("errors", []):
                    self.assertIn("error", by_id[str(tid)])
                if "cost" in case:
                    self.assertEqual((res["requisition_cost"], res["unknown_cost_shells"]), (case["cost"], case["unknown_cost"]))
                if "dual" in case:
                    self.assertEqual([p["targets"] for p in res["dual_tube"]], case["dual"])

    def test_triangulate(self):
        fns = {
            "two_azimuths": server.triangulate_two_azimuths,
            "az_dist": server.triangulate_az_dist,
            "two_distances": server.triangulate_two_distances,
        }
        for case in VECTORS["triangulate"]:
            with self.subTest(case=case):
                got = fns[case["mode"]](case["a"], case["p1"], case["b"], case["p2"])
                self.assertEqual(bool(got.get("error")), bool(case.get("error")), got)
                if "points" in case:
                    self.assertEqual([p["token"] for p in got["points"]], case["points"])
                if "note" in case:
                    self.assertEqual(got["note"], case["note"])


class TestTools(unittest.TestCase):
    def test_firing_solution_does_not_reparse_text(self):
        far = server.call_tool("iron_nest_firing_solution", {"azimuth_deg": 10, "distance_km": 35})
        self.assertIn("error", far["solutions"][0])
        self.assertEqual(far["fire_order"], [])
        s = server.call_tool("iron_nest_firing_solution", {"azimuth_deg": -10, "distance_km": 5, "target_type": "nest"})
        sol = s["solutions"][0]
        self.assertEqual((sol["az"], sol["km"], sol["kind"], sol["shell"]), (350, 5, "nest", "AP"))

    def test_pick_shell_nest(self):
        self.assertEqual(server.call_tool("iron_nest_pick_shell", {"target_type": "nest"})["shell"], "AP")

    def test_ballistics_rejects_short_charge(self):
        self.assertIn("error", server.call_tool("iron_nest_ballistics", {"distance_km": 20, "charges": 1}))
        with self.assertRaises(ValueError):
            server.call_tool("iron_nest_ballistics", {"distance_km": 20, "charges": 2.5})

    def test_invalid_arguments(self):
        with self.assertRaisesRegex(ValueError, "azimuth_b_deg"):
            args = {"mode": "two_azimuths", "point_a": "A1 0:0", "point_b": "C1 0:0", "azimuth_a_deg": 1}
            server.call_tool("iron_nest_triangulate", args)
        with self.assertRaisesRegex(ValueError, "charge_mode"):
            server.call_tool("iron_nest_solve_mission", {"brief": "az 1 2", "charge_mode": "fast"})

    def test_grid_shot_same_cell(self):
        self.assertEqual(server.grid_shot("B2 1:2", "B2 1:2")["error"], "distance nulle")

    def test_grid_shot_decimal_cells(self):
        shot = server.call_tool("iron_nest_grid_shot", {"nest": "B2 1:2", "target": "C5 4.5:6"})
        self.assertEqual(shot["target"]["token"], "C5 4.5:6")
        self.assertAlmostEqual(shot["distance_m"], 3658.2, places=1)

    def test_ammo_table(self):
        self.assertEqual(server.SHELLS, AMMO)
        self.assertEqual(server.call_tool("iron_nest_list_ammo", {}), AMMO)
        wiki = {"HE": (0.27, 3), "HCHE": (0.63, 5), "AP": (0.14, 3), "STAR": (12.74, 1), "SMK": (1.86, 1)}
        for name, (blast, cost) in wiki.items():
            self.assertEqual((AMMO[name]["blast_km"], AMMO[name]["cost"], AMMO[name]["confirmed"]), (blast, cost, True))
        for name, shell in AMMO.items():
            self.assertEqual(set(shell), {"dmg", "blast_km", "cost", "confirmed", "chem", "note", "vs"}, name)
            self.assertEqual(set(shell["vs"]), {"infantry", "vehicle", "artillery", "bunker", "nest"}, name)
            if not shell["confirmed"]:
                self.assertIsNone(shell["cost"], name)

    def test_every_tool_is_documented(self):
        readme = (ROOT / "iron-nest-mcp" / "README.md").read_text(encoding="utf-8")
        for tool in server.TOOLS:
            self.assertIn(f"`{tool['name']}`", readme)


def rpc(id_, method, params=None):
    msg = {"jsonrpc": "2.0", "method": method}
    if id_ is not None:
        msg["id"] = id_
    if params is not None:
        msg["params"] = params
    return msg


class TestJsonRpc(unittest.TestCase):
    def test_errors_do_not_kill_the_server(self):
        self.assertEqual(server.process_line("{oops")["error"]["code"], -32700)
        self.assertEqual(server.process_line('"hello"')["error"]["code"], -32600)
        self.assertEqual(server.process_line("[]")["error"]["code"], -32600)
        self.assertEqual(server.process_line('{"jsonrpc":"2.0","id":3,"method":"nope"}')["error"]["code"], -32601)
        self.assertIsNone(server.process_line('{"jsonrpc":"2.0","method":"notifications/initialized"}'))

    def test_batch_returns_array(self):
        reply = server.process_line(json.dumps([rpc(1, "ping"), rpc(None, "notifications/initialized"), 2]))
        self.assertIsInstance(reply, list)
        self.assertEqual([r.get("id") for r in reply], [1, None])

    def test_tool_error_is_reported(self):
        call = {"name": "iron_nest_grid_shot", "arguments": {"nest": "Z9", "target": "A1 1:1"}}
        reply = server.process_line(json.dumps(rpc(4, "tools/call", call)))
        self.assertTrue(reply["result"]["isError"])

    def test_stdio_is_utf8_even_with_cp1252_locale(self):
        brief = "Azimut 55.3 distance 12.7 fantassin éclaireur\nAzimut 54.2 distance 9.7"
        call = {"name": "iron_nest_solve_mission", "arguments": {"brief": brief}}
        lines = [
            '"not an object"',
            json.dumps(rpc(1, "tools/call", call), ensure_ascii=False),
            json.dumps(rpc(2, "ping")),
        ]
        env = dict(os.environ, PYTHONIOENCODING="cp1252", PYTHONDONTWRITEBYTECODE="1")
        proc = subprocess.run(
            [sys.executable, str(SERVER)], input="\n".join(lines).encode("utf-8"), capture_output=True, env=env, timeout=30
        )
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))
        replies = [json.loads(line) for line in proc.stdout.decode("utf-8").splitlines()]
        self.assertEqual([r.get("id") for r in replies], [None, 1, 2])
        text = replies[1]["result"]["content"][0]["text"]
        self.assertIn("Δaz", text)
        self.assertIn("éclaireur", text)


if __name__ == "__main__":
    unittest.main()
