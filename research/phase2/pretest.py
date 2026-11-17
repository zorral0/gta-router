"""Checks to run before the full Phase 2 run (review issues #1, #2, #12).

  cutoff   Does the requested cutoff change results? Transit at 08:00 with
           cutoff 30M, 45M and 60M from the 20 pilot origins; compares the
           30-minute and 45-minute areas and the cells themselves.
  departs  Are 7 departures, 10 minutes apart, enough? Transit every minute
           07:30-08:39 at 45M; compares the 7-sample median (10 different
           start offsets, and 5-minute spacing) with the every-minute median
           over 07:30-08:30.
  calib    Car traffic factor against the surface itself, not the trip
           planner: reads the CAR surface at each calibration trip's
           destination and divides Google's typical time by it.

  transit-template
           Writes research/data/transit_check/transit_trips.csv (18 trips,
           no engine needed). Fill google_arrive by hand from Google Maps.
  transit  Transit spot check: engine trip planner and 08:00 surface vs
           Google's scheduled arrival, flags trips off by >5 min or >20%.

    research/.venv/bin/python research/phase2/pretest.py [cutoff|departs|calib|all|transit-template|transit]

Needs the reach engine on :8090 (except transit-template). Surfaces are cached in
research/phase2/pretest_results/cache/ so re-runs make no new requests.
"""
import csv
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(RESEARCH / "pilot"))
from surface import NODATA, TIFF_MAGIC, area_km2, read_surface  # noqa: E402

API = "http://localhost:8090/otp/traveltime/surface"
DAY = "2026-09-22"
OUT = HERE / "pretest_results"
CACHE = OUT / "cache"
WORKERS = 8
TRANSIT = "WALK,TRANSIT"
MINUTES = [f"{(450 + i) // 60:02d}{(450 + i) % 60:02d}" for i in range(70)]  # 07:30 .. 08:39


# ---------------------------------------------------------------- engine

def surface_path(tag, hhmm, modes, cutoff):
    return CACHE / f"{tag}_{modes.replace(',', '-')}_{hhmm}_{cutoff}.tif"


def fetch(tag, lat, lon, hhmm, modes, cutoff):
    path = surface_path(tag, hhmm, modes, cutoff)
    if path.exists() and path.stat().st_size >= 200:
        return path
    params = {"location": f"{lat},{lon}", "time": f"{DAY}T{hhmm[:2]}:{hhmm[2:]}:00-04:00",
              "modes": modes, "cutoff": cutoff}
    last = ""
    for _ in range(3):
        try:
            r = requests.get(API, params=params, timeout=180)
            if r.status_code == 200 and r.content[:4] in TIFF_MAGIC and len(r.content) >= 200:
                path.write_bytes(r.content)
                return path
            last = f"http {r.status_code}"
        except requests.RequestException as e:
            last = str(e)
    raise RuntimeError(f"no surface for {tag} {hhmm} {modes} {cutoff}: {last}")


def fetch_all(jobs, label):
    todo = [j for j in jobs if not surface_path(j[0], j[3], j[4], j[5]).exists()]
    print(f"[{label}] {len(jobs)} surfaces, {len(todo)} to request", flush=True)
    with ThreadPoolExecutor(WORKERS) as ex:
        for i, _ in enumerate(ex.map(lambda j: fetch(*j), todo), 1):
            if i % 100 == 0:
                print(f"  {i}/{len(todo)}", flush=True)


# ---------------------------------------------------------------- helpers

def pilot_origins():
    with open(HERE / "pilot_origins_snapped.csv", newline="") as f:
        return [(r["DAUID"], float(r["snap_lat"]), float(r["snap_lon"])) for r in csv.DictReader(f)]


def cell_map(path):
    """{global cell key: seconds} for reached cells, so grids with different extents line up."""
    w, h, v, t = read_surface(path)
    cx, cy = abs(t.cell_x), abs(t.cell_y)
    m = {}
    for r in range(h):
        ky = round((t.origin_y + (r + 0.5) * t.cell_y) / cy)
        row = v[r * w:(r + 1) * w]
        for c, x in enumerate(row):
            if x != NODATA and x >= 0:
                m[(round((t.origin_x + (c + 0.5) * t.cell_x) / cx), ky)] = x
    return m


def value_at(path, lat, lon):
    """Seconds at the cell containing (lat, lon); nearest reached neighbour if that cell is empty."""
    w, h, v, t = read_surface(path)
    c, r = int((lon - t.origin_x) / t.cell_x), int((lat - t.origin_y) / t.cell_y)

    def get(rr, cc):
        if 0 <= rr < h and 0 <= cc < w:
            x = v[rr * w + cc]
            return x if x != NODATA and x >= 0 else None
        return None

    x = get(r, c)
    if x is not None:
        return x, "cell"
    near = [y for dr in (-1, 0, 1) for dc in (-1, 0, 1) if (y := get(r + dr, c + dc)) is not None]
    return (min(near), "neighbour") if near else (None, "unreached")


def write_csv(name, rows):
    with open(OUT / name, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"  wrote {OUT / name}")


def spread(label, xs):
    xs = sorted(xs)
    print(f"  {label:44} median {statistics.median(xs):7.3f}  min {xs[0]:7.3f}  max {xs[-1]:7.3f}")


# ---------------------------------------------------------------- tests

def test_cutoff():
    origins = pilot_origins()
    fetch_all([(oid, lat, lon, "0800", TRANSIT, c) for oid, lat, lon in origins for c in ("30M", "45M", "60M")],
              "cutoff")
    rows = []
    for oid, _, _ in origins:
        p = {c: surface_path(oid, "0800", TRANSIT, c) for c in ("30M", "45M", "60M")}
        m30, m45 = cell_map(p["30M"]), cell_map(p["45M"])
        in30 = {k for k, x in m30.items() if x <= 1800}
        in45 = {k for k, x in m45.items() if x <= 1800}
        shared = [abs(m30[k] - m45[k]) for k in in30 & in45]
        a30 = {c: area_km2(p[c], 1800) for c in p}
        a45 = {c: area_km2(p[c], 2700) for c in ("45M", "60M")}
        rows.append({
            "origin": oid,
            "t30_from_30M_km2": round(a30["30M"], 2),
            "t30_from_45M_km2": round(a30["45M"], 2),
            "t30_from_60M_km2": round(a30["60M"], 2),
            "t30_ratio_45M_over_30M": round(a30["45M"] / a30["30M"], 3) if a30["30M"] else "",
            "t45_from_45M_km2": round(a45["45M"], 2),
            "t45_from_60M_km2": round(a45["60M"], 2),
            "t45_ratio_60M_over_45M": round(a45["60M"] / a45["45M"], 3) if a45["45M"] else "",
            "cells_30min_in_only_one_pct": round(100 * len(in30 ^ in45) / max(1, len(in30 | in45)), 1),
            "median_abs_sec_diff_shared": statistics.median(shared) if shared else "",
        })
    write_csv("cutoff.csv", rows)
    print("\nTEST 1: does the requested cutoff change results? (1.000 = identical)")
    spread("30-min area, 45M request / 30M request", [r["t30_ratio_45M_over_30M"] for r in rows if r["t30_ratio_45M_over_30M"] != ""])
    spread("45-min area, 60M request / 45M request", [r["t45_ratio_60M_over_45M"] for r in rows if r["t45_ratio_60M_over_45M"] != ""])
    spread("% of 30-min cells reached in only one", [r["cells_30min_in_only_one_pct"] for r in rows])
    spread("median |seconds| difference, shared cells", [r["median_abs_sec_diff_shared"] for r in rows if r["median_abs_sec_diff_shared"] != ""])


def test_departures():
    origins = pilot_origins()
    fetch_all([(oid, lat, lon, hhmm, TRANSIT, "45M") for oid, lat, lon in origins for hhmm in MINUTES], "departs")
    rows = []
    for oid, _, _ in origins:
        grids = [read_surface(surface_path(oid, hhmm, TRANSIT, "45M")) for hhmm in MINUTES]
        for secs in (1800, 2700):
            a = [area_km2(g, secs) for g in grids]
            truth = statistics.median(a[0:61])
            if not truth:
                continue

            def err(x):
                return round(100 * (x / truth - 1), 1)

            ten = [err(statistics.median(a[k:k + 61:10])) for k in range(10)]
            five = [err(statistics.median(a[k:k + 61:5])) for k in range(5)]
            rows.append({
                "origin": oid, "minutes": secs // 60,
                "every_minute_median_km2": round(truth, 2),
                "single_departure_min_km2": round(min(a[0:61]), 2),
                "single_departure_max_km2": round(max(a[0:61]), 2),
                "plan_7x10min_err_pct": ten[0],
                "worst_7x10min_err_pct": max(ten, key=abs),
                "worst_13x5min_err_pct": max(five, key=abs),
            })
    write_csv("departures.csv", rows)
    print("\nTEST 2: 7 departures 10 min apart vs every minute (% error of the median area)")
    for m in (30, 45):
        sub = [r for r in rows if r["minutes"] == m]
        spread(f"{m} min: plan's sample, |error %|", [abs(r["plan_7x10min_err_pct"]) for r in sub])
        spread(f"{m} min: worst of 10 start offsets, |error %|", [abs(r["worst_7x10min_err_pct"]) for r in sub])
        spread(f"{m} min: every 5 min (13), worst |error %|", [abs(r["worst_13x5min_err_pct"]) for r in sub])
        print(f"  {m} min: origins where some 10-min offset is off by >10%: "
              f"{sum(abs(r['worst_7x10min_err_pct']) > 10 for r in sub)}/{len(sub)}")


def test_calibration():
    from calibrate_car import Q as CAR_Q, TRIPS
    from pilot import snap_to_roads

    pts = [(f"{t[0]}a", t[2], t[3], "") for t in TRIPS] + [(f"{t[0]}b", t[5], t[6], "") for t in TRIPS]
    snapped = {s[0]: s for s in snap_to_roads(pts)}
    fetch_all([(f"trip{t[0]}", snapped[f"{t[0]}a"][1], snapped[f"{t[0]}a"][2], "0800", "CAR", c)
               for t in TRIPS for c in ("30M", "45M")], "calib")
    with open(RESEARCH / "data" / "traffic" / "calibration_trips.csv", newline="") as f:
        trips = {int(r["trip"]): r for r in csv.DictReader(f)}
    rows = []
    for t in TRIPS:
        tid, b = t[0], snapped[f"{t[0]}b"]
        cal = trips[tid]
        g30, how30 = value_at(surface_path(f"trip{tid}", "0800", "CAR", "30M"), b[1], b[2])
        g45, how45 = value_at(surface_path(f"trip{tid}", "0800", "CAR", "45M"), b[1], b[2])
        used, grid_s, how = ("30M", g30, how30) if g30 is not None else ("45M", g45, how45)
        # Planner time queried live (the CSV's engine_min predates the coordinate fixes).
        a = snapped[f"{tid}a"]
        its = requests.post(GQL, json={"query": CAR_Q % (a[1], a[2], b[1], b[2])},
                            timeout=120).json()["data"]["plan"]["itineraries"]
        car_legs = [l for l in its[0]["legs"] if l["mode"] == "CAR"] if its else []
        planner = round(sum(l["duration"] for l in car_legs) / 60, 1) if car_legs else None
        grid_min = grid_s / 60 if grid_s is not None else None
        rows.append({
            "trip": tid, "road_type": cal["road_type"], "planner_min": planner if planner else "",
            "grid30_min": round(g30 / 60, 1) if g30 is not None else "", "grid30_read": how30,
            "grid45_min": round(g45 / 60, 1) if g45 is not None else "",
            "grid_used": used if grid_min else "none",
            "grid_over_planner": round(grid_min / planner, 3) if grid_min and planner else "",
            "old_factor_mid": float(cal["ratio_mid"]),
            "new_factor_low": round(float(cal["google_min_low"]) / grid_min, 3) if grid_min else "",
            "new_factor_mid": round(float(cal["google_mid"]) / grid_min, 3) if grid_min else "",
            "new_factor_high": round(float(cal["google_min_high"]) / grid_min, 3) if grid_min else "",
        })
    write_csv("calibration_grid.csv", rows)
    ok = [r for r in rows if r["grid_over_planner"] != ""]
    print(f"\nCALIBRATION against the car surface ({len(ok)}/{len(rows)} trips readable; "
          f"{sum(r['grid_used'] == '45M' for r in ok)} needed the 45M surface)")
    spread("surface time / planner time", [r["grid_over_planner"] for r in ok])
    spread("OLD factor (Google mid / planner)", [r["old_factor_mid"] for r in ok])
    for rt in ("all", "city", "highway"):
        sub = [r for r in ok if rt == "all" or r["road_type"] == rt]
        if sub:
            spread(f"NEW factor mid / surface ({rt}, n={len(sub)})", [r["new_factor_mid"] for r in sub])
    spread("NEW factor low / surface (all)", [r["new_factor_low"] for r in ok])
    spread("NEW factor high / surface (all)", [r["new_factor_high"] for r in ok])
    new = statistics.median(r["new_factor_mid"] for r in ok)
    print(f"  -> central factor {new:.2f}; run_reach.py SLOWED_CAR_S would be {round(1800 / new)} s "
          f"(currently {round(1800 / 1.35)} s)")


# ---------------------------------------------------------------- transit spot check

TRANSIT_CHECK = RESEARCH / "data" / "transit_check" / "transit_trips.csv"
GQL = "http://localhost:8090/otp/routers/default/index/graphql"
DEPART_MS = datetime(2026, 9, 22, 8, 0, tzinfo=timezone(timedelta(hours=-4))).timestamp() * 1000

# Points already used in pilot/calibrate_car.py.
POINTS = {
    "Union Station": (43.6453, -79.3806), "Yonge & Eglinton": (43.7066, -79.3985),
    "Kensington Market": (43.6547, -79.4005), "Pape & Danforth": (43.6797, -79.3446),
    "Jane & Finch": (43.7580, -79.5190), "Yorkdale Shopping Centre": (43.7254, -79.4521),
    "Scarborough Town Centre": (43.7756, -79.2578), "Kennedy Station": (43.7324, -79.2637),
    "Square One Shopping Centre": (43.5933, -79.6425), "Port Credit GO": (43.5553, -79.5870),
    "Mount Joy GO": (43.9004, -79.2627), "CF Markville": (43.8690, -79.2890),
    "Oakville GO": (43.4553, -79.6823), "Oakville Place": (43.4695, -79.6870),
    "Brampton GO": (43.6868, -79.7627), "Bramalea City Centre": (43.7162, -79.7225),
    "Pearson Airport Terminal 1": (43.6822, -79.6133), "Oshawa Centre": (43.8890, -78.8820),
    "Whitby GO": (43.8648, -78.9384), "Vaughan Metropolitan Centre": (43.7942, -79.5273),
    "Fairview Mall": (43.7778, -79.3445), "Milton GO": (43.5236, -79.8672),
    "Richmond Hill Centre (Yonge & Hwy 7)": (43.8420, -79.4270), "Burlington GO": (43.3406, -79.8093),
    "Oakville Trafalgar Memorial Hospital": (43.4488, -79.7664),
}
# Pearson T1, Milton GO and the hospital corrected 2026-09-14 to GTFS stop locations.

# Subway, streetcar, 905 buses, GO, UP Express, and cross-agency transfers.
TRANSIT_TRIPS = [
    (1, "Union Station", "Yonge & Eglinton"),
    (2, "Kensington Market", "Pape & Danforth"),
    (3, "Jane & Finch", "Yorkdale Shopping Centre"),
    (4, "Jane & Finch", "Vaughan Metropolitan Centre"),
    (5, "Scarborough Town Centre", "Kennedy Station"),
    (6, "Scarborough Town Centre", "Fairview Mall"),
    (7, "Square One Shopping Centre", "Port Credit GO"),
    (8, "Brampton GO", "Bramalea City Centre"),
    (9, "Union Station", "Pearson Airport Terminal 1"),
    (10, "Mount Joy GO", "CF Markville"),
    (11, "Richmond Hill Centre (Yonge & Hwy 7)", "CF Markville"),
    (12, "Vaughan Metropolitan Centre", "Yorkdale Shopping Centre"),
    (13, "Oshawa Centre", "Whitby GO"),
    (14, "Oakville GO", "Oakville Place"),
    (15, "Burlington GO", "Oakville Trafalgar Memorial Hospital"),
    (16, "Milton GO", "Square One Shopping Centre"),
    (17, "Pearson Airport Terminal 1", "Square One Shopping Centre"),
    (18, "Kennedy Station", "Union Station"),
]

PLAN_Q = """{ plan(from:{lat:%f,lon:%f}, to:{lat:%f,lon:%f}, date:"%s", time:"08:00",
  transportModes:[{mode:WALK},{mode:TRANSIT}], numItineraries:3) {
  itineraries { endTime legs { mode route { shortName } } } } }"""


def transit_template():
    if TRANSIT_CHECK.exists():
        print(f"{TRANSIT_CHECK} already exists; not overwriting it")
        return
    TRANSIT_CHECK.parent.mkdir(parents=True, exist_ok=True)
    with open(TRANSIT_CHECK, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["trip", "from", "to", "google_arrive", "google_route", "notes"])
        for tid, a, b in TRANSIT_TRIPS:
            w.writerow([tid, a, b, "", "", ""])
    print(f"wrote {TRANSIT_CHECK}")


def test_transit():
    from pilot import snap_to_roads

    if not TRANSIT_CHECK.exists():
        transit_template()
        return
    with open(TRANSIT_CHECK, newline="") as f:
        filled = {int(r["trip"]): r for r in csv.DictReader(f)}
    trips = [t for t in TRANSIT_TRIPS if t[0] in filled]
    # Origins snapped the same way as the study's origins; destinations read where they are.
    snapped = {s[0]: s for s in snap_to_roads([(str(tid), *POINTS[a], "") for tid, a, _ in trips])}
    fetch_all([(f"ttrip{tid}", snapped[str(tid)][1], snapped[str(tid)][2], "0800", TRANSIT, "45M")
               for tid, _, _ in trips], "transit")
    rows = []
    for tid, a, b in trips:
        o, (blat, blon) = snapped[str(tid)], POINTS[b]
        its = requests.post(GQL, json={"query": PLAN_Q % (o[1], o[2], blat, blon, DAY)},
                            timeout=120).json()["data"]["plan"]["itineraries"]
        best = min(its, key=lambda i: i["endTime"]) if its else None
        planner = round((best["endTime"] - DEPART_MS) / 60000, 1) if best else None
        route = " + ".join(f"{l['mode'].lower()} {(l.get('route') or {}).get('shortName') or ''}".strip()
                           for l in best["legs"] if l["mode"] != "WALK") if best else ""
        s, how = value_at(surface_path(f"ttrip{tid}", "0800", TRANSIT, "45M"), blat, blon)
        surface = round(s / 60, 1) if s is not None else None
        g = filled[tid]["google_arrive"].strip()
        google = int(g.split(":")[0]) * 60 + int(g.split(":")[1]) - 480 if g else None

        flags = []
        if planner is None:
            flags.append("ENGINE NO ROUTE")
        if google is None:
            flags.append("no google time")
        else:
            tol = max(5, 0.2 * google)
            if planner is not None and abs(planner - google) > tol:
                flags.append("CHECK planner")
            if surface is None and google <= 45:
                flags.append("CHECK surface unreached")
            elif surface is not None and abs(surface - google) > tol:
                flags.append("check surface")
        rows.append({
            "trip": tid, "from": a, "to": b,
            "google_min": google if google is not None else "",
            "planner_min": planner if planner is not None else "",
            "planner_route": route,
            "surface_0800_min": surface if surface is not None else "",
            "surface_read": how,
            "planner_minus_google": round(planner - google, 1) if planner is not None and google is not None else "",
            "surface_minus_google": round(surface - google, 1) if surface is not None and google is not None else "",
            "flags": "; ".join(flags),
        })
    write_csv("transit_check.csv", rows)
    print("\nTRANSIT SPOT CHECK (minutes after an 08:00 departure; flagged if off by more than 5 min or 20%)")
    print(f"  {'trip':>4} {'google':>6} {'planner':>7} {'surface':>7}  engine route | flags")
    for r in rows:
        print(f"  {r['trip']:>4} {str(r['google_min']):>6} {str(r['planner_min']):>7} "
              f"{str(r['surface_0800_min']):>7}  {r['planner_route']} | {r['flags']}")
    for col, label in (("planner_minus_google", "planner minus Google (min)"),
                       ("surface_minus_google", "surface minus Google (min)")):
        vals = [r[col] for r in rows if r[col] != ""]
        if vals:
            spread(label, vals)


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    CACHE.mkdir(parents=True, exist_ok=True)
    if which == "transit-template":
        transit_template()
    elif which == "transit":
        test_transit()
    for name, fn in (("cutoff", test_cutoff), ("calib", test_calibration), ("departs", test_departures)):
        if which in (name, "all"):
            fn()
