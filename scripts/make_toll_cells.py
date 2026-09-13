"""Build web/toll-roads.json: a coarse grid of every tolled road in the map.

OTP has no toll support at all (checked the 2.9 GraphQL schema - there is no
avoidTolls anywhere), so the app can't ask the engine for a toll-free drive.
What it CAN do is recognise a car leg that runs on the 407 ETR and offer to
hide those options. This script rasterises the tolled ways into ~30 m cells;
the client decodes a car leg's geometry and measures how much of it lands in
one, so "did this drive use the toll road" is a lookup, not a geometry
library.

setup.sh runs this automatically after it crops and patches the OSM extract
(see its "Rebuilding the toll-road grid" step), so a fresh download can't
leave a stale grid behind. To do it by hand:
    osmium tags-filter engine/gta.osm.pbf w/toll=yes -o toll.osm.pbf --overwrite
    osmium export toll.osm.pbf -f geojson -o toll.geojson --overwrite
    python3 scripts/make_toll_cells.py toll.geojson web/toll-roads.json
"""
import json, math, sys

# ~30 m cells. Lon degrees are shorter this far north, so the two steps
# differ - a square cell keeps the "within one cell" tolerance isotropic.
LAT0, LON0 = 43.0, -80.5
DLAT = 30.0 / 111320.0
DLON = 30.0 / (111320.0 * math.cos(math.radians(43.8)))
STEP = 12.0          # metres between rasterised samples along a segment


def cell(lat, lon):
    return int((lat - LAT0) / DLAT), int((lon - LON0) / DLON)


def metres(a, b):
    dy = (b[1] - a[1]) * 111320.0
    dx = (b[0] - a[0]) * 111320.0 * math.cos(math.radians(43.8))
    return math.hypot(dx, dy)


def main(src, dst):
    gj = json.load(open(src))
    cells = set()
    ways = 0
    for f in gj["features"]:
        g = f.get("geometry") or {}
        if g.get("type") != "LineString":
            continue
        # keep drivable ways only: toll=yes also lands on gantries, barriers
        # and the odd footway crossing the highway.
        # highway=service is EXCLUDED on purpose: in this extract the only
        # tolled service ways are the aisles of one paid parking garage at
        # Yonge/Sheppard (18 of them, tagged toll=yes for the parking fee).
        # They are not a toll road, and once the app started putting a DOLLAR
        # figure on toll metres, counting a garage as Highway 407 would have
        # invented money. Real toll roads here are motorways and their ramps.
        hw = (f.get("properties") or {}).get("highway")
        if hw not in ("motorway", "motorway_link", "trunk", "trunk_link",
                      "primary", "primary_link", "secondary", "tertiary",
                      "unclassified", "residential"):
            continue
        ways += 1
        pts = g["coordinates"]
        for (lon1, lat1), (lon2, lat2) in zip(pts, pts[1:]):
            d = metres((lon1, lat1), (lon2, lat2))
            n = max(1, int(d / STEP))
            for i in range(n + 1):
                t = i / n
                cells.add(cell(lat1 + (lat2 - lat1) * t,
                               lon1 + (lon2 - lon1) * t))

    # pack as {x: [y, y, ...]} - roughly half the size of a list of pairs,
    # and the client wants a per-x lookup anyway
    by_x = {}
    for x, y in sorted(cells):
        by_x.setdefault(str(x), []).append(y)
    out = {"lat0": LAT0, "lon0": LON0, "dlat": DLAT, "dlon": DLON,
           "step_m": 30, "cells": by_x}
    with open(dst, "w") as fh:
        json.dump(out, fh, separators=(",", ":"))
    print(f"{ways} tolled ways -> {len(cells)} cells -> {dst}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
