// Unit tests for web/core.js: fares, tolls, ranking, dedupe, Toronto time.
//
// No engine, no browser, no packages: core.js runs inside a Node vm exactly
// as the page loads it (one classic script, plain globals).
//
//   node --test tests/core.test.mjs
//
// Every trip below is made up; what matters is the rule each one exercises.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const root = new URL("../", import.meta.url);
const read = p => readFileSync(new URL(p, root), "utf8");

/* A fresh copy of core.js per call, so no test leaks state into another.
   app.js declares `rider` and `GO_FARES`; core.js only reads them. */
function load({ rider = "adult", goFares = null, toll = null, tollRate = null } = {}){
  const ctx = vm.createContext({ console });
  vm.runInContext(read("web/core.js"), ctx, { filename: "core.js" });
  ctx.__cfg = { rider, goFares, toll, tollRate };
  vm.runInContext(`let rider = __cfg.rider; let GO_FARES = __cfg.goFares;
    TOLL = __cfg.toll; TOLLRATE = __cfg.tollRate;`, ctx);
  return code => vm.runInContext(code, ctx);
}

/* ---- a tiny trip builder ---- */
const T0 = Date.parse("2026-10-06T12:00:00Z");          // Tue 8:00 AM Toronto
const leg = (mode, startMin, endMin, o = {}) => ({
  mode, distance: o.dist ?? 1000, duration: (endMin - startMin) * 60,
  rentedBike: !!o.rented, startTime: T0 + startMin * 60000, endTime: T0 + endMin * 60000,
  // agencies by feed id, the way the engine's gtfsId carries them ("TTC:1")
  agency: o.ag ? { gtfsId: o.ag + ":1", name: o.ag } : null,
  route: o.rt || o.rtLong ? { shortName: o.rt || "", longName: o.rtLong || "" } : null,
  from: { name: o.from || "A", stop: o.fs ? { gtfsId: o.fs } : null },
  to: { name: o.to || "B", stop: o.ts ? { gtfsId: o.ts } : null },
  legGeometry: o.geom ? { points: o.geom } : null,
});
const trip = (...legs) => ({ legs, duration: (legs.at(-1).endTime - legs[0].startTime) / 1000,
                             startTime: legs[0].startTime, endTime: legs.at(-1).endTime });
const TTC = "TTC", YRT = "YRT", GO = "GO";
const cost = (core, it) => core("itineraryCostDetail")(it);
const money = x => Math.round(x * 100) / 100;

/* ===================== Toronto time ===================== */

test("torontoISO pins the picked time to Toronto, across both DST changes", () => {
  const core = load();
  assert.equal(core(`torontoISO("2026-10-06", "08:00")`), "2026-10-06T12:00:00.000Z"); // EDT
  assert.equal(core(`torontoISO("2026-12-15", "08:00")`), "2026-12-15T13:00:00.000Z"); // EST
  assert.equal(core(`torontoISO("2026-11-01", "08:00")`), "2026-11-01T13:00:00.000Z"); // fall back
  assert.equal(core(`torontoISO("2026-03-08", "08:00")`), "2026-03-08T12:00:00.000Z"); // spring forward
});

test("torontoWall reads Toronto's clock whatever this machine's zone is", () => {
  const core = load();
  const w = core(`torontoWall(Date.parse("2026-10-06T03:30:00Z"))`);  // 11:30 PM Oct 5
  assert.equal(w.getDate(), 5);
  assert.equal(w.getHours(), 23);
  assert.equal(w.getMinutes(), 30);
});

/* ===================== fares ===================== */

test("a TTC-only trip pays one TTC fare, adult or youth", () => {
  const it = trip(leg("WALK", 0, 5), leg("SUBWAY", 5, 20, { ag: TTC }), leg("WALK", 20, 25));
  assert.equal(money(cost(load(), it).total), 3.30);
  assert.equal(money(cost(load({ rider: "youth" }), it).total), 2.35);
});

test("One Fare: local transit is free once GO is in the trip", () => {
  const it = trip(leg("RAIL", 0, 40, { ag: GO, dist: 30000 }), leg("SUBWAY", 45, 55, { ag: TTC }));
  const { total, items } = cost(load(), it);
  // no fare table loaded, so GO is the distance estimate: 3.70 + 0.11/km
  assert.equal(money(total), money(3.70 + 0.11 * 30));
  assert.match(items.find(x => x.label.startsWith("TTC")).label, /One Fare/);
});

test("GO uses the real station-to-station table when it has one, with 40% off for youth", () => {
  const goFares = { zones: { UI: "Z1", UN: "Z2" }, fares: { "Z2|Z1": 6.5 } };   // either order
  const it = trip(leg("RAIL", 0, 40, { ag: GO, fs: "GO:UI", ts: "GO:UN", dist: 30000 }));
  assert.equal(money(cost(load({ goFares }), it).total), 6.50);
  assert.equal(money(cost(load({ goFares, rider: "youth" }), it).total), money(6.5 * 0.6));
});

test("One Fare: YRT then TTC pays YRT only", () => {
  const it = trip(leg("BUS", 0, 30, { ag: YRT }), leg("SUBWAY", 32, 50, { ag: TTC }));
  assert.equal(money(cost(load(), it).total), 4.24);
});

test("Halton co-fare: Oakville is free with GO but NOT on a TTC transfer", () => {
  const withGo = trip(leg("BUS", 0, 10, { ag: "OAKVILLE" }), leg("RAIL", 12, 50, { ag: GO, dist: 30000 }));
  const free = cost(load(), withGo).items.find(x => x.label.startsWith("Oakville"));
  assert.equal(free.amount, 0);
  const withTtc = trip(leg("BUS", 0, 10, { ag: "OAKVILLE" }), leg("SUBWAY", 12, 30, { ag: TTC }));
  assert.equal(money(cost(load(), withTtc).total), money(3.50 + 3.30));
});

test("Burlington youth ride free on weekday evenings and weekends only", () => {
  const core = load({ rider: "youth" });
  const at = iso => trip({ ...leg("BUS", 0, 10, { ag: "BURLINGTON" }), startTime: Date.parse(iso) });
  assert.equal(cost(core, at("2026-10-06T22:30:00Z")).total, 0);       // Tue 6:30 PM
  assert.equal(money(cost(core, at("2026-10-06T21:30:00Z")).total), 2); // Tue 5:30 PM
  assert.equal(cost(core, at("2026-10-10T16:00:00Z")).total, 0);       // Sat noon
  assert.equal(money(cost(load(), at("2026-10-06T22:30:00Z")).total), 2.85); // adults pay
});

test("UP Express charges the Pearson fare only on airport trips", () => {
  const up = to => trip(leg("RAIL", 0, 25, { ag: "UP", from: "Union Station", to }));
  assert.equal(money(cost(load(), up("Pearson Airport Terminal 1")).total), 9.25);
  assert.equal(money(cost(load({ rider: "youth" }), up("Pearson Airport Terminal 1")).total), 7.41);
  assert.equal(money(cost(load(), up("Bloor")).total), 5.02);
});

test("Bike Share is $1 plus 12 cents a minute, rounded up", () => {
  const it = trip(leg("BICYCLE", 0, 9.5, { rented: true }), leg("SUBWAY", 12, 20, { ag: TTC }));
  assert.equal(money(cost(load(), it).total), money(1 + 10 * 0.12 + 3.30));
});

test("driving to a station costs gas and wear, with no parking fee", () => {
  const it = trip(leg("CAR", 0, 12, { dist: 10000 }), leg("RAIL", 15, 50, { ag: GO, dist: 30000 }));
  const items = cost(load(), it).items;
  assert.equal(money(items.find(x => x.label.startsWith("Driving")).amount), 2.40);
  assert.ok(!items.some(x => /parking/i.test(x.label)));
});

test("an agency the fare table doesn't know is never priced as another one", () => {
  // the old name matching priced Hamilton as Milton; by feed id it can't happen
  const it = trip(leg("BUS", 0, 20, { ag: "HSR" }));
  assert.equal(cost(load(), it).items.length, 0);
  assert.equal(load()("prettyAgency")({ agency: { gtfsId: "MILTON:0", name: "x" } }), "Milton Transit");
});

test("UP Express replacement buses in the GO feed charge the UP fare, not GO's", () => {
  const bus = trip(leg("BUS", 0, 40, { ag: GO, rtLong: "Union Pearson Express",
    from: "Union Station Bus Terminal", to: "Pearson Airport Terminal 1" }));
  const { total, items } = cost(load(), bus);
  assert.equal(money(total), 9.25);
  assert.ok(items[0].label.startsWith("UP Express"));
});

/* ===================== tolls ===================== */

/* Price a drive straight along the 407 centreline. The toll GRID is replaced
   by "everything is tolled", so this tests the pricing (zones, direction,
   time band, trip charge) and nothing about the map geometry. */
const rates = JSON.parse(read("web/toll-rates.json"));
const everywhere = { lat0: 0, lon0: 0, dlat: 1, dlon: 1,
                     cells: new Proxy({}, { get: () => ({ has: () => true }) }) };
function encode(pts){            // Google polyline, the inverse of decodePolyline
  let out = "", pLat = 0, pLng = 0;
  const one = v => { v = v < 0 ? ~(v << 1) : v << 1;
    while (v >= 0x20){ out += String.fromCharCode((0x20 | (v & 0x1f)) + 63); v >>= 5; }
    out += String.fromCharCode(v + 63); };
  for (const [lng, lat] of pts){
    const a = Math.round(lat * 1e5), b = Math.round(lng * 1e5);
    one(a - pLat); one(b - pLng); pLat = a; pLng = b;
  }
  return out;
}
function along(kmFrom, kmTo){    // points on the centreline between two km marks
  const line = rates.centreline, cum = rates.centreline_km, pts = [];
  const at = km => { const i = cum.findIndex(c => c >= km); const t = (km - cum[i-1]) / (cum[i] - cum[i-1]);
    return [line[i-1][0] + t * (line[i][0] - line[i-1][0]), line[i-1][1] + t * (line[i][1] - line[i-1][1])]; };
  for (let k = kmFrom; kmFrom < kmTo ? k <= kmTo : k >= kmTo; k += kmFrom < kmTo ? 0.1 : -0.1) pts.push(at(k));
  return pts;
}
const drive = (pts, iso) => ({ ...leg("CAR", 0, 5, { geom: encode(pts), dist: 3000 }), startTime: Date.parse(iso) });

test("407: zone rate x km + the per-trip charge, eastbound at the morning peak", () => {
  const core = load({ toll: everywhere, tollRate: rates });
  const l = drive(along(18, 21), "2026-10-06T12:00:00Z");           // zone 3, Tue 8:00 AM
  const g = core("legTollGeom")(l);
  assert.equal(g.dir, "eastbound");
  assert.deepEqual(Object.keys(g.byZone), ["3"]);
  const expected = (g.m / 1000) * rates.rates.eastbound.weekday[1][2] / 100 + rates.fees.trip_charge;
  assert.equal(money(core("legTollCost")(l)), money(expected));
  assert.ok(Math.abs(g.m - 3000) < 100, `measured ${g.m} m for a 3 km stretch`);
});

test("407: the same stretch costs less late at night, and reverses to westbound", () => {
  const core = load({ toll: everywhere, tollRate: rates });
  const peak = core("legTollCost")(drive(along(18, 21), "2026-10-06T12:00:00Z"));
  const night = core("legTollCost")(drive(along(18, 21), "2026-10-07T03:00:00Z"));  // 11 PM
  assert.ok(night < peak, `night ${night} should be under peak ${peak}`);
  assert.equal(core("legTollGeom")(drive(along(21, 18), "2026-10-06T12:00:00Z")).dir, "westbound");
});

test("407: no toll off the toll grid, and nothing before the grid loads", () => {
  const nowhere = { lat0: 0, lon0: 0, dlat: 1, dlon: 1, cells: {} };
  const l = drive(along(18, 21), "2026-10-06T12:00:00Z");
  assert.equal(load({ toll: nowhere, tollRate: rates })("legTollCost")(l), 0);
  assert.equal(load({ toll: null, tollRate: rates })("legTollCost")(l), 0);
});

test("407: a rate chart goes stale on January 1st of the next year, Toronto time", () => {
  const core = load();
  const stale = core("tollRatesStale");
  const chart = { _effective: "2026-01-01" };
  assert.equal(stale(chart, Date.parse("2026-12-31T12:00:00Z")), false);
  assert.equal(stale(chart, Date.parse("2027-01-01T04:30:00Z")), false);  // 11:30 PM Dec 31 in Toronto
  assert.equal(stale(chart, Date.parse("2027-01-01T06:00:00Z")), true);   // 1 AM Jan 1 in Toronto
  assert.equal(stale({}, Date.parse("2030-01-01T12:00:00Z")), false);     // no date: don't cry wolf
});

/* ===================== dedupe and ranking ===================== */

const rideFrom = (stop, start) => trip(leg("CAR", start, start + 10), leg("RAIL", start + 12, start + 50,
  { ag: GO, rt: "ST", fs: "GO:" + stop }));

test("dedupe keeps one card per pattern and collects the other departures", () => {
  const core = load();
  const out = core("dedupeAlts")([rideFrom("UI", 0), rideFrom("UI", 30)]);
  assert.equal(out.length, 1);
  assert.deepEqual([...out[0].altTimes], [T0 + 30 * 60000]);
});

test("dedupe never merges trips that board at different stations", () => {
  const core = load();
  assert.equal(core("dedupeAlts")([rideFrom("UI", 0), rideFrom("MJ", 30)]).length, 2);
});

test("dedupe leaves its input alone, so a filtered-out trip can't stick", () => {
  const core = load();
  const a = rideFrom("UI", 0), b = rideFrom("UI", 30);
  core("dedupeAlts")([a, b]);
  assert.equal(a.altTimes, undefined);
  assert.equal(core("dedupeAlts")([a])[0].altTimes.length, 0);
});

const opt = (mins, cost, startMin = 0) => ({ it: { duration: mins * 60, startTime: T0 + startMin * 60000 }, cost });

test("ranking hides anything both slower and no cheaper than another option", () => {
  const core = load();
  const fast = opt(40, 10), cheap = opt(70, 3), worse = opt(50, 12);
  const r = core("rankPool")([worse, cheap, fast], false);
  assert.deepEqual(r.main, [fast, cheap]);
  assert.deepEqual(r.rest, [worse]);
  assert.equal(r.fastestIt, fast.it);
  assert.equal(r.cheapestIt, cheap.it);
});

test("ranking pins the cheapest option into the top five", () => {
  const core = load();
  const pool = [opt(30, 20), opt(31, 19), opt(32, 18), opt(33, 17), opt(34, 16), opt(35, 15), opt(90, 1)];
  const r = core("rankPool")(pool, false);
  assert.equal(r.main.length, 5);
  assert.ok(r.main.includes(pool[6]), "the $1 option must headline");
});

test("Arrive by: leaving later counts, and the latest leave is badged", () => {
  const core = load();
  const early = opt(40, 5, 0), late = opt(45, 5, 20);   // slower, same price, leaves later
  assert.equal(core("rankPool")([early, late], false).main.length, 1);
  const r = core("rankPool")([early, late], true);
  assert.equal(r.main.length, 2);
  assert.equal(r.latestIt, late.it);
});

test("spreadByDrive keeps short drives even when long ones are faster", () => {
  const core = load();
  const d = (km, mins) => trip({ ...leg("CAR", 0, 10, { dist: km * 1000 }) }, leg("RAIL", 12, mins, { ag: GO }));
  const far = [1, 2, 3, 4, 5, 6].map(i => d(35, 40 + i));
  const near = d(3, 80);
  const kept = core("spreadByDrive")([...far, near]);
  assert.ok(kept.includes(near), "the 3 km option must survive");
});

test("at-the-start and at-the-end legs are judged against the transit legs", () => {
  const core = load();
  const bikeShareEnd = trip(leg("RAIL", 0, 30, { ag: GO }), leg("BICYCLE", 32, 40, { rented: true }));
  const rented = l => l.mode === "BICYCLE" && l.rentedBike;
  assert.equal(core("endLegOnly")(bikeShareEnd, rented), true);
  assert.equal(core("startLegOnly")(bikeShareEnd, rented), false);
});

/* ===================== alerts ===================== */

test("alerts: live ones only, http links only, and a cut-off TTC header gives way", () => {
  const core = load();
  const now = Date.now() / 1000;
  const out = core("cleanAlerts")([
    { id: "old", alertHeaderText: "Over", effectiveEndDate: now - 60 },
    { id: "js", alertHeaderText: "Bad link", alertUrl: "javascript:alert(1)" },
    { id: "ok", alertHeaderText: "Good link", alertUrl: "https://www.ttc.ca/x" },
    { id: "cut", alertHeaderText: "16 Mccowan: Buses are not stoppi",
      alertDescriptionText: "16 Mccowan: Buses are not stopping at Lawrence." },
  ]);
  assert.deepEqual([...out].map(a => a.id), ["js", "ok", "cut"]);  // [...] : a plain array from this realm, not the vm's
  assert.equal(out[0].url, "");
  assert.equal(out[1].url, "https://www.ttc.ca/x");
  assert.equal(out[2].header, "16 Mccowan: Buses are not stopping at Lawrence.");
});

/* ===================== the audit's copy of the mode mixes ===================== */

test("tests/route-audit.py mirrors COMBOS and DRIVE_RELUCTANCE exactly", () => {
  const core = load();
  const py = read("tests/route-audit.py");
  const body = py.slice(py.indexOf("APP_COMBOS = [") + "APP_COMBOS = ".length);
  const literal = body.slice(0, body.indexOf("\n]") + 2)
    .replace(/#[^\n]*/g, "").replace(/\bTrue\b/g, "true").replace(/\bFalse\b/g, "false")
    .replace(/,(\s*[\]}])/g, "$1");
  const audit = JSON.parse(literal);
  // what the app fires with every toggle on; `need` is a UI concern only
  const app = JSON.parse(core("JSON.stringify(COMBOS)")).map(({ need, ...c }) => c);
  assert.deepEqual(audit, app);
  const rel = py.match(/^DRIVE_RELUCTANCE = (\[[^\]]*\])/m)[1];
  assert.deepEqual(JSON.parse(rel), JSON.parse(core("JSON.stringify(DRIVE_RELUCTANCE)")));
});

/* ===================== the audit's copy of the filters ===================== */

/* route-audit.py re-implements comboModes / comboPrefs / filterCombo in
   Python. Run BOTH on the same made-up engine answers for every mode mix and
   insist they agree, so the audit can never grade a filter the app doesn't
   have. */
import { spawnSync } from "node:child_process";

test("tests/route-audit.py filters, modes and preferences match core.js", () => {
  const core = load();
  const L = (mode, mins, rented = false) => ({ mode, rentedBike: rented, duration: mins * 60 });
  const I = (...legs) => ({ legs, duration: legs.reduce((s, l) => s + l.duration, 0) });
  const fixtures = [
    I(L("WALK", 5), L("RAIL", 30), L("WALK", 5)),                       // plain transit
    I(L("CAR", 10), L("WALK", 3), L("RAIL", 30), L("WALK", 5)),          // drive to station
    I(L("WALK", 5), L("SUBWAY", 20), L("CAR", 12)),                      // pickup at the end
    I(L("CAR", 25), L("WALK", 2)),                                       // no transit at all
    I(L("BICYCLE", 12), L("RAIL", 30), L("WALK", 4)),                    // own bike to station
    I(L("WALK", 4), L("RAIL", 30), L("BICYCLE", 8, true), L("WALK", 1)), // Bike Share at the end
    I(L("WALK", 2), L("BICYCLE", 8, true), L("BUS", 25), L("WALK", 3)),  // Bike Share at the start
    I(L("WALK", 3), L("BICYCLE", 24, true), L("WALK", 2)),               // Bike Share the whole way
    I(L("BICYCLE", 50)), I(L("BICYCLE", 70)), I(L("BICYCLE", 30)),       // bike whole way, one over cap
    I(L("WALK", 40)), I(L("WALK", 50)),                                  // walk whole way, one over cap
    I(L("CAR", 10), L("RAIL", 30), L("CAR", 12)),                        // drive both ends
    I(L("WALK", 3), L("RAIL", 10), L("CAR", 5), L("RAIL", 10)),          // car in the middle
    I(L("BICYCLE", 10, true), L("RAIL", 30), L("BICYCLE", 8, true)),     // rented both ends
    I(L("CAR", 10), L("RAIL", 30), L("BICYCLE", 8, true)),               // drive + Bike Share
    I(L("BICYCLE", 10), L("RAIL", 30), L("BICYCLE", 8, true)),           // bike + Bike Share
    I(L("BICYCLE", 10), L("RAIL", 30), L("CAR", 8)),                     // bike + pickup
  ];
  const combos = JSON.parse(core("JSON.stringify(COMBOS)"));
  const rels = [null, 30, 2];
  const js = {
    keep: combos.map(c => [...core("filterCombo")(c, fixtures)].map(it => fixtures.indexOf(it))),
    modes: combos.map(c => JSON.parse(JSON.stringify(core("comboModes")(c)))),
    prefs: combos.map(c => rels.map(r => JSON.parse(JSON.stringify(core("comboPrefs")(c, r, "safest"))))),
  };
  const py = spawnSync("python3", ["-c", `
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("audit", "tests/route-audit.py")
audit = importlib.util.module_from_spec(spec); spec.loader.exec_module(audit)
d = json.load(sys.stdin)
fx = d["fixtures"]
for i, f in enumerate(fx): f["_i"] = i
print(json.dumps({
  "keep": [[it["_i"] for it in audit.keep(c, fx)] for c in d["combos"]],
  "modes": [audit.modes_for(c) for c in d["combos"]],
  "prefs": [[audit.prefs_for(c, r) for r in d["rels"]] for c in d["combos"]],
}))`], { cwd: new URL(".", root).pathname, input: JSON.stringify({ fixtures, combos, rels }), encoding: "utf8" });
  assert.equal(py.status, 0, py.stderr);
  const got = JSON.parse(py.stdout);
  combos.forEach((c, i) => {
    assert.deepEqual(got.keep[i], js.keep[i], `filter differs for "${c.key}"`);
    assert.deepEqual(got.modes[i], js.modes[i], `modes differ for "${c.key}"`);
    assert.deepEqual(got.prefs[i], js.prefs[i], `preferences differ for "${c.key}"`);
  });
  // and the fixtures really exercise the filters: every mix keeps something
  // and drops something
  js.keep.forEach((k, i) => assert.ok(k.length > 0 && k.length < fixtures.length, combos[i].key));
});
