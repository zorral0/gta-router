# GTA Router

Multimodal trip planning for the GTA: routes that combine driving or biking
to a GO station with transit, plus true dollar cost next to travel time.

## What each file does

- setup.sh: one-time. Installs Java, downloads the routing engine (OTP2),
  all transit schedules (GO, UP Express, TTC, YRT, MiWay, Brampton, DRT),
  and the GTA street map. Also patches TTC subway transfers.
- build.sh: stitches all that data into one routing graph. Re-run monthly
  when schedules update.
- run.sh: starts everything - the routing engine plus the app - and opens
  the app in your browser at http://localhost:8081. Ctrl+C stops it all.
- web/index.html: THE APP (what run.sh opens). Click the map (or type
  places) for start and end, and see transit-only vs bike-to-station vs
  drive-to-station side by side, each with minutes AND dollars.
- build-config.json / router-config.json / otp-config.json: settings the
  engine reads. router-config.json is where routing behaviour gets tuned.
- costs.py: attaches dollar costs to routes (fares, One Fare transfers,
  gas, parking). The web page has the same model built in - if you change
  one, change the other.
- compare.py: command-line demo. Same three-way comparison for one trip,
  printed as text.
- benchmark.py + benchmarks.json: the test suite. ~10 GTA trips with known
  sane answers; run `python3 benchmark.py` after any change to check
  nothing got worse. Currently 9/9 passing.
- patch_ttc_transfers.py: injects subway interchange transfers the TTC
  feed omits (Bloor-Yonge etc.). setup.sh runs it; must run before build.sh.

## Setup (once)

1. Open Terminal, cd into this folder
2. bash setup.sh   (downloads ~2 GB total, takes a while)
3. bash build.sh   (5-15 min)
4. bash run.sh   (opens the app in your browser automatically)

To re-check routing quality any time (server must be running):

    python3 benchmark.py

## Known rough edges

- YRT's download sometimes requires accepting a licence on their site.
  If setup.sh warns about it, grab the zip manually from
  yrt.ca > About us > Open Data, save as yrt-gtfs.zip.
- Brampton's download URL changes occasionally; setup.sh has the current
  one and a comment on where to find a replacement (transit.land).
- Some fare constants in costs.py are marked UNVERIFIED (YRT, DRT,
  Brampton PRESTO, UP Express). TTC and MiWay were verified July 2026.
- Park-and-ride routing depends on GO lots being tagged in OpenStreetMap.
  Most are, but if a station you know isn't offered, that's why.
- Feeds go stale. If routes disappear, re-run the setup.sh downloads and
  then build.sh.
- The web page's search box uses the free OpenStreetMap geocoder
  (internet required for search and map tiles; routing itself is local).

## Roadmap (agreed scope)

- MVP: smart routing for unfamiliar trips + cost comparison (done)
- Later: parking lot occupancy, Bike Share Toronto availability,
  real-time delays, arrival-end (last mile) quality
