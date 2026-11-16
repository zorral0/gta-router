// Replays saved engine answers through the page's own ranking code.
//
// No engine, no browser, no packages. tests/capture-routing-fixtures.mjs
// saves what the real engine said for each trip in tests/routing-trips.json
// into tests/fixtures/routing/<id>.json; this file feeds those answers
// through core.js (the same functions the page calls: comboAnswer,
// mergeDriveTries, rankParts) and checks the ranked list.
//
//   node --test tests/routing.test.mjs
//   UPDATE_ROUTING_SNAPSHOTS=1 node --test tests/routing.test.mjs   (rewrite .expected.json)

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, writeFileSync, readdirSync, existsSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import vm from "node:vm";

const root = new URL("../", import.meta.url);
const read = p => readFileSync(new URL(p, root), "utf8");
const FIXTURES = new URL("tests/fixtures/routing/", root);
const UPDATE = !!process.env.UPDATE_ROUTING_SNAPSHOTS;

/* ---- loading core.js the way app.js leaves the page ---- */
const goFares = JSON.parse(read("web/go-fares.json"));
const tollRoads = JSON.parse(read("web/toll-roads.json"));
const tollRates = JSON.parse(read("web/toll-rates.json"));
/* Mirrors app.js after it fetches toll-roads.json: each grid row of cells
   (a list of numbers) becomes a Set, so inToll() can ask `has(y)`.
   toll-rates.json is used as is (TOLLRATE = j). */
for (const k in tollRoads.cells) tollRoads.cells[k] = new Set(tollRoads.cells[k]);

function loadCore(rider){
  const ctx = vm.createContext({ console });
  vm.runInContext(read("web/core.js"), ctx, { filename: "core.js" });
  ctx.__cfg = { rider, goFares, toll: tollRoads, tollRate: tollRates };
  vm.runInContext(`let rider = __cfg.rider; let GO_FARES = __cfg.goFares;
    TOLL = __cfg.toll; TOLLRATE = __cfg.tollRate;`, ctx);
  return code => vm.runInContext(code, ctx);
}

/* ---- replay: saved answers in, the page's ranked result out ----
   `overrides` can change maxDriveKm, avoidTolls, arriveBy or rider. */
function replay(fixture, overrides = {}){
  const t = { ...fixture.trip, ...overrides };
  const core = loadCore(t.rider || "adult");
  const combos = core("COMBOS");
  const parts = [];
  for (const c of combos){                       // COMBOS order, like the page
    const mine = fixture.answers.filter(a => a.combo === c.key);
    if (!mine.length) continue;
    const tries = mine.map(a => core("comboAnswer")(c, a.nodes));
    parts.push({ c, its: c.drive ? core("mergeDriveTries")(tries) : tries[0] });
  }
  const result = core("rankParts")(parts, t.maxDriveKm * 1000, !!t.avoidTolls, !!t.arriveBy);
  result.core = core;
  result.arriveBy = !!t.arriveBy;
  result.capM = t.maxDriveKm * 1000;
  return result;
}

/* ---- summarize: plain data a person can read in a diff ---- */
function summarize(result){
  const one = x => {
    const it = x.it;
    const transit = it.legs.find(l => ["BUS","RAIL","SUBWAY","TRAM","FERRY"].includes(l.mode));
    const badges = [];
    if (it === result.fastestIt) badges.push("Fastest");
    if (it === result.latestIt && it !== result.fastestIt) badges.push("Latest leave");
    if (it === result.cheapestIt) badges.push("Cheapest");
    return {
      minutes: Math.round(it.duration / 60),
      cost: Number(x.cost.toFixed(2)),
      legs: it.legs.map(l => l.mode + ((l.route || {}).shortName ? " " + l.route.shortName : "")).join(" > "),
      firstBoard: transit ? (transit.from || {}).name || null : null,
      badges,
    };
  };
  return JSON.parse(JSON.stringify({ main: result.main.map(one), rest: result.rest.map(one) }));
}

/* ---- invariants: true for every trip, whatever the engine said ---- */
const beats = (y, x, arriveBy) =>
  y.it.duration <= x.it.duration && y.cost <= x.cost
  && (!arriveBy || y.it.startTime >= x.it.startTime)
  && (y.it.duration < x.it.duration || y.cost < x.cost
      || (arriveBy && y.it.startTime > x.it.startTime));
const hasCar = x => x.it.legs.some(l => l.mode === "CAR");
const INVARIANTS = [
  ["shows at most 5 headline trips", r =>
    r.main.length <= 5 ? null : `${r.main.length} trips headline`],
  ["the cheapest trip is among the headlines", r =>
    r.main.some(x => x.it === r.cheapestIt) ? null : "the cheapest trip is hidden under more options"],
  ["no headline trip is beaten on both time and price", r => {
    for (const x of r.main){
      const y = r.pool.find(y => y !== x && beats(y, x, r.arriveBy));
      if (y) return `a ${Math.round(x.it.duration / 60)} min, $${x.cost.toFixed(2)} headline is beaten by a ${Math.round(y.it.duration / 60)} min, $${y.cost.toFixed(2)} trip`;
    }
    return null;
  }],
  ["no trip with a car leg is beaten by a trip with no car", r => {
    for (const x of r.pool.filter(hasCar)){
      const y = r.pool.find(y => !hasCar(y) && beats(y, x, r.arriveBy));
      if (y) return `a drive of ${Math.round(x.it.duration / 60)} min, $${x.cost.toFixed(2)} survives although a car-free ${Math.round(y.it.duration / 60)} min, $${y.cost.toFixed(2)} trip beats it`;
    }
    return null;
  }],
  ["no visible trip drives further than the drive cap", r => {
    const longest = r.core("longestCarLegM");
    const bad = r.pool.find(x => longest(x.it) > r.capM);
    return bad ? `a trip has a ${(longest(bad.it) / 1000).toFixed(1)} km drive, cap is ${r.capM / 1000} km` : null;
  }],
  ["every trip has a real price of zero or more", r => {
    const bad = r.pool.find(x => !Number.isFinite(x.cost) || x.cost < 0);
    return bad ? `a trip is priced ${bad.cost}` : null;
  }],
  ["exactly one Fastest and one Cheapest", r => {
    const all = r.main.concat(r.rest);
    const f = all.filter(x => x.it === r.fastestIt).length;
    const c = all.filter(x => x.it === r.cheapestIt).length;
    return f === 1 && c === 1 ? null : `Fastest on ${f} trips, Cheapest on ${c}`;
  }],
];

/* ---- snapshot: the whole summary must match the saved .expected.json ---- */
function checkSnapshot(id, summary, dir, update){
  const file = new URL(`${id}.expected.json`, dir);
  if (update){ writeFileSync(file, JSON.stringify(summary, null, 2) + "\n"); return; }
  const why = `The ranked results for ${id} changed. If you changed ranking, fares or filters on purpose, re-run with UPDATE_ROUTING_SNAPSHOTS=1 and read the diff of the .expected.json file before committing. If you did not mean to change results, your change broke routing.`;
  if (!existsSync(file)) assert.fail(`${why} (There is no ${id}.expected.json yet.)`);
  assert.deepEqual(summary, JSON.parse(readFileSync(file, "utf8")), why);
}

/* ===================== the real fixtures ===================== */

const files = existsSync(FIXTURES)
  ? readdirSync(FIXTURES).filter(f => f.endsWith(".json") && !f.endsWith(".expected.json")) : [];

if (!files.length){
  test("replay the saved engine answers", { skip: "fixtures are not captured yet (they need a running engine: node tests/capture-routing-fixtures.mjs)" }, () => {});
}
for (const f of files){
  const fixture = JSON.parse(readFileSync(new URL(f, FIXTURES), "utf8"));
  const id = fixture.trip.id;
  const result = replay(fixture);
  for (const [name, check] of INVARIANTS)
    test(`${id}: ${name}`, () => {
      assert.ok(result.pool.length > 0, "the saved answers produced no trips at all");
      const problem = check(result);
      assert.equal(problem, null, problem || "");
    });
  test(`${id}: ranked results match the saved snapshot`, () =>
    checkSnapshot(id, summarize(result), FIXTURES, UPDATE));
}

/* ===================== trip-specific checks =====================
   The behaviours that matter most, each pinned to one saved trip. If one of
   these fails, the app has stopped doing something it was built to do.
   docs/routing-notes.md explains the rule behind each. */

const saved = id => {
  const f = new URL(id + ".json", FIXTURES);
  return existsSync(f) ? JSON.parse(readFileSync(f, "utf8")) : null;
};
const onFixture = (id, name, fn) => {
  const fx = saved(id);
  test(`${id}: ${name}`, { skip: fx ? false : "fixture not captured" }, () => fn(fx));
};
const modes = x => x.it.legs.map(l => l.mode);
const carFree = x => !hasCar(x);
const mins = x => Math.round(x.it.duration / 60);

onFixture("park_and_ride_headlines", "driving to a GO station is the top result and clearly beats transit alone", fx => {
  const r = replay(fx);
  const top = r.main[0];
  assert.deepEqual(modes(top).filter(m => m === "CAR" || m === "RAIL"), ["CAR", "RAIL"],
    "the top card should be a drive to a station followed by a train");
  const bestCarFree = Math.min(...r.pool.filter(carFree).map(mins));
  assert.ok(mins(top) + 20 <= bestCarFree,
    `park-and-ride (${mins(top)} min) should beat transit alone (${bestCarFree} min) by 20 minutes or more`);
  assert.equal(r.fastestIt, top.it);
});

onFixture("park_and_ride_headlines", "the drive limit hides drives but never the transit options", fx => {
  const r = replay(fx, { maxDriveKm: 1 });
  assert.ok(!r.pool.some(hasCar), "no drive over 1 km should be shown with the limit at 1 km");
  assert.ok(r.pool.some(carFree), "transit options must still be there");
  assert.ok(r.raw.some(it => it.legs.some(l => l.mode === "CAR")),
    "the hidden drives must still be known, so the page can say what the limit is hiding");
});

onFixture("short_downtown_no_pointless_drive", "drives that a car-free trip beats are removed, not just folded away", fx => {
  const r = replay(fx);
  assert.ok(r.raw.some(it => it.legs.some(l => l.mode === "CAR")),
    "the engine did offer drives for this trip (if not, this fixture no longer tests the rule)");
  assert.ok(!r.pool.some(hasCar),
    "every drive here is slower and dearer than the subway or a bike, so none may be shown");
});

onFixture("go_fare_mount_joy_union", "the GO fare comes from the real fare table, with 40% off for youth", fx => {
  const adult = replay(fx), youth = replay(fx, { rider: "youth" });
  assert.equal(adult.main[0].cost.toFixed(2), "10.05");
  assert.equal(youth.main[0].cost.toFixed(2), "6.03");
});

onFixture("short_trip_pure_modes", "walking and cycling the whole way are offered on a short trip, inside their limits", fx => {
  const r = replay(fx);
  const only = m => r.pool.filter(x => modes(x).every(k => k === m));
  assert.equal(only("WALK").length, 1, "one walk-the-whole-way option");
  assert.equal(only("BICYCLE").length, 1, "one bike-the-whole-way option");
  assert.ok(mins(only("WALK")[0]) <= 45 && mins(only("BICYCLE")[0]) <= 60);
  assert.equal(only("BICYCLE")[0].cost, 0);
});

onFixture("arrive_by_evening", "Arrive by still ranks fastest first, and badges the latest departure", fx => {
  const r = replay(fx);
  assert.equal(mins(r.main[0]), Math.min(...r.pool.map(mins)), "the fastest trip leads");
  assert.ok(r.latestIt, "one trip carries the Latest leave badge");
  assert.equal(r.latestIt.startTime, Math.max(...r.pool.map(x => x.it.startTime)));
  assert.ok(r.main.some(x => x.it === r.latestIt), "and it is not hidden under more options");
  assert.equal(replay(fx, { arriveBy: false }).latestIt, null, "no such badge in Leave at mode");
});

/* ===================== proving the harness, with a made-up fixture ===================== */

const T0 = Date.parse("2026-10-06T12:00:00Z");       // Tue 8:00 AM Toronto
const iso = m => new Date(T0 + m * 60000).toISOString();
const nLeg = (mode, a, b, o = {}) => ({
  mode, distance: o.dist ?? 1000, duration: (b - a) * 60, headsign: null, rentedBike: false,
  start: { scheduledTime: iso(a), estimated: null }, end: { scheduledTime: iso(b), estimated: null },
  agency: o.ag ? { gtfsId: o.ag + ":1", name: o.ag } : null,
  route: o.rt ? { shortName: o.rt, longName: "", color: null } : null,
  from: { name: o.from || "A", lat: 43.7, lon: -79.4, stop: o.fs ? { gtfsId: o.fs } : null },
  to: { name: o.to || "B", lat: 43.7, lon: -79.4, stop: null },
  alerts: [],
});
const nNode = (...legs) => ({ duration: (legs.at(-1).end.scheduledTime && (Date.parse(legs.at(-1).end.scheduledTime) - Date.parse(legs[0].start.scheduledTime)) / 1000),
  start: legs[0].start.scheduledTime, end: legs.at(-1).end.scheduledTime, legs });

const madeUp = {
  trip: { id: "made_up", have: { carStart: true }, maxDriveKm: 15, rider: "adult",
    arriveBy: false, weekday: "tuesday", time: "08:00" },
  date: "2026-10-06", capturedAt: "2026-01-01T00:00:00Z",
  answers: [
    { combo: "Transit only", reluctance: null, nodes: [
      nNode(nLeg("WALK", 0, 5), nLeg("SUBWAY", 5, 35, { ag: "TTC", rt: "1", from: "Finch" }), nLeg("WALK", 35, 40)),
      nNode(nLeg("WALK", 10, 15), nLeg("BUS", 15, 70, { ag: "TTC", rt: "36", from: "Stop" }), nLeg("WALK", 70, 75)),
    ] },
    { combo: "Walk the whole way", reluctance: null, nodes: [] },
    { combo: "Drive to station", reluctance: 30, nodes: [
      nNode(nLeg("CAR", 0, 10, { dist: 5000 }), nLeg("WALK", 10, 12),
            nLeg("RAIL", 20, 45, { ag: "GO", rt: "LW", from: "Test GO", dist: 25000 }), nLeg("WALK", 45, 48)),
      // a far drive: hidden by the 15 km cap
      nNode(nLeg("CAR", 0, 25, { dist: 30000 }), nLeg("WALK", 25, 27),
            nLeg("RAIL", 30, 40, { ag: "GO", rt: "LW", from: "Far GO", dist: 20000 }), nLeg("WALK", 40, 42)),
    ] },
    { combo: "Drive to station", reluctance: 2, nodes: [
      nNode(nLeg("CAR", 0, 10, { dist: 5000 }), nLeg("WALK", 10, 12),
            nLeg("RAIL", 20, 45, { ag: "GO", rt: "LW", from: "Test GO", dist: 25000 }), nLeg("WALK", 45, 48)),
    ] },
  ],
};

test("harness: replay, summarize and the invariants work on a made-up fixture", () => {
  const result = replay(madeUp);
  const s = summarize(result);
  assert.ok(result.pool.length >= 2);
  assert.ok(s.main.length >= 1 && s.main.length <= 5);
  // the far drive is over the cap and must not be visible
  assert.ok(![...s.main, ...s.rest].some(t => t.legs.startsWith("CAR") && t.minutes === 42));
  for (const t of s.main.concat(s.rest)){
    assert.equal(typeof t.minutes, "number");
    assert.equal(t.cost, Number(t.cost.toFixed(2)));
    assert.ok(Array.isArray(t.badges));
  }
  assert.ok(s.main.some(t => t.legs.includes("SUBWAY 1") && t.firstBoard === "Finch"));
  for (const [name, check] of INVARIANTS) assert.equal(check(result), null, name);
  // a tighter cap hides the drive; the override reaches rankParts
  const tight = summarize(replay(madeUp, { maxDriveKm: 1 }));
  assert.ok(![...tight.main, ...tight.rest].some(t => t.legs.includes("CAR")));
});

test("harness: the snapshot check passes when nothing changed and explains itself when it did", () => {
  const dir = mkdtempSync(`${tmpdir()}/routing-`);
  const dirUrl = new URL(`file://${dir}/`);
  try {
    const s = summarize(replay(madeUp));
    assert.throws(() => checkSnapshot("made_up", s, dirUrl, false), /There is no made_up.expected.json/);
    checkSnapshot("made_up", s, dirUrl, true);                    // write it
    checkSnapshot("made_up", s, dirUrl, false);                   // matches
    const changed = JSON.parse(JSON.stringify(s));
    changed.main[0].minutes += 1;
    assert.throws(() => checkSnapshot("made_up", changed, dirUrl, false),
      /The ranked results for made_up changed\. If you changed ranking, fares or filters on purpose, re-run with UPDATE_ROUTING_SNAPSHOTS=1/);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});
