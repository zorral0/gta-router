"""Build web/toll-rates.json: what a drive on Highway 407 actually costs.

WHY THIS EXISTS: the app can already measure how many metres of a drive run
on a toll road (make_toll_cells.py / web/toll-roads.json), but for a while it
could only say "toll" and leave the money out of the price. That made a 27 km
run up the 407 look CHEAPER than it is, and a tolled trip could even win the
"Cheapest" badge. 407 ETR bills per kilometre, and the rate depends on which
of its 12 zones you are in, which direction you are going and what time you
entered - so pricing it needs the zone geometry and the rate chart, which is
what this script packs up for the client.

TWO INPUTS:

1. rates.json - the official light-vehicle rate chart, scraped from
   https://www.407etr.com/en/rate-chart-light . The tables there are drawn by
   JavaScript, so a plain download will NOT contain them; open the page in a
   browser and run this in the console:

     (() => { const grab = t => [...t.querySelectorAll('tr')].map(tr =>
         [...tr.querySelectorAll('th,td')].map(c => c.innerText.trim()))
       .slice(1).filter(r => r.length > 1 && /a\\.m\\.|p\\.m\\./.test(r[0]));
       const ts = [...document.querySelectorAll('table')].slice(0,4);
       return JSON.stringify({ wbWeek: grab(ts[0]), wbWknd: grab(ts[1]),
                               ebWeek: grab(ts[2]), ebWknd: grab(ts[3]) }); })()

   The first two tables are the WESTBOUND tab, the last two EASTBOUND (check
   this if the page is ever redesigned - getting it backwards silently
   misprices every trip by up to 10 cents a kilometre). Rates change every
   January 1st, so re-scrape then.

2. toll.geojson - the tolled ways out of the OSM extract, the same file
   make_toll_cells.py reads. setup.sh already produces it.

Run:  python3 scripts/make_toll_rates.py rates.json toll.geojson web/toll-rates.json
"""
import json, math, sys

# ---------------------------------------------------------------- geometry
K = math.cos(math.radians(43.8)) * 111320.0     # metres per degree of lon
DEG_LAT = 111320.0
STEP_M = 2000.0                                 # centreline sample spacing

# 407 ETR's 12 zones, in order from the west end. Each entry is the road that
# STARTS the zone and the point where it crosses the 407, measured out of
# this same OSM extract (every crossing node of that road within 60 m of the
# 407 mainline, averaged). Interchanges do not move, so these are constants;
# they were checked against the highway's own exit numbers, which are
# kilometre posts.
ZONE_STARTS = [
    ("QEW",              -79.83128, 43.34392),
    ("Dundas St",        -79.83398, 43.38310),
    ("Neyagawa Blvd",    -79.77008, 43.48220),
    ("Highway 403",      -79.72429, 43.52830),
    ("Highway 401",      -79.81003, 43.58834),
    ("Highway 410",      -79.69968, 43.66826),
    ("Highway 427",      -79.63151, 43.75509),
    ("Highway 400",      -79.53720, 43.78324),
    ("Yonge St",         -79.42865, 43.83420),
    ("Highway 404",      -79.36840, 43.83853),
    ("McCowan Rd",       -79.28144, 43.85630),
    ("York-Durham Line", -79.18590, 43.89059),
]
EAST_END = ("Brock Rd", -79.09759, 43.91810)   # ETR ends here; MTO beyond

# when each rate band starts (the chart's row labels), local time. A trip is
# billed on the band it ENTERED the highway in; the last band of each list
# wraps around midnight into the next day.
WEEKDAY_BANDS = ["05:00", "07:00", "09:30", "10:30", "14:30", "15:30",
                 "18:00", "21:00"]
WEEKEND_BANDS = ["08:30", "10:00", "19:00", "21:00"]

FEES = {
    # per trip, charged with or without a transponder
    "trip_charge": 1.00,
    # per trip, only if the plate is photographed instead (no transponder)
    "camera_charge": 5.30,
}


def metres(a, b):
    return math.hypot((b[0] - a[0]) * K, (b[1] - a[1]) * DEG_LAT)


def centreline(toll_geojson):
    """A coarse ordered polyline down the middle of the 407, west to east.

    The OSM ways arrive as unordered pieces of two carriageways, so this
    walks them nearest-neighbour from the southernmost point (the QEW end).
    The walk hops between the two carriageways as it goes, which costs a
    little length but keeps it moving in one direction; resampling every
    STEP_M smooths that back out.
    """
    pts = set()
    for f in json.load(open(toll_geojson))["features"]:
        p = f.get("properties") or {}
        g = f.get("geometry") or {}
        if (g.get("type") == "LineString" and p.get("highway") == "motorway"
                and (p.get("ref") or "").startswith("407")):
            pts.update((c[0], c[1]) for c in g["coordinates"])
    pts = sorted(pts)
    if not pts:
        raise SystemExit("no 407 mainline in " + toll_geojson)

    cell = 0.01
    grid = {}
    for p in pts:
        grid.setdefault((int(p[0] / cell), int(p[1] / cell)), []).append(p)
    left = set(pts)
    cur = min(pts, key=lambda p: p[1])
    left.discard(cur)
    path = [cur]
    while left:
        cand, best, r = None, 1e9, 1
        while cand is None and r <= 6:
            cx, cy = int(cur[0] / cell), int(cur[1] / cell)
            for dx in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    for p in grid.get((cx + dx, cy + dy), ()):
                        if p in left:
                            d = metres(cur, p)
                            if d < best:
                                best, cand = d, p
            r += 1
        if cand is None:
            break
        path.append(cand)
        left.discard(cand)
        cur = cand

    line, acc = [path[0]], 0.0
    for i in range(1, len(path)):
        acc += metres(path[i - 1], path[i])
        if acc >= STEP_M:
            line.append(path[i])
            acc = 0.0
    if line[-1] != path[-1]:
        line.append(path[-1])
    cum = [0.0]
    for i in range(1, len(line)):
        cum.append(cum[-1] + metres(line[i - 1], line[i]))
    return line, cum


def chainage(line, cum, lon, lat):
    """How far along the centreline (km) the nearest point to lon/lat is."""
    best_d, best_km = 1e18, 0.0
    px, py = lon * K, lat * DEG_LAT
    for i in range(1, len(line)):
        ax, ay = line[i - 1][0] * K, line[i - 1][1] * DEG_LAT
        bx, by = line[i][0] * K, line[i][1] * DEG_LAT
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 == 0 else max(0.0, min(1.0,
            ((px - ax) * dx + (py - ay) * dy) / L2))
        d = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
        if d < best_d:
            best_d = d
            best_km = (cum[i - 1] + t * math.sqrt(L2)) / 1000.0
    return best_km


# ------------------------------------------------------------------- rates
def cents(v):
    return round(float(str(v).replace("¢", "").strip()), 2)


def table(rows, bands, what):
    """[[12 rates] per band] out of the scraped rows, order checked."""
    if len(rows) != len(bands):
        raise SystemExit(f"{what}: {len(rows)} rows, expected {len(bands)}")
    out = []
    for row in rows:
        vals = [cents(v) for v in row[1:]]
        if len(vals) != 12:
            raise SystemExit(f"{what}: {len(vals)} zones in row {row[0]!r}")
        out.append(vals)
    return out


def main(rates_src, toll_src, dst):
    scraped = json.load(open(rates_src))
    line, cum = centreline(toll_src)

    zones = []
    edges = [chainage(line, cum, lon, lat) for _, lon, lat in ZONE_STARTS]
    edges.append(chainage(line, cum, EAST_END[1], EAST_END[2]))
    for i, (name, _, _) in enumerate(ZONE_STARTS):
        zones.append({"n": i + 1, "from": name,
                      "to": (ZONE_STARTS + [EAST_END])[i + 1][0],
                      "km": round(edges[i], 3)})
    # sanity: zones must run west to east with no overlap
    for a, b in zip(edges, edges[1:]):
        if b <= a:
            raise SystemExit(f"zone boundaries out of order: {edges}")

    out = {
        "_source": "https://www.407etr.com/en/rate-chart-light",
        "_vehicle": "light (car, van, SUV, small pickup under 5000 kg)",
        "_effective": "2026-01-01",
        "_retrieved": "2026-07-25",
        "_note": ("Cents per kilometre by zone, direction and the band the "
                  "trip ENTERED in. Statutory holidays bill at weekend rates "
                  "but are not modelled here. Only the 407 ETR section (QEW "
                  "to Brock Rd) is covered; the MTO-run 407 East beyond Brock "
                  "has its own rates and is not tagged as tolled in the OSM "
                  "extract anyway."),
        "centreline": [[round(p[0], 5), round(p[1], 5)] for p in line],
        "centreline_km": [round(c / 1000.0, 3) for c in cum],
        "zones": zones,
        "end_km": round(edges[-1], 3),
        "bands": {"weekday": WEEKDAY_BANDS, "weekend": WEEKEND_BANDS},
        "rates": {
            "westbound": {
                "weekday": table(scraped["wbWeek"]["body"], WEEKDAY_BANDS, "wb weekday"),
                "weekend": table(scraped["wbWknd"]["body"], WEEKEND_BANDS, "wb weekend")},
            "eastbound": {
                "weekday": table(scraped["ebWeek"]["body"], WEEKDAY_BANDS, "eb weekday"),
                "weekend": table(scraped["ebWknd"]["body"], WEEKEND_BANDS, "eb weekend")}},
        "fees": FEES,
    }
    with open(dst, "w") as fh:
        json.dump(out, fh, separators=(",", ":"))
    print(f"{len(line)} centreline points, {cum[-1]/1000:.1f} km end to end")
    for z in zones:
        print(f"  zone {z['n']:2d}  km {z['km']:6.2f}  {z['from']} -> {z['to']}")
    print(f"-> {dst}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
