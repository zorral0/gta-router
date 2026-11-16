# Routing notes: why the routing is the way it is

This file records what was measured, what was tried, and what failed, so
nobody has to repeat it. Read the relevant section before changing a config
value, a mode mix or a ranking rule. Each section says WHAT is true, WHY, and
HOW TO CHECK it still holds. Where a claim could not be re-checked against
the current files it is marked "(from older notes, not re-verified)".

Paths: the page is `web/index.html` (layout and CSS), `web/app.js` (page
code), `web/core.js` (fares, tolls, mode mixes, ranking). Scripts are in
`scripts/`, checks in `tests/`, the map patch in `data/parking-patch.osc`,
and everything the routing engine reads (configs, schedules, jars, graphs)
in `engine/`.

## Contents

1. The drive-to-station fix (four stacked causes)
2. Engine config landmines
3. OTP 2.9 GraphQL facts
4. OTP behaviours that are not bugs
5. The query fan-out and the drive reluctance ladder
6. The tenth mix that was built and reverted
7. The pointless-drives rule
8. Search speed: dead ends and the real cause
9. Ranking rules, pure-mode caps, the drive cap
10. Data fixes (TTC transfers, GO alerts, Durham, TTC real-time)
11. Fares and tolls
12. Judging routing against outside planners
13. The verification tools

---

## 1. The drive-to-station fix (four stacked causes)

WHAT. The complaint was "drive to station sends me to the wrong station".
Four independent causes were stacked. All four had to be fixed together.
Fixing any one alone changed nothing visible, which is why it survived earlier
tuning. A test trip of downtown to Vaughan with a car to the station went from
102 minutes to 54 minutes.

| # | Kind | Cause | Fix (current value, read from the files) |
|---|------|-------|------------------------------------------|
| 1 | Data | The engine only parks at map objects tagged `park_ride=yes`. About 28 real commuter lots lacked the tag. | `data/parking-patch.osc` adds the tags |
| 2 | Config | `accessEgress.maxStopCount` defaulted to 500. It collected 500 stops of nearby lots and never reached lots 25 km or more away. | `engine/router-config.json`: `"maxStopCount": 4000` |
| 3 | Config | The itinerary filter `removeTransitWithHigherCostThanBestOnStreetOnly` silently dropped park-and-ride plus transit trips that cost more (internally) than the best drive-and-walk trip, even when they were 30 minutes faster on the clock. Car minutes cost 3x internally and walking 2x. | `"removeTransitWithHigherCostThanBestOnStreetOnly": "9h + 9.0 t"` (effectively never drops) |
| 4 | Config | The dynamic search window shrank at peak. The right bus fell outside it: the option worked at 8:30 and vanished at exactly 8:00. | `transit.dynamicSearchWindow.minWindow: "1h"` |

Also in `accessEgress`: `maxDuration` is `"45m"` and `maxDurationForMode` has
`CAR_TO_PARK: "45m"`. A value of 30m hid the right lot for downtown-to-suburb
trips (downtown to the Hwy 407 and Pioneer Village subway lots is about 30 to
32 minutes of driving).

### The patch must be re-applied after every fresh map download

`data/parking-patch.osc` is a list of edits to the OpenStreetMap data. If
someone downloads a new OpenStreetMap extract and does not re-apply it, the
fix silently regresses: nothing errors, the app just drives you to the wrong
station again.

`setup.sh` does it correctly, in this order:

1. Step 4 of 6 downloads `ontario-latest.osm.pbf`.
2. Step 5 of 6 crops it with `osmium extract --bbox -80.30,43.20,-78.40,44.35`
   (line 71) into `engine/gta.osm.pbf`.
3. Right after, line 78: `osmium apply-changes gta.osm.pbf ../data/parking-patch.osc`
   writes `gta-parkfix.osm.pbf`, which is then moved over `gta.osm.pbf`.
4. Only after that is the toll grid rebuilt and the graph built (Step 6 of 6).

`refresh.sh` does NOT download map data (only schedules), so it never needs
the patch. If anyone builds by hand, they must do step 3 themselves.
`engine/gta.osm.pbf.orig` is the unpatched copy kept for reference.

HOW TO CHECK IT STILL HOLDS.
- The patch file holds 43 ways and 1 node (44 elements). The node is a
  working entrance point for the Centennial GO garage.
- After building a graph, start the engine and look at its startup output.
  It reports the number of car park-and-ride areas. The last recorded
  figure was 197 (from older notes, not re-verified). A sharp drop means the
  patch was not applied.
- Run `python3 tests/benchmark.py`. The drive-to-station column must not be
  slower than transit-only on the commuter trips.
- If a user says "it will not let me drive to station X but biking works",
  it is almost certainly a missing `park_ride=yes` tag. Ask the engine for the
  nearest CAR_PARK to the station before debugging routing.

### The GO station park-and-ride audit

All 71 GO stations were checked for a car park within 500 m. 25 had none (the
map tags bike racks generously but marks car lots rarely). 15 were fixed by
tagging the largest qualifying lot (largest parking area within 300 m of the
station). That is why the patch has 43 ways.

Deliberately NOT patched:
- Union: there is no park-and-ride product there.
- Exhibition, Downsview Park, Mount Dennis: the nearby lots are venue or
  mall parking. Tagging them would lie about cost and availability.
- 6 stations outside the cropped map area.

Known imperfect: Etobicoke North's lot is linked but unreachable within 1200 m
of network distance from the station point (from older notes, not
re-verified).

Two more lessons from the same work:
- `groupSimilarityKeepOne` merges near-identical trips and keeps the one with
  the lowest INTERNAL cost, and internal cost prices walking at 2x. That hid
  a faster trip. The default 0.85 was changed to `0.95` in `router-config.json`.
- A filter the app applies to the engine's answers (such as the drive-distance
  slider) breaks silently, because the engine crops to best-by-arrival first.
  That is why the app asks for drive-to-station several times with different
  reluctance values (section 5).
- A "missing stop" report turned out to be real schedule behaviour (a bus
  loop served one direction only after 15:32). Check the schedule's service
  pattern by time of day before assuming a graph problem.

---

## 2. Engine config landmines

Wrong config key names are silently ignored, except for one WARN line at
startup. After ANY config change, restart and search the engine's startup
output (the Terminal window running `bash run.sh`) for the text
`Unexpected config parameter`. There must be none.

What is easy to get wrong, with the current correct values:

- Access and egress limits live under `routingDefaults.accessEgress`
  (`maxDuration`, `maxStopCount`, `maxDurationForMode`). An older block named
  `maxAccessEgressDuration` was silently ignored for weeks.
- `removeTransitWithHigherCostThanBestOnStreetOnly` is a linear-function
  STRING, not true or false. Setting it to `false` crashes the server at
  startup. Current value `"9h + 9.0 t"`.
- `routingDefaults.bicycle.optimization` must be the enum string
  `"SAFEST_STREETS"` (2.9). The 2.5 object form `{ "type": "safest-streets" }`
  is silently ignored on 2.9 (the error says "The enum value '' is not
  legal"). Until it was fixed (2026-07-18), "safest" and "fastest" gave the
  same answer.
- `staticBikeParkAndRide: true` is needed in `engine/build-config.json`.
  Without it the graph has zero bike racks and every bike-to-station query
  fails, even though the map has the racks.
- `transitModelTimeZone: "America/Toronto"` is required in
  `engine/build-config.json` because Brampton's feed declares
  America/New_York and the build refuses to mix time zones otherwise.
- `MinimumTransferTimeIsDefinitive: true` in `engine/otp-config.json` makes
  the engine trust the minimum transfer times we inject for TTC subway
  interchanges. Without it the engine still walks you out to the sidewalk at
  Bloor-Yonge. It is a real OTP 2.9 feature flag (confirmed by reading the
  flag list out of the jar).
- Environment variables are needed even to BUILD a graph. The engine reads
  `engine/router-config.json` every time it starts, even for `--build`, and
  that file names `${METROLINX_KEY}` and `${GTA_ROUTER_DIR}`. With either
  unset the engine refuses to start. `scripts/engine-env.sh` sets both (the
  key comes from the git-ignored `metrolinx.env`). `run.sh`, `setup.sh` and
  `refresh.sh` all source it. If you run `java -jar engine/otp.jar --build`
  by hand, source that script first. Never paste the key into a tracked file.
- A 2.9 jar cannot load a 2.5 graph, and a 2.5 jar cannot load a 2.9 graph.
  The main engine is `engine/otp.jar` (2.9.0) with `engine/graph.obj`. The
  Reach map engine is `engine/otp25.jar` (2.5) with `engine/graph.obj.otp25`
  (linked as `engine/reach-engine/graph.obj`). If the map or schedule inputs
  change, BOTH graphs must be rebuilt from the same patched inputs or the
  Reach map goes stale. `refresh.sh` rebuilds both and keeps the old ones as
  `graph.obj.prev` and `graph.obj.otp25.prev` for rollback.
- Java zip64 problem: Java 25 can reject a schedule zip that Python reads
  fine (error "Invalid CEN header (invalid zip64 extra data field size)").
  It happened with a Barrie feed. Fix: repack the zip as a standard zip, or
  run java with `-Djdk.util.zip.disableZip64ExtraFieldValidation=true`.
  None of the ten current feeds needed this.
- Other values in `router-config.json` right now: `walk.speed` 1.4 (the
  1.33 default made station walks feel padded), `walk.stairsTimeFactor` 1.6
  (the default 3 adds phantom minutes to every subway entrance because
  stations are mapped stair by stair), `transferPenalty` 300, `bicycle.speed`
  4.5, `car.reluctance` 3.0.

What takes effect when:

| Change | What is needed |
|---|---|
| `web/*` (page, core.js, app.js) | Browser reload only |
| `engine/router-config.json`, `engine/otp-config.json` | Engine restart (the owner does this) |
| `engine/build-config.json`, map data, schedules | Graph rebuild (4 to 15 minutes) |

---

## 3. OTP 2.9 GraphQL facts

The page, `tests/benchmark.py` and friends all use `planConnection`. The old
`plan` query is gone.

- Coordinates are `latitude` and `longitude`. OTP 2.5's `plan` wanted `lat`
  and `lon`, the exact inverse. This bites every time.
- `dateTime.earliestDeparture` (and the arrive-by form) is an ISO date-time
  with offset.
- Results arrive as `edges { node { ... } }`.
- Itinerary and leg times are ISO strings under `start` and `end` (for legs,
  `start { scheduledTime }`), not millisecond numbers. `normalizeItin()` in
  `web/core.js` converts them.
- `intermediatePlaces` is gone. Use `stopCalls` and slice off the first and
  last entries for the old meaning (core.js does exactly that).
- `BICYCLE_RENTAL` and `CAR_PICKUP` must have `WALK` next to them in the same
  access or egress list, or the query errors.
- Introspection that asks for `inputFields` on many types at once is rejected
  as "BadFaithIntrospection". Ask for one type per request.
- Never parse the `Duration` scalar. Compute durations from two timestamps.
- OTP 2.9 removed the travel-time (isochrone) API. That is why the Reach map
  runs on a separate 2.5 engine.

---

## 4. OTP behaviours that are not bugs

- There is no traffic model. Car legs run at free-flow speed, roughly 75 to
  80 km/h across Toronto at 8 AM. Any comparison that involves driving is
  optimistic for the car. The UI says "light traffic assumed" on car legs.
- OTP 2.9 has no toll support at all (no avoid-tolls option, no toll cost on
  car preferences). The engine can never route around the 407. The app
  measures tolled metres itself (section 11).
- The engine returns ONE optimal lot per `carReluctance` value. Raising
  `first` from 8 to 40 changes nothing. That is why the drive-to-station fix
  needed several queries instead of a bigger result set.
- A car-only query to a pin inside a mall (Scarborough Town Centre, Square One
  centroids) returns empty with no error, because the car cannot legally
  reach the exact pin. Harmless.
- For arrive-by queries keep `first: 8`. Using `last` pads the answer with
  pointlessly early departures.
- For rental-bike egress on short end walks (under about 2 km) the engine
  groups the walk ending and the Bike Share ending as siblings and keeps the
  walk. Fixed with a per-request `walk.reluctance` of 6.0 on the Bike Share
  mixes only (`walkReluctance: 6.0` in `COMBOS`).
- `subwayAccessTime`: the graph builder adds 2 minutes (default) to every
  walk into or out of a subway stop, including a transfer from a bus. It is
  invisible in the step list; the walk just comes out slow. The setting is
  one global number with no per-station override. It is deliberately left at
  the default. The check of all 71 stations found 16 stations whose indoor
  paths are mapped (there the 2 minutes is double-counted), 35 stations where
  the walk ends at street level with no indoor path (there the 2 minutes is
  the only thing standing for getting down to the platform), and 20 mixed.
  Setting it to 0 would fix 16 stations and break 55. The real fix would be
  mapping station interiors in OpenStreetMap, which is large and not started.
  How it was proven: the same 220 m walk was 322 s as a transit access leg and
  202 s as a walk-only trip, exactly 120 s more (from older notes, not
  re-verified).
- Plain street walking is correct: a 3580 m walk-only option came out at
  1.30 m/s, matching the configured speed. Only station-internal walking is
  slow, for the reason above.
- Bike-to-station can headline slower than transit-only in north York Region
  because no bike parking is mapped at some stops on fast corridors, so the
  bike graph rides many km to the one parkable spot. Same family as the car
  `park_ride` gap (from older notes, not re-verified).

---

## 5. The query fan-out and the drive reluctance ladder

WHAT. `COMBOS` in `web/core.js` lists 12 mode mixes: nine with transit
("Transit only", "Bike to station", "Bike Share at the start", "Drive to
station", "Drive at the end", "Bike Share at the end", "Drive + Bike Share at
the end", "Bike + Bike Share at the end", "Bike + drive at the end") and three
whole-way ones ("Bike the whole way", "Bike Share the whole way", "Walk the
whole way"). A mix is only fired when the matching "Using:" toggles are on.
Every mix is one `planConnection` query, all sent at once. Every mix that has
a car leg is sent once per value of `DRIVE_RELUCTANCE`, which is
`[30.0, 2.0, 1.0]`, and "Drive to station" gets one extra value from
`extraReluctance: [8.0]`.

With every toggle on that is 21 queries (8 single ones, 3 drive mixes x 3
values, and 4 for "Drive to station").

WHY a ladder. The engine has no "maximum drive distance" and no way to name a
station. The only request knob that changes which parking lot it picks is
`car.reluctance`, and each value returns the one lot that is optimal at that
value. Measured from a suburban origin to downtown, distinct lots returned:

| reluctance | lots returned |
|---|---|
| 30 and up | 2.3 and 2.4 km only (the walk-to-your-own-station tier) |
| 4 to 12 | 2.5 km only |
| 2 to 3 | 2.5 km and 24.8 km |
| 1 to 1.5 | 2.5, 24.8, 33.5 and 38.6 km (the only wide answer) |

So 1.0 surfaces a middle-distance station. 30 is kept because at 1.0 the very
near lots drop out. 2.0 is kept because the near/middle split depends on the
origin and the extra query is cheap. Values below 1.0 only buy longer drives,
which the drive cap already handles.

WHY 8.0, and why only on one mix. `tests/reluctance-ladder.py` priced every
candidate ladder over 25 trips (the audit set then in use; the public file
`tests/audit-trips.json` holds 15). Each drive mix is asked once per value, so
a ladder's score is the best over its own subset and testing a candidate costs
no extra queries.

| ladder | trips helped by 5 min or more | total minutes saved |
|---|---|---|
| [30, 2, 1] (before 8.0) | 0 | 0 |
| [30, 8, 2, 1] | 1 | 5 |
| [30, 5, 2, 1] | 0 | 0 |
| [30, 8, 4, 2, 1] | 1 | 5 |
| every value from 30 down to 1 | 1 | 5 |

Asking for EVERY value buys nothing beyond adding 8.0. That is the ceiling of
this whole line of attack. The one trip it helps is Markham to Square One: 8.0
reaches a lot that catches a GO train 5 minutes earlier (arrive 09:32 instead
of 09:37). Nothing else moves it: not `groupSimilarityKeepOne` at 0.99, not
keep-three, not `groupedOtherThanSameLegsMaxCostMultiplier`, not `first: 50`,
not a 3 hour search window.

Cost of putting 8.0 on all four drive mixes, measured in the browser on the
same trips:

| trip | before | 8.0 on all four | 8.0 on "Drive to station" only |
|---|---|---|---|
| Markham to Square One | 3.9 s, arrive 09:37 | 6.3 s, arrive 09:32 | 4.0 s, arrive 09:32 |
| a Markham to downtown trip | 5.5 s | 6.3 s | 5.2 s |

All four mixes cost 0.8 to 2.4 seconds on every plan for a 4% hit rate. The
primary mix alone gets the whole measured win for about 90 ms.

A lesson from this: the tag on a deleted itinerary (such as
`similar-legs-filter-85p-1x`) names the filter that removed it inside the
audit's own over-wide query. It does not prove that filter is what keeps it
off the screen. The first diagnosis blamed that filter and was wrong.

HOW TO CHECK.
- `grep -n "DRIVE_RELUCTANCE\|extraReluctance" web/core.js` should show
  `[30.0, 2.0, 1.0]` and `extraReluctance: [8.0]` on one mix.
- Re-run `python3 tests/reluctance-ladder.py` (engine running) before
  changing the ladder.

---

## 6. The tenth mix that was built and reverted

"Drive to station, picked up at the end" (`CAR_PARKING` access plus
`CAR_PICKUP` egress, a car at BOTH ends) was written, measured and reverted.
Do not rebuild it without reading this.

It worked: on a Richmond Hill trip the earliest arrival went from 09:16 to
08:41, a 35 minute gain, with the longest drive 13.7 km (inside the cap). It
was reverted on speed. A query with a car at both ends explores the road
network twice and is very expensive at the low reluctance the pickup needs:

| reluctances asked | that trip's plan time |
|---|---|
| none (before) | about 4 s |
| 30, 2, 1, 8, 4 | about 16 s median |
| 4 only | 9.5 s, and one run hit the 25 s abort |

The trade was one trip in 25 gaining 35 minutes against every plan on that
shape of trip taking 2 to 6 times longer, plus abort risk.

There is no per-request lever to bound it. In the 2.9 request, car preferences
only have `boardCost`, `reluctance`, `parking` and `rental`. The only bound is
server-side `routingDefaults.accessEgress.maxDurationForMode`, which would
also apply to the existing "Drive at the end" mix.

WHAT MUST BE TRUE before retrying:
1. Add a `CAR_PICKUP` entry to `maxDurationForMode` in
   `engine/router-config.json`.
2. Prove, with the engine running, that the whole plan on the Richmond Hill
   trip stays under about 5 seconds.
3. Only then add the mix. Give it `carBothEnds`, NOT `carAfter`: `carAfter`
   demands every car leg come after transit, so it rejects every result the
   moment the trip also drives to the station. (`carBothEnds` does not exist
   in the code today; it would be new.)
4. Measure with `tests/combo-proposal.py`, which was written for exactly this
   change.

Related bug that was fixed on the way and matters if two-car-leg mixes ever
return: the drive cap measures the LONGEST single car leg, not the sum
(`longestCarLegM()` in `web/core.js`; `tests/route-audit.py` mirrors it as
`car_distance`). Summing would make a 2 km drive plus a 13 km lift read as a
15 km drive and vanish at the default cap.

---

## 7. The pointless-drives rule

WHAT. In `rankPool` (`web/core.js`), a trip with a car leg is dropped when
some trip with NO car leg beats it on BOTH time and price. It uses the same
`beats` test as the Pareto filter. Dropped trips are removed outright, not
folded into "more options".

WHY. The drive mixes demand a car leg, so the engine always finds one, even a
pointless one. A trip from near Bathurst and Bloor at 12:54 AM drove 4 km west
to the Dundas West lot and rode Line 2 back east past home, slower and dearer
than just taking the subway, and it sat under "more options".

Removing a beaten trip can never change which trips lead, because whatever
beat it still beats everything it beat. So `tests/route-audit.py` needs no
matching change.

THE OWNER REJECTED A DIRECTION RULE. A first version dropped drives that move
away from the destination. The owner said "sometimes you have to drive
backwards", for example back to a GO station to catch a faster train. Never
add a direction test, a "wrong way" test or a distance-from-destination test.
The test is only: some car-free trip is at least as fast AND at least as
cheap (and strictly better on one). The owner also decided that ANY time
saving keeps a drive: there is no minimum number of minutes.

Evidence it is safe: on 25 saved trips, 62 drive options were removed and 91
kept; no top card was lost and every wrong-way drive went anyway. Re-checked
live: 63 removed, 87 kept, top cards identical to the old code on all 25
trips.

Still open: "drive nearly the whole way, then one bus" cards when the drive
slider is at Any.

HOW TO CHECK. `node --test tests/core.test.mjs` covers ranking. If a user
reports another silly drive, replay the exact trip through the ranking code
on saved engine results first; do not guess a new rule.

---

## 8. Search speed: dead ends and the real cause

The owner reported searches feeling slow, and once a late-evening search timed
out with every mix aborted.

Measured on a Markham to downtown trip: 21 queries are about 25 s of engine
work if run one at a time and about 10 s at 6 at a time. The first card took
"way more than a second" for the owner against about 1 s warm in testing.

Dead ends, do not repeat:
- Browsers allow only 6 connections per host, so the page never truly sent 21
  at once. A test that fires all 21 at once in Node is NOT what the browser
  does (emulate it with a pool of 6).
- Reordering so the drive mixes go last, and a 4-at-a-time queue: measured, no
  gain, reverted.
- Lowering the engine's `-Xmx` (the Java memory cap): measured at 3G, 4G, 5G
  and 6G on 21-query plans, 6 at a time. 3G hit full garbage collections and
  was slower. 4G and 5G were no steadier than 6G (8 to 20 s at every cap).
  6G (in `run.sh`) was kept. The machine had about 70 MB free with only the
  main engine up, so the cap was never the problem.

Real cause: the 16 GB Mac ran out of memory. macOS had compressed 5.0 of the
main engine's 5.8 GB (the live heap was only 2.5 GB) and all 3.3 GB of the
Reach engine, with 7.6 GB of swap in use. On the failed evening search, 6406 of
6413 MB were compressed, 96 MB were free and 10 GB of swap was in use. A
second copy of `run.sh` had also been started while the first was running,
loading a second 6 GB engine that could not even bind the port.
Use `top -stats pid,mem,cmprs` to see this; `ps` RSS is misleading (tiny).

What was done:
- `run.sh` refuses to start if ports 8080, 8081 or 8090 are in use.
- `stop.sh` stops everything `run.sh` started, from any Terminal window.
- The Reach engine (2.5, about 3.3 GB) starts on demand from
  `scripts/web-server.py`, on the first Reach request, and stops after 15 quiet
  minutes (`REACH_IDLE_MIN` changes that for testing). While it loads,
  `/otp/traveltime/*` answers 503 and the page retries.

The owner's decision: KEEP every mode mix. Do not propose dropping the car
mixes to save time, even though a no-car search takes about 2 s.

HOW TO CHECK. If searches slow down again, check memory first (`top -stats
pid,mem,cmprs`, and whether two engines are running), then time the search
before touching any code.

---

## 9. Ranking rules, pure-mode caps, the drive cap

All in `web/core.js` (`rankPool`, `filterCombo`) unless noted.

- Ranking is fastest first in BOTH Leave-at and Arrive-by modes
  (`metric = duration`). Sorting arrive-by results by "latest departure"
  buried genuinely fast trips that left slightly earlier. The blue "Fastest"
  badge always means fastest.
- Under a deadline (arrive-by), departure time is a third dominance dimension
  (an option survives if nothing else is at least as fast, as cheap AND leaves
  at least as late) and gets its own quiet "Latest leave" badge.
- The Pareto filter keeps only trips nothing else beats on both time and cost.
  The main list shows at most 5; everything else goes under "N more options".
- The cheapest trip is pinned into the main list, so it can never hide under
  "more options". Same for "Latest leave" under a deadline.
- Exactly one Fastest and one Cheapest badge overall. On ties the badge goes
  to a trip that actually headlines.
- Pure-mode caps (`maxMin` in `COMBOS`): bike the whole way 60 min, Bike Share
  the whole way 60 min, walk the whole way 45 min. A pure ride costs $0, and
  the cheapest option is always pinned, so without a cap a 3 hour walk would
  pin itself to the top of every long trip. `directOnly: true` is mandatory
  for these: asking for `direct: ["BICYCLE"]` alone returns walk-plus-transit
  trips instead.
- Pure CAR mode is deliberately NOT offered. On free-flow times the car wins
  almost every trip, so it should wait for a traffic answer. (An older note
  mentions a `DOWNTOWN_PARKING` branch kept for parity; it no longer exists
  under that name in `web/`.)
- The drive cap (slider, default 15 km, `maxDriveM` in `web/app.js`, top
  setting "Any") measures the LONGEST single car leg (`longestCarLegM`), as its
  label says: "Longest drive (to the station, or at the end)". `driveHint`
  tells the user what the cap is hiding and offers a one-tap Show.
- Drive results are merged by `spreadByDrive`: the fastest two in each 10 km
  band of driving plus the fastest few overall, capped at 10. Sorting by time
  and slicing used to throw away every short-drive option once six faster
  long drives existed, so a low slider had nothing to show.
- Trips with the same pattern are collapsed by `dedupeAlts`, and the other
  departure times show as "also 8:38 PM" on the card. The pattern includes
  where each ride boards, otherwise two park-and-rides to different stations
  with the same duration merged into one card.

---

## 10. Data fixes

### TTC transfers (`scripts/patch_ttc_transfers.py`)

WHAT. The TTC publishes no `transfers.txt`. The script adds one to
`engine/ttc-gtfs.zip`: a 180 second minimum transfer between subway platforms
of each interchange. `setup.sh` and `refresh.sh` run it after every TTC
download. It also moves four platforms at Bloor-Yonge to their shared centre.

WHY. Without it the engine "transfers" at Bloor-Yonge by walking out to the
sidewalk, and the subway loses to streetcars. The Bloor-Yonge co-location
exists because the TTC places each platform's point at a different spot along
the platform. Line 1 northbound and southbound, side platforms a few metres
apart in the building, sit 115 m apart in the data. The tell was asymmetry:
eastbound to northbound was 6 m apart and produced no walk leg, while eastbound
to southbound was 115 m apart and produced 275 m of street routing, 8 minutes,
for a transfer a rider measures at 2 to 3 minutes.

THE 150 m GUARD. `MAX_MOVE_M = 150.0` in the script: it refuses to move a stop
further than that. Every interchange shows a 150 to 370 m spread, but at
places like Spadina the long Line 1 to Line 2 walk is REAL. Flattening it
would trade an overstatement for an understatement. Only Bloor-Yonge is
patched, because a rider gave a measured figure for it. Do not extend the list
without a measured figure from a rider.

Ruled out while chasing this, do not re-check: the missing-OSM-data theory
(the platforms are connected underground in the map, 63 m indoors) and
`stairsTimeFactor` (14 m of steps at 1.6 costs about 6 s against a gap of about
170 s).

HOW TO CHECK. After a TTC refresh, `unzip -l engine/ttc-gtfs.zip` must list
`transfers.txt`. The Bloor-Yonge platform pairs have `transfer_type=2,
min_transfer_time=180`. Then plan a Line 2 to Line 1 trip at Bloor-Yonge: it
must have no street-walk leg between the two subway rides.

### GO alerts filter (`scripts/go-alerts-filter.py`)

Metrolinx's alerts feed carries present-but-EMPTY `agency_id` and `route_id`
fields next to a good `stop_id`. OTP throws "Missing mandatory id on
FeedScopeId" and the error aborts the whole GO alerts batch every cycle:
55 alerts published, zero in the engine, while TTC and MiWay arrived fine.
The script strips only the empty strings (checked lossless: 55 alerts and 85
selectors in and out). `run.sh` starts it; `router-config.json` reads
`go-alerts-filtered.pb` through a `file:` URL. Log: `engine/go-alerts.log`.

### Durham filter (`scripts/drt-rt-filter.py`)

DRT's trip updates carry `stop_time_updates` for stops that are not on the
trip (sequences 50 to 53 on a 49-stop trip), placed before the real tail so the
sequence also runs backwards. OTP reports INVALID_STOP_SEQUENCE and discards
the whole trip: about 30 trips a cycle, roughly 22% of the feed, silently back
on scheduled times. The script drops only updates whose stop sequence is not in
the static trip. After filtering: 0 unknown stops, 0 backwards sequences.
Every DRT live trip does match a static trip, so no rebuild is needed.

Two gotchas:
1. The endpoint answers a bare Python request with 403 unless a User-Agent is
   sent (the script sets `OpenTripPlanner/2.9.0`).
2. The script reads `engine/drt-gtfs.zip` to learn which sequences are real,
   so restart it (restart `run.sh`) after `refresh.sh` replaces that zip.

### TTC real-time is not possible with the current feed

It was re-diagnosed and closed on 2026-09-19. Evidence: of 1890 live trip
updates, 0 matched a static trip id. The live ids are synthetic and some are
negative (for example `10994070`, `-31351846`). The trip descriptor has only
three fields, and two are misused: `start_time` arrives as an integer where
"HH:MM:SS" belongs, and `start_date` carries route numbers like `510` instead
of a date. There is no `route_id` and no `direction_id`, so fuzzy trip matching
cannot rescue it either. A fresh static download covered the same service
period, so refreshing does not help. `scripts/ttc-rt-filter.py` solves an older
problem (the feed's "NEW" trips crashing the updater) and is unused.

Re-probe the feed before assuming any of this still holds. It was one
afternoon's snapshot. TTC delays become possible only if the TTC starts
publishing real trip ids, or a route plus direction plus start time.

Other live feeds: GO, YRT, MiWay and DRT delays are wired in
`engine/router-config.json`; Brampton's old real-time endpoint is dead; the
UP Express feed returned nothing when probed (from older notes, not
re-verified).

### Feeds expire

Each agency's schedule has an end date. After it, the app answers from stale
data with confidence. Before blaming routing for a regression, check the
feeds' service dates. A past refresh loaded a TTC feed that did not start
until eight days later, and TTC vanished from every trip for a week.
`refresh.sh` now runs `scripts/check-feeds.py` before building and asks
before going on when a feed has not started yet.

---

## 11. Fares and tolls

### Verified fares (all PRESTO level, checked against agency pages in July 2026)

These are the values in `LOCAL_FARES` and the constants in `web/core.js` now:

| System | Adult | Youth |
|---|---|---|
| TTC | 3.30 | 2.35 |
| MiWay | 3.50 | 2.90 |
| YRT | 4.24 | 3.29 (July 1 2026 increase) |
| DRT | 3.84 | 3.46 |
| Brampton | 3.55 | 2.95 (the older 4.75 was the CASH fare) |
| Oakville | 3.50 | 0.00 (youth 13 to 19 ride free) |
| Burlington | 2.85 | 2.00 (youth also free weekday evenings after 6 pm and weekends, handled by a rule) |
| Milton | 3.85 | 2.90 (no PRESTO; single e-ticket price modelled) |
| UP Express to or from Pearson | 9.25 | 7.41 |
| UP Express city-only (Union, Bloor, Weston) | 5.02 | 3.39 |
| GO | the real station-to-station table in `web/go-fares.json` | 40% off |

The Halton rows were verified 2026-09-19; the others July 2026. Until
2026-09-21 every UP trip was charged the city fare, so airport trips were
undercharged. On GO, PRESTO and contactless pay the same single-ride price;
PRESTO matters only for youth and senior discounts. A rider check confirmed a
Mount Joy GO youth fare of about $6 each way (adult 10.05, youth 6.03).

One Fare versus Halton co-fare (the `transfer program` column in
`LOCAL_FARES`):
- `onefare` (TTC, YRT, MiWay, DRT, Brampton): free transfer to and from GO,
  and between these agencies and the TTC. With GO in the trip, local systems
  are free in both directions; otherwise only the first local fare is charged.
- `gocofare` (Oakville, Burlington, Milton): NOT part of One Fare (checked
  against Metrolinx's own page). Each runs a GO co-fare, so the local ride is
  free when the trip touches GO, but a TTC transfer with no GO is paid in
  full. Feeds are matched by feed id; matching agency NAMES by substring once
  made "MILTON" match "HAMILTON". The three Halton feeds were once priced at
  $0 with no warning, because nobody added rows when the feeds arrived.

WHEN TO RE-VERIFY. Every January and February (MiWay, Brampton) and July
(YRT). An unverified row shows "fare unverified" in the UI.

### The fare model exists twice

The fare model lives in `web/core.js` AND in `scripts/costs.py`, which is a
local-only file (not in the public repository). `tests/fare-sync.py` diffs every
`LOCAL_FARES` row and the scalar constants. With `--feeds` (engine running) it
also checks that every agency in the running graph has a fare row at all. If
`costs.py` is absent, the two-copy diff is skipped and the other checks still
run (CI runs it without `--feeds`). Tolls are client-only: `costs.py` has no
route geometry, so the sync rule does not apply to them.

### 407 ETR tolls

The engine cannot price tolls, so the page does:
- `web/toll-roads.json`: a grid (about 30 m cells) of tolled ways, rebuilt by
  `scripts/make_toll_cells.py` from the same `gta.osm.pbf` the graph uses
  (`setup.sh` does it). A leg counts only if at least 400 m of it is tolled.
  `highway=service` ways are excluded: the only tolled ones in the extract are
  the aisles of one paid parking garage, and counting them would invent money.
- `web/toll-rates.json`: 12 zones, direction, time bands and the rate chart.
  Its `_effective` is 2026-01-01 and `fees` are a $1.00 trip charge and a $5.30
  camera charge (no transponder).
- RATES CHANGE EVERY JANUARY 1. Re-run `scripts/make_toll_rates.py` (its header
  explains how to copy the chart out of the 407 ETR page: the tables are drawn
  by JavaScript, so a plain download has no numbers, and the first two tables
  are westbound, the last two eastbound; getting that backwards misprices
  every trip).
- Stated limits shown in the UI: assumes a transponder; statutory holidays
  bill at weekend rates and are not modelled; only the ETR section (QEW to
  Brock Rd) is covered because the MTO-run 407 East is not tagged `toll=yes`
  in the extract.

---

## 12. Judging routing against outside planners

- Triplinx is shut down (checked 2026-09-19; the site says so). Do not plan an
  audit around it.
- Google Maps has no park-and-ride. Its transit options offer only a mode
  preference and a route preference, no drive-to-transit. For a Markham origin
  to downtown at 10 AM it returned six transit-only itineraries and never
  suggested the Stouffville GO train.
- So grade transit-only trips directly against Google Maps. For
  drive-to-station, composite the ground truth by hand: Google Maps driving
  from the origin to each plausible station, plus the agency timetable for the
  train leg, add them, and compare station choices. Never write "Google
  agrees" about a park-and-ride answer: it was never asked the question.

The first comparison (Saturday afternoon, 2026-09-19, transit only, both
planners asked to leave at the same moment):

| trip | ours | Google | delta |
|---|---|---|---|
| Annex to Yonge and Dundas | 30 min | 20 min | 10 min slower |
| Guildwood to King and Bay | 38 min | 38 min | 0 |
| Kipling to Scarborough Centre | 76 min | 78 min | 2 min faster |
| Markham (Mount Joy GO) to downtown | 75 min | 73 min | 2 min slower |
| Oakville to King and Bay | 52 min | 54 min | 2 min faster |

Four of five agree within 2 minutes on the same routes. The Annex outlier came
from walking inside subway stations (the Bloor-Yonge platform split fixed in
section 10, plus `subwayAccessTime` in section 4), not from missing routes.

VIA Rail is not loaded, so it is invisible to the app. Google offered Oakville
to downtown on VIA in 39 minutes against 52 here. Probably out of scope for a
commuter tool, but it is a real option a rider has.

---

## 13. The verification tools

All use only the Python standard library, and need the engine running unless
stated. After any routing change run `tests/benchmark.py`. A change that is
purely in the page (colours, layout) needs no benchmark; say so rather than
re-running out of habit, but be sure it really is client-side.

| Tool | What it answers |
|---|---|
| `python3 tests/benchmark.py` | Are the answers sane? 10 trips in `tests/benchmarks.json` (transit only, bike and ride, drive to station) graded PASS or MISS. All ten have an expected answer; two were corrected by a local rider and the rest were written by the developer, so treat a MISS after a schedule refresh as something to look at, not automatically a bug. |
| `python3 tests/route-audit.py` | Could the engine have shown a BETTER answer than the app did? Runs the app's real fan-out, then an over-wide "oracle" search (14-value reluctance ladder, 3 hour window, `first: 50`, LIST_ALL debug profile showing what OTP's own filters deleted). Anything the oracle reaches that the app cannot is a hole. Findings: MISSED (a real gap) or POLICY (hidden on purpose: past the drive cap, a pure-mode cap, or a carried bike). About 3 minutes per trip. Uses `tests/audit-trips.json` (15 trips, neutral names). |
| `python3 tests/reluctance-ladder.py` | Which drive reluctance ladder gets there earliest, priced for all candidates in one run (section 5). |
| `python3 tests/combo-proposal.py` | What a proposed extra mode mix would buy, across all audit trips (section 6). |
| `python3 tests/fare-sync.py [--feeds]` | Do the two fare models agree, and does every loaded agency have a fare row. |
| `node --test tests/core.test.mjs` | Fares, tolls, ranking, dedupe, Toronto time. No engine needed. CI runs it. |

`route-audit.py` ranks by ARRIVAL time, not duration. The first version ranked
on duration and called a 20 minute trip departing at 01:46 "better" than a 64
minute trip departing at 22:22. Three of its first five findings were that
mistake. The waiting is part of the trip.

IF A TOOL'S OUTPUT LOOKS EMPTY RATHER THAN WRONG, CHECK ITS DATE FIRST. A
car-probe script once had its date hard-coded to July. Every schedule then
started in September, so on that date there was no transit at all, and the
tool printed "no itineraries" for weeks while still looking like it worked.
The tools now pick the next Tuesday, as `benchmark.py` always did.

Public test data uses neutral names. `tests/audit-trips.json` is in a public
repository, so it must not hold a personal travel pattern. It uses a public
station (Mount Joy GO) to a generic downtown intersection at four times of day
(`stouffville_corridor_*`). Keep it that way: a named building plus a fixed
pair at four times of day reads as somebody's timetable. One known and
deliberately unchased finding there: `stouffville_corridor_saturday` shows one
MISSED worth 3 minutes, in the same reluctance-band family as section 5, whose
measured ceiling was 5 minutes across 25 trips.
