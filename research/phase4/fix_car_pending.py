"""Re-check the 20 points in car_pending.csv (car maps that failed to start).

Same rule as the September fix (PLAN.md, "Car-start fix completed"): a car
map is only replaced when the original is clearly broken and the replacement
(1) covers a normal area and (2) can drive back to the original point, which
proves both starts are on the same road network. Never "keep the larger".

For each point, candidates in order:
  car_30_alt.tif   the backup street (reused if already saved)
  car_30_oct.tif   the nearest primary, secondary or tertiary road at least
                   MIN_MOVE_M from the main start (so a broken stretch right
                   at the start is skipped), within SEARCH_M
"Normal" = full 30-minute area at least half the median of the 10 nearest
points (from car_suspects.csv). "Drives back" = the replacement map reaches
the main start point within 30 minutes.

Verdicts: use_alt, use_oct, still_broken (left out of the car comparison and
disclosed). Writes car_fix_oct.csv; never overwrites saved maps.

Needs the research buffer engine on :8091.
Run: research/.venv/bin/python research/phase4/fix_car_pending.py
"""
import csv
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import numpy as np

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
sys.path.insert(0, str(RESEARCH / "phase2"))
sys.path.insert(0, str(RESEARCH / "phase3"))
import run_reach as rr  # noqa: E402
from score_points import Grid  # noqa: E402

SURF = RESEARCH / "phase2" / "surfaces_v2"
BIG_ROADS = {"primary", "secondary", "tertiary", "primary_link", "secondary_link", "tertiary_link"}
MIN_MOVE_M, SEARCH_M = 150, 3000
OUT = HERE / "car_fix_oct.csv"


def area30(path):
    return Grid(path).area_km2(1800)


def reaches(path, lat, lon):
    t, _ = Grid(path).times(np.array([float(lat)]), np.array([float(lon)]))
    return float(t[0]) if np.isfinite(t[0]) and t[0] <= 1800 else None


def main():
    import geopandas as gpd
    import shapely
    from pyproj import Transformer

    pending = list(csv.DictReader(open(HERE / "car_pending.csv")))
    sus = {r["origin_id"]: r for r in csv.DictReader(open(HERE / "car_suspects.csv"))}
    origins = {r["origin_id"]: r for r in csv.DictReader(open(RESEARCH / "phase2" / "origins_snapped_v2.csv"))}

    geoms, cls = [], []
    with open(rr.ROADS) as f:
        for line in f:
            if line.strip():
                feat = json.loads(line.lstrip("\x1e"))
                hw = (feat.get("properties") or {}).get("highway", "")
                if hw in BIG_ROADS:
                    geoms.append(shapely.geometry.shape(feat["geometry"]))
                    cls.append(hw)
    roads = gpd.GeoSeries(geoms, crs="EPSG:4326").to_crs(rr.UTM).values
    tree = shapely.STRtree(roads)
    fwd = Transformer.from_crs("EPSG:4326", rr.UTM, always_xy=True)
    back = Transformer.from_crs(rr.UTM, "EPSG:4326", always_xy=True)

    args = SimpleNamespace(api="http://localhost:8091", timeout=180, periods=["am"])
    runner = rr.Runner(args, SURF, HERE / "car_fix_oct_errors.csv", HERE / "car_fix_oct_qa_unused.csv")

    def bigger_road(o):
        x, y = fwd.transform(float(o["snap_lon"]), float(o["snap_lat"]))
        p = shapely.points(x, y)
        idx = [int(k) for k in tree.query(p, predicate="dwithin", distance=SEARCH_M)]
        best = None
        for k in idx:
            q = roads[k].interpolate(roads[k].project(p))
            d = q.distance(p)
            if d < MIN_MOVE_M:
                continue  # same stretch as the failed start
            if best is None or d < best[0]:
                best = (d, q, cls[k])
        if best is None:
            return None
        lon, lat = back.transform(best[1].x, best[1].y)
        return round(lat, 6), round(lon, 6), f"{best[2]} at {best[0]:.0f} m"

    def run_one(p):
        oid = p["origin_id"]
        o = origins[oid]
        normal = 0.5 * float(sus[oid]["nb_car"]) if oid in sus else 300.0
        row = {"origin_id": oid, "DAUID": o["DAUID"], "weight": o["weight"], "main_km2": round(area30(SURF / oid / "car_30.tif"), 2),
               "normal_min_km2": round(normal, 1)}
        cands = []
        if o.get("alt_lat"):
            cands.append(("car_30_alt.tif", o["alt_lat"], o["alt_lon"], f"backup street ({o.get('alt_highway', '')})"))
        br = bigger_road(o)
        if br:
            cands.append(("car_30_oct.tif", br[0], br[1], br[2]))
        row["verdict"], row["car_source"] = "still_broken", "car_30.tif"
        for name, lat, lon, how in cands:
            path = SURF / oid / name
            try:
                if not path.exists():
                    rr.atomic_write(path, runner.fetch(lat, lon, rr.CAR_WHEN, "CAR", "30M"))
            except rr.FetchError as ex:
                row[f"{name}_note"] = f"request failed: {ex}"
                continue
            a = area30(path)
            back_s = reaches(path, o["snap_lat"], o["snap_lon"])
            key = name.replace(".tif", "")
            row[f"{key}_how"], row[f"{key}_km2"], row[f"{key}_drive_back_s"] = how, round(a, 2), back_s
            if a >= normal and back_s is not None and row["verdict"] == "still_broken":
                row["verdict"] = "use_alt" if name == "car_30_alt.tif" else "use_oct"
                row["car_source"] = name
        return row

    with ThreadPoolExecutor(max_workers=6) as ex:
        rows = list(ex.map(run_one, pending))
    cols = []
    for r in rows:
        cols += [k for k in r if k not in cols]
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: r["origin_id"]))
    from collections import Counter
    print(Counter(r["verdict"] for r in rows))
    for r in rows:
        print(r)


if __name__ == "__main__":
    main()
