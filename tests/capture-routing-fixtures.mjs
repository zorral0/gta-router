// Saves real engine answers so tests/routing.test.mjs can replay them.
//
//   node tests/capture-routing-fixtures.mjs            every trip
//   node tests/capture-routing-fixtures.mjs <id> ...   only these
//   node tests/capture-routing-fixtures.mjs --engine http://host:8080/otp/gtfs/v1
//
// Needs the engine running (the page's own address is the default). For each
// trip in tests/routing-trips.json it asks the engine exactly what the page
// asks (same query, same variables, built by core.js) for every mode mix that
// is switched on and every car reluctance, and writes
// tests/fixtures/routing/<id>.json. No packages: Node 22+ has fetch.

import { readFileSync, writeFileSync, mkdirSync, statSync } from "node:fs";
import vm from "node:vm";

const root = new URL("../", import.meta.url);
const read = p => readFileSync(new URL(p, root), "utf8");

const args = process.argv.slice(2);
let engine = "http://localhost:8080/otp/gtfs/v1";   // same as OTP in web/app.js
const ids = [];
for (let i = 0; i < args.length; i++){
  if (args[i] === "--engine") engine = args[++i];
  else ids.push(args[i]);
}

const ctx = vm.createContext({ console });
vm.runInContext(read("web/core.js"), ctx, { filename: "core.js" });
const core = code => vm.runInContext(code, ctx);

const trips = JSON.parse(read("tests/routing-trips.json")).trips;
const chosen = ids.length ? trips.filter(t => ids.includes(t.id)) : trips;
for (const id of ids)
  if (!trips.some(t => t.id === id)) throw new Error(`No trip called "${id}" in tests/routing-trips.json`);

const DAYS = ["sunday","monday","tuesday","wednesday","thursday","friday","saturday"];
/* the next `weekday` at least 2 days after today, by Toronto's calendar */
function pickDate(weekday){
  const want = DAYS.indexOf(weekday.toLowerCase());
  if (want < 0) throw new Error(`Unknown weekday "${weekday}"`);
  const p = core(`torontoParts(${Date.now()})`);
  const base = new Date(Date.UTC(p.year, p.month - 1, p.day + 2));
  while (base.getUTCDay() !== want) base.setUTCDate(base.getUTCDate() + 1);
  return base.toISOString().slice(0, 10);
}

/* keep files small and stable: no alerts (they change by the minute), no stop
   lists, and no geometry except for car legs (tolls are priced from it) */
function slim(node){
  return { ...node, legs: node.legs.map(l => {
    const { stopCalls, legGeometry, ...rest } = l;
    return { ...rest, alerts: [],
      ...(l.mode === "CAR" && legGeometry ? { legGeometry } : {}) };
  }) };
}

async function ask(variables){
  const r = await fetch(engine, { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query: core("PC_QUERY"), variables }),
    signal: AbortSignal.timeout(60000) });
  if (!r.ok) throw new Error(`Engine answered HTTP ${r.status}`);
  const js = await r.json();
  if (js.errors) throw new Error("GraphQL errors: " + js.errors.map(e => e.message).join("; "));
  return (((js.data || {}).planConnection || {}).edges || []).map(e => slim(e.node));
}

/* run jobs, at most `n` at a time, stopping at the first failure */
async function pool(jobs, n){
  const out = new Array(jobs.length); let next = 0, failed = null;
  await Promise.all(Array.from({ length: n }, async () => {
    while (!failed && next < jobs.length){
      const i = next++;
      try { out[i] = await jobs[i](); } catch (e){ failed = failed || e; }
    }
  }));
  if (failed) throw failed;
  return out;
}

mkdirSync(new URL("tests/fixtures/routing/", root), { recursive: true });
for (const t of chosen){
  const date = pickDate(t.weekday);
  console.log(`${t.id}: ${t.weekday} ${date} ${t.time}${t.arriveBy ? " (arrive by)" : ""}`);
  const jobs = [], meta = [];
  const combos = JSON.parse(core(`JSON.stringify(activeCombos(${JSON.stringify(t.have)}))`));
  for (const c of combos){
    const rels = JSON.parse(core(`JSON.stringify(reluctancesFor(COMBOS.find(c => c.key === ${JSON.stringify(c.key)})))`));
    for (const r of rels){
      meta.push({ combo: c.key, reluctance: r });
      jobs.push(() => ask(core(`planVariables(COMBOS.find(c => c.key === ${JSON.stringify(c.key)}),
        ${JSON.stringify(t.from)}, ${JSON.stringify(t.to)}, ${JSON.stringify(date)},
        ${JSON.stringify(t.time)}, ${!!t.arriveBy}, ${JSON.stringify(r)}, "safest")`)));
    }
  }
  const results = await pool(jobs, 4);
  const answers = meta.map((m, i) => ({ ...m, nodes: results[i] }));
  const file = new URL(`tests/fixtures/routing/${t.id}.json`, root);
  writeFileSync(file, JSON.stringify({ trip: t, date, capturedAt: new Date().toISOString(), answers }));
  console.log(`  ${answers.length} answers, ${(statSync(file).size / 1024).toFixed(0)} KB`);
}
