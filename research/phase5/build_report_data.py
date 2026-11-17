"""Step 5: data files for the interactive report page.

Writes into research/phase5/report/data/:
  da.geojson      every populated GTA DA, simplified outlines (~15 m), with the
                  numbers shown on the map and in the click-for-details card
  summary.json    headline numbers for the text (from phase3/summary.json)
  stories.json    the three story areas: outline, centre, numbers
Needs phase5/da_no_stop.csv (run no_stop_check.py first).

Short property names keep the file small; report.js documents them.
Run: research/.venv/bin/python research/phase5/build_report_data.py
"""
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
OUT = HERE / "report" / "data"
OUT.mkdir(parents=True, exist_ok=True)
LOW_DENSITY = 150  # people per km2: drawn faded, per the plan's masking rule
# On-demand services that run in parts of these places. No agency publishes zone
# outlines as data, so the name is only attached to DAs with no scheduled stop
# within walking distance (phase5/no_stop_check.py), worded as "runs in parts of".
ON_DEMAND = {"Durham": "Durham Region Transit On Demand", "York": "YRT On-Request",
             "Milton": "Milton Transit OnDemand", "Oakville": "Oakville Transit Ride On-Demand"}

STORIES = {  # id: (title, shortlist measure, municipality, place substring)
    "oshawa": ("South Oshawa", "jobs60", "Oshawa", "Albert Street"),
    "kerr": ("Kerr Village, Oakville", "jobs60", "Oakville", "Dorval Drive & Speers"),
}


def r(v, nd=0):
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return None
    return round(float(v), nd) if nd else int(round(float(v)))


def main():
    da = pd.read_csv(RESEARCH / "phase3" / "da_scores.csv", dtype={"DAUID": str})
    geo = gpd.read_file(RESEARCH / "data" / "census" / "da_gta.gpkg")[["DAUID", "geometry"]]
    ns = pd.read_csv(HERE / "da_no_stop.csv", dtype={"DAUID": str})[["DAUID", "no_stop"]]
    g = geo.merge(da, on="DAUID").merge(ns, on="DAUID", how="left").to_crs(3161)
    g["geometry"] = g.geometry.simplify(15, preserve_topology=True)
    g = g.to_crs(4326)
    g["geometry"] = shapely.set_precision(g.geometry.values, 0.00001)

    feats = []
    for row in g.itertuples():
        p = {
            "id": row.DAUID, "m": row.CSDNAME, "r": row.CDNAME, "pop": r(row.pop2021),
            "lo": r(row.lim_at_pct, 1), "zc": r(row.pct_zero_car_tts, 1),
            "s65": r(row.pct_65plus, 1), "imm": r(row.pct_recent_imm, 1),
            "tp": r(row.tr30_pop), "cp": r(row.car_main_pop), "mag": r(row.mag_pop, 3),
            "j": r(row.tr60_jobs), "g30": r(row.tr30_groc, 1), "gc30": r(row.car_main_groc),
            "ng": r(row.tr_near_groc_min, 1), "ne": r(row.tr_near_ed_min, 1),
            "n": int(row.need_class) if pd.notna(row.need_class) else None,
            "faded": int(row.density_per_km2 < LOW_DENSITY),
        }
        for k, col in (("aM", "acc_mag_pop"), ("aT", "acc_transit_pop30"), ("aJ", "acc_jobs60"),
                       ("aG", "acc_near_groc"), ("aE", "acc_near_ed")):
            p[k] = int(getattr(row, col)) if pd.notna(getattr(row, col)) else None
        for k, col in (("sM", "stable_mag_pop"), ("sJ", "stable_jobs60"), ("sE", "stable_near_ed"), ("sG", "stable_near_groc")):
            p[k] = int(getattr(row, col))
        if row.no_stop == 1:  # most residents are more than 800 m from a stop with morning service
            p["ns"] = 1
            od = ON_DEMAND.get(row.CSDNAME) or ON_DEMAND.get(row.CDNAME)
            if od:
                p["od"] = od
        feats.append({"type": "Feature", "properties": p, "geometry": shapely.geometry.mapping(row.geometry)})
    (OUT / "da.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":")))

    s = json.loads((RESEARCH / "phase3" / "summary.json").read_text())
    # headline: highest low-income third AND worst third for people reachable by transit,
    # stable in every sensitivity run (phase3/class_people.csv)
    cp = pd.read_csv(RESEARCH / "phase3" / "class_people.csv")
    row = cp[(cp.measure == "transit_pop30") & (cp.low_income_class == 3) & (cp.access_class == 1)].iloc[0]
    s["people_high_need_low_transit"] = int(row.people)
    s["people_high_need_low_transit_stable"] = int(row.stable_people)
    (OUT / "summary.json").write_text(json.dumps(s, indent=1))

    # stories: South Oshawa and Kerr Village from the shortlist clusters; Brampton = the city
    sl = pd.read_csv(HERE / "shortlist.csv", dtype=str)
    stories = {}
    for sid, (title, measure, muni, place) in STORIES.items():
        c = sl[(sl.measure == measure) & (sl.municipality == muni) & sl.place.str.contains(place, regex=False)].iloc[0]
        ids = c.dauids.split()
        sub = g[g.DAUID.isin(ids)]
        w = sub.pop2021
        stories[sid] = {"title": title, "dauids": ids, "people": int(w.sum()),
                        "bbox": [round(v, 5) for v in sub.total_bounds],
                        "low_income_pct": r(np.average(sub.lim_at_pct, weights=w), 1),
                        "zero_car_pct": r(np.average(sub.pct_zero_car_tts.fillna(0), weights=w), 1),
                        "transit_people_30": r(np.average(sub.tr30_pop, weights=w)),
                        "car_people_30": r(np.average(sub.car_main_pop, weights=w)),
                        "jobs_60": r(np.average(sub.tr60_jobs, weights=w)),
                        "near_ed_min": r(np.nanmedian(sub.tr_near_ed_min), 1),
                        "near_groc_min": r(np.nanmedian(sub.tr_near_groc_min), 1)}
    b = g[g.CSDNAME == "Brampton"]
    over = b[b.tr_near_ed_min_over60 == 1]
    stories["brampton"] = {"title": "Brampton", "people": int(b.pop2021.sum()), "bbox": [round(v, 5) for v in b.total_bounds],
                           "people_ed_over60": int(over.pop2021.sum()),
                           "near_ed_min_median": r(np.nanmedian(np.repeat(b.tr_near_ed_min.fillna(61).to_numpy(), b.pop2021.astype(int))), 1)}
    # one clean outline per story (dissolved DAs) for the map
    outl = []
    for sid, st in stories.items():
        sub = g[g.CSDNAME == "Brampton"] if sid == "brampton" else g[g.DAUID.isin(st["dauids"])]
        geom = sub.to_crs(3161).buffer(2).union_all().buffer(-2).simplify(10)
        geom = gpd.GeoSeries([geom], crs=3161).to_crs(4326).iloc[0]
        outl.append({"type": "Feature", "properties": {"story": sid}, "geometry": shapely.geometry.mapping(geom)})
    (OUT / "story_outlines.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": outl}))
    # emergency departments (GTA and the buffer) for the ER map
    hc = pd.read_csv(RESEARCH / "data" / "healthcare" / "healthcare_gta.csv")
    eds = [(n, la, lo) for n, t, la, lo in zip(hc.name, hc["type"], hc.lat, hc.lon) if t == "hospital_emergency"]
    eb = pd.read_csv(RESEARCH / "data" / "buffer" / "ed_buffer.csv")
    eds += list(zip(eb.name, eb.lat, eb.lon))
    (OUT / "eds.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"name": n}, "geometry": {"type": "Point", "coordinates": [round(lo, 5), round(la, 5)]}}
        for n, la, lo in eds]}))
    (OUT / "stories.json").write_text(json.dumps(stories, indent=1))
    mb = (OUT / "da.geojson").stat().st_size / 1e6
    print(f"da.geojson {len(feats)} DAs, {mb:.1f} MB; stories: " + ", ".join(f"{k} {v['people']:,}" for k, v in stories.items()))


if __name__ == "__main__":
    main()
