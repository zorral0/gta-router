"""Second pass for the points where both the main and backup car surfaces are small.

Tries a third start point on a bigger road (primary, secondary or tertiary)
within 3 km, in case the first two both sat in a pocket of road that is not
connected to the rest of the network in the map data. Verdicts:

  use_third      the bigger road gives a normal car area (map connection problem)
  confirmed_low  three different start points all give a small area, so the
                 place really does have very little car access

Writes car_fix2_v2.csv. Nothing already saved is overwritten.
"""
import csv
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_reach as rr  # noqa: E402
from surface import area_km2  # noqa: E402

LOW_CAR_KM2 = 50.0
BIG_ROADS = {"primary", "secondary", "tertiary", "primary_link", "secondary_link", "tertiary_link"}
SEARCH_M = 3000
OUT = HERE / "car_fix2_v2.csv"


def main():
    import shapely
    from pyproj import Transformer

    rows = [r for r in csv.DictReader(open(HERE / "car_fix_v2.csv")) if r["verdict"] == "genuinely_low"]
    origins = {r["origin_id"]: r for r in csv.DictReader(open(HERE / "origins_snapped_v2.csv"))}
    print(f"{len(rows)} points to re-check from a bigger road")

    geoms, cls = [], []
    with open(rr.ROADS) as f:
        for line in f:
            if not line.strip():
                continue
            feat = json.loads(line.lstrip("\x1e"))
            hw = (feat.get("properties") or {}).get("highway", "")
            if hw in BIG_ROADS:
                geoms.append(shapely.geometry.shape(feat["geometry"]))
                cls.append(hw)
    import geopandas as gpd
    roads = gpd.GeoSeries(geoms, crs="EPSG:4326").to_crs(rr.UTM).values
    print(f"  {len(roads)} bigger roads loaded")
    tree = shapely.STRtree(roads)
    fwd = Transformer.from_crs("EPSG:4326", rr.UTM, always_xy=True)
    back = Transformer.from_crs(rr.UTM, "EPSG:4326", always_xy=True)

    picks = []
    for r in rows:
        o = origins[r["origin_id"]]
        x, y = fwd.transform(float(o["lon"]), float(o["lat"]))
        p = shapely.points(x, y)
        idx = [int(k) for k in tree.query(p, predicate="dwithin", distance=SEARCH_M)]
        if not idx:
            picks.append((r, None, None, None))
            continue
        k = min(idx, key=lambda k: roads[k].distance(p))
        q = roads[k].interpolate(roads[k].project(p))
        lon, lat = back.transform(q.x, q.y)
        picks.append((r, round(lat, 6), round(lon, 6), f"{cls[k]} at {q.distance(p):.0f} m"))

    args = SimpleNamespace(api="http://localhost:8091", timeout=180, periods=["am"])
    runner = rr.Runner(args, HERE / "surfaces_v2", HERE / "car_fix_errors_v2.csv", HERE / "car_fix_qa_unused.csv")

    def run_one(item):
        r, lat, lon, how = item
        o = origins[r["origin_id"]]
        out = dict(r, third_lat=lat, third_lon=lon, third_how=how or "", lat=o["lat"], lon=o["lon"])
        if lat is None:
            out["car30_third_km2"] = ""
            out["verdict2"] = "no_bigger_road"
            return out
        path = HERE / "surfaces_v2" / r["origin_id"] / "car_30_third.tif"
        try:
            if not path.exists():
                rr.atomic_write(path, runner.fetch(lat, lon, rr.CAR_WHEN, "CAR", "30M"))
        except rr.FetchError as ex:
            runner.log_error(r["origin_id"], "car_30_third", str(ex))
            out["car30_third_km2"] = ""
            out["verdict2"] = "request_failed"
            return out
        a = area_km2(path, 1800)
        out["car30_third_km2"] = round(a, 2)
        out["verdict2"] = "use_third" if a >= LOW_CAR_KM2 else "confirmed_low"
        return out

    with ThreadPoolExecutor(max_workers=8) as ex:
        out_rows = list(ex.map(run_one, picks))

    cols = ["origin_id", "DAUID", "kind", "weight", "lat", "lon", "snap_highway", "car30_km2", "car30_alt_km2",
            "car30_third_km2", "third_how", "third_lat", "third_lon", "transit30_km2", "verdict2"]
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(out_rows, key=lambda r: r["origin_id"]))

    counts, people = {}, {}
    for r in out_rows:
        counts[r["verdict2"]] = counts.get(r["verdict2"], 0) + 1
        people[r["verdict2"]] = people.get(r["verdict2"], 0) + int(float(r["weight"] or 0))
    print("verdicts:", counts, "| residents:", people)
    for r in sorted(out_rows, key=lambda r: r["verdict2"]):
        print(f"  {r['verdict2']:14} {r['origin_id']:12} DA {r['DAUID']} at {r['lat']},{r['lon']} "
              f"main {r['car30_km2']:>7} alt {r['car30_alt_km2']:>8} third {r['car30_third_km2']:>8} ({r['third_how']})")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
