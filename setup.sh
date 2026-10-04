#!/bin/bash
# GTA Router - one-time setup script for macOS
# Installs Java, downloads OpenTripPlanner and all GTA data, and builds the
# routing graph. The engine's files all live in engine/.
# Run from inside the gta-router folder:  bash setup.sh

set -e  # stop on first error
cd "$(dirname "$0")"

echo "=== Step 1/6: Installing Java 25 and osmium (via Homebrew) ==="
if ! command -v brew &> /dev/null; then
  echo "Homebrew not found. Install it first from https://brew.sh then re-run this script."
  exit 1
fi
brew install openjdk@25 osmium-tool || true
# Make java visible on the command line
sudo ln -sfn "$(brew --prefix)/opt/openjdk@25/libexec/openjdk.jdk" /Library/Java/JavaVirtualMachines/openjdk-25.jdk || true
java -version

# downloads, map data and the graph all go in engine/
cd engine

echo ""
echo "=== Step 2/6: Downloading OpenTripPlanner 2.9.0 (~150 MB) ==="
if [ ! -f otp.jar ]; then
  curl -L -o otp.jar "https://repo1.maven.org/maven2/org/opentripplanner/otp-shaded/2.9.0/otp-shaded-2.9.0-shaded.jar"
else
  echo "otp.jar already present, skipping."
fi

echo ""
echo "=== Step 3/6: Downloading GTFS transit schedules ==="
# The list of feeds and the download checks live in scripts/feeds.sh,
# shared with refresh.sh. A broken download (an error page saved as .zip)
# is caught here, before anything below tries to use it.
. ../scripts/feeds.sh
if ! fetch_all; then
  echo ""
  echo "Some schedule feeds could not be downloaded (see PROBLEM above)."
  echo "The graph cannot be built without them. Fix the link or download the"
  echo "file by hand into engine/, then run this script again."
  exit 1
fi

# TTC publishes no transfers.txt; inject subway interchange transfers so
# the router knows Bloor-Yonge etc. are internal
python3 ../scripts/patch_ttc_transfers.py

# Extract GO's real station-to-station fare table for the cost model
python3 ../scripts/make_go_fares.py

# The subway/streetcar/GO lines painted on the map, in their own colours
python3 ../scripts/make_transit_lines.py

echo ""
echo "=== Step 4/6: Downloading OpenStreetMap data for Ontario (~1.5 GB) ==="
if [ ! -f ontario-latest.osm.pbf ]; then
  curl -L -o ontario-latest.osm.pbf "https://download.geofabrik.de/north-america/canada/ontario-latest.osm.pbf"
else
  echo "Ontario extract already present, skipping."
fi

echo ""
echo "=== Step 5/6: Cropping OSM data to the GTA ==="
# Bounding box covers Hamilton to Oshawa, Lake Ontario to Barrie fringe.
# Cropping keeps the graph build fast and memory use reasonable.
osmium extract --bbox -80.30,43.20,-78.40,44.35 ontario-latest.osm.pbf -o gta.osm.pbf --overwrite

# Mark known commuter lots as park-and-ride. OpenStreetMap is missing the
# park_ride=yes tag on ~28 real commuter lots (TTC subway lots like
# Hwy 407 / Pioneer Village / Finch West, several GO lots, MTO carpool
# lots), so the router would never park at them; this also adds a working
# entrance point for the Centennial GO garage.
osmium apply-changes gta.osm.pbf ../data/parking-patch.osc -o gta-parkfix.osm.pbf --overwrite
mv gta-parkfix.osm.pbf gta.osm.pbf

echo ""
echo "=== Rebuilding the toll-road grid (web/toll-roads.json) ==="
# The router engine has NO toll support, so the app measures for itself how
# much of a drive runs on Highway 407 and prices it - from this grid, built
# out of the OSM data we just downloaded. Stale grid = wrong toll marks and
# wrong toll dollars, so it is rebuilt here, from the SAME gta.osm.pbf the
# graph will be built from. See scripts/make_toll_cells.py.
# Deliberately non-fatal: a missing grid only costs the toll marks (the app
# checks and carries on), which is not worth failing a 2 GB setup over.
toll_grid () {
  local tmp
  tmp="$(mktemp -d)" || return 1
  osmium tags-filter gta.osm.pbf w/toll=yes -o "$tmp/toll.osm.pbf" --overwrite \
    && osmium export "$tmp/toll.osm.pbf" -f geojson -o "$tmp/toll.geojson" --overwrite \
    && python3 ../scripts/make_toll_cells.py "$tmp/toll.geojson" ../web/toll-roads.json
  local rc=$?
  rm -rf "$tmp"
  return $rc
}
if toll_grid; then
  echo "OK: web/toll-roads.json rebuilt from this OSM extract"
else
  echo "WARNING: could not rebuild web/toll-roads.json. Everything still"
  echo "works, but the app will not mark or price Highway 407 tolls until"
  echo "this succeeds. Re-run:  bash setup.sh  (or see scripts/make_toll_cells.py)"
fi

echo ""
echo "=== Step 6/6: Building the routing graph (5-15 minutes) ==="
java -Xmx8G -jar otp.jar --build --save .

echo ""
echo "Setup complete. Next:  bash run.sh"
