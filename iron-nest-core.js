/*
 * IRON NEST — cœur de calcul partagé.
 * Chargé par iron-nest-fcs.html et iron-nest-grid.html (window.IronNest) et par les
 * tests Node (module.exports). Même logique que iron-nest-mcp/server.py : les deux
 * implémentations sont vérifiées contre tests/vectors.json.
 */
(function (root, factory) {
  "use strict";
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.IronNest = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  // Copie de iron-nest-mcp/ammo.json (source de vérité) — tests/core.test.js vérifie l'égalité.
  const AMMO = {
    HE: {"dmg": 1, "blast_km": 0.27, "cost": 3, "confirmed": true, "chem": false, "note": "HE standard — infanterie, artillerie, mécanisé", "vs": {"infantry": "ok", "vehicle": "ok", "artillery": "ok", "bunker": "weak", "nest": "weak"}},
    HCHE: {"dmg": 1, "blast_km": 0.63, "cost": 5, "confirmed": true, "chem": false, "note": "Haut volume — clusters / formations serrées", "vs": {"infantry": "ok", "vehicle": "ok", "artillery": "ok", "bunker": "weak", "nest": "weak"}},
    AP: {"dmg": 2, "blast_km": 0.14, "cost": 3, "confirmed": true, "chem": false, "note": "Pénétration — bunkers, blindés, positions dures", "vs": {"infantry": "weak", "vehicle": "ok", "artillery": "ok", "bunker": "ok", "nest": "ok"}},
    STAR: {"dmg": 0, "blast_km": 12.74, "cost": 1, "confirmed": true, "chem": false, "note": "S.T.A.R. illumination — 0 dégât, révèle la carte (nuit / brouillard)", "vs": {"infantry": "no", "vehicle": "no", "artillery": "no", "bunker": "no", "nest": "no"}},
    SMK: {"dmg": 0, "blast_km": 1.86, "cost": 1, "confirmed": true, "chem": false, "note": "SMOKE — écran / repli allié, 0 dégât", "vs": {"infantry": "no", "vehicle": "no", "artillery": "no", "bunker": "no", "nest": "no"}},
    PHGN: {"dmg": 1, "blast_km": 1.85, "cost": null, "confirmed": false, "chem": true, "note": "PHOSGENE — gaz toxique (infanterie), infrastructures intactes — coût non confirmé", "vs": {"infantry": "ok", "vehicle": "weak", "artillery": "weak", "bunker": "no", "nest": "no"}},
    TGAS: {"dmg": 0, "blast_km": 1.86, "cost": null, "confirmed": false, "chem": false, "note": "TEAR GAS — non létal, révèle les cachés — coût non confirmé", "vs": {"infantry": "no", "vehicle": "no", "artillery": "no", "bunker": "no", "nest": "no"}},
    APHE: {"dmg": 2, "blast_km": 0.25, "cost": null, "confirmed": false, "chem": false, "note": "AP + souffle (hypothèse)", "vs": {"infantry": "ok", "vehicle": "ok", "artillery": "ok", "bunker": "ok", "nest": "ok"}},
    EQKE: {"dmg": 2, "blast_km": 0.55, "cost": null, "confirmed": false, "chem": false, "note": "Burst souterrain retardé (hypothèse)", "vs": {"infantry": "weak", "vehicle": "weak", "artillery": "ok", "bunker": "ok", "nest": "ok"}},
    CLMN: {"dmg": 1, "blast_km": 0.5, "cost": null, "confirmed": false, "chem": false, "note": "Sous-munitions (hypothèse)", "vs": {"infantry": "ok", "vehicle": "ok", "artillery": "ok", "bunker": "weak", "nest": "weak"}},
    FLCH: {"dmg": 1, "blast_km": 0.62, "cost": null, "confirmed": false, "chem": false, "note": "Fléchettes — infanterie à découvert (hypothèse)", "vs": {"infantry": "ok", "vehicle": "weak", "artillery": "weak", "bunker": "no", "nest": "no"}},
    CYAN: {"dmg": 1, "blast_km": 0.75, "cost": null, "confirmed": false, "chem": true, "note": "Cyanogène — pas contre les fortifiés (hypothèse)", "vs": {"infantry": "ok", "vehicle": "weak", "artillery": "weak", "bunker": "no", "nest": "no"}},
    INCN: {"dmg": 1, "blast_km": 0.25, "cost": null, "confirmed": false, "chem": false, "note": "Incendiaire (hypothèse)", "vs": {"infantry": "ok", "vehicle": "ok", "artillery": "ok", "bunker": "no", "nest": "no"}},
    THRM: {"dmg": 1, "blast_km": 0.35, "cost": null, "confirmed": false, "chem": false, "note": "Thermite (hypothèse)", "vs": {"infantry": "ok", "vehicle": "ok", "artillery": "ok", "bunker": "weak", "nest": "weak"}},
    WP: {"dmg": 0, "blast_km": 0.75, "cost": null, "confirmed": false, "chem": false, "note": "Phosphore blanc — écran / harcèlement, 0 dégât modélisé (hypothèse)", "vs": {"infantry": "no", "vehicle": "no", "artillery": "no", "bunker": "no", "nest": "no"}},
    LE: {"dmg": 1, "blast_km": 0.15, "cost": null, "confirmed": false, "chem": false, "note": "HE léger / économique (hypothèse)", "vs": {"infantry": "ok", "vehicle": "weak", "artillery": "weak", "bunker": "no", "nest": "no"}}
  };

  // --- Balistique (formules du jeu) -----------------------------------------
  const SPEEDS = {1: 0.21, 2: 0.31, 3: 0.41, 4: 0.50, 5: 0.60, 6: 0.70}; // v_eff km/s
  const KM_PER_CHARGE = 5;
  const MAX_RANGE_KM = 30;
  const CLUSTER_KM = 0.55;
  const DUAL_TUBE_AZ_TOL = 2;
  const MAX_PLANS = 10;

  const TARGET_KINDS = ["unknown", "infantry", "vehicle", "artillery", "bunker", "nest"];
  const MISSION_KINDS = TARGET_KINDS.concat(["smoke", "illum"]);
  const HARD = new Set(["bunker", "nest"]);
  const PRIORITY = {nest: 0, bunker: 1, artillery: 2, vehicle: 3, infantry: 4, unknown: 5};
  // Tirs groupés : uniquement des obus qui font des dégâts, chimiques seulement en mode "chem".
  const AREA_SHELLS = {
    auto: ["HCHE", "CLMN", "FLCH", "HE", "APHE", "EQKE", "THRM"],
    eco: ["HCHE", "CLMN", "FLCH", "HE", "APHE", "EQKE", "THRM"],
    he: ["HE", "HCHE"],
    chem: ["PHGN", "CYAN", "HCHE", "HE"]
  };

  function minCharge(km) {
    if (!(km > 0 && km <= MAX_RANGE_KM)) return null;
    return Math.max(1, Math.min(6, Math.ceil(km / KM_PER_CHARGE - 1e-9)));
  }
  function rangeError(km) {
    if (!(km > 0)) return "distance nulle";
    if (km > MAX_RANGE_KM) return "hors portée (> " + MAX_RANGE_KM + " km)";
    return null;
  }
  const elevation = (km, c) => 12 * km / c;
  const timeOfFlight = (km, c) => km / SPEEDS[c];

  function ballistics(km, charges) {
    const err = rangeError(km);
    if (err) return {km, error: err};
    const cMin = minCharge(km);
    const c = charges == null ? cMin : charges;
    if (!SPEEDS[c]) return {km, chargeMin: cMin, error: "charge invalide (1 à 6)"};
    if (c < cMin) return {km, chargeMin: cMin, charge: c, error: "C" + c + " porte à " + KM_PER_CHARGE * c + " km max : il faut au moins C" + cMin};
    return {km, chargeMin: cMin, charge: c, elev: elevation(km, c), tof: timeOfFlight(km, c), maxRangeKm: KM_PER_CHARGE * c};
  }

  // --- Classification / choix d'obus -----------------------------------------
  function classify(text) {
    const t = String(text || "").toLowerCase();
    if (/iron.?nest|nest enem|\bnest\b/.test(t)) return "nest";
    if (/bunker|fort|armor|armour|hard|palace/.test(t)) return "bunker";
    if (/infant|troop|squad|fantassin/.test(t)) return "infantry";
    if (/artill|battery|fdc|canon/.test(t)) return "artillery";
    if (/train|boat|ship|convoi|vehicle|tank|mech/.test(t)) return "vehicle";
    if (/smoke|fum/.test(t)) return "smoke";
    if (/illum|star|night|nuit/.test(t)) return "illum";
    return "unknown";
  }
  function normalizeKind(value) {
    const v = String(value == null ? "" : value).trim().toLowerCase();
    return MISSION_KINDS.includes(v) ? v : classify(v);
  }
  function pickShell(kind, pref, clustered) {
    if (pref === "he") return "HE";
    if (HARD.has(kind)) return clustered ? "APHE" : "AP";
    if (kind === "infantry") return pref === "chem" ? "PHGN" : "HCHE";
    if (kind === "artillery") return clustered ? "HCHE" : "HE";
    if (kind === "vehicle") return "HE";
    if (kind === "smoke") return "SMK";
    if (kind === "illum") return "STAR";
    if (pref === "eco") return "LE";
    if (clustered) return "HCHE";
    return "HE";
  }
  function effectiveness(shellName, kind) {
    const sh = AMMO[shellName] || AMMO.HE;
    const k = kind || "unknown";
    if (!(sh.dmg > 0)) {
      const detail = shellName === "STAR" ? "STAR = illumination / révélation carte, 0 dégât (SAFE amis)"
        : (shellName === "SMK" || shellName === "TGAS") ? "Écran / non létal — 0 dégât, SAFE amis (permet le déplacement)"
        : "Pas de dégâts";
      return {ok: false, level: "no", tag: "NO DMG", detail};
    }
    const level = k === "unknown" ? "ok" : (sh.vs[k] || "ok");
    if (level === "ok") return {ok: true, level, tag: "OK", detail: "Obus adapté"};
    if (level === "weak") return {ok: false, level, tag: "FAIBLE", detail: "Peu efficace vs " + k + " — risque de ne pas détruire"};
    return {ok: false, level: "no", tag: "INEFFICACE", detail: "Obus incapable de détruire une cible " + k};
  }

  // --- Lecture du briefing -----------------------------------------------------
  // Une cible par ligne : « azimut distance [km|m] [libellé] ». Il faut un vrai séparateur
  // entre les deux nombres (sinon « 12 cibles » serait lu azimut 1 / distance 2).
  const LINE_RE = /(?:^|[^\w.,])(?:(?:azim(?:ut|uth|ute)?|az|bearing)\s*[:=]?\s*)?(\d+(?:[.,]\d+)?)(?:\s*(?:°|deg)?\s*(?:[,;/\-]|dist(?:ance)?|range)\s*|\s*(?:°|deg)\s*|\s+)(\d+(?:[.,]\d+)?)(?:\s*(km|m)\b)?\s*(.*)$/i;
  const toFloat = s => parseFloat(s.replace(",", "."));

  function parseBrief(text) {
    const out = [];
    for (const line of String(text || "").split(/\r\n|\r|\n/)) {
      const m = LINE_RE.exec(line);
      if (!m) continue;
      const az = toFloat(m[1]), dist = toFloat(m[2]), unit = (m[3] || "").toLowerCase();
      const t = {az, km: dist, label: m[4].trim(), kind: classify(line)};
      if (unit === "m") t.km = dist / 1000;
      else if (!unit && dist > MAX_RANGE_KM) {
        // sans unité : ≥ 100 = mètres, entre 30 et 100 = ambigu
        if (dist >= 100) t.km = dist / 1000;
        else t.error = "distance ambiguë : préciser km ou m";
      }
      if (az > 360) t.error = "azimut hors 0–360°";
      else t.az = az % 360;
      if (!t.error) {
        const e = rangeError(t.km);
        if (e) t.error = e;
      }
      out.push(t);
    }
    return out;
  }

  // --- Géométrie polaire (Nest au centre, km) --------------------------------------
  const xy = (az, km) => [km * Math.sin(az * Math.PI / 180), km * Math.cos(az * Math.PI / 180)];
  const polar = (x, y) => ({az: (Math.atan2(x, y) * 180 / Math.PI + 360) % 360, km: Math.hypot(x, y)});
  function sepKm(a, b) {
    const [x1, y1] = xy(a.az, a.km), [x2, y2] = xy(b.az, b.km);
    return Math.hypot(x1 - x2, y1 - y2);
  }
  function clusterIds(targets) {
    const ids = new Set();
    for (let i = 0; i < targets.length; i++)
      for (let j = i + 1; j < targets.length; j++)
        if (sepKm(targets[i], targets[j]) <= CLUSTER_KM) { ids.add(targets[i].id); ids.add(targets[j].id); }
    return ids;
  }
  function covered(ax, ay, targets, radius, splashHard) {
    const ids = [];
    for (const t of targets) {
      const [x, y] = xy(t.az, t.km);
      const d = Math.hypot(x - ax, y - ay);
      if (d > radius + 1e-9) continue;
      // bunker / Nest : seul un obus pénétrant les touche par le souffle
      if (HARD.has(t.kind) && !splashHard && d > 0.02) continue;
      ids.push(t.id);
    }
    return ids;
  }
  const costKey = c => (c == null ? Infinity : c);
  const round2 = v => Math.round(v * 100) / 100;

  function multiKill(targets, pref) {
    targets = targets.filter(t => !t.error);
    if (targets.length < 2) return [];
    const shells = (AREA_SHELLS[pref] || AREA_SHELLS.auto).filter(s => AMMO[s].dmg > 0);
    const cands = targets.map(t => { const [x, y] = xy(t.az, t.km); return {x, y, note: "sur T" + t.id}; });
    for (let i = 0; i < targets.length; i++)
      for (let j = i + 1; j < targets.length; j++) {
        const [x1, y1] = xy(targets[i].az, targets[i].km), [x2, y2] = xy(targets[j].az, targets[j].km);
        cands.push({x: (x1 + x2) / 2, y: (y1 + y2) / 2, note: "milieu T" + targets[i].id + "-T" + targets[j].id});
      }
    const plans = [], seen = new Set();
    for (const c of cands) {
      const p = polar(c.x, c.y);
      const cMin = minCharge(p.km);
      if (!cMin) continue;
      for (const shell of shells) {
        const st = AMMO[shell];
        const ids = covered(c.x, c.y, targets, st.blast_km, st.dmg >= 2);
        if (ids.length < 2) continue;
        const key = ids.slice().sort((a, b) => a - b).join("-") + "|" + shell;
        if (seen.has(key)) continue;
        seen.add(key);
        plans.push({
          aimAz: p.az, aimKm: p.km, note: c.note, shell, blastKm: st.blast_km, confirmed: st.confirmed,
          covers: ids, n: ids.length, cMin, elevMin: elevation(p.km, cMin), tofMin: timeOfFlight(p.km, cMin),
          elevMax: elevation(p.km, 6), tofMax: timeOfFlight(p.km, 6), cost: st.cost, saved: ids.length - 1
        });
      }
    }
    plans.sort((a, b) => b.n - a.n || (a.confirmed ? 0 : 1) - (b.confirmed ? 0 : 1)
      || costKey(a.cost) - costKey(b.cost) || round2(a.aimKm) - round2(b.aimKm));
    return plans.slice(0, MAX_PLANS);
  }

  function dualTubePairs(targets, mode, tol) {
    targets = targets.filter(t => !t.error);
    tol = tol == null ? DUAL_TUBE_AZ_TOL : tol;
    const side = t => { const c = mode === "min" ? minCharge(t.km) : 6; return {id: t.id, az: t.az, km: t.km, charge: c, elev: elevation(t.km, c)}; };
    const pairs = [];
    for (let i = 0; i < targets.length; i++)
      for (let j = i + 1; j < targets.length; j++) {
        let d = Math.abs(targets[i].az - targets[j].az);
        d = Math.min(d, 360 - d);
        if (d <= tol) pairs.push({ids: [targets[i].id, targets[j].id], deltaAz: d, left: side(targets[i]), right: side(targets[j])});
      }
    return pairs;
  }

  function solveTargets(targets, mode, pref) {
    mode = mode === "min" ? "min" : "max";
    pref = AREA_SHELLS[pref] ? pref : "auto";
    targets.forEach((t, i) => { t.id = i + 1; });
    const valid = targets.filter(t => !t.error);
    const clustered = clusterIds(valid);
    const solutions = targets.map(t => {
      if (t.error) return Object.assign({}, t);
      const chargeMin = minCharge(t.km);
      const charge = mode === "max" ? 6 : chargeMin;
      const shell = pickShell(t.kind, pref, clustered.has(t.id));
      return Object.assign({}, t, {
        clustered: clustered.has(t.id), chargeMin, charge,
        elev: elevation(t.km, charge), elevMin: elevation(t.km, chargeMin), tof: timeOfFlight(t.km, charge), shell
      });
    });
    const rank = s => (s.kind in PRIORITY ? PRIORITY[s.kind] : 6);
    const ordered = solutions.slice().sort((a, b) => (a.error ? 1 : 0) - (b.error ? 1 : 0) || rank(a) - rank(b) || a.km - b.km);
    // tubes alternés dans l'ordre de tir : un tube recharge pendant que l'autre tire
    let n = 0;
    for (const s of ordered) if (!s.error) s.tube = n++ % 2 === 0 ? "GAUCHE" : "DROITE";
    const fired = solutions.filter(s => !s.error);
    return {
      solutions, ordered,
      fireOrder: ordered.filter(s => !s.error).map(s => s.id),
      cost: fired.reduce((sum, s) => sum + (AMMO[s.shell].cost || 0), 0),
      unknownCost: fired.filter(s => AMMO[s.shell].cost == null).length,
      multiKill: multiKill(valid, pref),
      dual: dualTubePairs(valid, mode)
    };
  }

  // --- Grille A1–T10 ----------------------------------------------------------------
  // X vers l'Est, Y vers le Nord, en mètres. Colonne A = X 0–1000, ligne 1 = Y 0–1000
  // (sud de la carte). Subdivision « sx:sy » = centaines de mètres, au 0.1 près (10 m).
  const COLS = "ABCDEFGHIJKLMNOPQRST";
  const GRID_W_M = 20000, GRID_H_M = 10000, EDGE_TOL_M = 0.5;
  const CELL_RE = /(?:^|[^A-Za-z0-9])([A-Ta-t])\s*(10|[1-9])\s*[ ,]?\s*(\d+(?:\.\d+)?)\s*[:/,]\s*(\d+(?:\.\d+)?)/;
  const roundSub = v => Math.floor(v * 10 + 0.5) / 10;
  const fmtSub = v => String(v);

  function parseCell(s) {
    const m = CELL_RE.exec(String(s == null ? "" : s));
    if (!m) return null;
    const col = COLS.indexOf(m[1].toUpperCase());
    const row = +m[2], sx = roundSub(+m[3]), sy = roundSub(+m[4]);
    if (col < 0 || row < 1 || row > 10 || sx < 0 || sx > 10 || sy < 0 || sy > 10) return null;
    return {token: COLS[col] + row + " " + fmtSub(sx) + ":" + fmtSub(sy), col, row, sx, sy,
      x: Math.round((col * 1000 + sx * 100) * 10) / 10, y: Math.round(((row - 1) * 1000 + sy * 100) * 10) / 10};
  }
  function cellOf(x, y) {
    const tol = EDGE_TOL_M; // bruit de calcul flottant sur un bord de carte
    if (!(x >= -tol && y >= -tol && x <= GRID_W_M + tol && y <= GRID_H_M + tol)) return {token: "hors carte", x, y};
    x = Math.min(Math.max(x, 0), GRID_W_M); y = Math.min(Math.max(y, 0), GRID_H_M);
    let col = Math.min(19, Math.floor(x / 1000));
    let row = Math.min(10, Math.floor(y / 1000) + 1);
    let sx = Math.floor((x - col * 1000) / 10 + 0.5) / 10;
    let sy = Math.floor((y - (row - 1) * 1000) / 10 + 0.5) / 10;
    // 10 = bord de case : on passe à la case suivante, sauf au bord de la carte
    if (sx >= 10 && col < 19) { col++; sx = 0; }
    if (sy >= 10 && row < 10) { row++; sy = 0; }
    return {token: COLS[col] + row + " " + fmtSub(sx) + ":" + fmtSub(sy), x, y, col, row, sx, sy};
  }
  function azimuthTo(dx, dy) { return (Math.atan2(dx, dy) * 180 / Math.PI + 360) % 360; }
  function dir(az) { const r = az * Math.PI / 180; return {dx: Math.sin(r), dy: Math.cos(r)}; }

  function rayRay(A, azA, B, azB) {
    if (A.x === B.x && A.y === B.y) return {error: "deux azimuts depuis le même point ne localisent pas une cible", points: []};
    const a = dir(azA), b = dir(azB);
    const den = a.dx * b.dy - a.dy * b.dx;
    if (Math.abs(den) < 1e-9) return {error: "rayons parallèles", points: []};
    const dx = B.x - A.x, dy = B.y - A.y;
    const t = (dx * b.dy - dy * b.dx) / den, s = (dx * a.dy - dy * a.dx) / den;
    return {points: [{x: A.x + t * a.dx, y: A.y + t * a.dy}], note: (t <= 0 || s <= 0) ? "intersection derrière un rayon" : null};
  }
  function rayCircle(A, az, B, R) {
    const d = dir(az), fx = A.x - B.x, fy = A.y - B.y;
    const qb = 2 * (fx * d.dx + fy * d.dy), qc = fx * fx + fy * fy - R * R, disc = qb * qb - 4 * qc;
    if (disc < -1e-6) return {error: "pas d'intersection rayon / cercle", points: []};
    const root = Math.sqrt(Math.max(0, disc));
    const tangent = root < 1e-3;
    const ts = (tangent ? [(-qb - root) / 2] : [(-qb - root) / 2, (-qb + root) / 2]).filter(t => t > 1);
    if (!ts.length) return {error: "intersection derrière le rayon", points: []};
    return {points: ts.map(t => ({x: A.x + t * d.dx, y: A.y + t * d.dy})), note: tangent ? "tangence" : (ts.length === 2 ? "2 solutions" : null)};
  }
  function circleCircle(A, rA, B, rB) {
    const dx = B.x - A.x, dy = B.y - A.y, d = Math.hypot(dx, dy);
    if (d < 1e-6) return {error: "points confondus", points: []};
    if (d > rA + rB + 1e-6) return {error: "cercles disjoints", points: []};
    if (d < Math.abs(rA - rB) - 1e-6) return {error: "un cercle contenu dans l'autre", points: []};
    const a = (rA * rA - rB * rB + d * d) / (2 * d);
    const h = Math.sqrt(Math.max(0, rA * rA - a * a));
    const mx = A.x + a * dx / d, my = A.y + a * dy / d, px = -dy / d * h, py = dx / d * h;
    if (h < 1e-4) return {points: [{x: mx, y: my}], note: "tangence"};
    return {points: [{x: mx + px, y: my + py}, {x: mx - px, y: my - py}], note: "2 solutions — départager avec un 3e indice"};
  }

  // --- Divers --------------------------------------------------------------------------
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  }

  return {
    AMMO, SPEEDS, KM_PER_CHARGE, MAX_RANGE_KM, CLUSTER_KM, DUAL_TUBE_AZ_TOL, TARGET_KINDS, MISSION_KINDS, HARD, PRIORITY,
    COLS, GRID_W_M, GRID_H_M,
    minCharge, rangeError, elevation, timeOfFlight, ballistics,
    classify, normalizeKind, pickShell, effectiveness,
    parseBrief, xy, polar, sepKm, clusterIds, multiKill, dualTubePairs, solveTargets,
    parseCell, cellOf, azimuthTo, dir, rayRay, rayCircle, circleCircle,
    esc
  };
});
