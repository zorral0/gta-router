/* GTA Router - the app's rules, with no map and no page in them.

   Fares, tolls, the mode mixes the planner fires, how results are filtered,
   deduplicated and ranked, and Toronto time. index.html loads this first, as
   a classic script, so everything here is a plain global exactly as it was
   when it lived inline. Keeping it free of the DOM and the map is what lets
   tests/core.test.mjs run it in Node without a browser.

   Globals this file READS but does not own (index.html declares them):
     rider     "adult" | "youth"
     GO_FARES  the GO fare table from go-fares.json, or null until loaded
   TOLL and TOLLRATE are declared here and filled in by index.html once
   toll-roads.json and toll-rates.json arrive. */
"use strict";

/* ---- Toronto time ----
   Every timetable here runs on Toronto's clock, but a bare Date reads the
   clock of whatever computer the page is on: a visitor in Vancouver asking
   for 8:00 AM got Toronto's 11:00 AM, and the 407 rate band and Burlington's
   free evening rides were judged on the wrong hour. All date maths goes
   through these instead. */
const TZ = "America/Toronto";
const tzFmt = new Intl.DateTimeFormat("en-CA", { timeZone: TZ, hourCycle: "h23",
  year: "numeric", month: "2-digit", day: "2-digit",
  hour: "2-digit", minute: "2-digit", second: "2-digit" });
/* A "wall clock" Date: a local Date whose fields (getHours, getDay,
   getDate...) read what a Toronto clock reads at instant `ms`. Fine for
   reading fields and for calendar arithmetic; never send it to the engine. */
function torontoParts(ms){
  const p = {};
  for (const x of tzFmt.formatToParts(new Date(ms))) p[x.type] = +x.value;
  p.hour %= 24;
  return p;
}
function torontoWall(ms){
  const p = torontoParts(ms);
  return new Date(p.year, p.month - 1, p.day, p.hour, p.minute, p.second);
}
/* the real instant at which Toronto's clock reads `date` ("YYYY-MM-DD") and
   `time` ("HH:MM"), as an ISO string for the engine */
function torontoISO(date, time){
  const [y, mo, d] = date.split("-").map(Number), [h, mi] = time.split(":").map(Number);
  const want = Date.UTC(y, mo - 1, d, h, mi);
  const offsetAt = ms => {          // Toronto minus UTC at instant ms, in ms
    const p = torontoParts(ms);     // parts, not a wall Date: the browser's own
                                    // DST gap must not shift the answer
    return Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute, p.second)
      - Math.floor(ms / 1000) * 1000;
  };
  let ms = want - offsetAt(want);
  ms = want - offsetAt(ms);         // second pass settles the DST changeover days
  return new Date(ms).toISOString();
}

/* ---- fare model ---- */
// verified against each agency's official fare page (July 2026, Halton
// 2026-09-19); PRESTO-level, and an unverified fare says so in the UI
/* [feed id, adult, youth (null = no youth rate modelled), verified,
    transfer program]. The feed id is the one in engine/build-config.json,
    which is also the prefix of every agency's gtfsId (see feedOf). These
    used to be matched against agency NAMES by substring, which is how a
    "MILTON" key once caught HAMILTON. tests/fare-sync.py checks every
    loaded feed has a row.

    The transfer program decides who rides free, and the two are not the
    same thing:
      onefare   Ontario's One Fare. Free transfer to and from GO, and
                between these agencies and the TTC.
      gocofare  Halton. Checked against Metrolinx's own One Fare page on
                2026-09-19: Oakville, Burlington and Milton are NOT in it.
                Each runs its own GO co-fare instead, which makes the local
                ride free when the trip touches GO, but a transfer from the
                TTC with no GO in it is paid in full. */
const LOCAL_FARES = [["TTC",3.30,2.35,true,"onefare"],
                     ["YRT",4.24,3.29,true,"onefare"],["MIWAY",3.50,2.90,true,"onefare"],
                     ["DRT",3.84,3.46,true,"onefare"],["BRAMPTON",3.55,2.95,true,"onefare"],
                     // Halton, verified 2026-09-19. Oakville youth 13-19 ride
                     // FREE every day with PRESTO. Burlington youth also ride
                     // free on weekdays after 6 pm and at weekends, which is
                     // NOT modelled, so an evening Burlington fare reads high.
                     // Milton takes no PRESTO at all: its single-use e-ticket
                     // price is modelled (cash is $4.25 for adult and youth).
                     ["OAKVILLE",3.50,0.00,true,"gocofare"],
                     // Burlington youth also ride free on weekday evenings and
                     // all weekend: see burlingtonYouthFree(), which is a rule
                     // rather than a number because it depends on the clock.
                     ["BURLINGTON",2.85,2.00,true,"gocofare"],
                     ["MILTON",3.85,2.90,true,"gocofare"]];
// UP PRESTO fares: any trip to or from Pearson pays the airport fare;
// city-only trips (Union, Bloor, Weston) are 4.71-5.02, top modelled.
const GO_BASE = 3.70, GO_PER_KM = 0.11, UP_FARE = 9.25, UP_PEARSON_YOUTH = 7.41,
      UP_CITY = 5.02, UP_YOUTH = 3.39;
const GO_YOUTH_FACTOR = 0.60;  // 40% off, gotransit.com youth discount
// GO station parking is free today; the knob is here for the day it isn't
const GAS_PER_KM = 0.14, WEAR_PER_KM = 0.10, GO_PARKING = 0.0;
// Bike Share Toronto pay-as-you-go, classic bike: $1 unlock + 12 cents/min
// (verified Jul 2026, bikesharetoronto.com/pricing; e-bikes 20 cents/min
// not modelled - OTP doesn't tell us which kind we'd get)
const BIKESHARE_UNLOCK = 1.00, BIKESHARE_PER_MIN = 0.12;
const TRANSIT = new Set(["BUS","RAIL","SUBWAY","TRAM","FERRY"]);
function stopIdOf(place){
  const id = ((place || {}).stop || {}).gtfsId || "";
  return id.startsWith("GO:") ? id.slice(3) : null;
}
function goTableFare(fromStop, toStop){
  if (!GO_FARES || !fromStop || !toStop) return null;
  const o = GO_FARES.zones[fromStop], d = GO_FARES.zones[toStop];
  if (!o || !d) return null;
  const p = GO_FARES.fares[o + "|" + d] ?? GO_FARES.fares[d + "|" + o];
  return p ?? null;
}

/* Which feed a leg belongs to: the prefix of its agency's gtfsId ("GO:GO",
   "TTC:1", "MILTON:0"), the same ids as engine/build-config.json. */
function feedOf(l){ return (((l.agency || {}).gtfsId) || "").split(":")[0]; }
/* UP Express replacement buses run inside the GO feed as route 35, "Union
   Pearson Express" (they ran 2026-09-11 to 09-20). They charge the UP fare,
   so they count as UP, not GO. */
const isUP = l => feedOf(l) === "UP"
  || /union pearson/i.test((l.route || {}).longName || "");
const isGO = l => feedOf(l) === "GO" && !isUP(l);
const FEED_NAME = { GO: "GO Transit", UP: "UP Express", TTC: "TTC", YRT: "YRT",
  MIWAY: "MiWay", DRT: "DRT", BRAMPTON: "Brampton Transit",
  OAKVILLE: "Oakville Transit", BURLINGTON: "Burlington Transit",
  MILTON: "Milton Transit" };
/* the name a rider knows the leg's agency by */
function prettyAgency(l){
  if (isUP(l)) return "UP Express";
  return FEED_NAME[feedOf(l)] || (l.agency || {}).name || "Transit";
}

/* Burlington youth 13-19 ride free on weekdays after 6 pm and all weekend
   (burlington.ca/en/transit/fares.aspx, checked 2026-09-19). It is the only
   fare here that depends on WHEN you board, so it cannot live as a number in
   LOCAL_FARES. Judged on the time you board that agency, not on when the
   whole trip starts: an afternoon trip that reaches Burlington after 6 pm
   qualifies, and the rider is the one standing at the stop. */
function burlingtonYouthFree(ms){
  if (!ms) return false;             // unknown time: charge the fare
  const d = torontoWall(ms), day = d.getDay();   // 0 Sunday ... 6 Saturday
  return day === 0 || day === 6 || d.getHours() >= 18;
}

function itineraryCostDetail(it){
  const legs = it.legs, tlegs = legs.filter(l => TRANSIT.has(l.mode));
  const items = [];
  const goLegs = tlegs.filter(isGO);
  const usedGo = goLegs.length > 0;
  if (usedGo){
    const exact = goTableFare(stopIdOf(goLegs[0].from),
                              stopIdOf(goLegs[goLegs.length-1].to));
    let f, label;
    if (exact != null){ f = exact; label = "GO Transit"; }
    else {
      const goKm = goLegs.reduce((s,l) => s + (l.distance||0)/1000, 0);
      f = GO_BASE + GO_PER_KM * goKm;
      label = "GO Transit (estimated)";
    }
    if (rider === "youth"){ f *= GO_YOUTH_FACTOR; label += ", youth 40% off"; }
    items.push({ label, amount: f });
  }
  const upLegs = tlegs.filter(isUP);
  if (upLegs.length){
    const airport = upLegs.some(l => [l.from, l.to].some(
      e => ((e && e.name) || "").toUpperCase().includes("PEARSON")));
    const youth = rider === "youth";
    items.push({ label: "UP Express" + (airport ? " to or from Pearson" : "")
                        + (youth ? ", youth" : ""),
                 amount: airport ? (youth ? UP_PEARSON_YOUTH : UP_FARE)
                                 : (youth ? UP_YOUTH : UP_CITY) });
  }
  const ridden = [];
  for (const l of tlegs){
    const feed = feedOf(l);
    const hit = LOCAL_FARES.find(([k]) => k === feed);
    if (hit && !ridden.some(r => r.key === feed))
      ridden.push({ leg: l, key: hit[0], at: l.startTime,
                    fare: (rider === "youth" && hit[2] != null) ? hit[2] : hit[1],
                    ver: hit[3], prog: hit[4] });
  }
  /* Who rides free depends on WHICH programme the agency is in, not just on
     boarding order. A One Fare agency is free once GO is in the trip or once
     another One Fare agency has been paid. A Halton co-fare agency is free
     only when the trip touches GO: it has no free transfer from the TTC. */
  let paidOneFare = false;
  ridden.forEach(r => {
    let free = false, why = "";
    if (r.prog === "gocofare"){ free = usedGo; why = "GO co-fare"; }
    else if (usedGo || paidOneFare){ free = true; why = "One Fare transfer"; }
    else paidOneFare = true;
    // a free ride for another reason still beats paying, whatever programme
    if (!free && rider === "youth" && r.key === "BURLINGTON"
        && burlingtonYouthFree(r.at)){
      free = true; why = "youth, evenings and weekends";
    }
    items.push({ label: prettyAgency(r.leg)
      + (free ? `, free (${why})`
              : (r.ver ? "" : ", fare unverified")), amount: free ? 0 : r.fare });
  });
  legs.forEach((l,i) => {
    if (l.mode === "BICYCLE" && l.rentedBike){
      const mins = Math.ceil((l.duration||0)/60);
      items.push({ label: `Bike Share (${mins} min, $1 + 12¢/min)`,
                   amount: BIKESHARE_UNLOCK + mins * BIKESHARE_PER_MIN });
    }
    if (l.mode === "CAR"){
      const later = legs.slice(i+1).some(x => TRANSIT.has(x.mode));
      const km = (l.distance||0)/1000;
      items.push({ label: `Driving (${km.toFixed(1)} km, gas + wear)`,
                   amount: km * (GAS_PER_KM + WEAR_PER_KM) });
      // Highway 407 is billed by the kilometre and the engine knows nothing
      // about it, so the app measures the tolled metres off the route
      // geometry and prices them itself - see the toll blocks below.
      const toll = legTollCost(l);
      if (toll > 0)
        items.push({ label: `Highway 407 toll (estimated, `
          + `${(legTollM(l)/1000).toFixed(1)} km)`, amount: toll });
      // a drive BEFORE transit parks at the station; a car AFTER transit is
      // a pickup or your car already waiting, which pays nothing. Every trip
      // the app prices has transit in it, so there is no third case.
      if (later && GO_PARKING > 0) items.push({ label: "Station parking", amount: GO_PARKING });
    }
  });
  return { total: items.reduce((s,x) => s + x.amount, 0), items };
}
function itineraryCost(it){ return itineraryCostDetail(it).total; }


/* ---- toll roads ----
   OTP 2.9 has NO toll support (checked its GraphQL schema: no avoidTolls,
   no toll cost, nothing), so the engine happily sends the "fastest" drive
   27 km up the 407 ETR and then prices the trip at the transit fare alone.
   web/toll-roads.json is a ~30 m grid of every toll=yes way in the OSM
   extract, built by make_toll_cells.py; a car leg whose geometry runs
   through those cells is on a toll road. We cannot make OTP route AROUND
   one - all we can do is say so, and hide those options on request. */
const TOLL_MIN_M = 400;      // ignore a leg that merely clips a toll ramp
let TOLL = null;
function inToll(lng, lat){
  const x = Math.floor((lat - TOLL.lat0) / TOLL.dlat),
        y = Math.floor((lng - TOLL.lon0) / TOLL.dlon);
  for (let dx = -1; dx <= 1; dx++){
    const ys = TOLL.cells[x + dx];
    if (!ys) continue;
    for (let dy = -1; dy <= 1; dy++) if (ys.has(y + dy)) return true;
  }
  return false;
}
/* Everything the geometry can tell us about one driving leg's toll section:
   how many metres of it are tolled, how those metres split across 407 ETR's
   twelve rate zones, which way it was going and when it got on. Cached on
   the leg (the grid has to be loaded first, so nothing is cached before
   that - index.html re-renders once it arrives). */
function legTollGeom(l){
  if (!TOLL || l.mode !== "CAR" || !l.legGeometry) return null;
  if (l._tollGeom !== undefined) return l._tollGeom;
  const pts = decodePolyline(l.legGeometry.points);   // [lng, lat]
  const byZone = {};
  let m = 0, run = 0, enteredAt = null, kmFirst = null, kmLast = null;
  for (let i = 1; i < pts.length; i++){
    const a = pts[i-1], b = pts[i];
    const dy = (b[1] - a[1]) * 111320,
          dx = (b[0] - a[0]) * 111320 * Math.cos(a[1] * Math.PI / 180);
    const d = Math.hypot(dx, dy);
    run += d;
    if (!inToll(a[0], a[1]) || !inToll(b[0], b[1])) continue;
    if (enteredAt === null) enteredAt = run - d;      // metres driven first
    m += d;
    const km = tollKmAlong((a[0] + b[0]) / 2, (a[1] + b[1]) / 2);
    if (km != null){
      if (kmFirst === null) kmFirst = km;
      kmLast = km;
      const z = tollZoneAt(km);
      byZone[z] = (byZone[z] || 0) + d;
    }
  }
  const g = m ? { m, byZone, legM: run, enteredAt,
                  // 407 rates differ by direction; east = further along the
                  // centreline, which runs QEW -> Brock Rd
                  dir: (kmLast > kmFirst) ? "eastbound" : "westbound" } : null;
  // The zone split needs the RATES file (that is where the centreline lives),
  // and the two files land independently. If the grid got here first, hand
  // back what we have but do NOT cache it - a leg measured in that window
  // would otherwise keep an empty zone split for good and later price at
  // nothing but the flat per-trip charge.
  if (!TOLLRATE) return g;
  return (l._tollGeom = g);
}
function legTollM(l){ const g = legTollGeom(l); return g ? g.m : 0; }
const tollM = it => it.legs.reduce((s, l) => s + legTollM(l), 0);
const isTolled = it => tollM(it) >= TOLL_MIN_M;

/* ---- what the toll costs ----
   OTP prices nothing about the 407, so before this the app could headline a
   27 km run up it at the transit fare alone - and a tolled trip could take
   the "Cheapest" badge off a genuinely cheaper one. 407 ETR bills per
   kilometre at a rate that depends on which of its 12 zones you are in,
   which direction you are going, and which time band you ENTERED in, plus a
   flat charge per trip. web/toll-rates.json carries their published
   light-vehicle chart and the zone geometry (see make_toll_rates.py); this
   turns a leg's tolled metres into dollars.
   It is an ESTIMATE and labelled as one wherever it is shown: the metres
   come from the engine's idea of the route, statutory holidays (billed at
   weekend rates) are not modelled, and it assumes a transponder - without
   one 407 ETR adds a camera charge per trip, which the detail view says. */
let TOLLRATE = null;
/* how far along the 407 a point is, in km from the QEW end (null if the
   rates file hasn't loaded). The centreline is ~50 points, so this is a
   short scan, and it only ever runs on points already known to be tolled. */
function tollKmAlong(lng, lat){
  if (!TOLLRATE) return null;
  const line = TOLLRATE.centreline, cum = TOLLRATE.centreline_km;
  const K = 111320 * Math.cos(lat * Math.PI / 180);
  const px = lng * K, py = lat * 111320;
  let best = Infinity, bestKm = 0;
  for (let i = 1; i < line.length; i++){
    const ax = line[i-1][0] * K, ay = line[i-1][1] * 111320,
          bx = line[i][0] * K, by = line[i][1] * 111320;
    const dx = bx - ax, dy = by - ay, L2 = dx*dx + dy*dy;
    const t = L2 ? Math.max(0, Math.min(1, ((px-ax)*dx + (py-ay)*dy) / L2)) : 0;
    const qx = ax + t*dx, qy = ay + t*dy;
    const d = Math.hypot(px - qx, py - qy);
    if (d < best){
      best = d;
      bestKm = cum[i-1] + t * (cum[i] - cum[i-1]);
    }
  }
  return bestKm;
}
/* which zone (1-12) a kilometre mark falls in */
function tollZoneAt(km){
  const zs = TOLLRATE.zones;
  for (let i = zs.length - 1; i >= 0; i--) if (km >= zs[i].km) return zs[i].n;
  return 1;
}
/* the rate band a trip entering at `when` is billed in. The last band of the
   day wraps past midnight, so anything before the first one bills at it. */
function tollBandAt(when){
  const weekend = when.getDay() === 0 || when.getDay() === 6;
  const kind = weekend ? "weekend" : "weekday";
  const bands = TOLLRATE.bands[kind];
  const hm = String(when.getHours()).padStart(2, "0") + ":"
           + String(when.getMinutes()).padStart(2, "0");
  let idx = -1;
  for (let i = 0; i < bands.length; i++) if (hm >= bands[i]) idx = i;
  return { kind, idx: idx < 0 ? bands.length - 1 : idx };
}
/* dollars for one leg's toll section: per-zone kilometres at that zone's
   rate, plus the flat per-trip charge. 0 when there is no toll, no rates
   file, or the leg merely clips a ramp. */
function legTollCost(l){
  const g = legTollGeom(l);
  if (!g || !TOLLRATE || g.m < TOLL_MIN_M) return 0;
  // billed on the time you got ON, not when the drive started
  const enter = torontoWall(l.startTime + (g.legM
    ? (g.enteredAt / g.legM) * (l.duration * 1000) : 0));
  const band = tollBandAt(enter);
  const rates = TOLLRATE.rates[g.dir][band.kind][band.idx];
  let total = 0;
  for (const z in g.byZone) total += (g.byZone[z] / 1000) * rates[z - 1] / 100;
  return total + TOLLRATE.fees.trip_charge;
}
const tollCost = it => it.legs.reduce((s, l) => s + legTollCost(l), 0);
/* 407 ETR changes its rates every January 1st, so a chart from an earlier
   year prices every toll at last year's rates. True once Toronto's calendar
   has moved past the chart's year (re-run make_toll_rates.py then). */
function tollRatesStale(rate, nowMs){
  const eff = rate && rate._effective;
  if (!eff) return false;
  return torontoWall(nowMs).getFullYear() > +String(eff).slice(0, 4);
}
function decodePolyline(str){ // Google encoded polyline, precision 5
  let i = 0, lat = 0, lng = 0; const out = [];
  while (i < str.length){
    for (const which of [0,1]){
      let shift = 0, result = 0, b;
      do { b = str.charCodeAt(i++) - 63; result |= (b & 0x1f) << shift; shift += 5; }
      while (b >= 0x20);
      const d = (result & 1) ? ~(result >> 1) : result >> 1;
      if (which === 0) lat += d; else lng += d;
    }
    out.push([lng / 1e5, lat / 1e5]);
  }
  return out;
}

/* ---- planning (OTP 2.9 planConnection: access and egress street modes
   are separate lists, so any mix of start and end is one query) ----
   need: which "Using:" toggles must be on (carStart = drive to a station,
   carEnd = a car for the last leg). needsLeg: results must really contain
   that leg (OTP pads with plain walk+transit trips otherwise).
   carAfter/rentEnd: the car / rented-bike legs must come AFTER transit.
   drive: run twice (car reluctance 30 + 2) and cap by the drive filter. */
const COMBOS = [
  { key: "Transit only",
    access: ["WALK"], egress: ["WALK"], need: [] },
  { key: "Bike to station",
    access: ["BICYCLE_PARKING"], egress: ["WALK"],
    need: ["bike"], needsLeg: "BICYCLE" },
  // Bike Share ridden TO the boarding station (rental as ACCESS - the
  // mirror of "Bike Share at the end"). Same walkReluctance-6 trick: for
  // short accesses the engine otherwise keeps the plain-walk sibling
  // (rental pays unlock time internally) and the rental never surfaces.
  { key: "Bike Share at the start",
    access: ["BICYCLE_RENTAL", "WALK"], egress: ["WALK"],
    need: ["share"], rentStart: true, walkReluctance: 6.0 },
  { key: "Drive to station",
    access: ["CAR_PARKING"], egress: ["WALK"],
    // one extra reluctance, this combo only: see the DRIVE_RELUCTANCE note
    need: ["carStart"], drive: true, needsLeg: "CAR", extraReluctance: [8.0] },
  { key: "Drive at the end",
    access: ["WALK"], egress: ["WALK", "CAR_PICKUP"],
    need: ["carEnd"], drive: true, carAfter: true },
  // walkReluctance 6: for end-walks under ~2 km the engine treats the
  // walk ending and the Bike Share ending of the same ride as siblings
  // and keeps the walk one (rental pays unlock/dock time internally), so
  // Bike Share never surfaced. These queries EXIST to find the rental
  // ending - make walking expensive inside them; the ranked list then
  // compares the result fairly against everything else. (Same trick as
  // carReluctance 30 for the near-station drive queries.)
  { key: "Bike Share at the end",
    access: ["WALK"], egress: ["WALK", "BICYCLE_RENTAL"],
    need: ["share"], rentEnd: true, walkReluctance: 6.0 },
  { key: "Drive + Bike Share at the end",
    access: ["CAR_PARKING"], egress: ["WALK", "BICYCLE_RENTAL"],
    need: ["carStart", "share"], drive: true, needsLeg: "CAR", rentEnd: true,
    walkReluctance: 6.0 },
  { key: "Bike + Bike Share at the end",
    access: ["BICYCLE_PARKING"], egress: ["WALK", "BICYCLE_RENTAL"],
    need: ["bike", "share"], needsLeg: "BICYCLE", rentEnd: true,
    walkReluctance: 6.0 },
  { key: "Bike + drive at the end",
    access: ["BICYCLE_PARKING"], egress: ["WALK", "CAR_PICKUP"],
    need: ["bike", "carEnd"], drive: true, needsLeg: "BICYCLE", carAfter: true },
  // Pure modes, no transit at all, for when biking or walking the whole way
  // is simply faster. `directOnly` is what stops the engine padding the
  // answer with the walk+transit trips it otherwise prefers - ask for
  // direct:[BICYCLE] alone and you get transit itineraries back instead.
  //
  // maxMin keeps these honest rather than noisy. A pure ride is free, and
  // renderResults deliberately never hides the cheapest option, so an
  // uncapped 3-hour walk would pin itself to the top of every long trip.
  // Past these limits nobody is choosing to walk or ride anyway.
  { key: "Bike the whole way", pure: "BICYCLE", need: ["bike"], maxMin: 60 },
  // Bike Share the whole way: walk to a dock, ride, walk from a dock. The
  // engine refuses a rental on its own ("needs to be combined with WALK"),
  // and with walking at normal cost it just returns the plain walk on short
  // trips, so walking is made expensive here as in the other Bike Share
  // combos. A result with no rented bike in it is that plain walk, which
  // "Walk the whole way" already covers, so the filter drops it.
  { key: "Bike Share the whole way", pure: "BICYCLE_RENTAL",
    direct: ["WALK", "BICYCLE_RENTAL"], need: ["share"],
    walkReluctance: 6.0, maxMin: 60 },
  { key: "Walk the whole way", pure: "WALK",    need: [],       maxMin: 45 },
];

/* How reluctant to drive, once per query, for every combo with drive:true.
   Reluctance is the only knob that changes which lot the engine picks (OTP
   2.9 has no "max drive distance" and no way to name a station: the request
   preferences are car.reluctance, car.boardCost and parking filters), and
   each value returns the one lot that is optimal at it. Measured from a
   suburban origin to downtown, distinct lots returned per value:
     30 and up  2.3 / 2.4 km  (the walk-to-your-own-station tier)
     4 to 12    2.5 km only
     2 to 3     2.5 km + 24.8 km
     1 to 1.5   2.5 + 24.8 + 33.5 + 38.6 km   <- the only wide answer
   So 1.0 is what surfaces a middle-distance station; 30 is kept because at
   1.0 the very-near lots drop out, and 2.0 because the near/middle split is
   origin-dependent and one more query is cheap (they all run in parallel).
   Values below 1.0 only buy longer drives, which the drive cap and
   driveHint already handle.

   8.0 (see extraReluctance on "Drive to station") was added 2026-09-19 after
   tests/reluctance-ladder.py priced every candidate ladder over 25 trips. The
   band between 2 and 30 was a real hole: on Markham to Square One it is the
   only value that reaches a lot catching a GO train 5 minutes earlier, and
   neither a bigger `first`, a wider searchWindow nor a looser similar-legs
   filter surfaces it at any other reluctance.

   Be clear about the size of this: 5 minutes on 1 trip in 25, and querying
   EVERY value from 30 down to 1 buys nothing beyond it. Measured in the
   browser, adding 8.0 to ALL FOUR drive combos cost 0.8-2.4 s on every plan,
   which is a bad trade for a 4% hit rate. It is on the primary drive combo
   only, which is where the whole measured win came from. */
const DRIVE_RELUCTANCE = [30.0, 2.0, 1.0];

/* true when the itinerary uses transit and every leg matching `match`
   comes AFTER the last transit leg (i.e. it really is an "at the end" leg) */
function endLegOnly(it, match){
  let lastTransit = -1;
  it.legs.forEach((l, i) => { if (TRANSIT.has(l.mode)) lastTransit = i; });
  if (lastTransit < 0) return false;
  const hits = it.legs.map((l, i) => match(l) ? i : -1).filter(i => i >= 0);
  return hits.length > 0 && hits.every(i => i > lastTransit);
}
/* mirror of endLegOnly for the START: transit is used and every leg
   matching `match` comes BEFORE the first transit leg (a real "at the
   start" access leg - e.g. a rented Bike Share bike ridden to the station) */
function startLegOnly(it, match){
  let firstTransit = -1;
  it.legs.forEach((l, i) => { if (firstTransit < 0 && TRANSIT.has(l.mode)) firstTransit = i; });
  if (firstTransit < 0) return false;
  const hits = it.legs.map((l, i) => match(l) ? i : -1).filter(i => i >= 0);
  return hits.length > 0 && hits.every(i => i < firstTransit);
}
/* reshape a planConnection itinerary to the leg fields the rest of the
   app has always used (startTime/endTime millis, intermediatePlaces).
   When the engine has LIVE data (GTFS-RT updaters running), each LegTime
   carries estimated.time - prefer it, and keep the delay in seconds
   (computed from the two timestamps, so the Duration scalar format
   never matters). estimated == null means schedule-only. */
/* GTFS-RT service alerts: keep the currently-in-effect ones, dedupe by id
   (the same alert rides in on several legs/stops), and hand back a clean,
   plain-words shape. effective*Date are epoch SECONDS (OTP GTFS API). An
   alert with no dates is treated as always-active. */
function cleanAlerts(raw){
  const now = Date.now();
  const out = [], seen = new Set();
  for (const a of (raw || [])){
    const start = a.effectiveStartDate ? a.effectiveStartDate * 1000 : null;
    const end = a.effectiveEndDate ? a.effectiveEndDate * 1000 : null;
    if (start && start > now) continue;        // not started yet
    if (end && end < now) continue;            // already over
    const head = (a.alertHeaderText || "").trim();
    const desc = (a.alertDescriptionText || "").trim();
    if (!head && !desc) continue;              // nothing to show
    const key = a.id || (head + "|" + desc);
    if (seen.has(key)) continue;
    seen.add(key);
    /* The TTC feed hard-caps alertHeaderText at 32 characters and cuts
       mid-word ("16 Mccowan: Buses are not stoppi"). Measured against the
       live feed: no header anywhere exceeded 32, 29 of 79 sat
       exactly at 32, every one of those had a description, and none ended in
       sentence punctuation. So a 32-char header that doesn't end a sentence
       is a truncated one. The description is the whole story (sometimes
       worded differently, not just a longer prefix), so show that instead of
       a broken title followed by the real text. */
    const cut = head && desc
      && ((head.length === 32 && !/[.!?]$/.test(head))
          || (desc.length > head.length && desc.slice(0, head.length) === head));
    out.push({ id: key, header: cut ? desc : (head || desc),
      desc: cut ? "" : (desc && desc !== head ? desc : ""),
      // feed text becomes a clickable href: only plain web links, never
      // javascript: or data: (escaping alone does not stop those)
      url: /^https?:\/\//i.test(a.alertUrl || "") ? a.alertUrl : "", severity: a.alertSeverityLevel || "",
      feed: a.feed || "" });   // present on the global query, absent on legs
  }
  return out;
}
function normalizeItin(n){
  return { duration: n.duration,
    startTime: Date.parse(n.start), endTime: Date.parse(n.end),
    legs: n.legs.map(l => {
      const sSched = (l.start || {}).scheduledTime,
            eSched = (l.end || {}).scheduledTime;
      const sEst = ((l.start || {}).estimated || {}).time,
            eEst = ((l.end || {}).estimated || {}).time;
      return { ...l,
        startTime: Date.parse(sEst || sSched),
        endTime: Date.parse(eEst || eSched),
        live: !!(sEst || eEst),
        rtDelaySec: sEst ? Math.round((Date.parse(sEst) - Date.parse(sSched)) / 1000) : null,
        alerts: cleanAlerts(l.alerts),
        intermediatePlaces: (l.stopCalls || []).slice(1, -1) };
    }) };
}

/* The drive slider is labelled "Longest drive (to the station, or at the end)"
   and that is now what it measures. It used to SUM every car leg, which was
   the same number for every trip the app could produce, because no mode mix
   made two car legs. Once one does, summing means a 2 km drive to the station
   plus a 13 km lift at the far end reads as a 15 km drive and vanishes at the
   default setting, even though neither drive is long. Measure the longest leg,
   which is what the label promises and what a person pictures. */
function longestCarLegM(it){
  return it.legs.reduce((m, l) =>
    l.mode === "CAR" ? Math.max(m, l.distance || 0) : m, 0);
}

/* Merge the drive queries keeping the pool WIDE IN DRIVE DISTANCE, not just
   fast. This used to be sort-by-duration + slice(0, 6), which quietly threw
   away every short-drive option the moment six longer-drive ones were faster
   - so the drive slider, set low, had nothing left to show. Now: the fastest
   two in each 10 km band of driving, plus the fastest few overall, capped.
   Everything kept is still ranked normally afterwards (and anything over the
   cap stays hidden by the slider, which driveHint reports). */
const DRIVE_BAND_M = 10000, DRIVE_PER_BAND = 2, DRIVE_KEEP = 10;
function spreadByDrive(its){
  const byDur = its.slice().sort((a, b) => a.duration - b.duration);
  const kept = new Set(byDur.slice(0, 4));          // the outright fastest
  const bands = new Map();
  for (const it of byDur){                          // already fastest-first
    const b = Math.floor(longestCarLegM(it) / DRIVE_BAND_M);
    const n = (bands.get(b) || 0);
    if (n >= DRIVE_PER_BAND) continue;
    bands.set(b, n + 1);
    kept.add(it);
  }
  return byDur.filter(it => kept.has(it)).slice(0, DRIVE_KEEP);
}

/* Where each ride boards is part of the pattern. Without it, two
   park-and-rides to DIFFERENT stations that happened to take the same number
   of minutes collapsed into one card, and "also 8:10" named a departure from
   somewhere else entirely. */
const itinSig = it => Math.round(it.duration/60) + "|" + it.legs.map(l =>
  l.mode + ((l.route||{}).shortName || "")
  + (TRANSIT.has(l.mode)
      ? "@" + ((((l.from || {}).stop || {}).gtfsId) || (l.from || {}).name || "")
      : "")).join(",");

/* the same trip pattern often comes back several times (other query, later
   departure). Keep ONE card, but remember the other departure times so
   "when's the next one?" isn't silently erased.
   Returns copies and never writes to the input: the results are re-rendered
   from the same stored trips whenever a filter changes, and merging into
   those used to leave a hidden trip's time stuck on a visible card. */
function dedupeAlts(list){
  const kept = new Map();
  for (const it of list){
    const sig = itinSig(it);
    const k = kept.get(sig);
    if (!k){ kept.set(sig, { ...it, altTimes: (it.altTimes || []).slice() }); continue; }
    for (const t of [it.startTime, ...(it.altTimes || [])])
      if (t !== k.startTime && !k.altTimes.includes(t)) k.altTimes.push(t);
  }
  return [...kept.values()];
}

/* ---- what each mode mix asks the engine for, and what it keeps ----
   tests/route-audit.py mirrors these three, and tests/core.test.mjs fails
   if the mirror ever answers differently. */
/* the bike routing trade-off picked in Trip options. "safest" is the
   engine's own default (router-config.json), so it sends nothing. */
const BIKE_OPT = { balanced: "SAFE_STREETS", fastest: "SHORTEST_DURATION" };
function comboModes(combo){
  return combo.pure
    ? { directOnly: true, direct: combo.direct || [combo.pure] }
    : { transit: { access: combo.access, egress: combo.egress } };
}
function comboPrefs(combo, carReluctance, bikePref){
  // per-request bike optimization only matters when this mode mix
  // actually rides a bike (own bike to a station, Bike Share, or the
  // whole way)
  const usesBike = combo.pure === "BICYCLE"
    || combo.pure === "BICYCLE_RENTAL"
    || (combo.access || []).includes("BICYCLE_PARKING")
    || (combo.access || []).includes("BICYCLE_RENTAL")
    || (combo.egress || []).includes("BICYCLE_RENTAL");
  const bikeOpt = usesBike && BIKE_OPT[bikePref]
    ? { bicycle: { optimization: { type: BIKE_OPT[bikePref] } } } : {};
  const street = Object.assign({},
    carReluctance ? { car: { reluctance: carReluctance } } : {},
    combo.walkReluctance ? { walk: { reluctance: combo.walkReluctance } } : {},
    bikeOpt);
  return Object.keys(street).length ? { street } : null;
}
/* Which of the engine's answers really belong to this mode mix. */
function filterCombo(combo, its){
  const rented = l => l.mode === "BICYCLE" && l.rentedBike;
  // a pure ride is a single mode end to end and has no departure choices to
  // spread, so keep just the fastest one - and only if it's inside the
  // effort cap
  if (combo.pure){
    const ok = combo.pure === "BICYCLE_RENTAL"
      ? it => it.legs.some(rented)
              && it.legs.every(l => l.mode === "WALK" || rented(l))
      : it => it.legs.length && it.legs.every(l => l.mode === combo.pure);
    return its.filter(it => ok(it) && it.duration <= combo.maxMin * 60)
      .sort((a, b) => a.duration - b.duration).slice(0, 1);
  }
  // results must actually contain transit and the advertised access leg -
  // OTP pads with plain walk+transit trips that belong to Transit only
  its = its.filter(it => it.legs.some(l => TRANSIT.has(l.mode)));
  if (combo.needsLeg)
    its = its.filter(it =>
      it.legs.some(l => l.mode === combo.needsLeg && !l.rentedBike));
  if (combo.carAfter)
    its = its.filter(it => endLegOnly(it, l => l.mode === "CAR"));
  if (combo.rentEnd)
    its = its.filter(it => endLegOnly(it, rented));
  if (combo.rentStart)
    its = its.filter(it => startLegOnly(it, rented));
  return its;
}

/* ---- ranking ----
   Ranking is fastest first in both modes. Ranking "Arrive by" results by
   how late you can leave buries genuinely fast trips that happen to leave
   a little earlier. Leaving late still matters under a deadline, so in
   Arrive-by mode departure time stays a dominance dimension and keeps its
   own badge; it just doesn't set the order.
   pool: [{ it, cost }]. Returns the pool sorted, the cards that headline
   (main) and the ones folded under "more options" (rest), and which trip
   earns each badge. */
function rankPool(pool, arriveBy){
  const metric = it => it.duration;
  pool = pool.slice().sort((a,b) => metric(a.it) - metric(b.it));

  // keep only options nothing else beats outright: at least as fast AND at
  // least as cheap (and, with a deadline, leaving at least as late)
  const beats = (y, x) =>
    metric(y.it) <= metric(x.it) && y.cost <= x.cost
    && (!arriveBy || y.it.startTime >= x.it.startTime)
    && (metric(y.it) < metric(x.it) || y.cost < x.cost
        || (arriveBy && y.it.startTime > x.it.startTime));
  const lead = pool.filter(x => !pool.some(y => y !== x && beats(y, x)));
  let main = lead.slice(0, 5);
  let cheapest = null, latest = null;
  for (const x of pool){
    if (!cheapest || x.cost < cheapest.cost) cheapest = x;
    if (arriveBy && (!latest || x.it.startTime > latest.it.startTime)) latest = x;
  }
  // the cheapest option - and, with a deadline, the one you can leave
  // latest for - must never hide inside collapsed "more options"
  const pins = [cheapest, latest].filter((x, i, a) =>
    x && lead.includes(x) && !main.includes(x) && a.indexOf(x) === i);
  if (pins.length) main = lead.slice(0, 5 - pins.length).concat(pins);
  const rest = pool.filter(x => !main.includes(x));

  // on metric ties, the badge goes to a card that actually headlines
  const fastestIt = pool.length
    ? (lead.find(x => metric(x.it) === metric(pool[0].it)) || pool[0]).it
    : null;
  return { pool, main, rest, fastestIt,
           cheapestIt: cheapest ? cheapest.it : null,
           latestIt: latest ? latest.it : null };
}
