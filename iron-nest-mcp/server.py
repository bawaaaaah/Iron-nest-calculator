#!/usr/bin/env python3
"""IRON NEST Fire Control — Model Context Protocol server (stdio JSON-RPC 2.0)."""

from __future__ import annotations

import json
import math
import re
import sys
from typing import Any

PROTOCOL = "2024-11-05"
SERVER_NAME = "iron-nest-fcs"
SERVER_VERSION = "1.0.0"

SPEEDS = {1: 0.21, 2: 0.31, 3: 0.41, 4: 0.50, 5: 0.60, 6: 0.70}

SHELLS = {
    "HE":   {"dmg": 1, "blast": 0.25, "cost": 10, "note": "Fragmentation standard", "roles": ["soft", "artillery", "vehicle", "unknown"]},
    "HCHE": {"dmg": 1, "blast": 0.55, "cost": 18, "note": "Gros rayon / clusters", "roles": ["cluster", "infantry", "artillery"]},
    "AP":   {"dmg": 2, "blast": 0.15, "cost": 10, "note": "Pénétration bunker / Nest", "roles": ["bunker", "armor", "nest", "hard"]},
    "APHE": {"dmg": 2, "blast": 0.25, "cost": 15, "note": "AP + souffle", "roles": ["bunker", "armor", "nest"]},
    "EQKE": {"dmg": 2, "blast": 0.55, "cost": 26, "note": "Burst souterrain retardé", "roles": ["bunker", "hard"]},
    "CLMN": {"dmg": 1, "blast": 0.50, "cost": 17, "note": "Sous-munitions", "roles": ["infantry", "cluster", "vehicle"]},
    "FLCH": {"dmg": 1, "blast": 0.62, "cost": 20, "note": "Fléchettes infanterie à découvert", "roles": ["infantry"]},
    "PHGN": {"dmg": 1, "blast": 0.62, "cost": 10, "note": "Phosgène", "roles": ["infantry"]},
    "CYAN": {"dmg": 1, "blast": 0.75, "cost": 28, "note": "Cyanogène — pas les fortifiés", "roles": ["infantry"]},
    "INCN": {"dmg": 1, "blast": 0.25, "cost": 12, "note": "Incendiaire", "roles": ["soft"]},
    "THRM": {"dmg": 1, "blast": 0.35, "cost": 22, "note": "Thermite large", "roles": ["soft"]},
    "SMK":  {"dmg": 0, "blast": 1.00, "cost": 2,  "note": "Fumigène", "roles": ["smoke"]},
    "STAR": {"dmg": 0, "blast": 0.50, "cost": 2,  "note": "Éclairement", "roles": ["illum"]},
    "TEAR": {"dmg": 0, "blast": 0.75, "cost": 8,  "note": "Lacrymo / révèle cachés", "roles": ["suppress"]},
    "WP":   {"dmg": 0, "blast": 0.75, "cost": 10, "note": "Phosphore blanc", "roles": ["infantry", "suppress"]},
    "LE":   {"dmg": 1, "blast": 0.15, "cost": 8,  "note": "HE économique", "roles": ["soft"]},
}

COLS = "ABCDEFGHIJKLMNOPQRST"
GRID_RE = re.compile(
    r"([A-Ta-t])\s*(10|[1-9])\s*[ ,]?\s*(\d{1,2})\s*[:/,]\s*(\d{1,2})",
    re.I,
)


def parse_cell(text: str) -> dict[str, Any] | None:
    m = GRID_RE.search(text or "")
    if not m:
        return None
    col = COLS.find(m.group(1).upper())
    row = int(m.group(2))
    sx, sy = int(m.group(3)), int(m.group(4))
    if col < 0 or not (1 <= row <= 10) or not (0 <= sx <= 10) or not (0 <= sy <= 10):
        return None
    x = col * 1000 + sx * 100
    y = (row - 1) * 1000 + sy * 100
    return {
        "token": f"{m.group(1).upper()}{row} {sx}:{sy}",
        "col": col,
        "row": row,
        "sx": sx,
        "sy": sy,
        "x_m": x,
        "y_m": y,
    }


def _dir(az_deg: float) -> tuple[float, float]:
    r = math.radians(az_deg)
    return math.sin(r), math.cos(r)


def cell_of(x: float, y: float) -> dict[str, Any]:
    if x < 0 or y < 0 or x > 20000 or y > 10000:
        return {"token": "hors carte", "x_m": round(x, 1), "y_m": round(y, 1)}
    col = min(19, int(x // 1000))
    row = min(10, int(y // 1000) + 1)
    sx = int(round((x - col * 1000) / 100))
    sy = int(round((y - (row - 1) * 1000) / 100))
    if sx >= 10:
        col = min(19, col + 1)
        sx = 0
    if sy >= 10:
        row = min(10, row + 1)
        sy = 0
    return {
        "token": f"{COLS[col]}{row} {sx}:{sy}",
        "x_m": round(x, 1),
        "y_m": round(y, 1),
        "col": col,
        "row": row,
        "sx": sx,
        "sy": sy,
    }


def triangulate_two_azimuths(a: str, az_a: float, b: str, az_b: float) -> dict[str, Any]:
    A, B = parse_cell(a), parse_cell(b)
    if not A or not B:
        raise ValueError("Point A ou B invalide")
    if A["x_m"] == B["x_m"] and A["y_m"] == B["y_m"]:
        return {"error": "deux azimuts depuis le meme point ne localisent pas une cible", "points": []}
    adx, ady = _dir(az_a)
    bdx, bdy = _dir(az_b)
    den = adx * bdy - ady * bdx
    if abs(den) < 1e-9:
        return {"error": "rayons paralleles", "points": []}
    dx, dy = B["x_m"] - A["x_m"], B["y_m"] - A["y_m"]
    t = (dx * bdy - dy * bdx) / den
    s = (dx * ady - dy * adx) / den
    x, y = A["x_m"] + t * adx, A["y_m"] + t * ady
    return {
        "mode": "2_azimuths",
        "behind_a_ray": t <= 0,
        "behind_b_ray": s <= 0,
        "points": [cell_of(x, y)],
    }


def triangulate_az_dist(a: str, az_a: float, b: str, dist_km: float) -> dict[str, Any]:
    A, B = parse_cell(a), parse_cell(b)
    if not A or not B:
        raise ValueError("Point A ou B invalide")
    dx, dy = _dir(az_a)
    fx, fy = A["x_m"] - B["x_m"], A["y_m"] - B["y_m"]
    r = dist_km * 1000
    qb = 2 * (fx * dx + fy * dy)
    qc = fx * fx + fy * fy - r * r
    disc = qb * qb - 4 * qc
    if disc < -1e-6:
        return {"error": "pas d'intersection rayon/cercle", "points": []}
    root = math.sqrt(max(0.0, disc))
    ts = [t for t in ((-qb - root) / 2, (-qb + root) / 2) if t > 1]
    if not ts:
        return {"error": "intersections derriere le rayon", "points": []}
    return {
        "mode": "azimuth_plus_distance",
        "n": len(ts),
        "points": [cell_of(A["x_m"] + t * dx, A["y_m"] + t * dy) for t in ts],
        "note": "2 solutions" if len(ts) == 2 else None,
    }


def triangulate_two_distances(a: str, da_km: float, b: str, db_km: float) -> dict[str, Any]:
    A, B = parse_cell(a), parse_cell(b)
    if not A or not B:
        raise ValueError("Point A ou B invalide")
    dx, dy = B["x_m"] - A["x_m"], B["y_m"] - A["y_m"]
    d = math.hypot(dx, dy)
    rA, rB = da_km * 1000.0, db_km * 1000.0
    if d < 1e-6:
        return {"error": "points confondus", "points": []}
    if d > rA + rB + 1e-6:
        return {"error": "cercles disjoints", "points": []}
    if d < abs(rA - rB) - 1e-6:
        return {"error": "un cercle contenu dans l'autre", "points": []}
    aa = (rA * rA - rB * rB + d * d) / (2 * d)
    h = math.sqrt(max(0.0, rA * rA - aa * aa))
    mx, my = A["x_m"] + aa * dx / d, A["y_m"] + aa * dy / d
    px, py = -dy / d * h, dx / d * h
    pts = [cell_of(mx + px, my + py), cell_of(mx - px, my - py)]
    if h < 1e-4:
        return {"mode": "2_distances", "n": 1, "note": "tangence", "points": [pts[0]]}
    return {
        "mode": "2_distances",
        "n": 2,
        "note": "2 solutions — departager avec un 3e indice",
        "points": pts,
    }


def grid_shot(nest_s: str, target_s: str) -> dict[str, Any]:
    nest = parse_cell(nest_s)
    tgt = parse_cell(target_s)
    if not nest or not tgt:
        raise ValueError("Coordonnée invalide. Exemple: B2 1:2 et C5 4:6")
    dx = tgt["x_m"] - nest["x_m"]
    dy = tgt["y_m"] - nest["y_m"]
    dist_m = math.hypot(dx, dy)
    az = math.degrees(math.atan2(dx, dy))
    if az < 0:
        az += 360
    km = dist_m / 1000.0
    cmin = min_charge(km)
    out: dict[str, Any] = {
        "nest": nest,
        "target": tgt,
        "vector_m": {"x": dx, "y": dy},
        "distance_m": round(dist_m, 1),
        "distance_km": round(km, 3),
        "azimuth_deg": round(az, 1),
        "convention": "0° Nord (+Y), 90° Est (+X), 180° Sud, 270° Ouest",
    }
    if cmin:
        out["charge_min"] = cmin
        out["elevation_min_deg"] = round(elevation(km, cmin), 2)
        out["tof_min_s"] = round(time_of_flight(km, cmin), 1)
        out["charge_6"] = 6
        out["elevation_c6_deg"] = round(elevation(km, 6), 2)
        out["tof_c6_s"] = round(time_of_flight(km, 6), 1)
    else:
        out["error"] = "hors portée 30 km"
    return out


LINE_RE = re.compile(
    r"(?:azim(?:ut|ute)?|az|bearing)?\s*"
    r"([0-9]+(?:[.,][0-9]+)?)\s*(?:°|deg)?\s*"
    r"(?:[,;/]|dist(?:ance)?|range|-)?\s*"
    r"([0-9]+(?:[.,][0-9]+)?)\s*(km|m)?"
    r"\s*(.*)?",
    re.I,
)


def min_charge(km: float) -> int | None:
    if km <= 0 or km > 30:
        return None
    return max(1, min(6, math.ceil(km / 5.0)))


def elevation(km: float, charges: int) -> float:
    return (12.0 * km) / charges


def time_of_flight(km: float, charges: int) -> float:
    return km / SPEEDS[charges]


def classify(text: str) -> str:
    t = (text or "").lower()
    if re.search(r"iron.?nest|nest enem", t):
        return "nest"
    if re.search(r"bunker|fort|armor|armour|hard|palace", t):
        return "bunker"
    if re.search(r"infant|troop|squad|fantassin", t):
        return "infantry"
    if re.search(r"artill|battery|fdc|canon", t):
        return "artillery"
    if re.search(r"train|boat|ship|convoi|vehicle|tank|mech", t):
        return "vehicle"
    if re.search(r"smoke|fum", t):
        return "smoke"
    if re.search(r"illum|star|night|nuit", t):
        return "illum"
    return "unknown"


def pick_shell(kind: str, pref: str, clustered: bool) -> str:
    if pref == "he":
        return "HE"
    if kind in {"bunker", "nest", "hard"}:
        return "APHE" if clustered else "AP"
    if kind == "infantry":
        if pref == "chem":
            return "PHGN"
        return "HCHE"
    if kind == "artillery":
        return "HCHE" if clustered else "HE"
    if kind == "vehicle":
        return "HE"
    if kind == "smoke":
        return "SMK"
    if kind == "illum":
        return "STAR"
    if pref == "eco":
        return "LE"
    if clustered:
        return "HCHE"
    return "HE"


def sep_km(az1: float, d1: float, az2: float, d2: float) -> float:
    r1, r2 = math.radians(az1), math.radians(az2)
    x1, y1 = d1 * math.sin(r1), d1 * math.cos(r1)
    x2, y2 = d2 * math.sin(r2), d2 * math.cos(r2)
    return math.hypot(x1 - x2, y1 - y2)


def parse_brief(text: str) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    for line in text.splitlines():
        m = LINE_RE.search(line)
        if not m:
            continue
        az = float(m.group(1).replace(",", "."))
        dist = float(m.group(2).replace(",", "."))
        unit = (m.group(3) or "").lower()
        if unit == "m" or (dist > 30 and dist <= 30000):
            dist = dist / 1000.0
        label = (m.group(4) or "").strip()
        if az > 360 or dist <= 0 or dist > 30:
            continue
        targets.append(
            {
                "az": az,
                "km": dist,
                "label": label,
                "kind": classify(label + " " + line),
            }
        )
    return targets


HARD = {"bunker", "nest", "hard", "armor"}
AREA_SHELLS = ["HCHE", "CLMN", "FLCH", "PHGN", "CYAN", "HE", "APHE", "EQKE", "WP", "THRM"]


def xy(az: float, km: float) -> tuple[float, float]:
    r = math.radians(az)
    return km * math.sin(r), km * math.cos(r)


def polar(x: float, y: float) -> tuple[float, float]:
    km = math.hypot(x, y)
    az = (math.degrees(math.atan2(x, y)) + 360) % 360
    return az, km


def covered(ax: float, ay: float, targets: list[dict[str, Any]], radius: float, splash_hard: bool) -> list[int]:
    hit = []
    for t in targets:
        tx, ty = xy(t["az"], t["km"])
        if math.hypot(tx - ax, ty - ay) <= radius + 1e-9:
            if t["kind"] in HARD and not splash_hard:
                if math.hypot(tx - ax, ty - ay) > 0.02:
                    continue
            hit.append(t["id"])
    return hit


def multi_kill_plans(targets: list[dict[str, Any]], ammo_pref: str) -> list[dict[str, Any]]:
    if len(targets) < 2:
        return []
    plans = []
    seen: set[tuple] = set()
    shells = AREA_SHELLS if ammo_pref != "he" else ["HE", "HCHE"]
    if ammo_pref == "chem":
        shells = ["PHGN", "CYAN", "WP", "HCHE", "HE"]
    candidates: list[tuple[float, float, str]] = []
    for t in targets:
        candidates.append((*xy(t["az"], t["km"]), f"sur T{t['id']}"))
    for i in range(len(targets)):
        for j in range(i + 1, len(targets)):
            x1, y1 = xy(targets[i]["az"], targets[i]["km"])
            x2, y2 = xy(targets[j]["az"], targets[j]["km"])
            candidates.append(((x1 + x2) / 2, (y1 + y2) / 2, f"milieu T{targets[i]['id']}-T{targets[j]['id']}"))
    for ax, ay, label in candidates:
        az, km = polar(ax, ay)
        if km <= 0 or km > 30:
            continue
        cmin = min_charge(km)
        if cmin is None:
            continue
        for shell in shells:
            blast = SHELLS[shell]["blast"]
            splash_hard = shell in {"EQKE", "APHE", "ATMC"} or SHELLS[shell]["dmg"] >= 2
            ids = covered(ax, ay, targets, blast, splash_hard)
            if len(ids) < 2:
                continue
            key = (tuple(sorted(ids)), shell)
            if key in seen:
                continue
            seen.add(key)
            plans.append(
                {
                    "aim_az": round(az, 2),
                    "aim_km": round(km, 2),
                    "aim_note": label,
                    "shell": shell,
                    "blast_km": blast,
                    "covers": ids,
                    "n": len(ids),
                    "charge_min": cmin,
                    "elevation_min_deg": round(elevation(km, cmin), 2),
                    "tof_min_s": round(time_of_flight(km, cmin), 1),
                    "charge_max": 6,
                    "elevation_max_deg": round(elevation(km, 6), 2),
                    "tof_max_s": round(time_of_flight(km, 6), 1),
                    "cost": SHELLS[shell]["cost"],
                    "saved_shots": len(ids) - 1,
                }
            )
    plans.sort(key=lambda p: (-p["n"], p["cost"], p["aim_km"]))
    return plans[:12]


def dual_tube_pairs(targets: list[dict[str, Any]], az_tol: float = 2.0) -> list[dict[str, Any]]:
    pairs = []
    for i in range(len(targets)):
        for j in range(i + 1, len(targets)):
            daz = abs(targets[i]["az"] - targets[j]["az"])
            daz = min(daz, 360 - daz)
            if daz > az_tol:
                continue
            pairs.append(
                {
                    "targets": [targets[i]["id"], targets[j]["id"]],
                    "delta_az_deg": round(daz, 2),
                    "note": "Même traverse tourelle — GAUCHE et DROITE à élévations différentes",
                    "left": {"id": targets[i]["id"], "az": targets[i]["az"], "km": targets[i]["km"]},
                    "right": {"id": targets[j]["id"], "az": targets[j]["az"], "km": targets[j]["km"]},
                }
            )
    return pairs


def solve_mission(brief: str, charge_mode: str = "max", ammo_pref: str = "auto") -> dict[str, Any]:
    targets = parse_brief(brief)
    for i, t in enumerate(targets, 1):
        t["id"] = i
    clustered: set[int] = set()
    for i in range(len(targets)):
        for j in range(i + 1, len(targets)):
            if sep_km(targets[i]["az"], targets[i]["km"], targets[j]["az"], targets[j]["km"]) <= 0.55:
                clustered.add(targets[i]["id"])
                clustered.add(targets[j]["id"])

    solutions = []
    for idx, t in enumerate(targets):
        cmin = min_charge(t["km"])
        if cmin is None:
            solutions.append({**t, "error": "hors portée (>30 km)"})
            continue
        charges = 6 if charge_mode == "max" else cmin
        shell = pick_shell(t["kind"], ammo_pref, t["id"] in clustered)
        sol = {
            **t,
            "clustered": t["id"] in clustered,
            "charge_min": cmin,
            "charge": charges,
            "elevation_deg": round(elevation(t["km"], charges), 2),
            "elevation_min_deg": round(elevation(t["km"], cmin), 2),
            "tof_s": round(time_of_flight(t["km"], charges), 1),
            "shell": shell,
            "shell_stats": SHELLS[shell],
            "fallback_shell": None if shell == "HE" else "HE",
            "tube": "GAUCHE" if idx % 2 == 0 else "DROITE",
        }
        solutions.append(sol)

    cost = sum(SHELLS.get(s.get("shell", ""), {}).get("cost", 0) for s in solutions)
    priority = {"nest": 0, "bunker": 1, "artillery": 2, "vehicle": 3, "infantry": 4, "unknown": 5}
    ordered = sorted(solutions, key=lambda s: (priority.get(s.get("kind", "unknown"), 9), s.get("km", 99)))
    mcp_lines = [
        "IRON NEST MCP / FIRE MISSION",
        f"mode={charge_mode} pref={ammo_pref} rc={cost} n={len(solutions)}",
        "",
    ]
    for s in ordered:
        if s.get("error"):
            mcp_lines.append(f"T{s['id']} ERROR {s['error']}")
            continue
        mcp_lines.append(
            f"T{s['id']} {s['kind'].upper()} AZ {s['az']:.1f} DIST {s['km']:.2f}km "
            f"TUBE {s['tube']} {s['shell']} C{s['charge']} ELEV {s['elevation_deg']:.2f} "
            f"ToF {s['tof_s']:.1f}s"
        )
    valid = [t for t in targets if min_charge(t["km"])]
    mk = multi_kill_plans(valid, ammo_pref)
    dual = dual_tube_pairs(valid)
    if mk:
        mcp_lines += ["", "TIRS GROUPÉS (1 obus, N cibles dans le blast)"]
        for p in mk[:5]:
            mcp_lines.append(
                f"  {p['shell']} blast {p['blast_km']}km @ AZ {p['aim_az']:.1f} {p['aim_km']:.2f}km "
                f"couvre T{',T'.join(map(str,p['covers']))}  économise {p['saved_shots']} tir(s)"
            )
    if dual:
        mcp_lines += ["", "SALVES DOUBLE TUBE (azimuts proches)"]
        for p in dual:
            mcp_lines.append(
                f"  T{p['targets'][0]}+T{p['targets'][1]}  Δaz {p['delta_az_deg']}°  — poser GAUCHE/DROITE"
            )
    return {
        "targets": len(solutions),
        "requisition_cost": cost,
        "solutions": solutions,
        "fire_order": [s["id"] for s in ordered if "error" not in s],
        "multi_kill": mk,
        "dual_tube": dual,
        "mcp_text": "\n".join(mcp_lines),
    }


TOOLS = [
    {
        "name": "iron_nest_solve_mission",
        "description": (
            "Parse a free-text Iron Nest briefing with multiple targets "
            "(azimuth, distance, optional type) and return firing solutions: "
            "charge, elevation, time of flight, recommended shell, gun tube, MCP plan."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "brief": {
                    "type": "string",
                    "description": "Mission text, one target per line. Ex: Azimut 55.3 distance 12.7 bunker",
                },
                "charge_mode": {
                    "type": "string",
                    "enum": ["min", "max"],
                    "description": "min = cheapest charge that reaches; max = 6 charges for shortest ToF",
                    "default": "max",
                },
                "ammo_pref": {
                    "type": "string",
                    "enum": ["auto", "he", "eco", "chem"],
                    "description": "auto picks best shell; he forces HE; eco uses LE; chem allows PHGN on infantry",
                    "default": "auto",
                },
            },
            "required": ["brief"],
        },
    },
    {
        "name": "iron_nest_firing_solution",
        "description": "Compute one Iron Nest firing solution from azimuth, range and target type.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "azimuth_deg": {"type": "number"},
                "distance_km": {"type": "number"},
                "target_type": {
                    "type": "string",
                    "description": "unknown, infantry, bunker, nest, artillery, vehicle, smoke, illum",
                    "default": "unknown",
                },
                "charge_mode": {"type": "string", "enum": ["min", "max"], "default": "max"},
                "ammo_pref": {"type": "string", "enum": ["auto", "he", "eco", "chem"], "default": "auto"},
            },
            "required": ["azimuth_deg", "distance_km"],
        },
    },
    {
        "name": "iron_nest_pick_shell",
        "description": "Recommend the best Iron Nest shell for a target class. Defaults to HE if unsure.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target_type": {"type": "string"},
                "clustered": {"type": "boolean", "default": False},
                "ammo_pref": {"type": "string", "enum": ["auto", "he", "eco", "chem"], "default": "auto"},
            },
            "required": ["target_type"],
        },
    },
    {
        "name": "iron_nest_ballistics",
        "description": "Elevation and time of flight for a range and powder charge (1-6).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "distance_km": {"type": "number"},
                "charges": {"type": "integer", "minimum": 1, "maximum": 6},
            },
            "required": ["distance_km"],
        },
    },
    {
        "name": "iron_nest_list_ammo",
        "description": "List all modeled Iron Nest shells with damage, blast radius in km, cost and roles.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "iron_nest_grid_shot",
        "description": (
            "Convert Iron Nest map cells A1-T10 with 100m subdivisions into XY meters, "
            "firing vector, distance and azimuth (0=North). Example nest B2 1:2 target C5 4:6."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "nest": {"type": "string", "description": "Canon cell, e.g. B2 1:2"},
                "target": {"type": "string", "description": "Target cell, e.g. C5 4:6 bunker"},
            },
            "required": ["nest", "target"],
        },
    },
    {
        "name": "iron_nest_grid_mission",
        "description": "Several grid targets from one Nest cell. Returns all firing solutions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "nest": {"type": "string"},
                "targets": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List like ['C5 4:6', 'D3 2:8 bunker']",
                },
            },
            "required": ["nest", "targets"],
        },
    },
    {
        "name": "iron_nest_triangulate",
        "description": (
            "Locate a target on the A1-T10 grid from mixed intel: two azimuths from two points, "
            "one azimuth plus one distance, or two distances (often two solutions)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["two_azimuths", "az_dist", "two_distances"]},
                "point_a": {"type": "string", "description": "Cell e.g. B2 1:2"},
                "point_b": {"type": "string"},
                "azimuth_a_deg": {"type": "number"},
                "azimuth_b_deg": {"type": "number"},
                "distance_a_km": {"type": "number"},
                "distance_b_km": {"type": "number"},
            },
            "required": ["mode", "point_a", "point_b"],
        },
    },
    {
        "name": "iron_nest_multi_kill",
        "description": (
            "From a briefing, propose shots that catch several targets in one blast radius, "
            "and dual-tube pairs that share nearly the same azimuth."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "brief": {"type": "string"},
                "ammo_pref": {"type": "string", "enum": ["auto", "he", "eco", "chem"], "default": "auto"},
            },
            "required": ["brief"],
        },
    },
]


def call_tool(name: str, arguments: dict[str, Any]) -> Any:
    if name == "iron_nest_solve_mission":
        return solve_mission(
            arguments["brief"],
            arguments.get("charge_mode", "max"),
            arguments.get("ammo_pref", "auto"),
        )
    if name == "iron_nest_firing_solution":
        kind = classify(arguments.get("target_type", "unknown"))
        brief = f"Azimut {arguments['azimuth_deg']} distance {arguments['distance_km']} {kind}"
        return solve_mission(
            brief,
            arguments.get("charge_mode", "max"),
            arguments.get("ammo_pref", "auto"),
        )
    if name == "iron_nest_pick_shell":
        kind = classify(arguments["target_type"])
        shell = pick_shell(kind, arguments.get("ammo_pref", "auto"), bool(arguments.get("clustered")))
        return {"kind": kind, "shell": shell, "stats": SHELLS[shell], "fallback": "HE"}
    if name == "iron_nest_ballistics":
        km = float(arguments["distance_km"])
        cmin = min_charge(km)
        if cmin is None:
            return {"error": "distance hors 0-30 km"}
        charges = int(arguments.get("charges") or cmin)
        charges = max(1, min(6, charges))
        return {
            "distance_km": km,
            "charge_min": cmin,
            "charge": charges,
            "elevation_deg": round(elevation(km, charges), 2),
            "tof_s": round(time_of_flight(km, charges), 1),
            "v_eff": SPEEDS[charges],
            "max_range_km": 5 * charges,
        }
    if name == "iron_nest_list_ammo":
        return SHELLS
    if name == "iron_nest_grid_shot":
        return grid_shot(arguments["nest"], arguments["target"])
    if name == "iron_nest_grid_mission":
        return {
            "shots": [grid_shot(arguments["nest"], t) for t in arguments.get("targets") or []]
        }
    if name == "iron_nest_triangulate":
        mode = arguments["mode"]
        a, b = arguments["point_a"], arguments["point_b"]
        if mode == "two_azimuths":
            return triangulate_two_azimuths(a, float(arguments["azimuth_a_deg"]), b, float(arguments["azimuth_b_deg"]))
        if mode == "az_dist":
            return triangulate_az_dist(a, float(arguments["azimuth_a_deg"]), b, float(arguments["distance_b_km"]))
        if mode == "two_distances":
            return triangulate_two_distances(a, float(arguments["distance_a_km"]), b, float(arguments["distance_b_km"]))
        raise ValueError("mode inconnu")
    if name == "iron_nest_multi_kill":
        targets = parse_brief(arguments["brief"])
        for i, t in enumerate(targets, 1):
            t["id"] = i
        return {
            "multi_kill": multi_kill_plans(targets, arguments.get("ammo_pref", "auto")),
            "dual_tube": dual_tube_pairs(targets),
        }
    raise ValueError(f"Unknown tool: {name}")


def ok(id_, result):
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def err(id_, code, message):
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def handle(msg: dict[str, Any]) -> dict[str, Any] | None:
    mid = msg.get("id")
    method = msg.get("method")
    params = msg.get("params") or {}

    if method == "initialize":
        return ok(
            mid,
            {
                "protocolVersion": PROTOCOL,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        )
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return ok(mid, {})
    if method == "tools/list":
        return ok(mid, {"tools": TOOLS})
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            result = call_tool(name, args)
            return ok(
                mid,
                {
                    "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}],
                    "structuredContent": result,
                },
            )
        except Exception as exc:  # noqa: BLE001
            return ok(
                mid,
                {
                    "content": [{"type": "text", "text": f"error: {exc}"}],
                    "isError": True,
                },
            )
    if mid is not None:
        return err(mid, -32601, f"Method not found: {method}")
    return None


def main() -> None:
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(msg, list):
            replies = [handle(m) for m in msg]
            for r in replies:
                if r is not None:
                    sys.stdout.write(json.dumps(r, ensure_ascii=False) + "\n")
            sys.stdout.flush()
            continue
        reply = handle(msg)
        if reply is not None:
            sys.stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
