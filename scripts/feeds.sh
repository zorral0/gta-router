# GTA Router - the GTFS schedule feeds, in one place.
#
# Sourced by setup.sh and refresh.sh (from inside engine/), so the two can
# never disagree about which feeds exist or where they live. To add a feed,
# add it here AND to engine/build-config.json.

# "file url" pairs
FEEDS=(
  # GO Transit and UP Express (Metrolinx open data)
  "go-gtfs.zip https://assets.metrolinx.com/raw/upload/v1683228856/Documents/Metrolinx/Open%20Data/GO-GTFS.zip"
  "up-gtfs.zip https://assets.metrolinx.com/raw/upload/v1682367798/Documents/Metrolinx/Open%20Data/UP-GTFS.zip"
  # TTC merged feed (subway + streetcar + bus), City of Toronto open data
  "ttc-gtfs.zip https://ckan0.cf.opendata.inter.prod-toronto.ca/dataset/7795b45e-e65a-4465-81fc-c36b9dfff169/resource/cfb6b2b8-6191-41e3-bda1-b175c51148cb/download/TTC%20Routes%20and%20Schedules%20Data.zip"
  # YRT. The long-standing direct link; if it fails, download by hand from
  # https://www.yrt.ca/en/about-us/open-data.aspx and save as yrt-gtfs.zip
  "yrt-gtfs.zip https://www.yrt.ca/google/google_transit.zip"
  # MiWay (Mississauga)
  "miway-gtfs.zip https://www.miapp.ca/GTFS/google_transit.zip"
  # Brampton Transit. The old brampton.ca link died mid-2026; this is the
  # ArcGIS item transit.land lists as the official feed. If it fails, check
  # https://www.transit.land/feeds/f-dpz2-bramptontransit for the current URL.
  "brampton-gtfs.zip https://www.arcgis.com/sharing/rest/content/items/a355aabd5a8c490186bdce559c9c75fb/data"
  # Durham Region Transit
  "drt-gtfs.zip https://maps.durham.ca/OpenDataGTFS/GTFS_Durham_TXT.zip"
  # Halton local buses: Oakville, Burlington, Milton (without them Halton
  # only has GO). Sources found via mobilitydatabase.org and transit.land.
  "oakville-gtfs.zip https://www.arcgis.com/sharing/rest/content/items/d78a1c1ad6a940009de8b68839a8f606/data"
  "burlington-gtfs.zip https://opendata.burlington.ca/gtfs-rt/GTFS_Data.zip"
  "milton-gtfs.zip https://metrolinx.tmix.se/gtfs/gtfs-milton.zip"
)

# fetch <file> <url>: download to a side file and only replace the real one
# if it is a genuine GTFS zip. A failed or broken download (an HTML error
# page saved as .zip, say) never overwrites a good copy.
fetch () {
  local f="$1" url="$2"
  if curl -fsSL --retry 2 -m 300 -o "$f.new" "$url" \
     && unzip -l "$f.new" 2>/dev/null | grep -q "stops.txt"; then
    mv "$f.new" "$f"
    echo "OK: $f"
  else
    rm -f "$f.new"
    if [ -f "$f" ]; then
      echo "WARNING: $f download failed or looked broken - KEEPING the old copy."
    else
      echo "PROBLEM: $f download failed or looked broken, and there is no"
      echo "         older copy. See the note for it in scripts/feeds.sh."
    fi
  fi
}

# fetch every feed; returns non-zero if any feed is missing afterwards
fetch_all () {
  local entry missing=0
  for entry in "${FEEDS[@]}"; do
    # shellcheck disable=SC2086
    fetch $entry
  done
  for entry in "${FEEDS[@]}"; do
    [ -f "${entry%% *}" ] || missing=1
  done
  return $missing
}
