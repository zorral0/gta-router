"""Re-check the points whose car map looks like it never got moving.

A car surface that covers less ground than the transit surface almost always
means the start point sat on an edge a car cannot use. For every such point
this script asks the engine for a car surface from that point's BACKUP street
(car_30_alt.tif, reused if already saved) and then decides:

  use_backup      the backup is a normal size, so the main surface failed
  genuinely_low   both are small, so the place really has little car access
                  (for example the Toronto Islands)
  no_backup       no backup point exists; left as is and disclosed

Nothing is overwritten: the verdicts go to car_fix_v2.csv for the scoring step.

    research/.venv/bin/python research/phase2/fix_car_starts.py
"""
import csv
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_reach as rr  # noqa: E402
from surface import area_km2, is_valid_tiff  # noqa: E402

LOW_CAR_KM2 = 50.0     # a real 30-minute drive covers far more than this anywhere in the region
MIN_TRANSIT_KM2 = 0.5  # transit works here, so the point itself is not cut off
OUT = HERE / "car_fix_v2.csv"


def main():
    qa = {r["origin_id"]: r for r in csv.DictReader(open(HERE / "qa_flags_v2.csv"))}
    origins = {r["origin_id"]: r for r in csv.DictReader(open(HERE / "origins_snapped_v2.csv"))}
    todo = []
    for oid, q in qa.items():
        car = float(q["car30_km2"] or 0)
        transit = float(q["transit30_am_median_km2"] or 0)
        if car < LOW_CAR_KM2 and transit >= MIN_TRANSIT_KM2:
            todo.append((oid, car, transit))
    print(f"{len(todo)} points to re-check (car under {LOW_CAR_KM2:g} km2 with working transit)")

    args = SimpleNamespace(api="http://localhost:8091", timeout=180, periods=["am"])
    runner = rr.Runner(args, HERE / "surfaces_v2", HERE / "car_fix_errors_v2.csv", HERE / "car_fix_qa_unused.csv")
    surfaces = HERE / "surfaces_v2"

    def fetch_alt(item):
        oid, car, transit = item
        o = origins[oid]
        path = surfaces / oid / "car_30_alt.tif"
        if not o.get("alt_lat"):
            return dict(origin_id=oid, car30_km2=car, car30_alt_km2="", transit30_km2=transit, verdict="no_backup")
        if not is_valid_tiff(path):
            try:
                rr.atomic_write(path, runner.fetch(o["alt_lat"], o["alt_lon"], rr.CAR_WHEN, "CAR", "30M"))
            except rr.FetchError as ex:
                runner.log_error(oid, "car_30_alt", str(ex))
                return dict(origin_id=oid, car30_km2=car, car30_alt_km2="", transit30_km2=transit, verdict="request_failed")
        alt = area_km2(path, 1800)
        verdict = "use_backup" if alt >= LOW_CAR_KM2 else "genuinely_low"
        return dict(origin_id=oid, car30_km2=round(car, 2), car30_alt_km2=round(alt, 2),
                    transit30_km2=round(transit, 2), verdict=verdict)

    with ThreadPoolExecutor(max_workers=8) as ex:
        rows = list(ex.map(fetch_alt, todo))

    for r in rows:
        o = origins[r["origin_id"]]
        r.update(DAUID=o["DAUID"], kind=o["kind"], weight=o["weight"], snap_m=o["snap_m"],
                 snap_highway=o.get("snap_highway", ""), alt_how=o.get("alt_how", ""))
    cols = ["origin_id", "DAUID", "kind", "weight", "snap_m", "snap_highway", "alt_how",
            "car30_km2", "car30_alt_km2", "transit30_km2", "verdict"]
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: r["origin_id"]))

    counts = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    print("verdicts:", counts)
    people = {}
    for r in rows:
        people[r["verdict"]] = people.get(r["verdict"], 0) + int(float(r["weight"] or 0))
    print("residents affected by verdict:", people)
    for v in ("use_backup", "genuinely_low", "no_backup", "request_failed"):
        ex_rows = [r for r in rows if r["verdict"] == v][:4]
        for r in ex_rows:
            print(f"  {v:14} {r['origin_id']:12} DA {r['DAUID']} main {r['car30_km2']:>7} alt {r['car30_alt_km2']:>8} "
                  f"transit {r['transit30_km2']:>6} ({r['snap_highway']}, {r['alt_how']})")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
