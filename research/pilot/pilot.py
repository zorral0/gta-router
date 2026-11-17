"""Phase 0 pilot: 20 hand-picked origins across the GTA.

Asks the 2.5 reach engine (:8090) for walk+transit and car isochrones,
measures their areas, and times every call so we can estimate the full run.
See research/PLAN.md, Phase 0 step 3. Run with the research venv:

    research/.venv/bin/python research/pilot/pilot.py
"""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests
from shapely import STRtree
from shapely.geometry import Point, shape

API = "http://localhost:8090/otp/traveltime/isochrone"
OUT = Path(__file__).parent / "out"
UTM = "EPSG:32617"  # metres, UTM zone 17N, covers the GTA

# Study times from PLAN.md (EDT, UTC-4)
TIMES = {
    "wkday_0800": "2026-09-22T08:00:00-04:00",
    "wkday_2100": "2026-09-22T21:00:00-04:00",
    "sunday_1100": "2026-09-20T11:00:00-04:00",
}
TRANSIT_CUTS = [30, 45, 60]
SLOWDOWN = 1.4  # placeholder until Phase 1 finds a cited Toronto factor
# Built by: osmium tags-filter gta.osm.pbf w/highway=residential,... (see PLAN.md)
ROADS = Path(__file__).parent.parent / "data" / "osm" / "drive-roads.geojsonseq"


def snap_to_roads(origins):
    """Move each origin onto the nearest ordinary drivable street.

    The engine snaps a point to the nearest edge of ANY kind. Toronto's OSM
    draws many sidewalks as separate footways, so a raw point often lands on
    one, and a CAR request from a footway returns only the walking area
    (first pilot: 9 of 20 origins). On a road centreline, the road wins.
    """
    with open(ROADS) as f:
        geoms = [shape(json.loads(line.lstrip("\x1e"))["geometry"]) for line in f if line.strip()]
    roads = gpd.GeoSeries(geoms, crs="EPSG:4326").to_crs(UTM).values
    tree = STRtree(roads)
    pts = gpd.GeoSeries([Point(lon, lat) for _, lat, lon, _ in origins], crs="EPSG:4326").to_crs(UTM)
    snapped = []
    for o, p in zip(origins, pts):
        line = roads[tree.nearest(p)]
        on = line.interpolate(line.project(p))
        ll = gpd.GeoSeries([on], crs=UTM).to_crs("EPSG:4326").iloc[0]
        snapped.append((o[0], round(ll.y, 6), round(ll.x, 6), o[3], round(p.distance(on), 1)))
    return snapped

# name, lat, lon, kind. Points sit on residential streets near the named place.
ORIGINS = [
    ("downtown_union",        43.6453, -79.3806, "core"),
    ("thorncliffe_park",      43.7050, -79.3470, "inner suburb"),
    ("jane_finch",            43.7580, -79.5190, "inner suburb"),
    ("malvern",               43.8055, -79.2220, "inner suburb"),
    ("rexdale",               43.7220, -79.5710, "inner suburb"),
    ("long_branch",           43.5920, -79.5360, "inner suburb"),
    ("mount_joy_markham",     43.8990, -79.2600, "outer suburb"),
    ("richmond_hill",         43.8790, -79.4400, "outer suburb"),
    ("vaughan_maple",         43.8530, -79.5100, "outer suburb"),
    ("mississauga_centre",    43.5930, -79.6420, "outer suburb"),
    ("meadowvale",            43.5890, -79.7520, "outer suburb"),
    ("brampton_springdale",   43.7600, -79.7300, "outer suburb"),
    ("bramalea",              43.7160, -79.7300, "outer suburb"),
    ("oakville_glen_abbey",   43.4400, -79.7250, "outer suburb (Halton)"),
    ("burlington_downtown",   43.3260, -79.7990, "outer suburb (Halton)"),
    ("milton_dempsey",        43.5290, -79.8650, "outer suburb (Halton)"),
    ("pickering",             43.8370, -79.0870, "outer suburb"),
    ("oshawa_downtown",       43.8970, -78.8650, "outer suburb"),
    ("newmarket",             44.0520, -79.4600, "exurb"),
    ("bolton_caledon",        43.8750, -79.7350, "exurb"),
]


def fmt_cut(minutes):
    whole = int(minutes)
    secs = round((minutes - whole) * 60)
    return f"{whole}M{secs}S" if secs else f"{whole}M"


def iso(lat, lon, when, modes, cuts):
    params = [("location", f"{lat},{lon}"), ("time", when), ("modes", modes),
              ("arriveBy", "false")] + [("cutoff", fmt_cut(c)) for c in cuts]
    t0 = time.perf_counter()
    r = requests.get(API, params=params, timeout=180)
    secs = time.perf_counter() - t0
    if r.status_code != 200:
        return None, secs, f"http {r.status_code}"
    return r.json(), secs, None


def areas_km2(fc):
    """cutoff seconds -> km2, measured in UTM."""
    if not fc or not fc.get("features"):
        return {}
    g = gpd.GeoDataFrame(
        {"time": [int(f["properties"]["time"]) for f in fc["features"]]},
        geometry=[shape(f["geometry"]) for f in fc["features"]], crs="EPSG:4326",
    ).to_crs(UTM)
    return dict(zip(g["time"], g.geometry.area / 1e6))


def run_origin(o):
    name, lat, lon, kind, snap_m = o
    row = {"origin": name, "kind": kind, "lat": lat, "lon": lon, "snap_m": snap_m}
    calls = []
    for tkey, when in TIMES.items():
        fc, secs, err = iso(lat, lon, when, "WALK,TRANSIT", TRANSIT_CUTS)
        calls.append(("transit", tkey, secs, err))
        a = areas_km2(fc)
        for c in TRANSIT_CUTS:
            row[f"transit{c}_{tkey}_km2"] = round(a.get(c * 60, 0.0), 2)
        if fc:
            (OUT / "geojson" / f"{name}_transit_{tkey}.geojson").write_text(json.dumps(fc))
    # Car has no traffic model, so time of day does not change it: one call.
    slowed = 30 / SLOWDOWN
    fc, secs, err = iso(lat, lon, TIMES["wkday_0800"], "CAR", [30, slowed])
    calls.append(("car", "wkday_0800", secs, err))
    a = areas_km2(fc)
    row["car30_freeflow_km2"] = round(a.get(1800, 0.0), 2)
    row["car30_slowed_km2"] = round(a.get(round(slowed * 60), 0.0), 2)
    if fc:
        (OUT / "geojson" / f"{name}_car.geojson").write_text(json.dumps(fc))
    for mode, tkey, secs, err in calls:
        row[f"secs_{mode}_{tkey}"] = round(secs, 2)
        if err:
            row.setdefault("errors", []).append(f"{mode}/{tkey}: {err}")
    return row


def main():
    (OUT / "geojson").mkdir(parents=True, exist_ok=True)
    origins = snap_to_roads(ORIGINS)

    # Pass 1: one at a time, so per-call timings are clean.
    t0 = time.perf_counter()
    rows = []
    for o in origins:
        row = run_origin(o)
        rows.append(row)
        print(f"{row['origin']:22} transit45@8am {row['transit45_wkday_0800_km2']:8.1f} km2"
              f"   car30 slowed {row['car30_slowed_km2']:8.1f} km2   {row.get('errors', '')}",
              flush=True)
    serial_secs = time.perf_counter() - t0

    df = pd.DataFrame(rows)
    for tkey in TIMES:
        t30 = df[f"transit30_{tkey}_km2"]
        df[f"ratio_area_slowed_{tkey}"] = (df["car30_slowed_km2"] / t30.where(t30 > 0)).round(1)
        df[f"ratio_area_freeflow_{tkey}"] = (df["car30_freeflow_km2"] / t30.where(t30 > 0)).round(1)
    # Signature of the footway-snap failure: a "car" area no bigger than a
    # walk. Any real 30-minute free-flow drive covers far more.
    df["car_looks_like_walking"] = df["car30_freeflow_km2"] < 3 * df["transit30_wkday_0800_km2"]
    df.to_csv(OUT / "pilot_results.csv", index=False)

    # Pass 2: same 20 origins, 4 at a time. Checks throughput under
    # concurrency AND that the engine gives the same answer twice.
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=4) as ex:
        rows2 = list(ex.map(run_origin, origins))
    parallel_secs = time.perf_counter() - t0
    df2 = pd.DataFrame(rows2).set_index("origin")
    area_cols = [c for c in df.columns if c.endswith("_km2")]
    diff = (df.set_index("origin")[area_cols] - df2[area_cols]).abs().max().max()

    per_origin_serial = serial_secs / len(ORIGINS)
    per_origin_par = parallel_secs / len(ORIGINS)
    summary = {
        "origins": len(ORIGINS),
        "calls_per_origin": len(TIMES) + 1,
        "serial_total_secs": round(serial_secs, 1),
        "serial_secs_per_origin": round(per_origin_serial, 2),
        "parallel4_total_secs": round(parallel_secs, 1),
        "parallel4_secs_per_origin": round(per_origin_par, 2),
        "repeat_max_area_diff_km2": round(float(diff), 3),
        "estimate_hours_8000_origins_serial": round(8000 * per_origin_serial / 3600, 1),
        "estimate_hours_8000_origins_parallel4": round(8000 * per_origin_par / 3600, 1),
        "slowdown_factor_used": SLOWDOWN,
        "max_snap_m": float(df["snap_m"].max()),
        "car_looks_like_walking": df.loc[df["car_looks_like_walking"], "origin"].tolist(),
        "errors": {r["origin"]: r["errors"] for r in rows if r.get("errors")},
    }
    (OUT / "pilot_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
