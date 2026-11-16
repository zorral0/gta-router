# Known issues

How to use this list:

1. Find the issue in the contents, read its **Status** first. A status that starts with "open", "partly done" or "written, untested" is yours to work on.
2. Items marked "needs the owner's decision" or "cannot be fixed" must not be changed without asking the owner.
3. Search the code for the function name or the quoted string in **Where**. Line numbers move, so none are given.
4. Do the numbered steps in **How to fix** in order, then do **How to check it worked**.
5. Before any change, read `docs/routing-notes.md` (why routing works as it does) and `docs/testing-notes.md`. Chores and hosting steps are in `docs/runbooks.md`. Look and feel rules are in `docs/design-rules.md`. Unfinished plans are in `docs/plans.md`.

## Contents

Before hosting publicly
- [1. Toggle clicks re-plan with no debounce](#1-toggle-clicks-re-plan-with-no-debounce)
- [2. No rate limiting in front of a hosted engine](#2-no-rate-limiting-in-front-of-a-hosted-engine)
- [21. Cloud setup files have never been run on a server](#21-cloud-setup-files-have-never-been-run-on-a-server)
- [19. The live-data recorder loses data when the laptop sleeps](#19-the-live-data-recorder-loses-data-when-the-laptop-sleeps)

App behaviour
- [3. Opening the app from a phone on the same Wi-Fi does not work](#3-opening-the-app-from-a-phone-on-the-same-wi-fi-does-not-work)
- [4. Bike Share dock information is hover only](#4-bike-share-dock-information-is-hover-only)
- [5. A search takes 5 to 14 seconds](#5-a-search-takes-5-to-14-seconds)
- [6. The page code is one 3300-line file](#6-the-page-code-is-one-3300-line-file)
- [17. Interface rough edges](#17-interface-rough-edges)
- [22. Photon search and map tiles are outside services](#22-photon-search-and-map-tiles-are-outside-services-found-while-writing-this-list)
- [23. Leftover unused CSS rule](#23-leftover-unused-css-rule-found-while-writing-this-list)

Data gaps
- [8. Subway boarding diagrams cover few stations](#8-subway-boarding-diagrams-cover-few-stations)
- [9. Bike to station can look slow in north York Region](#9-bike-to-station-can-look-slow-in-north-york-region)
- [10. Etobicoke North GO parking lot unreachable](#10-etobicoke-north-go-parking-lot-unreachable)
- [11. Station walking times include a fixed 2 minutes](#11-station-walking-times-include-a-fixed-2-minutes)
- [12. No VIA Rail, Hamilton, Guelph or Barrie local transit](#12-no-via-rail-hamilton-guelph-or-barrie-local-transit)
- [13. Live data that does not work](#13-live-data-that-does-not-work)
- [14. Highway 407 toll limits](#14-highway-407-toll-limits)

Needs the owner's decision
- [15. Benchmark expected answers never confirmed by a rider](#15-benchmark-expected-answers-never-confirmed-by-a-rider)
- [16. Drive slider at "Any" shows near-all-drive trips](#16-drive-slider-at-any-shows-near-all-drive-trips)

Not bugs
- [7. Fare rules also exist in a local-only script](#7-fare-rules-also-exist-in-a-local-only-script)
- [18. Not built: which door at Union for GO trains](#18-not-built-which-door-at-union-for-go-trains)
- [20. Pure car trips are deliberately not offered](#20-pure-car-trips-are-deliberately-not-offered)

Notes: a few files named below are on the owner's computer only and are not in the repository: `scripts/costs.py`, `HANDOFF-go-union-door.md`, `ttc-rider-efficiency-guide-2005.pdf`, the old `ISSUES.md`, and everything in `research/` and `recordings/`. If one is missing on your copy, that is why. `deploy/` IS in the repository.

---

## Before hosting publicly

### 1. Toggle clicks re-plan with no debounce
- **Status:** open
- **What is wrong:** One search sends about 21 questions to the routing engine at once. Every time you flip a "Using:" button, a rider or option control that re-plans, change the day or time, or swap the ends, all 21 go out again immediately. Click three buttons fast and the engine gets the burst three times. Fine on one computer, a problem on a shared hosted engine.
- **Where:** `web/app.js`, function `plan()` (search for `async function plan`). The page code is being refactored, so search by name. The count of 21 comes from `web/core.js`: `activeCombos` picks the mixes the toggles allow, `reluctancesFor` gives how many queries each runs, and `COMBOS` has 12 mode mixes with every toggle on. Five are single queries that are neither pure nor drive (Transit only, Bike to station, Bike Share at the start, Bike Share at the end, Bike + Bike Share at the end). Three are "pure" single queries (the three `pure:` entries: bike, Bike Share, walk the whole way). That is 8 single queries. The four mixes marked `drive: true` run once per value in `DRIVE_RELUCTANCE` (`[30.0, 2.0, 1.0]`, so 3 each), and "Drive to station" has `extraReluctance: [8.0]`, so it runs 4 times. 8 + 4 + 3 + 3 + 3 = 21. All four toggles default to on (in `web/app.js`, `let have = Object.assign({ bike: true, carStart: true, carEnd: true, share: true }`), so 21 is the default.
  Call sites of `plan()` (search `plan()` and `, plan)` in `web/app.js`):
  - Plan trip button: `document.getElementById("go").onclick = plan;` (leave as is)
  - Toggles and controls, which should be debounced: `document.getElementById("daySel").addEventListener("change", plan)`, the same for `timeSel`, the `bikeSel` change handler (comment "routing changes, not just filtering"), the `#whenSeg button` handler (Leave now / Arrive by), the `HAVE_LABEL` loop's `b.onclick` (the four "Using:" buttons), and `swapEnds()`.
  - Point changes, which should stay immediate: the marker `m.on("dragend", ...)` in `setPoint`, the `map.on("click", ...)` handler, the `pick` function inside `attachSuggest`, and the end of the shared-link block (`if (shared) plan();`).
  Not call sites, despite what older notes say: the rider (adult/youth) buttons, the drive slider and the Avoid tolls button never call `plan()`. They only re-rank what is already on screen (`renderResults(lastParts, ...)`).
- **How to fix:**
  1. In `web/app.js`, just above `async function plan`, add:
     ```js
     let planTimer = null;
     function planSoon(){ clearTimeout(planTimer); planTimer = setTimeout(plan, 300); }
     ```
  2. At the very top of `plan()`, add `clearTimeout(planTimer);` so a Plan trip click or a point change cancels any waiting call.
  3. Replace `plan` with `planSoon` in exactly these places: the `daySel` listener, the `timeSel` listener, the `bikeSel` handler (`plan();   // routing changes`), the `#whenSeg` handler, the `HAVE_LABEL` loop `b.onclick`, and `swapEnds`. In the two `addEventListener("change", plan)` lines, pass `planSoon` instead.
  4. In `clearTrip()` (search `function clearTrip`), add `clearTimeout(planTimer);` so Clear is not undone by a waiting plan.
  5. Do not touch the Plan trip button, the drag, click, suggestion pick or shared-link calls.
- **How to check it worked:** Run the app (`bash run.sh`, see `docs/runbooks.md`), plan a trip, open the browser's network tab, and click two "Using:" buttons within half a second. You should see one batch of requests to `/otp/gtfs/v1`, not two. Clicking Plan trip should still start at once. Press Clear right after a toggle: no results should appear. `node --test tests/core.test.mjs` should still pass.
- **Size:** small

### 2. No rate limiting in front of a hosted engine
- **Status:** open (cannot be tested until a server exists)
- **What is wrong:** Anyone who finds the address can send unlimited searches, and each costs about 21 engine queries. A few fast users could slow the engine for everyone. Caddy has no rate limiting built in.
- **Where:** `deploy/server-setup.sh`. Search for `Open 80 and 443 here` and the line `command -v netfilter-persistent`. `deploy/Caddyfile` is where a Caddy plugin would be configured.
- **How to fix:**
  1. Simplest: a firewall rule on the server that limits new connections to port 443 per source address. In `deploy/server-setup.sh`, after the `for p in 80 443` loop and before the `command -v netfilter-persistent` line, add:
     ```bash
     # Limit new HTTPS connections per source address (connection floods).
     sudo iptables -C INPUT -p tcp --dport 443 -m conntrack --ctstate NEW \
       -m hashlimit --hashlimit-name gta443 --hashlimit-mode srcip \
       --hashlimit-above 60/minute --hashlimit-burst 30 -j DROP 2>/dev/null \
     || sudo iptables -I INPUT 1 -p tcp --dport 443 -m conntrack --ctstate NEW \
       -m hashlimit --hashlimit-name gta443 --hashlimit-mode srcip \
       --hashlimit-above 60/minute --hashlimit-burst 30 -j DROP
     ```
     `-I INPUT 1` puts it above the ACCEPT rule, which matters because the first matching rule wins. The `-C` check makes the script safe to run twice.
  2. Know the limit of this rule: a browser sends all 21 queries over one connection (HTTP/2), so this stops connection floods, not one client sending many requests on one connection. QUIC (UDP 443) is not covered either; to avoid that gap add `servers { protocols h1 h2 }` in a global block at the top of `deploy/Caddyfile`.
  3. Heavier alternative: the `caddy-ratelimit` plugin (a custom Caddy build with a `rate_limit` block in the Caddyfile). It counts real requests, so it is the right tool if the firewall rule is not enough. Only do this if abuse actually happens.
  4. Fixing issue 1 first also reduces the load honestly generated by real users.
- **How to check it worked:** Needs a real server. From another machine, open about 100 connections in one minute (for example a shell loop of `curl -s -o /dev/null https://HOST/` ) and see the later ones time out, then confirm a normal browser session still works. On the server, `sudo iptables -L INPUT -n -v` should show the rule with a rising packet count.
- **Size:** small (firewall rule) / medium (plugin)

### 21. Cloud setup files have never been run on a server
- **Status:** written, untested until a server exists (found while writing this list)
- **What is wrong:** The older review said the cloud engine could not load GO alerts or Durham delays. The files now fix this: `deploy/gta-otp.service` sets `GTA_ROUTER_DIR`, `deploy/gta-go-alerts.service` and `deploy/gta-drt-rt.service` exist, `deploy/push-engine.sh` uploads the filter scripts and the Durham zip, and `deploy/server-setup.sh` enables the services. But no server has ever existed, so none of it has run.
- **Where:** the files above, all in `deploy/`.
- **How to fix:**
  1. When a server exists, follow `docs/runbooks.md` section 4.
  2. After `server-setup.sh` finishes, run `sudo systemctl status gta-go-alerts gta-drt-rt gta-otp` and confirm all three are active.
  3. Confirm the two `.pb` files exist in `/home/ubuntu/gta-router/` and are updating.
  4. Update the "Known gaps" list in `docs/runbooks.md` to match.
- **How to check it worked:** In the app, the Service alerts menu (the "More" menu) shows GO alerts, and Durham trips show "live".
- **Size:** small once a server exists

### 19. The live-data recorder loses data when the laptop sleeps
- **Status:** cannot be fixed on a laptop
- **What is wrong:** `scripts/record-feeds.py` saves the live feeds every few minutes. When the laptop sleeps, restarts or loses the network, there are gaps, and the reliability engine will have holes in its history.
- **Where:** `scripts/record-feeds.py`, `scripts/record.sh`, `tests/record-feeds.py`. The checking steps are in `docs/runbooks.md` section 3.
- **How to fix:**
  1. Run the recorder on a computer that is always on, such as the hosted server in issue 21.
  2. Until then, use `docs/runbooks.md` section 3 to check for gaps, and keep the laptop awake while recording matters.
  3. See `docs/plans.md` section 1 for the plan.
- **How to check it worked:** After a day, the saved files under `recordings/` should have no gaps longer than the recording interval.
- **Size:** medium (blocked on a host)

---

## App behaviour

### 3. Opening the app from a phone on the same Wi-Fi does not work
- **Status:** needs the owner's decision (only do this if the owner asks)
- **What is wrong:** The page and both engines listen on this computer only, on purpose. A phone that opens the computer's address gets a page that cannot find the engine.
- **Where:** `web/app.js`, near the top: `const LOCAL = ["localhost", "127.0.0.1", ""].includes(location.hostname);` followed by `const OTP = LOCAL ? "http://localhost:8080/otp/gtfs/v1" : "/otp/gtfs/v1";`. `LOCAL` is true only when the page was opened from this computer. In that case the page talks straight to the engine on port 8080. Otherwise it calls its own address, which is what a hosted copy needs. On a phone `LOCAL` is false, so the page asks the page server on port 8081 for `/otp/gtfs/v1`, which the server does not provide. `LOCAL` is also used once more: `else if (LOCAL) fetch("/reach-engine/wake")`.
  `scripts/web-server.py`: `class Handler`, method `do_GET`, forwards paths starting `/otp/traveltime/` to the Reach engine on `REACH_PORT` (8090) through `pass_to_reach()`, which calls `urllib.request.urlopen` on `http://127.0.0.1:8090` plus the path and sends the answer back. It only handles GET. The trip questions are POST requests, so the server has no `do_POST` yet.
- **How to fix:**
  1. In `scripts/web-server.py`, add a `pass_to_engine` method and a `do_POST`. It should accept only the path `/otp/gtfs/v1`, read `Content-Length` bytes of body, send them with `urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})` to `http://127.0.0.1:8080/otp/gtfs/v1` (timeout 60 seconds), and return status, content type and body the same way `pass_to_reach` does (catch `urllib.error.HTTPError` and `OSError` the same way). Any other POST path gets 404.
  2. In `web/app.js`, change the `OTP` line to `const OTP = "/otp/gtfs/v1";`. Keep `LOCAL` for the wake call only.
  3. In `scripts/web-server.py` `main()`, change `ThreadingHTTPServer(("127.0.0.1", PORT), ...)` to use `os.environ.get("GTA_LISTEN", "127.0.0.1")` as the address.
  4. In `run.sh`, document the opt-in: running `GTA_LISTEN=0.0.0.0 bash run.sh` exposes the page on the local network. Do not change the engines' `--bindAddress 127.0.0.1`; they stay private and only the page server forwards to them.
  5. Warn in the comment that anyone on the same Wi-Fi can then use the app and the engine.
  6. The hosted setup is unaffected: Caddy and Vercel already pass `/otp/gtfs/*` through.
- **How to check it worked:** Run `GTA_LISTEN=0.0.0.0 bash run.sh`, find the computer's address in System Settings, open `http://ADDRESS:8081` on the phone, and plan a trip. Then run `bash run.sh` normally and confirm `curl http://ADDRESS:8081` from the phone fails. On the computer, a plan must still work at `http://localhost:8081`.
- **Size:** medium

### 4. Bike Share dock information is hover only
- **Status:** open
- **What is wrong:** The bike counts and free docks appear only when a mouse pointer rests on a green dock dot. On a touch screen or with a keyboard, nothing shows.
- **Where:** `web/app.js`, search `dock info is hover-only`. The code is `map.on("mouseenter", "docks", ...)` which builds a `maplibregl.Popup` into `dockHover`, and `map.on("mouseleave", "docks", ...)` which removes it. A click on a dock currently drops a pin, handled by `map.on("click", ...)` (search `dock dots are hover-only now`). The trip detail view already has a `dockrow` button list with counts (search `docklist`), which works with a keyboard.
- **How to fix:**
  1. Move the popup-building body of the `mouseenter` handler into a function `showDockPopup(feature)`. Keep `mouseenter` calling it.
  2. Add `map.on("click", "docks", e => { showDockPopup(e.features[0]); })`. Leave the pin dropping as is, so the click does both. (Decision made: pin behaviour must not change, because downtown is dense and users still need to drop pins there.)
  3. Make the popup close on the next map click or after about 6 seconds on touch screens: set `dockHover` to a popup with `closeOnClick: true` for the click path, or clear it with a timer.
  4. Keyboard: dots are drawn on a canvas and cannot take focus. The keyboard path is the existing `dockrow` buttons in the trip detail view. Make sure each shows bikes and docks (it already does when counts exist). Do not try to build focusable dots.
  5. Keep `esc()` around every name, as the existing code does.
- **How to check it worked:** In the browser's device emulation (touch), zoom in to a downtown area and tap a green dot: a popup with the name, bikes and free docks appears. With a mouse, hover still works. Tab to a `dockrow` button in a Bike Share trip detail and press Enter: the map flies to the dock.
- **Size:** small

### 5. A search takes 5 to 14 seconds
- **Status:** cannot be fixed in code
- **What is wrong:** Planning takes several seconds. The first results appear in about 2 seconds, and the rest arrive as each mode mix answers.
- **Where:** The cause is the computer's memory, not the code. `run.sh` starts the engine with `java -Xmx6G`. On a 16 GB computer the engine, the browser and other apps do not all fit, so macOS compresses and swaps memory. The full measurements are in `docs/routing-notes.md` section 8 (search speed: dead ends and the real cause).
- **How to fix:** Already tried and not helpful: reordering the queries, a 4 at a time queue, and changing `-Xmx` between 3G and 6G. Already done: `run.sh` refuses a second copy, `stop.sh` stops it, and the Reach engine only runs while used (`scripts/web-server.py`). What is left:
  1. Close other apps (browsers with many tabs especially) before searching.
  2. Use a computer with more memory, or the hosted server in `docs/runbooks.md` section 4.
  3. Trim the mode mixes in `COMBOS` in `web/core.js`. The owner declined this and chose to keep every mix. Do not do it without asking.
- **How to check it worked:** With other apps closed, time a plan with the network tab open: all `/otp/gtfs/v1` requests should finish in under about 6 seconds.
- **Size:** not applicable

### 6. The page code is one 3300-line file
- **Status:** open, optional
- **What is wrong:** Nothing a user notices. `web/app.js` is hard to navigate and a weaker model can easily break something while editing it.
- **Where:** `web/app.js` (about 3,200 lines) and the `<style>` block in `web/index.html` (about 685 lines, from `<style>` to `</style>`). The file's own section comments show the groups: icons (`ICONS`, `icn`), subway diagrams (`BOARDING`, `boardingInfo`, `trainDiagram`), map looks (`LOOKS`, `PALETTES`, `appleGeometry`, `recolorStyle`, `applyLook`), highway shields (`SHIELD_REFS`, `prepareShields`, `ensureShields`), POI badges (`POI_BADGE`, `badgeSvg`, `ensurePoiBadges`), map buttons (look, 3D, rotate, compass), route drawing (`ensureRoute`, `drawRoute`), transit lines (`ensureTransit`), Bike Share docks (`loadDocks`), search suggestions (`attachSuggest`), planning (`fetchCombo`, `plan`), results (`renderResults`, `cardHTML`), detail view (`renderDetail`), controls, More menu, themed dropdowns (`skinSelect`), and Reach mode (the `REACH MODE` block).
- **How to fix:** Do only the two safe splits, one at a time, no build step:
  1. Move the CSS into `web/style.css` and replace the `<style>` block with `<link rel="stylesheet" href="style.css">`. Check that `deploy/deploy-web.sh` and any file lists include the new file.
  2. Move the map styling group (from the `map (vector, light/dark follows the system)` section through the POI badge functions, roughly lines 125 to 780) into `web/map-style.js`, loaded as a classic script before `app.js`. `app.js` is a classic script on purpose (its top-level `let` and `const` are shared with `core.js`), so do not turn anything into a module.
  3. After each move, run the checks below. Never move code and change it in the same step.
- **How to check it worked:** `node --test tests/core.test.mjs`, then run the app and click through: look button, 3D, a plan, a detail view, the Reach map. Compare screenshots before and after (see `docs/testing-notes.md`).
- **Size:** medium

### 17. Interface rough edges
- **Status:** open (the phone layout part needs the owner's decision)
- **What is wrong:** (a) The pinned search card floats over the top result card while you scroll. (b) Busy trips show a long chain of badges (car, bus, bus, subway, walk). (c) There is no real phone layout: the panel is a floating card, 384 px wide at most, and there is no width media query at all. It works at 375 px but was not designed for it. (d) The leftover unused CSS from the old card design is covered in issue 23.
- **Where:** (a) `web/index.html`, `.search { ... position: sticky; top: 0; z-index: 4; }` and `.search::before`. (b) `web/app.js`, `function legRow` (search `legrow`). (c) `web/index.html`, `#panel` (`width: min(384px, calc(100vw - 28px))`); the only `@media` rules are for dark mode and reduced motion.
- **How to fix:**
  1. (a) Give the results list a top padding equal to the search card's height, or make the card sit above the scroll area instead of inside it. Test by scrolling a long result list.
  2. (b) In `legRow`, if there are more than 5 non-walk legs, show the first two, a `+N` chip, and the last. Do this only on cards below the first one. Ask the owner before changing the top card.
  3. (c) Add a phone layout only if the owner asks: a `@media (max-width: 600px)` block that makes `#panel` a bottom sheet. Follow `docs/design-rules.md` first; the owner rejects a templated look.
- **How to check it worked:** Open the app at desktop width and in the browser's phone emulation (375 by 812). Plan a long trip and scroll: the search card must not hide text.
- **Size:** medium

### 22. Photon search and map tiles are outside services (found while writing this list)
- **Status:** cannot be fixed (a choice already made)
- **What is wrong:** Typing in the search boxes sends the text, and dropped pin coordinates, to the Photon geocoder. Map tiles and styles come from OpenFreeMap (`HOSTED` in `web/app.js`). If either is down or blocks the app, search or the map breaks while trip planning still works.
- **Where:** `web/app.js`, `attachSuggest` and `reverseLabel`; `const HOSTED`. The README states this.
- **How to fix:** Nothing to do unless one of them stops working. If so, search `photon` in `web/app.js` and switch the address to another Photon-compatible service.
- **How to check it worked:** Type "union station" in a search box and see suggestions.
- **Size:** small

### 23. Leftover unused CSS rule (found while writing this list)
- **Status:** open
- **What is wrong:** Nothing visible. Older notes listed `.via`, `.legs`, `.sep`, `.gchip` and `.abitem` as unused. I checked every CSS class in `web/index.html` against `web/index.html`, `web/app.js` and `web/core.js`. The first four no longer exist anywhere, so there is nothing to delete. `.abitem` is in use (the service alerts list in `web/app.js` builds `<div class="abitem">`). The only truly unused class is `.sect`.
- **Where:** `web/index.html`, search `.sect { margin-top: 14px; }` and the two rules after it (`.sect h2` and `.sect h2 .icn`). The `maplibregl-*` names that also show as unused belong to the map library and must stay.
- **How to fix:**
  1. Delete those three `.sect` rules.
  2. Re-run a class check: for every `.name` in the `<style>` block, search for `name` in the HTML body and the two scripts.
- **How to check it worked:** Reload the app, open a trip detail view: nothing changes visually.
- **Size:** small

---

## Data gaps

### 8. Subway boarding diagrams cover few stations
- **Status:** open, optional
- **What is wrong:** In a trip's detail view, a TTC subway leg can show which car to board. This only works for some stations; elsewhere nothing is shown. The numbers were transcribed by eye from a 2005 guide, so they may be off by one car, and stations renovated since then may be wrong. Union is left out on purpose because its platforms were rebuilt in 2015.
- **Where:** `web/subway-boarding.json`. It has a `stations` object. The file has 26 station keys now (older notes say 24, and about 69 stations exist). Each key is the station name in lowercase, without " Station", periods or apostrophes (for example `"queens park"`). Under each is a direction key (the terminus the train heads toward: `vaughan` or `finch` for Line 1, `kipling` or `kennedy` for Line 2, `donmills` or `sheppardyonge` for Line 4), then `{ "car": 5, "of": 6, "why": "the stairs & escalator up to College St" }`. An optional `transfer` entry overrides it when the next leg is another subway ride. The code is `boardingInfo` and `trainDiagram` in `web/app.js`. The source guide is `ttc-rider-efficiency-guide-2005.pdf` in the repo root. The data is licensed CC BY-NC-SA, not the project's licence (see the `_about` text in the file).
- **How to fix:**
  1. Add a station only from the PDF or from new data the owner supplies. Never guess.
  2. Copy an existing station block and change the key, the car number, `of` and the plain `why`.
  3. A wrong diagram is worse than none, so skip any station you cannot read clearly. Do not add Union.
  4. Keep the file valid JSON.
- **How to check it worked:** Plan a trip that rides the new station, open the detail view, and confirm the diagram shows the right car and wording. Run `python3 -c "import json;json.load(open('web/subway-boarding.json'))"`.
- **Size:** small per station

### 9. Bike to station can look slow in north York Region
- **Status:** partly done (the results list already softens it)
- **What is wrong:** In north York Region, "bike to station" can come out slower than transit alone, because OpenStreetMap has few bike racks mapped at stops there, so the router rides many kilometres to the one rack it knows.
- **Where:** `data/parking-patch.osc`. The file is an OpenStreetMap change file. Existing edits are `<modify>` blocks for parking areas and one `<create>` block with new nodes (ids start at 20000000001) near the end. `rankPool` in `web/core.js` already hides any option that is both slower and no cheaper than another by folding it under "more options", so these results are not headlined. Background: `docs/routing-notes.md` (bike parking data gap).
- **How to fix:**
  1. Find a stop where a rack really exists. Check it in person or in a map photo source; do not add racks you have not verified.
  2. Add a node inside the `<create>` block in `data/parking-patch.osc` with a new unused id, `lat`, `lon`, and tags `amenity=bicycle_parking` plus `bicycle_parking=stands`. Place it close to the stop, in the same way existing racks near other stops are mapped.
  3. Rebuild the graph (`docs/runbooks.md` section 2 or `bash setup.sh`). The patch must be applied to every fresh map download.
  4. Run `python3 tests/benchmark.py`.
- **How to check it worked:** Plan from the affected area to a downtown destination with "My bike" on; the bike option should ride to the new rack's stop.
- **Size:** medium

### 10. Etobicoke North GO parking lot unreachable
- **Status:** open, revisit only if reported
- **What is wrong:** The Etobicoke North station parking lot is tagged, but the router cannot reach it within 1200 m of walking distance from the station point, so driving there may not be offered.
- **Where:** `data/parking-patch.osc` and `docs/routing-notes.md` (the GO station park-and-ride audit).
- **How to fix:** Only if a rider reports it: find where the lot connects to the road in the map data, then add or fix the link in the patch file, rebuild, and test.
- **How to check it worked:** Plan a drive-to-station trip from nearby and see the lot used.
- **Size:** medium

### 11. Station walking times include a fixed 2 minutes
- **Status:** cannot be fixed (kept on purpose)
- **What is wrong:** Every walk into or out of a subway station includes a fixed 2 minutes. That is right for most stations but double counted at about 16 whose insides are mapped.
- **Where:** OpenTripPlanner's `subwayAccessTime`. It is one global number and cannot be set per station. See `docs/routing-notes.md`.
- **How to fix:** Leave it. The real fix is mapping station interiors in OpenStreetMap, which is large work and not started.
- **How to check it worked:** Not applicable.
- **Size:** not applicable

### 12. No VIA Rail, Hamilton, Guelph or Barrie local transit
- **Status:** cannot be fixed without scope change (out of scope unless asked)
- **What is wrong:** These services are not in the graph, so the app never shows them.
- **Where:** the feed list is `scripts/feeds.sh`; fares are in `LOCAL_FARES` in `web/core.js`; `tests/fare-sync.py --feeds` checks each feed has a fare.
- **How to fix:** Only if the owner asks. Add the feed in `scripts/feeds.sh`, add a fare row, rebuild, then run the benchmark.
- **How to check it worked:** A trip in the new area shows the new agency with a fare.
- **Size:** large

### 13. Live data that does not work
- **Status:** cannot be fixed (outside our control), except as noted
- **What is wrong:** (a) TTC delays: the live feed's trip ids do not match the schedule. (b) Brampton: the old live endpoint is dead and the new one has not been found. (c) UP Express: the feed was empty when tried. (d) GO and UP live feeds have been frozen or empty at the source since 2026-11-14, which is not our bug.
- **Where:** Detail in `docs/routing-notes.md` section 10. Feeds are wired in `engine/router-config.json`. The TTC filter `scripts/ttc-rt-filter.py` is local only and unused.
- **How to fix:**
  1. Re-probe each feed before believing it still fails. For TTC, check whether live trip ids match static ones (older notes found 0 of 1890).
  2. For Brampton, search the city's open data "Transit API Service" for a new realtime address.
  3. For UP, probe during service hours.
  4. Wire a feed only with a benchmark run before and after.
- **How to check it worked:** Trip cards show a "live" chip for trips on that agency.
- **Size:** medium each

### 14. Highway 407 toll limits
- **Status:** cannot be fixed fully (limits stated in the app)
- **What is wrong:** The toll estimate assumes a transponder, does not treat statutory holidays as weekend rates, leaves out the provincially run 407 East, and uses rates that change every January 1.
- **Where:** `web/core.js` (`legTollCost`, `tollRatesStale`), `web/toll-rates.json`, `web/toll-roads.json`, `scripts/make_toll_rates.py`, `scripts/make_toll_cells.py`. The page shows a warning bar when rates are stale (search `warnbar` in `web/app.js`).
- **How to fix:**
  1. Each January, re-read the rate chart on the 407 ETR site and run `scripts/make_toll_rates.py` (`docs/runbooks.md`, yearly chores).
  2. 407 East needs new map data, because it is not tagged as a toll road in the extract. Do not guess.
- **How to check it worked:** The warning bar is gone and `node --test tests/core.test.mjs` passes.
- **Size:** small each January

---

## Needs the owner's decision

### 15. Benchmark expected answers never confirmed by a rider
- **Status:** needs the owner's decision
- **What is wrong:** The routing benchmark's expected answers were written by the developer. Only two trips (`markham_to_square_one` and `richmond_hill_to_scarborough_centre`) were corrected by a local rider. The other eight were never confirmed.
- **Where:** `tests/benchmarks.json` (its `_readme` says so) and `tests/benchmark.py`. Older notes say one trip has no expected answer and is report-only; the file does not agree. No trip now has `expected_combo: null`, so none is report-only. The script still supports it (a null combo prints REPORT-ONLY).
- **How to fix:**
  1. Treat a FAIL after a schedule refresh as "look at it", not automatically a bug. Schedules change, and the expected answer may now be wrong.
  2. To update an answer honestly: ask a rider who knows the trip what they really do, check the answer against the GO or TTC timetable, then edit `expected_plain`, `must_include_any` and `max_minutes`, and write who confirmed it in the `_readme`.
  3. Never loosen a check just to make it pass.
- **How to check it worked:** `python3 tests/benchmark.py` (engine running); see `docs/testing-notes.md`.
- **Size:** small per trip

### 16. Drive slider at "Any" shows near-all-drive trips
- **Status:** needs the owner's decision
- **What is wrong:** With the drive slider at "Any", some results drive nearly the whole way and take one short bus.
- **Where:** `visibleTrips` in `web/core.js` (it applies the drive cap; it replaced `visibleIts` in `web/app.js`) and the slider block in `web/app.js` (`driveRange`, top of the track is 60 and means no limit); `rankPool` in `web/core.js`, which already drops drives beaten by a car-free trip.
- **How to fix:** Not decided. Do not add a rule based on direction (the owner rejected that). If the owner picks an approach, the place to add it is `rankPool` in `web/core.js`, with a unit test in `tests/core.test.mjs`.
- **How to check it worked:** Not applicable until decided.
- **Size:** small once decided

---

## Not bugs

### 7. Fare rules also exist in a local-only script
- **Status:** not a bug
- **What is wrong:** Nothing. `web/core.js` is the single source of truth. `scripts/costs.py` is a local-only copy.
- **Where:** `tests/fare-sync.py` compares the two when the local file is present.
- **How to fix:** Nothing to fix. Do not add features to the Python copy. Change fares in `web/core.js` only.
- **How to check it worked:** `python3 tests/fare-sync.py`.
- **Size:** not applicable

### 18. Not built: which door at Union for GO trains
- **Status:** not built (design only, `HANDOFF-go-union-door.md`)
- **What is wrong:** The app does not tell you where to stand on a GO train arriving at Union.
- **Where:** `HANDOFF-go-union-door.md`; the idea reuses the subway car diagram (`trainDiagram`, `web/subway-boarding.json`).
- **How to fix:** In five lines:
  1. Idea: aim for an end of the train, not a car. Union platforms run east to west, the east end leads to the Bay concourse and the subway, the west end to York concourse and the Skywalk.
  2. Locomotives sit at the east end at Union, and GO says trains stop with a fixed mark 122.5 m from the engine end, so east-end cars stop in the same place whatever the train length.
  3. A first version needs no new data: show "ride the east end for the subway" on a GO leg into Union.
  4. The exact door needs the live platform and the coach count, which the Metrolinx feeds give, plus a one-time survey of stairs on each platform.
  5. Platform numbers only appear about 10 to 20 minutes before departure, so the exact version only works near departure.
- **How to check it worked:** Not applicable.
- **Size:** large

### 20. Pure car trips are deliberately not offered
- **Status:** not a bug
- **What is wrong:** There is no "drive the whole way" option. Free-flow driving times would win almost every comparison and mislead.
- **Where:** `COMBOS` in `web/core.js` (the only pure modes are bike, Bike Share and walk).
- **How to fix:** Nothing, until there is a traffic model.
- **How to check it worked:** Not applicable.
- **Size:** not applicable
