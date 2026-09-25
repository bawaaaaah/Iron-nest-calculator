// Tests du cœur JS (Node ≥ 18, sans dépendance) : node --test tests/core.test.js
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.join(__dirname, "..");
const N = require(path.join(ROOT, "iron-nest-core.js"));
const V = JSON.parse(fs.readFileSync(path.join(__dirname, "vectors.json"), "utf8"));
const AMMO = JSON.parse(fs.readFileSync(path.join(ROOT, "iron-nest-mcp", "ammo.json"), "utf8")).shells;

const close = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) <= eps, `${a} ≉ ${b}`);
const withIds = ts => { ts.forEach((t, i) => { t.id = i + 1; }); return ts; };

test("la table d'obus embarquée est identique à iron-nest-mcp/ammo.json", () => {
  assert.deepEqual(N.AMMO, AMMO, "désynchronisé : lancer python3 tools/sync_ammo.py");
});

test("parseBrief", () => {
  for (const c of V.parse_brief) {
    const got = N.parseBrief(c.text);
    assert.equal(got.length, c.expect.length, c.text);
    got.forEach((t, i) => {
      for (const [k, v] of Object.entries(c.expect[i])) {
        if (k === "error") assert.equal(!!t.error, v, c.text);
        else if (k === "az" || k === "km") close(t[k], v);
        else assert.equal(t[k], v, c.text);
      }
    });
  }
});

test("classify / normalizeKind / pickShell / minCharge", () => {
  for (const [text, kind] of V.classify) assert.equal(N.classify(text), kind, text);
  for (const [text, kind] of V.normalize_kind) assert.equal(N.normalizeKind(text), kind, text);
  for (const [kind, pref, clustered, shell] of V.pick_shell) assert.equal(N.pickShell(kind, pref, clustered), shell, kind + "/" + pref);
  for (const [km, c] of V.min_charge) assert.equal(N.minCharge(km), c, String(km));
});

test("ballistics", () => {
  for (const c of V.ballistics) {
    const got = N.ballistics(c.km, c.charges);
    assert.equal(!!got.error, !!c.error, JSON.stringify(c));
    if ("charge" in c) {
      assert.equal(got.charge, c.charge);
      close(got.elev, c.elev, 0.01);
      close(got.tof, c.tof, 0.05);
    }
  }
});

test("parseCell / cellOf", () => {
  for (const [text, exp] of V.parse_cell) {
    const got = N.parseCell(text);
    if (exp === null) assert.equal(got, null, text);
    else assert.deepEqual([got.token, got.x, got.y], [exp.token, exp.x, exp.y], text);
  }
  for (const [x, y, token] of V.cell_of) assert.equal(N.cellOf(x, y).token, token, `${x},${y}`);
});

test("multiKill : jamais d'obus sans dégât, chimiques seulement en mode chem", () => {
  for (const c of V.multi_kill) {
    const plans = N.multiKill(withIds(N.parseBrief(c.brief)), c.pref);
    for (const p of plans) {
      assert.ok(N.AMMO[p.shell].dmg > 0, p.shell);
      if (c.pref !== "chem") assert.equal(N.AMMO[p.shell].chem, false, p.shell);
    }
    if (c.top === null) assert.deepEqual(plans, []);
    else assert.deepEqual([plans[0].shell, plans[0].covers], [c.top.shell, c.top.covers], c.brief);
  }
});

test("solveTargets : ordre de tir, tubes, obus, charges, coût, double tube", () => {
  for (const c of V.solve) {
    const res = N.solveTargets(N.parseBrief(c.brief), c.mode, c.pref);
    const byId = Object.fromEntries(res.solutions.map(s => [String(s.id), s]));
    if (c.fire_order) assert.deepEqual(res.fireOrder, c.fire_order);
    for (const [field, key] of [["tubes", "tube"], ["shells", "shell"], ["charges", "charge"]])
      for (const [id, v] of Object.entries(c[field] || {})) assert.equal(byId[id][key], v, `${field} T${id}`);
    for (const id of c.errors || []) assert.ok(byId[String(id)].error);
    if ("cost" in c) assert.deepEqual([res.cost, res.unknownCost], [c.cost, c.unknown_cost]);
    if (c.dual) assert.deepEqual(res.dual.map(p => p.ids), c.dual);
  }
});

test("double tube : la charge affichée correspond à l'élévation", () => {
  const ts = withIds(N.parseBrief("Azimut 55.3 distance 12.7\nAzimut 54.2 distance 9.7"));
  const [max] = N.dualTubePairs(ts, "max");
  assert.deepEqual([max.left.charge, max.right.charge], [6, 6]);
  close(max.left.elev, N.elevation(12.7, 6));
  const [min] = N.dualTubePairs(ts, "min");
  assert.deepEqual([min.left.charge, min.right.charge], [3, 2]);
  close(min.left.elev, N.elevation(12.7, 3));
});

test("triangulation", () => {
  for (const c of V.triangulate) {
    const A = N.parseCell(c.a), B = N.parseCell(c.b);
    const r = c.mode === "two_azimuths" ? N.rayRay(A, c.p1, B, c.p2)
      : c.mode === "az_dist" ? N.rayCircle(A, c.p1, B, c.p2 * 1000)
      : N.circleCircle(A, c.p1 * 1000, B, c.p2 * 1000);
    assert.equal(!!r.error, !!c.error, JSON.stringify(c));
    if (c.points) assert.deepEqual(r.points.map(p => N.cellOf(p.x, p.y).token), c.points);
    if (c.note) assert.equal(r.note, c.note);
  }
});

test("esc échappe le HTML", () => {
  assert.equal(N.esc(`Obs "Nord" <b>&'`), "Obs &quot;Nord&quot; &lt;b&gt;&amp;&#39;");
});
