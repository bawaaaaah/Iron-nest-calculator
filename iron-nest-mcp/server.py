#!/usr/bin/env python3
"""IRON NEST Fire Control — Model Context Protocol server (stdio JSON-RPC 2.0).

Aucune dépendance hors bibliothèque standard. La table des obus vient de
ammo.json (même dossier). La logique de calcul existe aussi en JS dans
../iron-nest-core.js pour les pages HTML : les deux implémentations sont
vérifiées contre les mêmes cas (../tests/vectors.json).
"""

from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path
from typing import Any

PROTOCOL = "2024-11-05"
SERVER_NAME = "iron-nest-fcs"
SERVER_VERSION = "1.1.0"

# --- Balistique (formules du jeu) ------------------------------------------

SPEEDS = {1: 0.21, 2: 0.31, 3: 0.41, 4: 0.50, 5: 0.60, 6: 0.70}  # v_eff km/s
KM_PER_CHARGE = 5.0
MAX_RANGE_KM = 30.0
CLUSTER_KM = 0.55  # deux cibles plus proches que ça = groupe
DUAL_TUBE_AZ_TOL = 2.0  # degrés
MAX_PLANS = 10

SHELLS: dict[str, dict[str, Any]] = json.loads(
    Path(__file__).with_name("ammo.json").read_text(encoding="utf-8")
)["shells"]

TARGET_KINDS = ("unknown", "infantry", "vehicle", "artillery", "bunker", "nest")
MISSION_KINDS = TARGET_KINDS + ("smoke", "illum")
HARD = {"bunker", "nest"}
PRIORITY = {"nest": 0, "bunker": 1, "artillery": 2, "vehicle": 3, "infantry": 4, "unknown": 5}
CHARGE_MODES = ("min", "max")
AMMO_PREFS = ("auto", "he", "eco", "chem")

# Obus candidats pour un tir groupé : uniquement des obus qui font des dégâts,
# et les chimiques seulement si ammo_pref == "chem".
AREA_SHELLS = {
    "auto": ["HCHE", "CLMN", "FLCH", "HE", "APHE", "EQKE", "THRM"],
    "eco": ["HCHE", "CLMN", "FLCH", "HE", "APHE", "EQKE", "THRM"],
    "he": ["HE", "HCHE"],
    "chem": ["PHGN", "CYAN", "HCHE", "HE"],
}


def min_charge(km: float) -> int | None:
    if not 0 < km <= MAX_RANGE_KM:
        return None
    return max(1, min(6, math.ceil(km / KM_PER_CHARGE - 1e-9)))


def range_error(km: float) -> str | None:
    if km <= 0:
        return "distance nulle"
    if km > MAX_RANGE_KM:
        return f"hors portée (> {MAX_RANGE_KM:g} km)"
    return None


def elevation(km: float, charges: int) -> float:
    return (12.0 * km) / charges


def time_of_flight(km: float, charges: int) -> float:
    return km / SPEEDS[charges]


def ballistics(km: float, charges: int | None = None) -> dict[str, Any]:
    err = range_error(km)
    if err:
        return {"distance_km": km, "error": err}
    cmin = min_charge(km)
    if charges is None:
        charges = cmin
    if charges not in SPEEDS:
        return {"distance_km": km, "charge_min": cmin, "error": "charge invalide (1 à 6)"}
    if charges < cmin:
        return {
            "distance_km": km,
            "charge_min": cmin,
            "charge": charges,
            "error": f"C{charges} porte à {KM_PER_CHARGE * charges:g} km max : il faut au moins C{cmin}",
        }
    return {
        "distance_km": km,
        "charge_min": cmin,
        "charge": charges,
        "elevation_deg": round(elevation(km, charges), 2),
        "tof_s": round(time_of_flight(km, charges), 1),
        "v_eff": SPEEDS[charges],
        "max_range_km": KM_PER_CHARGE * charges,
    }


# --- Classification / choix d'obus ------------------------------------------


def classify(text: str) -> str:
    t = (text or "").lower()
    if re.search(r"iron.?nest|nest enem|\bnest\b", t):
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


def normalize_kind(value: Any) -> str:
    v = str(value or "").strip().lower()
    return v if v in MISSION_KINDS else classify(v)


def pick_shell(kind: str, pref: str, clustered: bool) -> str:
    if pref == "he":
        return "HE"
    if kind in HARD:
        return "APHE" if clustered else "AP"
    if kind == "infantry":
        return "PHGN" if pref == "chem" else "HCHE"
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


# --- Lecture du briefing ------------------------------------------------------

_NUM = r"(\d+(?:[.,]\d+)?)"
# Entre azimut et distance il faut un vrai séparateur : sans ça « 12 » serait lu 1 / 2.
_SEP = r"(?:\s*(?:°|deg)?\s*(?:[,;/\-]|dist(?:ance)?|range)\s*|\s*(?:°|deg)\s*|\s+)"
LINE_RE = re.compile(
    r"(?:^|[^\w.,])"
    r"(?:(?:azim(?:ut|uth|ute)?|az|bearing)\s*[:=]?\s*)?"
    + _NUM
    + _SEP
    + _NUM
    + r"(?:\s*(km|m)\b)?\s*(.*)$",
    re.I | re.A,
)


def _to_float(s: str) -> float:
    return float(s.replace(",", "."))


def parse_brief(text: str) -> list[dict[str, Any]]:
    """Une cible par ligne : « azimut distance [km|m] [libellé] ».

    Sans unité : ≤ 30 → km, ≥ 100 → mètres, entre les deux → ambigu (erreur).
    Les lignes invalides (azimut > 360, hors portée) sont gardées avec « error ».
    """
    targets: list[dict[str, Any]] = []
    for line in (text or "").splitlines():
        m = LINE_RE.search(line)
        if not m:
            continue
        az = _to_float(m.group(1))
        dist = _to_float(m.group(2))
        unit = (m.group(3) or "").lower()
        t: dict[str, Any] = {"az": az, "km": dist, "label": m.group(4).strip(), "kind": classify(line)}
        if unit == "m":
            t["km"] = dist / 1000.0
        elif not unit and dist > MAX_RANGE_KM:
            if dist >= 100:
                t["km"] = dist / 1000.0
            else:
                t["error"] = "distance ambiguë : préciser km ou m"
        if az > 360:
            t["error"] = "azimut hors 0–360°"
        else:
            t["az"] = az % 360
        if "error" not in t:
            err = range_error(t["km"])
            if err:
                t["error"] = err
        targets.append(t)
    return targets


# --- Géométrie polaire (Nest au centre) --------------------------------------


def xy(az: float, km: float) -> tuple[float, float]:
    r = math.radians(az)
    return km * math.sin(r), km * math.cos(r)


def polar(x: float, y: float) -> tuple[float, float]:
    km = math.hypot(x, y)
    az = (math.degrees(math.atan2(x, y)) + 360) % 360
    return az, km


def sep_km(az1: float, d1: float, az2: float, d2: float) -> float:
    x1, y1 = xy(az1, d1)
    x2, y2 = xy(az2, d2)
    return math.hypot(x1 - x2, y1 - y2)


def cluster_ids(targets: list[dict[str, Any]]) -> set[int]:
    ids: set[int] = set()
    for i in range(len(targets)):
        for j in range(i + 1, len(targets)):
            a, b = targets[i], targets[j]
            if sep_km(a["az"], a["km"], b["az"], b["km"]) <= CLUSTER_KM:
                ids.update((a["id"], b["id"]))
    return ids


def covered(ax: float, ay: float, targets: list[dict[str, Any]], radius: float, splash_hard: bool) -> list[int]:
    hit = []
    for t in targets:
        tx, ty = xy(t["az"], t["km"])
        d = math.hypot(tx - ax, ty - ay)
        if d > radius + 1e-9:
            continue
        # bunker / Nest : seul un obus pénétrant les touche par le souffle
        if t["kind"] in HARD and not splash_hard and d > 0.02:
            continue
        hit.append(t["id"])
    return hit


def _cost_key(cost: Any) -> float:
    return math.inf if cost is None else cost


def multi_kill_plans(targets: list[dict[str, Any]], ammo_pref: str = "auto") -> list[dict[str, Any]]:
    targets = [t for t in targets if not t.get("error")]
    if len(targets) < 2:
        return []
    shells = [s for s in AREA_SHELLS.get(ammo_pref, AREA_SHELLS["auto"]) if SHELLS[s]["dmg"] > 0]
    candidates: list[tuple[float, float, str]] = []
    for t in targets:
        candidates.append((*xy(t["az"], t["km"]), f"sur T{t['id']}"))
    for i in range(len(targets)):
        for j in range(i + 1, len(targets)):
            x1, y1 = xy(targets[i]["az"], targets[i]["km"])
            x2, y2 = xy(targets[j]["az"], targets[j]["km"])
            candidates.append(((x1 + x2) / 2, (y1 + y2) / 2, f"milieu T{targets[i]['id']}-T{targets[j]['id']}"))
    plans = []
    seen: set[tuple] = set()
    for ax, ay, label in candidates:
        az, km = polar(ax, ay)
        cmin = min_charge(km)
        if cmin is None:
            continue
        for shell in shells:
            st = SHELLS[shell]
            ids = covered(ax, ay, targets, st["blast_km"], st["dmg"] >= 2)
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
                    "blast_km": st["blast_km"],
                    "confirmed": st["confirmed"],
                    "covers": ids,
                    "n": len(ids),
                    "charge_min": cmin,
                    "elevation_min_deg": round(elevation(km, cmin), 2),
                    "tof_min_s": round(time_of_flight(km, cmin), 1),
                    "charge_max": 6,
                    "elevation_max_deg": round(elevation(km, 6), 2),
                    "tof_max_s": round(time_of_flight(km, 6), 1),
                    "cost": st["cost"],
                    "saved_shots": len(ids) - 1,
                }
            )
    plans.sort(key=lambda p: (-p["n"], not p["confirmed"], _cost_key(p["cost"]), p["aim_km"]))
    return plans[:MAX_PLANS]


def dual_tube_pairs(
    targets: list[dict[str, Any]], charge_mode: str = "max", az_tol: float = DUAL_TUBE_AZ_TOL
) -> list[dict[str, Any]]:
    targets = [t for t in targets if not t.get("error")]

    def side(t: dict[str, Any]) -> dict[str, Any]:
        c = 6 if charge_mode == "max" else min_charge(t["km"])
        return {"id": t["id"], "az": t["az"], "km": t["km"], "charge": c, "elevation_deg": round(elevation(t["km"], c), 2)}

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
                    "left": side(targets[i]),
                    "right": side(targets[j]),
                }
            )
    return pairs


def solve_targets(targets: list[dict[str, Any]], charge_mode: str = "max", ammo_pref: str = "auto") -> dict[str, Any]:
    if charge_mode not in CHARGE_MODES:
        raise ValueError(f"charge_mode invalide : {charge_mode!r} (min ou max)")
    if ammo_pref not in AMMO_PREFS:
        raise ValueError(f"ammo_pref invalide : {ammo_pref!r} ({', '.join(AMMO_PREFS)})")
    for i, t in enumerate(targets, 1):
        t["id"] = i
    valid = [t for t in targets if not t.get("error")]
    clustered = cluster_ids(valid)

    solutions = []
    for t in targets:
        if t.get("error"):
            solutions.append(dict(t))
            continue
        cmin = min_charge(t["km"])
        charges = 6 if charge_mode == "max" else cmin
        shell = pick_shell(t["kind"], ammo_pref, t["id"] in clustered)
        solutions.append(
            {
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
            }
        )

    ordered = sorted(solutions, key=lambda s: (bool(s.get("error")), PRIORITY.get(s["kind"], 6), s["km"]))
    # tubes alternés dans l'ordre de tir : un tube recharge pendant que l'autre tire
    n = 0
    for s in ordered:
        if not s.get("error"):
            s["tube"] = "GAUCHE" if n % 2 == 0 else "DROITE"
            n += 1

    fired = [s for s in solutions if not s.get("error")]
    cost = sum(SHELLS[s["shell"]]["cost"] or 0 for s in fired)
    unknown_cost = sum(1 for s in fired if SHELLS[s["shell"]]["cost"] is None)
    mk = multi_kill_plans(valid, ammo_pref)
    dual = dual_tube_pairs(valid, charge_mode)

    lines = [
        "IRON NEST MCP / FIRE MISSION",
        f"mode={charge_mode} pref={ammo_pref} rc={cost}"
        + (f" (+{unknown_cost} obus au coût inconnu)" if unknown_cost else "")
        + f" n={len(solutions)}",
        "",
    ]
    for s in ordered:
        if s.get("error"):
            lines.append(f"T{s['id']} ERREUR {s['error']} (AZ {s['az']:g} DIST {s['km']:g})")
            continue
        lines.append(
            f"T{s['id']} {s['kind'].upper()} AZ {s['az']:.1f} DIST {s['km']:.2f}km "
            f"TUBE {s['tube']} {s['shell']} C{s['charge']} ELEV {s['elevation_deg']:.2f} "
            f"ToF {s['tof_s']:.1f}s"
        )
    if mk:
        lines += ["", "TIRS GROUPÉS (1 obus, N cibles dans le blast)"]
        for p in mk[:5]:
            lines.append(
                f"  {p['shell']} blast {p['blast_km']}km @ AZ {p['aim_az']:.1f} {p['aim_km']:.2f}km "
                f"couvre T{',T'.join(map(str, p['covers']))}  économise {p['saved_shots']} tir(s)"
            )
    if dual:
        lines += ["", "SALVES DOUBLE TUBE (azimuts proches)"]
        for p in dual:
            lines.append(
                f"  T{p['left']['id']} GAUCHE C{p['left']['charge']} {p['left']['elevation_deg']:.2f}° + "
                f"T{p['right']['id']} DROITE C{p['right']['charge']} {p['right']['elevation_deg']:.2f}°  "
                f"Δaz {p['delta_az_deg']}°"
            )
    return {
        "targets": len(solutions),
        "requisition_cost": cost,
        "unknown_cost_shells": unknown_cost,
        "solutions": solutions,
        "fire_order": [s["id"] for s in ordered if not s.get("error")],
        "multi_kill": mk,
        "dual_tube": dual,
        "mcp_text": "\n".join(lines),
    }


def solve_mission(brief: str, charge_mode: str = "max", ammo_pref: str = "auto") -> dict[str, Any]:
    return solve_targets(parse_brief(brief), charge_mode, ammo_pref)


# --- Grille A1–T10 ------------------------------------------------------------
# X vers l'Est, Y vers le Nord, en mètres. Colonne A = X 0–1000, ligne 1 = Y 0–1000
# (sud de la carte). Subdivision « sx:sy » = centaines de mètres, au 0.1 près (10 m).

COLS = "ABCDEFGHIJKLMNOPQRST"
GRID_W_M = 20000
GRID_H_M = 10000
EDGE_TOL_M = 0.5
_SUB = r"(\d+(?:\.\d+)?)"
GRID_RE = re.compile(
    r"(?:^|[^A-Za-z0-9])([A-Ta-t])\s*(10|[1-9])\s*[ ,]?\s*" + _SUB + r"\s*[:/,]\s*" + _SUB,
    re.A,
)


def _round_sub(v: float) -> float:
    """Arrondi au 0.1 (demi vers le haut, comme Math.round en JS)."""
    return math.floor(v * 10 + 0.5) / 10


def _fmt_sub(v: float) -> str:
    return f"{v:g}"


def parse_cell(text: str) -> dict[str, Any] | None:
    m = GRID_RE.search(text or "")
    if not m:
        return None
    col = COLS.find(m.group(1).upper())
    row = int(m.group(2))
    sx, sy = _round_sub(float(m.group(3))), _round_sub(float(m.group(4)))
    if col < 0 or not (1 <= row <= 10) or not (0 <= sx <= 10) or not (0 <= sy <= 10):
        return None
    return {
        "token": f"{COLS[col]}{row} {_fmt_sub(sx)}:{_fmt_sub(sy)}",
        "col": col,
        "row": row,
        "sx": sx,
        "sy": sy,
        "x_m": round(col * 1000 + sx * 100, 1),
        "y_m": round((row - 1) * 1000 + sy * 100, 1),
    }


def cell_of(x: float, y: float) -> dict[str, Any]:
    tol = EDGE_TOL_M  # bruit de calcul flottant sur un bord de carte
    if not (-tol <= x <= GRID_W_M + tol and -tol <= y <= GRID_H_M + tol):
        return {"token": "hors carte", "x_m": round(x, 1), "y_m": round(y, 1)}
    x, y = min(max(x, 0.0), GRID_W_M), min(max(y, 0.0), GRID_H_M)
    col = min(19, int(x // 1000))
    row = min(10, int(y // 1000) + 1)
    sx = math.floor((x - col * 1000) / 10 + 0.5) / 10
    sy = math.floor((y - (row - 1) * 1000) / 10 + 0.5) / 10
    # 10 = bord de case : on passe à la case suivante, sauf au bord de la carte
    if sx >= 10 and col < 19:
        col, sx = col + 1, 0.0
    if sy >= 10 and row < 10:
        row, sy = row + 1, 0.0
    return {
        "token": f"{COLS[col]}{row} {_fmt_sub(sx)}:{_fmt_sub(sy)}",
        "x_m": round(x, 1),
        "y_m": round(y, 1),
        "col": col,
        "row": row,
        "sx": sx,
        "sy": sy,
    }


def _dir(az_deg: float) -> tuple[float, float]:
    r = math.radians(az_deg)
    return math.sin(r), math.cos(r)


def _cells(a: str, b: str) -> tuple[dict[str, Any], dict[str, Any]]:
    A, B = parse_cell(a), parse_cell(b)
    if not A:
        raise ValueError(f"point A invalide : {a!r} (ex. B2 1:2)")
    if not B:
        raise ValueError(f"point B invalide : {b!r} (ex. C5 4:6)")
    return A, B


def triangulate_two_azimuths(a: str, az_a: float, b: str, az_b: float) -> dict[str, Any]:
    A, B = _cells(a, b)
    if A["x_m"] == B["x_m"] and A["y_m"] == B["y_m"]:
        return {"error": "deux azimuts depuis le même point ne localisent pas une cible", "points": []}
    adx, ady = _dir(az_a)
    bdx, bdy = _dir(az_b)
    den = adx * bdy - ady * bdx
    if abs(den) < 1e-9:
        return {"error": "rayons parallèles", "points": []}
    dx, dy = B["x_m"] - A["x_m"], B["y_m"] - A["y_m"]
    t = (dx * bdy - dy * bdx) / den
    s = (dx * ady - dy * adx) / den
    behind = t <= 0 or s <= 0
    return {
        "mode": "2_azimuths",
        "behind_a_ray": t <= 0,
        "behind_b_ray": s <= 0,
        "note": "intersection derrière un rayon" if behind else None,
        "points": [cell_of(A["x_m"] + t * adx, A["y_m"] + t * ady)],
    }


def triangulate_az_dist(a: str, az_a: float, b: str, dist_km: float) -> dict[str, Any]:
    A, B = _cells(a, b)
    dx, dy = _dir(az_a)
    fx, fy = A["x_m"] - B["x_m"], A["y_m"] - B["y_m"]
    r = dist_km * 1000
    qb = 2 * (fx * dx + fy * dy)
    qc = fx * fx + fy * fy - r * r
    disc = qb * qb - 4 * qc
    if disc < -1e-6:
        return {"error": "pas d'intersection rayon / cercle", "points": []}
    root = math.sqrt(max(0.0, disc))
    roots = [(-qb - root) / 2] if root < 1e-3 else [(-qb - root) / 2, (-qb + root) / 2]
    ts = [t for t in roots if t > 1]
    if not ts:
        return {"error": "intersection derrière le rayon", "points": []}
    note = "tangence" if root < 1e-3 else ("2 solutions" if len(ts) == 2 else None)
    return {
        "mode": "azimuth_plus_distance",
        "n": len(ts),
        "points": [cell_of(A["x_m"] + t * dx, A["y_m"] + t * dy) for t in ts],
        "note": note,
    }


def triangulate_two_distances(a: str, da_km: float, b: str, db_km: float) -> dict[str, Any]:
    A, B = _cells(a, b)
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
    if h < 1e-4:
        return {"mode": "2_distances", "n": 1, "note": "tangence", "points": [cell_of(mx, my)]}
    return {
        "mode": "2_distances",
        "n": 2,
        "note": "2 solutions — départager avec un 3e indice",
        "points": [cell_of(mx + px, my + py), cell_of(mx - px, my - py)],
    }


def grid_shot(nest_s: str, target_s: str, charge_mode: str = "max") -> dict[str, Any]:
    nest, tgt = parse_cell(nest_s), parse_cell(target_s)
    if not nest or not tgt:
        raise ValueError("Coordonnée invalide. Exemple : B2 1:2 et C5 4:6")
    dx = tgt["x_m"] - nest["x_m"]
    dy = tgt["y_m"] - nest["y_m"]
    km = math.hypot(dx, dy) / 1000.0
    az = (math.degrees(math.atan2(dx, dy)) + 360) % 360
    out: dict[str, Any] = {
        "nest": nest,
        "target": tgt,
        "vector_m": {"x": round(dx, 1), "y": round(dy, 1)},
        "distance_m": round(km * 1000, 1),
        "distance_km": round(km, 3),
        "azimuth_deg": round(az, 1),
        "convention": "0° Nord (+Y), 90° Est (+X), 180° Sud, 270° Ouest",
    }
    err = range_error(km)
    if err:
        out["error"] = err
        return out
    cmin = min_charge(km)
    c = 6 if charge_mode == "max" else cmin
    out.update(
        {
            "charge_min": cmin,
            "elevation_min_deg": round(elevation(km, cmin), 2),
            "tof_min_s": round(time_of_flight(km, cmin), 1),
            "charge": c,
            "elevation_deg": round(elevation(km, c), 2),
            "tof_s": round(time_of_flight(km, c), 1),
        }
    )
    return out


# --- Outils MCP -------------------------------------------------------------

_KINDS_DOC = ", ".join(MISSION_KINDS)

TOOLS = [
    {
        "name": "iron_nest_solve_mission",
        "description": (
            "Parse a free-text Iron Nest briefing with multiple targets "
            "(azimuth, distance, optional type) and return firing solutions: "
            "charge, elevation, time of flight, recommended shell, gun tube, MCP plan. "
            "Distances: km by default; add 'm' for metres (unitless values >= 100 are metres)."
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
                    "enum": list(CHARGE_MODES),
                    "description": "min = cheapest charge that reaches; max = 6 charges for shortest ToF",
                    "default": "max",
                },
                "ammo_pref": {
                    "type": "string",
                    "enum": list(AMMO_PREFS),
                    "description": "auto picks best shell; he forces HE; eco uses LE; chem allows chemical shells",
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
                "azimuth_deg": {"type": "number", "description": "0 = North, clockwise; negative values are wrapped"},
                "distance_km": {"type": "number", "exclusiveMinimum": 0, "maximum": MAX_RANGE_KM},
                "target_type": {
                    "type": "string",
                    "description": f"{_KINDS_DOC} (free text is classified)",
                    "default": "unknown",
                },
                "charge_mode": {"type": "string", "enum": list(CHARGE_MODES), "default": "max"},
                "ammo_pref": {"type": "string", "enum": list(AMMO_PREFS), "default": "auto"},
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
                "target_type": {"type": "string", "description": f"{_KINDS_DOC} (free text is classified)"},
                "clustered": {"type": "boolean", "default": False},
                "ammo_pref": {"type": "string", "enum": list(AMMO_PREFS), "default": "auto"},
            },
            "required": ["target_type"],
        },
    },
    {
        "name": "iron_nest_ballistics",
        "description": (
            "Elevation and time of flight for a range and powder charge (1-6). "
            "Returns an error if the charge cannot reach the range (max range = 5 km x charges)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "distance_km": {"type": "number", "exclusiveMinimum": 0, "maximum": MAX_RANGE_KM},
                "charges": {"type": "integer", "minimum": 1, "maximum": 6},
            },
            "required": ["distance_km"],
        },
    },
    {
        "name": "iron_nest_list_ammo",
        "description": (
            "List all modeled Iron Nest shells: dmg (0 none, 1 damage, 2 penetrating), blast_km, "
            "cost in rc (null = unknown), confirmed (wiki) or hypothesis, effectiveness per target type."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "iron_nest_grid_shot",
        "description": (
            "Convert Iron Nest map cells A1-T10 with sub-cell coordinates (0-10, 0.1 = 10 m) into XY metres, "
            "firing vector, distance, azimuth (0=North) and charges. Example nest B2 1:2 target C5 4.5:6."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "nest": {"type": "string", "description": "Gun cell, e.g. B2 1:2"},
                "target": {"type": "string", "description": "Target cell, e.g. C5 4:6"},
                "charge_mode": {"type": "string", "enum": list(CHARGE_MODES), "default": "max"},
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
                    "description": "List like ['C5 4:6', 'D3 2.5:8']",
                },
                "charge_mode": {"type": "string", "enum": list(CHARGE_MODES), "default": "max"},
            },
            "required": ["nest", "targets"],
        },
    },
    {
        "name": "iron_nest_triangulate",
        "description": (
            "Locate a target on the A1-T10 grid from mixed intel: two azimuths from two points, "
            "one azimuth from A plus one distance from B, or two distances (often two solutions)."
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
                "charge_mode": {"type": "string", "enum": list(CHARGE_MODES), "default": "max"},
                "ammo_pref": {"type": "string", "enum": list(AMMO_PREFS), "default": "auto"},
            },
            "required": ["brief"],
        },
    },
]


def _num(args: dict[str, Any], key: str) -> float:
    if args.get(key) is None:
        raise ValueError(f"paramètre manquant : {key}")
    v = args[key]
    try:
        if isinstance(v, bool):
            raise TypeError
        f = float(v.replace(",", ".")) if isinstance(v, str) else float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{key} doit être un nombre") from None
    if not math.isfinite(f):
        raise ValueError(f"{key} doit être un nombre fini")
    return f


def _str(args: dict[str, Any], key: str, default: str | None = None, choices: tuple[str, ...] | None = None) -> str:
    v = args.get(key, default)
    if v is None:
        raise ValueError(f"paramètre manquant : {key}")
    v = str(v)
    if choices and v not in choices:
        raise ValueError(f"{key} invalide : {v!r} ({', '.join(choices)})")
    return v


def _charges(args: dict[str, Any]) -> int | None:
    if args.get("charges") is None:
        return None
    c = _num(args, "charges")
    if not c.is_integer():
        raise ValueError("charges doit être un entier de 1 à 6")
    return int(c)


def call_tool(name: str, args: dict[str, Any]) -> Any:
    mode = _str(args, "charge_mode", "max", CHARGE_MODES)
    pref = _str(args, "ammo_pref", "auto", AMMO_PREFS)
    if name == "iron_nest_solve_mission":
        return solve_mission(_str(args, "brief"), mode, pref)
    if name == "iron_nest_firing_solution":
        target_type = _str(args, "target_type", "unknown")
        t: dict[str, Any] = {
            "az": _num(args, "azimuth_deg") % 360,
            "km": _num(args, "distance_km"),
            "label": target_type,
            "kind": normalize_kind(target_type),
        }
        err = range_error(t["km"])
        if err:
            t["error"] = err
        return solve_targets([t], mode, pref)
    if name == "iron_nest_pick_shell":
        kind = normalize_kind(_str(args, "target_type"))
        shell = pick_shell(kind, pref, bool(args.get("clustered")))
        return {"kind": kind, "shell": shell, "stats": SHELLS[shell], "fallback": "HE"}
    if name == "iron_nest_ballistics":
        return ballistics(_num(args, "distance_km"), _charges(args))
    if name == "iron_nest_list_ammo":
        return SHELLS
    if name == "iron_nest_grid_shot":
        return grid_shot(_str(args, "nest"), _str(args, "target"), mode)
    if name == "iron_nest_grid_mission":
        targets = args.get("targets") or []
        if not isinstance(targets, list):
            raise ValueError("targets doit être une liste de cases")
        nest = _str(args, "nest")
        return {"shots": [grid_shot(nest, str(t), mode) for t in targets]}
    if name == "iron_nest_triangulate":
        tri = _str(args, "mode", choices=("two_azimuths", "az_dist", "two_distances"))
        a, b = _str(args, "point_a"), _str(args, "point_b")
        if tri == "two_azimuths":
            return triangulate_two_azimuths(a, _num(args, "azimuth_a_deg"), b, _num(args, "azimuth_b_deg"))
        if tri == "az_dist":
            return triangulate_az_dist(a, _num(args, "azimuth_a_deg"), b, _num(args, "distance_b_km"))
        return triangulate_two_distances(a, _num(args, "distance_a_km"), b, _num(args, "distance_b_km"))
    if name == "iron_nest_multi_kill":
        targets = parse_brief(_str(args, "brief"))
        for i, t in enumerate(targets, 1):
            t["id"] = i
        return {"multi_kill": multi_kill_plans(targets, pref), "dual_tube": dual_tube_pairs(targets, mode)}
    raise ValueError(f"Unknown tool: {name}")


# --- JSON-RPC ---------------------------------------------------------------


def ok(id_: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def err(id_: Any, code: int, message: str) -> dict[str, Any]:
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
    if method == "ping":
        return ok(mid, {})
    if method == "tools/list":
        return ok(mid, {"tools": TOOLS})
    if method == "tools/call":
        if not isinstance(params, dict):
            return err(mid, -32602, "params doit être un objet")
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            return err(mid, -32602, "arguments doit être un objet")
        try:
            result = call_tool(str(params.get("name")), args)
        except Exception as exc:  # noqa: BLE001 — renvoyé au client comme erreur d'outil
            return ok(mid, {"content": [{"type": "text", "text": f"error: {exc}"}], "isError": True})
        return ok(
            mid,
            {
                "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}],
                "structuredContent": result,
            },
        )
    if mid is not None and method is not None:
        return err(mid, -32601, f"Method not found: {method}")
    return None  # notification, ou réponse du client


def safe_handle(msg: Any) -> dict[str, Any] | None:
    if not isinstance(msg, dict):
        return err(None, -32600, "Invalid Request")
    try:
        return handle(msg)
    except Exception as exc:  # noqa: BLE001 — ne jamais tuer le serveur sur un message
        mid = msg.get("id")
        return err(mid, -32603, f"Internal error: {exc}") if mid is not None else None


def process_line(raw: str) -> Any:
    """Traite une ligne reçue ; renvoie la réponse à écrire (objet, liste) ou None."""
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        return err(None, -32700, "Parse error")
    if isinstance(msg, list):
        if not msg:
            return err(None, -32600, "Invalid Request")
        replies = [r for r in (safe_handle(m) for m in msg) if r is not None]
        return replies or None
    return safe_handle(msg)


def main() -> None:
    # Le transport stdio MCP est en UTF-8 ; sous Windows le défaut d'un pipe est cp1252.
    for stream in (sys.stdin, sys.stdout):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        reply = process_line(raw)
        if reply is not None:
            sys.stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
