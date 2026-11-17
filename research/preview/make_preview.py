"""Preview of the overnight run: transit reach and the car gap, by neighbourhood.

Not the final measures. It uses a single 08:00 departure (the study uses the
median of 13) and no traffic factor or parking time on the car side.

    research/.venv/bin/python research/preview/make_preview.py
"""
import csv
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
sys.path.insert(0, str(RESEARCH / "phase2"))
from surface import area_km2  # noqa: E402

S = RESEARCH / "phase2" / "surfaces_v2"
OUT = HERE / "da_preview.csv"


def one(row):
    oid, dauid, weight = row
    d = S / oid
    try:
        t30 = area_km2(d / "am_30_0800.tif", 1800)
        t60 = area_km2(d / "am_60_0800.tif", 3600)
    except Exception:
        return None
    return oid, dauid, float(weight or 0), t30, t60


def main():
    origins = [(r["origin_id"], r["DAUID"], r["weight"]) for r in
               csv.DictReader(open(RESEARCH / "phase2" / "origins_snapped_v2.csv"))]
    car = {}
    for r in csv.DictReader(open(RESEARCH / "phase2" / "qa_flags_v2.csv")):
        car[r["origin_id"]] = float(r["car30_km2"] or 0)
    for r in csv.DictReader(open(RESEARCH / "phase2" / "car_source_v2.csv")):  # corrected car areas
        car[r["origin_id"]] = float(r["car30_km2"] or 0)

    print(f"reading {len(origins)} points ...", flush=True)
    with ProcessPoolExecutor() as ex:
        res = [x for x in ex.map(one, origins, chunksize=200) if x]
    print(f"  {len(res)} read", flush=True)

    das = {}
    for oid, dauid, w, t30, t60 in res:
        d = das.setdefault(dauid, dict(w=0.0, t30=0.0, t60=0.0, car=0.0, n=0))
        w = w or 1.0
        d["w"] += w; d["n"] += 1
        d["t30"] += w * t30; d["t60"] += w * t60; d["car"] += w * car.get(oid, 0.0)
    rows = []
    for dauid, d in das.items():
        w = d["w"] or 1.0
        t30 = d["t30"] / w
        rows.append(dict(DAUID=dauid, points=d["n"], pop=round(d["w"]), transit30_km2=round(t30, 2),
                         transit60_km2=round(d["t60"] / w, 1), car30_km2=round(d["car"] / w, 1),
                         car_over_transit=round((d["car"] / w) / t30, 1) if t30 > 0.05 else ""))
    rows.sort(key=lambda r: r["DAUID"])
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    import statistics as st
    print(f"wrote {OUT}: {len(rows)} neighbourhoods")
    print(f"  median transit 30 min {st.median(r['transit30_km2'] for r in rows):.1f} km2, "
          f"60 min {st.median(r['transit60_km2'] for r in rows):.0f} km2, car 30 min {st.median(r['car30_km2'] for r in rows):.0f} km2")
    ratios = [r["car_over_transit"] for r in rows if r["car_over_transit"] != ""]
    print(f"  car area over transit area: median {st.median(ratios):.0f}x, best 10% under {sorted(ratios)[len(ratios)//10]:.0f}x, "
          f"worst 10% over {sorted(ratios)[-len(ratios)//10]:.0f}x")


if __name__ == "__main__":
    main()
