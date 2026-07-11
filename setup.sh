#!/bin/bash
# GTA Router - one-time setup script for macOS
# Installs Java, downloads OTP2 and all GTA data.
# Run from inside the gta-router folder:  bash setup.sh

set -e  # stop on first error

echo "=== Step 1/5: Installing Java 25 and osmium (via Homebrew) ==="
if ! command -v brew &> /dev/null; then
  echo "Homebrew not found. Install it first from https://brew.sh then re-run this script."
  exit 1
fi
brew install openjdk@25 osmium-tool || true
# Make java visible on the command line
sudo ln -sfn "$(brew --prefix)/opt/openjdk@25/libexec/openjdk.jdk" /Library/Java/JavaVirtualMachines/openjdk-25.jdk || true
java -version

echo ""
echo "=== Step 2/5: Downloading OpenTripPlanner 2.9.0 (~150 MB) ==="
if [ ! -f otp.jar ]; then
  curl -L -o otp.jar "https://repo1.maven.org/maven2/org/opentripplanner/otp-shaded/2.9.0/otp-shaded-2.9.0-shaded.jar"
else
  echo "otp.jar already present, skipping."
fi

echo ""
echo "=== Step 3/5: Downloading GTFS transit schedules ==="
# GO Transit (Metrolinx open data)
curl -L -o go-gtfs.zip "https://assets.metrolinx.com/raw/upload/v1683228856/Documents/Metrolinx/Open%20Data/GO-GTFS.zip"
# UP Express
curl -L -o up-gtfs.zip "https://assets.metrolinx.com/raw/upload/v1682367798/Documents/Metrolinx/Open%20Data/UP-GTFS.zip"
# TTC merged feed (subway + streetcar + bus), City of Toronto open data
curl -L -o ttc-gtfs.zip "https://ckan0.cf.opendata.inter.prod-toronto.ca/dataset/7795b45e-e65a-4465-81fc-c36b9dfff169/resource/cfb6b2b8-6191-41e3-bda1-b175c51148cb/download/TTC%20Routes%20and%20Schedules%20Data.zip"
# YRT (York Region Transit). This URL is the long-standing direct link; if it
# fails, download manually from https://www.yrt.ca/en/about-us/open-data.aspx
curl -L -o yrt-gtfs.zip "https://www.yrt.ca/google/google_transit.zip" || \
  echo "WARNING: YRT download failed. Get it manually from yrt.ca open data page and save as yrt-gtfs.zip"
# MiWay (Mississauga)
curl -L -o miway-gtfs.zip "https://www.miapp.ca/GTFS/google_transit.zip"
# Brampton Transit. The old brampton.ca link died mid-2026; this is the
# ArcGIS item transit.land lists as the official feed. If it fails, check
# https://www.transit.land/feeds/f-dpz2-bramptontransit for the current URL.
curl -L -o brampton-gtfs.zip "https://www.arcgis.com/sharing/rest/content/items/a355aabd5a8c490186bdce559c9c75fb/data"
# DRT (Durham Region Transit)
curl -L -o drt-gtfs.zip "https://maps.durham.ca/OpenDataGTFS/GTFS_Durham_TXT.zip"

# TTC publishes no transfers.txt; inject subway interchange transfers so
# the router knows Bloor-Yonge etc. are internal (see patch_ttc_transfers.py)
python3 patch_ttc_transfers.py

# Extract GO's real station-to-station fare table for the cost model
python3 make_go_fares.py

echo ""
echo "=== Step 4/5: Downloading OpenStreetMap data for Ontario (~1.5 GB) ==="
if [ ! -f ontario-latest.osm.pbf ]; then
  curl -L -o ontario-latest.osm.pbf "https://download.geofabrik.de/north-america/canada/ontario-latest.osm.pbf"
else
  echo "Ontario extract already present, skipping."
fi

echo ""
echo "=== Step 5/5: Cropping OSM data to the GTA ==="
# Bounding box covers Hamilton to Oshawa, Lake Ontario to Barrie fringe.
# Cropping keeps the graph build fast and memory use reasonable.
osmium extract --bbox -80.30,43.20,-78.40,44.35 ontario-latest.osm.pbf -o gta.osm.pbf --overwrite

# Mark known commuter lots as park-and-ride. OpenStreetMap is missing the
# park_ride=yes tag on ~28 real commuter lots (TTC subway lots like
# Hwy 407 / Pioneer Village / Finch West, several GO lots, MTO carpool
# lots), so the router would never park at them; this also adds a working
# entrance point for the Centennial GO garage. See HANDOFF.md.
osmium apply-changes gta.osm.pbf parking-patch.osc -o gta-parkfix.osm.pbf --overwrite
mv gta-parkfix.osm.pbf gta.osm.pbf

# Basic sanity checks on the downloads
echo ""
echo "=== Verifying downloads ==="
for f in go-gtfs.zip up-gtfs.zip ttc-gtfs.zip yrt-gtfs.zip miway-gtfs.zip brampton-gtfs.zip drt-gtfs.zip; do
  if unzip -l "$f" | grep -q "stops.txt"; then
    echo "OK: $f looks like a valid GTFS feed"
  else
    echo "PROBLEM: $f does not contain stops.txt - it may be an error page. Re-download manually."
  fi
done

echo ""
echo "Setup complete. Next:  bash build.sh"
