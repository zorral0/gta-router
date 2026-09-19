"""
Fix subway interchanges in the TTC feed: transfers, and platform placement.

The TTC's published schedule data has no transfers.txt, so the router
doesn't know Bloor-Yonge, St George, etc. are internal transfers. It routes
you out to the sidewalk and back in, which makes every subway transfer look
slower than it is and skews rankings toward streetcars.

This script adds a transfers.txt to ttc-gtfs.zip declaring a minimum
transfer time between the subway platforms of each interchange station.
Re-run it after every fresh TTC download (setup.sh and refresh.sh do this).

It also co-locates the platforms of ONE station, Bloor-Yonge. The TTC places
each platform's point at a different spot ALONG the platform rather than at
the station, so Line 1 northbound and southbound, which are side platforms a
few metres apart, sit 115 m apart in the feed. The router then street-routes
between those two points, up through an underpass, 69 m of steps and 85 m of
sidewalk: 275 m and eight minutes for a transfer a rider measures at two to
three. Moving the four platforms to their shared centroid makes the geometry
match the building.

**Only Bloor-Yonge, deliberately.** Every interchange shows a spread of 150
to 370 m, but at most of them some of that distance is REAL. Spadina's
Line 1 to Line 2 walk genuinely is a long one, and snapping it would replace
an overstatement with an understatement. Bloor-Yonge is patched because a
rider gave a measured figure for it. Do not extend this list without one.

Usage:  python3 scripts/patch_ttc_transfers.py    (then rebuild the graph)
"""

import csv
import io
import os
import zipfile

FEED = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "engine", "ttc-gtfs.zip")
TRANSFER_SECONDS = 180  # 3 min: realistic for stairs between platforms

# Platforms are matched by stop_name prefix. Stations that interchange
# with each other are grouped; every subway platform in a group gets a
# transfer to every other platform in that group (and to itself, which
# covers changing direction).
INTERCHANGES = [
    # Line 1 <-> Line 2 at Bloor-Yonge (two GTFS station names, one building)
    ["Bloor Station", "Yonge Station"],
    ["St George Station"],       # Line 1 <-> Line 2
    ["Spadina Station"],         # Line 1 <-> Line 2
    ["Sheppard-Yonge Station"],  # Line 1 <-> Line 4
    ["Kennedy Station"],         # Line 2 <-> Line 5 (LRT platforms match too)
    # Line 5 and Line 6 LRT platforms are named "... Station Eastbound Platform",
    # "... Station LRT Platform", so the "Platform" rule below picks them up.
    ["Eglinton Station"],        # Line 1 <-> Line 5
    ["Cedarvale Station"],       # Line 1 <-> Line 5
    ["Finch West Station"],      # Line 1 <-> Line 6
]


# Stations whose platforms should share one point. Each entry needs a
# real-world transfer time from someone who has made the transfer; see the
# module docstring for why this list is short on purpose.
CO_LOCATED = [
    # measured by a rider at 2-3 minutes, 2026-09-19
    ["Bloor Station", "Yonge Station"],
]
# Only directional subway/LRT platforms move. Bus bays ("Platform A",
# "Drop-off Platform") keep their real positions: at Kennedy those are
# genuinely far from the subway.
DIRECTIONAL = ("Northbound Platform", "Southbound Platform",
               "Eastbound Platform", "Westbound Platform",
               "Subway Platform", "LRT Platform")
MAX_MOVE_M = 150.0        # refuse to shift a stop further than this


def snapped_stops(stops):
    """Return {stop_id: (lat, lon)} for the platforms that should move."""
    import math
    moves = {}
    for group in CO_LOCATED:
        chosen = [s for s in stops
                  if any(s["stop_name"].startswith(n) for n in group)
                  and s["stop_name"].endswith(DIRECTIONAL)]
        if len(chosen) < 2:
            print(f"{' + '.join(group)}: only {len(chosen)} platforms, not moving any")
            continue
        lat = sum(float(s["stop_lat"]) for s in chosen) / len(chosen)
        lon = sum(float(s["stop_lon"]) for s in chosen) / len(chosen)
        far = []
        for s in chosen:
            d = math.hypot((float(s["stop_lat"]) - lat) * 111320,
                           (float(s["stop_lon"]) - lon) * 82000)
            if d > MAX_MOVE_M:
                far.append((s["stop_name"], d))
        if far:
            for name, d in far:
                print(f"  REFUSING to move {name} by {d:.0f} m (limit {MAX_MOVE_M:.0f})")
            print(f"{' + '.join(group)}: left alone, the spread looks real")
            continue
        print(f"{' + '.join(group)}: co-locating {len(chosen)} platforms at "
              f"{lat:.6f}, {lon:.6f}")
        for s in chosen:
            d = math.hypot((float(s["stop_lat"]) - lat) * 111320,
                           (float(s["stop_lon"]) - lon) * 82000)
            print(f"    {s['stop_name']:<42} moves {d:>5.0f} m")
            moves[s["stop_id"]] = (lat, lon)
    return moves


def main():
    with zipfile.ZipFile(FEED) as z:
        stops = list(csv.DictReader(io.TextIOWrapper(z.open("stops.txt"),
                                                     encoding="utf-8-sig")))
        already_patched = "transfers.txt" in z.namelist()

    rows = []
    for group in INTERCHANGES:
        platforms = [s["stop_id"] for s in stops
                     if "Platform" in s["stop_name"]
                     and any(s["stop_name"].startswith(name) for name in group)]
        names = [s["stop_name"] for s in stops if s["stop_id"] in platforms]
        print(f"{' + '.join(group)}: {len(platforms)} platforms")
        for a in platforms:
            for b in platforms:
                if a != b:
                    rows.append((a, b, 2, TRANSFER_SECONDS))

    moves = snapped_stops(stops)

    # zipfile cannot replace a member in place, so rewrite the archive
    # without the files we are about to regenerate.
    import shutil
    drop = {"transfers.txt"} | ({"stops.txt"} if moves else set())
    if already_patched or moves:
        if already_patched:
            print("transfers.txt already present - rewriting it.")
        with zipfile.ZipFile(FEED) as zin, \
             zipfile.ZipFile(FEED + ".tmp", "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename not in drop:
                    zout.writestr(item, zin.read(item.filename))
        shutil.move(FEED + ".tmp", FEED)

    if moves:
        fields = list(stops[0].keys())
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=fields)
        w.writeheader()
        for s in stops:
            if s["stop_id"] in moves:
                s = dict(s)
                s["stop_lat"], s["stop_lon"] = (f"{v:.6f}" for v in moves[s["stop_id"]])
            w.writerow(s)
        with zipfile.ZipFile(FEED, "a", zipfile.ZIP_DEFLATED) as z:
            z.writestr("stops.txt", buf.getvalue())
        print(f"Rewrote stops.txt with {len(moves)} platforms co-located "
              f"({len(stops)} stops total, unchanged)")

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["from_stop_id", "to_stop_id", "transfer_type",
                     "min_transfer_time"])
    writer.writerows(rows)
    with zipfile.ZipFile(FEED, "a", zipfile.ZIP_DEFLATED) as z:
        z.writestr("transfers.txt", out.getvalue())
    print(f"Wrote {len(rows)} transfer rules into {FEED}/transfers.txt")


if __name__ == "__main__":
    main()
