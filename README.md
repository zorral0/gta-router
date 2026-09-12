# GTA Router

A trip planner for the Greater Toronto Area that answers the question Google
and Apple Maps don't: **is it faster and cheaper to drive to a GO station and
take the train, bike to the subway, or just take transit the whole way?**

Pick a start and an end on the map, and it lays the options side by side,
each with the travel time **and the real dollar cost**: fares with One Fare
transfers, gas, parking, and 407 tolls from the public rate card.

<!-- Add a screenshot here: save one as docs/screenshot.png, then replace
     this comment with:  ![GTA Router](docs/screenshot.png)  -->

## Why I built it

I kept seeing trip planners that treat "drive" and "transit" as two separate
worlds, when a lot of GTA commutes are really both: drive to the GO lot, then
ride in. I wanted to see those trips properly, with what they actually cost.
I tested every version on my own commute and fixed whatever felt wrong.

## What it does

- **Park-and-ride and bike-and-ride routing** across GO, UP Express, TTC,
  YRT, MiWay, Brampton Transit and Durham Region Transit, all in one network.
- **Money next to minutes** for every option, including 407 ETR tolls.
- **Live GO train delays and service alerts** from Metrolinx open data.
- **A map styled after Apple Maps**, with the subway, GO and bus lines drawn
  on it, 3D buildings, and trackpad rotate and tilt.
- **A "Reach" map** that colours everywhere you can get to within a
  given time.
- **A test suite** of real GTA trips with known sane answers, run after every
  routing change.

## How it was built

- Routing engine: [OpenTripPlanner 2.9](https://www.opentripplanner.org/),
  fed with each agency's public GTFS schedules and an OpenStreetMap extract
  of the GTA.
- Map: [MapLibre GL](https://maplibre.org/) with
  [OpenFreeMap](https://openfreemap.org/) tiles.
- Data prep scripts in Python; the app itself is one HTML page.
- Built with Claude Code as my coding partner. I came up with the idea,
  made the design calls, tested it on real trips, and directed every change.

## Running it yourself

You need a Mac or Linux machine with about 8 GB of free memory.

1. Get a free Metrolinx Open Data key
   ([register here](https://api.openmetrolinx.com/OpenDataAPI/Help/Registration/en)),
   copy `metrolinx.env.example` to `metrolinx.env`, and put the key in it.
2. `bash setup.sh`: downloads the engine, all transit schedules and the
   GTA street map (about 2 GB, takes a while).
3. `bash build.sh`: stitches it into one routing graph (5-15 min).
4. `bash run.sh`: starts everything and opens the app at
   http://localhost:8081. Ctrl+C stops it.

To check routing quality any time (while it's running):

    python3 benchmark.py

## What each file does

- setup.sh / refresh.sh: download (or re-download) the schedules and map.
- build.sh: builds the routing graph. Re-run when schedules update.
- run.sh: starts the routing engine plus the app.
- web/index.html: THE APP (what run.sh opens).
- build-config.json / router-config.json / otp-config.json: settings the
  engine reads. router-config.json is where routing behaviour gets tuned.
- costs.py: the dollar-cost model (fares, One Fare transfers, gas,
  parking). The web page has the same model built in; if you change one,
  change the other.
- compare.py: command-line demo of the same comparison for one trip.
- benchmark.py + benchmarks.json: the test suite.
- make_*.py: generate the fare zones, toll rates and line shapes the app
  draws.
- patch_ttc_transfers.py: adds subway interchange transfers the TTC feed
  leaves out (Bloor-Yonge etc.).
- deploy/: scripts for putting the app online.

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
- The search box uses the free OpenStreetMap geocoder, so search and map
  tiles need internet; routing itself runs locally.

## Data

Transit schedules come from each agency's open data program. Map data
© OpenStreetMap contributors.
