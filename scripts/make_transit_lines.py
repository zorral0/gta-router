#!/usr/bin/env python3
"""Build web/transit-lines.json: the rapid-transit lines drawn on the map.

Sam 2026-08-01 wanted the map itself to look like a transit app's, and the
biggest thing missing was the obvious one - the lines. Apple Maps and Transit
both paint the subway permanently on the map; we painted nothing until you
planned a trip.

Takes the GTFS feeds already in this folder and pulls out one polyline per
rapid-transit route, in that route's own official colour, straight from
route_color in the feed. Buses are deliberately left out: 210 TTC bus routes
would be a grey hairball, and they are not what anyone means by "the lines".

Run it after refresh.sh / setup.sh pulls new feeds:

    python3 make_transit_lines.py

No dependencies. Reads the zips in place, takes ~30s (TTC's shapes.txt is
17 MB and trips.txt is 12 MB), and writes a file of roughly 150 KB.
"""

import csv, io, json, os, sys, zipfile
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))

# Which feeds to mine, and which GTFS route_types count as rapid transit.
# 0 = tram/streetcar/LRT, 1 = subway, 2 = rail. 3 (bus) is deliberately absent.
FEEDS = [
    ("ttc-gtfs.zip", "TTC", {"0", "1"}),
    ("go-gtfs.zip",  "GO",  {"2"}),
    ("up-gtfs.zip",  "UP",  {"2"}),
]

# how hard to thin the polylines. GTFS shapes carry a point every few metres,
# which is far more than a screen can show. ~8 m of error is invisible at the
# zooms these lines are drawn at and cuts the file by about 90%.
SIMPLIFY_EPS = 0.00008


def read_csv(zf, name):
    """GTFS in the wild: UTF-8 BOM on some feeds, CRLF on most."""
    with zf.open(name) as fh:
        text = io.TextIOWrapper(fh, encoding="utf-8-sig", newline="")
        for row in csv.DictReader(text):
            yield row


def rdp(pts, eps):
    """Ramer-Douglas-Peucker, iterative so a 10k-point shape can't blow the
    recursion limit."""
    if len(pts) < 3:
        return pts[:]
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        lo, hi = stack.pop()
        if hi <= lo + 1:
            continue
        ax, ay = pts[lo]
        bx, by = pts[hi]
        dx, dy = bx - ax, by - ay
        norm = dx * dx + dy * dy
        worst, worst_i = -1.0, -1
        for i in range(lo + 1, hi):
            px, py = pts[i]
            if norm == 0:
                d = (px - ax) ** 2 + (py - ay) ** 2
            else:
                # perpendicular distance, squared, in degrees
                t = ((px - ax) * dx + (py - ay) * dy) / norm
                t = 0.0 if t < 0 else 1.0 if t > 1 else t
                qx, qy = ax + t * dx, ay + t * dy
                d = (px - qx) ** 2 + (py - qy) ** 2
            if d > worst:
                worst, worst_i = d, i
        if worst > eps * eps:
            keep[worst_i] = True
            stack.append((lo, worst_i))
            stack.append((worst_i, hi))
    return [p for p, k in zip(pts, keep) if k]


def mode_of(route_type, long_name):
    if route_type == "2":
        return "rail"
    if route_type == "1":
        return "subway"
    # TTC types Line 5 Eglinton and Line 6 Finch West as trams, but they are
    # LRT lines and belong with the subway, not with the King car.
    return "lrt" if long_name.strip().lower().startswith("line ") else "streetcar"


def hex_color(raw, fallback="#8e8e93"):
    raw = (raw or "").strip().lstrip("#")
    if len(raw) == 6 and all(c in "0123456789abcdefABCDEF" for c in raw):
        return "#" + raw.lower()
    return fallback


def build_feed(path, agency, want_types):
    zf = zipfile.ZipFile(path)

    routes = {}
    for r in read_csv(zf, "routes.txt"):
        if r.get("route_type") not in want_types:
            continue
        short = (r.get("route_short_name") or "").strip()
        long_ = (r.get("route_long_name") or "").strip()
        # TTC's 3xx are the overnight Blue Night versions of the same
        # streetcars; drawing both paints every line twice, in the wrong colour.
        if agency == "TTC" and short.startswith("3") and len(short) == 3:
            continue
        routes[r["route_id"]] = {
            "name": long_ or short,
            "short": short,
            "color": hex_color(r.get("route_color")),
            "mode": mode_of(r["route_type"], long_),
        }
    if not routes:
        return []

    # route -> the shape used by the most trips, longest wins ties. One line
    # per route: branches off the trunk are lost, which is a fidelity trade
    # made on purpose to keep this a clean picture rather than a spaghetti.
    shape_trips = defaultdict(int)
    shape_route = {}
    for t in read_csv(zf, "trips.txt"):
        rid, sid = t.get("route_id"), (t.get("shape_id") or "").strip()
        if rid in routes and sid:
            shape_trips[sid] += 1
            shape_route[sid] = rid

    wanted = set(shape_route)
    if not wanted:
        return []

    # single streaming pass over shapes.txt - it is the big file
    pts = defaultdict(list)
    for s in read_csv(zf, "shapes.txt"):
        sid = s["shape_id"]
        if sid in wanted:
            pts[sid].append((int(s["shape_pt_sequence"]),
                             float(s["shape_pt_lon"]), float(s["shape_pt_lat"])))

    best = {}
    for sid, raw in pts.items():
        rid = shape_route[sid]
        raw.sort()
        line = [(x, y) for _, x, y in raw]
        score = (len(line), shape_trips[sid])
        if rid not in best or score > best[rid][0]:
            best[rid] = (score, line)

    out = []
    for rid, (_, line) in best.items():
        meta = routes[rid]
        thin = rdp(line, SIMPLIFY_EPS)
        if len(thin) < 2:
            continue
        out.append({
            "type": "Feature",
            "geometry": {"type": "LineString",
                         "coordinates": [[round(x, 5), round(y, 5)] for x, y in thin]},
            "properties": {"name": meta["name"], "short": meta["short"],
                           "color": meta["color"], "mode": meta["mode"],
                           "agency": agency},
        })
    return out


def main():
    feats = []
    for fname, agency, types in FEEDS:
        path = os.path.join(HERE, fname)
        if not os.path.exists(path):
            print("skipping %s (not here)" % fname)
            continue
        got = build_feed(path, agency, types)
        print("%-16s %2d lines" % (agency, len(got)))
        feats.extend(got)

    if not feats:
        sys.exit("no lines built - are the GTFS zips missing?")

    # subway and rail last so they paint OVER the streetcars where they overlap
    order = {"streetcar": 0, "lrt": 1, "rail": 2, "subway": 3}
    feats.sort(key=lambda f: order.get(f["properties"]["mode"], 0))

    dest = os.path.join(HERE, "web", "transit-lines.json")
    with open(dest, "w") as fh:
        json.dump({"type": "FeatureCollection", "features": feats}, fh,
                  separators=(",", ":"))
    print("wrote %s (%d lines, %.0f KB)"
          % (dest, len(feats), os.path.getsize(dest) / 1024))


if __name__ == "__main__":
    main()
