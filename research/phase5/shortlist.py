"""Step 5: shortlist of story neighbourhoods.

Groups touching DAs that are in the highest low-income third AND the worst
access third on a measure, with the class stable across sensitivity runs
(Phase 3 stability rule). Each group is named by the nearest crossing of two
named major roads (OpenStreetMap). Output: phase5/shortlist.csv.

Run: research/.venv/bin/python research/phase5/shortlist.py
"""
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
DATA = RESEARCH / "data"
MEASURES = {"mag_pop": "transit vs car (people in 30 min)", "jobs60": "jobs by transit in 60 min",
            "near_ed": "nearest ER by transit", "groc30": "grocery stores in 30 min"}
MAJOR = {"primary", "secondary", "tertiary", "trunk"}


def road_namer():
    geoms, names = [], []
    for line in open(DATA / "osm" / "drive-roads.geojsonseq"):
        f = json.loads(line.lstrip("\x1e"))
        p = f.get("properties") or {}
        if p.get("highway") in MAJOR and p.get("name"):
            geoms.append(shapely.geometry.shape(f["geometry"]))
            names.append(p["name"])
    roads = gpd.GeoDataFrame({"name": names}, geometry=geoms, crs=4326).to_crs(3161)
    roads = roads.dissolve("name").reset_index()
    tree = shapely.STRtree(roads.geometry.values)

    def name(pt):
        idx = tree.query(pt, predicate="dwithin", distance=2500)
        if len(idx) == 0:
            return ""
        cand = sorted(idx, key=lambda k: roads.geometry.values[k].distance(pt))[:8]
        best = None
        for i in cand:
            for j in cand:
                if i >= j or roads.name[i] == roads.name[j]:
                    continue
                x = roads.geometry.values[i].intersection(roads.geometry.values[j])
                if x.is_empty:
                    continue
                d = x.distance(pt)
                if best is None or d < best[0]:
                    best = (d, f"{roads.name[i]} & {roads.name[j]}")
        return best[1] if best else roads.name[cand[0]]
    return name


def main():
    da = pd.read_csv(RESEARCH / "phase3" / "da_scores.csv", dtype={"DAUID": str})
    geo = gpd.read_file(DATA / "census" / "da_gta.gpkg")[["DAUID", "geometry"]].to_crs(3161)
    g = geo.merge(da, on="DAUID")
    namer = road_namer()
    rows = []
    for m, label in MEASURES.items():
        sel = g[(g.need_class == 3) & (g[f"acc_{m}"] == 1) & (g[f"stable_{m}"] == 1)].copy()
        if sel.empty:
            continue
        sel["geometry"] = sel.buffer(1)
        grp = sel.dissolve(aggfunc="first").explode(index_parts=False).reset_index(drop=True)
        grp["gid"] = range(len(grp))
        j = gpd.sjoin(sel[["DAUID", "pop2021", "CSDNAME", "lim_at_pct", "tr30_pop", "car_main_pop", "tr60_jobs",
                           "tr_near_ed_min", "tr_near_groc_min", "tr30_groc", "pct_zero_car_tts", "geometry"]],
                      grp[["gid", "geometry"]], predicate="within")
        for gid, c in j.groupby("gid"):
            w = c.pop2021
            pt = grp.geometry[gid].representative_point()
            rows.append({
                "measure": m, "measure_label": label, "people": int(w.sum()), "das": len(c),
                "place": namer(pt), "municipality": c.groupby("CSDNAME").pop2021.sum().idxmax(),
                "low_income_pct": round(np.average(c.lim_at_pct.fillna(0), weights=w), 1),
                "zero_car_pct": round(np.average(c.pct_zero_car_tts.fillna(0), weights=w), 1),
                "transit_people_30": int(np.average(c.tr30_pop, weights=w)),
                "car_people_30": int(np.average(c.car_main_pop.fillna(0), weights=w)),
                "jobs_60": int(np.average(c.tr60_jobs, weights=w)),
                "near_ed_min": round(float(np.nanmedian(c.tr_near_ed_min)), 1) if c.tr_near_ed_min.notna().any() else None,
                "near_ed_over60_share": round(float(c.tr_near_ed_min.isna().mean()), 2),
                "near_groc_min": round(float(np.nanmedian(c.tr_near_groc_min)), 1) if c.tr_near_groc_min.notna().any() else None,
                "lat": round(gpd.GeoSeries([pt], crs=3161).to_crs(4326).y[0], 5),
                "lon": round(gpd.GeoSeries([pt], crs=3161).to_crs(4326).x[0], 5),
                "dauids": " ".join(c.DAUID),
            })
    out = pd.DataFrame(rows).sort_values(["measure", "people"], ascending=[True, False])
    out.to_csv(HERE / "shortlist.csv", index=False)
    pd.set_option("display.width", 250)
    for m in MEASURES:
        print(out[(out.measure == m) & (out.people >= 2500)].drop(columns=["dauids", "measure_label"]).head(10).to_string(index=False))
        print()


if __name__ == "__main__":
    main()
