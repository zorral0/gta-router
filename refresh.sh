#!/bin/bash
# GTA Router - refresh all transit schedule data and rebuild the graphs.
#
# WHY: agencies replace their schedules constantly (TTC roughly every
# 6 weeks). The app keeps answering from whatever data it was built with,
# so stale data = confidently wrong answers - and TTC's live delays can
# only match up when the schedule data is current. Run this about once a
# month, or whenever the app shows the red "schedule data runs out"
# warning.
#
# WHAT IT DOES (roughly 10-15 minutes):
#   1. re-downloads the ten GTFS schedule zips (a failed or broken
#      download keeps the old copy - never leaves you worse off)
#   2. re-applies the TTC transfers patch + regenerates the GO fare table
#   3. rebuilds BOTH graphs (main 2.9 + the 2.5 reach-map one), keeping
#      the previous graphs as *.prev for rollback
#   4. prints what to do next (restart + benchmark)
#
# The map (OSM) data is NOT re-downloaded - roads change far slower than
# schedules. For fresh OSM use setup.sh (it re-applies
# data/parking-patch.osc in the right order).
#
# Usage:  Ctrl+C the running app first, then:  bash refresh.sh

set -e
cd "$(dirname "$0")/engine"   # feeds, jars and graphs live in engine/

# refuse to run alongside the servers: the build needs the RAM, and
# swapping graph files under a live engine helps nobody
if pgrep -f "otp.jar --load" >/dev/null || pgrep -f "otp25.jar" >/dev/null; then
  echo "The app is still running. Press Ctrl+C in its Terminal window first,"
  echo "then run this again."
  exit 1
fi

trap 'echo ""; echo "SOMETHING FAILED - your previous graphs are safe as"
echo "engine/graph.obj.prev / engine/graph.obj.otp25.prev. To restore them:"
echo "  cd engine && mv graph.obj.prev graph.obj && mv graph.obj.otp25.prev graph.obj.otp25"' ERR

echo "=== 1/4 Downloading fresh schedules ==="
fetch () {  # fetch <file> <url>
  local f="$1" url="$2"
  if curl -fsSL --retry 2 -m 300 -o "$f.new" "$url" \
     && unzip -l "$f.new" 2>/dev/null | grep -q "stops.txt"; then
    mv "$f.new" "$f"
    echo "OK: $f"
  else
    rm -f "$f.new"
    echo "WARNING: $f download failed or looked broken - KEEPING the old copy."
  fi
}
fetch go-gtfs.zip       "https://assets.metrolinx.com/raw/upload/v1683228856/Documents/Metrolinx/Open%20Data/GO-GTFS.zip"
fetch up-gtfs.zip       "https://assets.metrolinx.com/raw/upload/v1682367798/Documents/Metrolinx/Open%20Data/UP-GTFS.zip"
fetch ttc-gtfs.zip      "https://ckan0.cf.opendata.inter.prod-toronto.ca/dataset/7795b45e-e65a-4465-81fc-c36b9dfff169/resource/cfb6b2b8-6191-41e3-bda1-b175c51148cb/download/TTC%20Routes%20and%20Schedules%20Data.zip"
fetch yrt-gtfs.zip      "https://www.yrt.ca/google/google_transit.zip"
fetch miway-gtfs.zip    "https://www.miapp.ca/GTFS/google_transit.zip"
fetch brampton-gtfs.zip "https://www.arcgis.com/sharing/rest/content/items/a355aabd5a8c490186bdce559c9c75fb/data"
fetch drt-gtfs.zip      "https://maps.durham.ca/OpenDataGTFS/GTFS_Durham_TXT.zip"
# Halton local buses
fetch oakville-gtfs.zip   "https://www.arcgis.com/sharing/rest/content/items/d78a1c1ad6a940009de8b68839a8f606/data"
fetch burlington-gtfs.zip "https://opendata.burlington.ca/gtfs-rt/GTFS_Data.zip"
fetch milton-gtfs.zip     "https://metrolinx.tmix.se/gtfs/gtfs-milton.zip"

echo ""
echo "=== 2/4 Re-applying the TTC transfer patch + GO fare table ==="
python3 ../scripts/patch_ttc_transfers.py   # TTC ships no transfers.txt
python3 ../scripts/make_go_fares.py         # real GO fare table -> web/go-fares.json
python3 ../scripts/make_transit_lines.py    # lines drawn on the map -> web/transit-lines.json

echo ""
echo "=== 3/4 Rebuilding the reach-map graph (2.5 engine, ~4 min) ==="
# back up the current graphs before any build overwrites graph.obj
if [ -f graph.obj ]; then cp -f graph.obj graph.obj.prev; fi
if [ -f graph.obj.otp25 ]; then cp -f graph.obj.otp25 graph.obj.otp25.prev; fi
# The Reach map is optional: it needs OpenTripPlanner 2.5 saved as otp25.jar.
if [ -f otp25.jar ]; then
  java -Xmx8G -jar otp25.jar --build --save .
  mv graph.obj graph.obj.otp25
  ln -sf ../graph.obj.otp25 reach-engine/graph.obj
else
  echo "otp25.jar not found, skipping the Reach map graph."
fi

echo ""
echo "=== 4/4 Rebuilding the main graph (2.9 engine, ~4 min) ==="
java -Xmx8G -jar otp.jar --build --save .

echo ""
echo "DONE. Now:"
echo "  1. bash run.sh            (start the app again)"
echo "  2. python3 tests/benchmark.py   (every trip should PASS)"
echo ""
echo "If the benchmark fails or routes look wrong, roll back with:"
echo "  cd engine && mv graph.obj.prev graph.obj && mv graph.obj.otp25.prev graph.obj.otp25"
echo "then restart. The new data may need a fix."
