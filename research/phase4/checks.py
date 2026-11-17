"""Phase 4 checks that need no routing engine.

Reads research/phase3/da_scores.csv and points_scores.csv. Writes into
research/phase4/:

  extremes.csv          10 best and 10 worst DAs for each measure, with the
                        inputs that could make a result wrong (snap distance,
                        road type, replaced car map, density, edge flags) and
                        the median of the 10 nearest DAs for comparison
  outliers.csv          DAs whose value is far from their 10 nearest
                        neighbours (possible snapping or network errors)
  sam_comparison.csv    our measures vs Statistics Canada SAM 2024, by DA
  checks_summary.json   every number below, for the write-up

Checks: (1) extremes and (2) neighbour outliers; (3) origin placement (main vs
backup car start); (4) StatCan SAM rank correlation; (5) sensitivity: how many
residents change access class per case; (6) 45-minute sample vs 30 and 60;
(7) departure reliability (median vs p25); (8) edge test; (9) 200 m rule use.

Run: research/.venv/bin/python research/phase4/checks.py
"""
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
P3 = RESEARCH / "phase3"
DATA = RESEARCH / "data"
import sys  # noqa: E402
sys.path.insert(0, str(P3))
from score_da import access_class  # noqa: E402

MEASURES = {  # column: higher is better
    "mag_pop": True, "tr30_pop": True, "car_main_pop": True, "tr60_jobs": True,
    "tr30_groc": True, "tr_near_groc_min": False, "tr_near_ed_min": False,
}


def knn(xy, k):
    """Indices of the k nearest other points (brute force in chunks; ~8,500 points)."""
    out = np.empty((len(xy), k), int)
    for i in range(0, len(xy), 500):
        d = ((xy[i:i + 500, None, :] - xy[None, :, :]) ** 2).sum(-1)
        d[np.arange(d.shape[0]), np.arange(i, i + d.shape[0])] = np.inf
        out[i:i + 500] = np.argpartition(d, k, axis=1)[:, :k]
    return out


def spearman(a, b):
    m = a.notna() & b.notna()
    return float(a[m].rank().corr(b[m].rank())), int(m.sum())


def mode_share_check(da):
    """Spearman between our access measures and TTS 2022 transit share of trips, by home zone."""
    from io import StringIO
    lines = open(DATA / "tts" / "raw" / "tts2022_trips_homezone_mode.csv", encoding="utf-8").read().splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith(","))
    t = pd.read_csv(StringIO("\n".join(lines[start:])), index_col=0)
    t = t[pd.to_numeric(t.index, errors="coerce").notna()]
    t.index = t.index.astype(int)
    transit = t[["Transit excluding GO rail", "GO rail only", "Joint GO rail and local transit"]].sum(axis=1)
    zone = pd.DataFrame({"trips": t.sum(axis=1), "transit_share": transit / t.sum(axis=1),
                         "auto_share": t[["Auto driver", "Auto passenger"]].sum(axis=1) / t.sum(axis=1)})
    z = gpd.read_file(DATA / "tts" / "raw" / "zones2022" / "tts2022_v1_1_shapefile.shp").to_crs(4326)
    b = pd.read_csv(DATA / "buffer" / "blocks_buffer.csv", dtype={"DBUID": str, "DAUID": str})
    b = b[b.in_gta == 1]
    bg = gpd.GeoDataFrame(b, geometry=gpd.points_from_xy(b.lon, b.lat), crs=4326)
    j = gpd.sjoin(bg, z[["TTS2022", "geometry"]], predicate="within", how="inner")
    j = j[~j.index.duplicated()].merge(da[["DAUID", "mag_pop", "tr30_pop", "tr60_jobs"]], on="DAUID")
    def zavg(g):
        r = {}
        for c in ("mag_pop", "tr30_pop", "tr60_jobs"):
            ok = g[c].notna()
            r[c] = np.average(g.loc[ok, c], weights=g.loc[ok, "pop"]) if ok.any() and g.loc[ok, "pop"].sum() > 0 else np.nan
        r["pop"] = g["pop"].sum()
        return pd.Series(r)
    zs = j.groupby("TTS2022").apply(zavg, include_groups=False).join(zone, how="inner")
    zs = zs[zs.trips >= 2000]
    zs.to_csv(HERE / "tts_mode_share_by_zone.csv")
    res = {"zones": int(len(zs))}
    for c in ("mag_pop", "tr30_pop", "tr60_jobs"):
        res[f"spearman_{c}_vs_transit_share"] = spearman(zs[c], zs.transit_share)[0]
    res["spearman_mag_vs_auto_share"] = spearman(zs.mag_pop, zs.auto_share)[0]
    return res


def main():
    da = pd.read_csv(P3 / "da_scores.csv", dtype={"DAUID": str})
    pts = pd.read_csv(P3 / "points_scores.csv", dtype={"origin_id": str, "DAUID": str})
    snap = pd.read_csv(RESEARCH / "phase2" / "origins_snapped_v2.csv", dtype={"origin_id": str, "DAUID": str})
    qa = pd.read_csv(RESEARCH / "phase2" / "qa_flags_v2.csv", dtype={"origin_id": str})
    out = {}

    # DA centres for neighbour comparisons (population-weighted point mean)
    sp = snap.merge(pts[["origin_id"]], on="origin_id")
    sp["w"] = sp.weight.clip(lower=1)
    cen = sp.groupby("DAUID").apply(lambda g: pd.Series({
        "lat": np.average(g.lat, weights=g.w), "lon": np.average(g.lon, weights=g.w),
        "max_snap_m": g.snap_m.max(), "snap_highway": ",".join(sorted(set(g.snap_highway.astype(str))))}),
        include_groups=False)
    da = da.merge(cen, left_on="DAUID", right_index=True, how="left")
    g = gpd.GeoDataFrame(da, geometry=gpd.points_from_xy(da.lon, da.lat), crs=4326).to_crs(3161)
    xy = np.c_[g.geometry.x, g.geometry.y]
    nbr = knn(xy, 10)

    # (1) extremes, (2) outliers
    ext, outl = [], []
    cols = ["DAUID", "CDNAME", "CSDNAME", "pop2021", "density_per_km2", "n_points", "max_snap_m", "snap_highway",
            "car_replaced_share", "edge_car_share", "edge_tr60_share", "lat", "lon"]
    for m, hib in MEASURES.items():
        v = da[m]
        nb_med = np.nanmedian(v.to_numpy()[nbr], axis=1)
        da[f"{m}_nbr_median"] = nb_med
        ok = v.notna()
        order = v[ok].sort_values(ascending=not hib)
        for rank_name, idx in (("best", order.index[:10]), ("worst", order.index[::-1][:10])):
            for i in idx:
                r = da.loc[i, cols].to_dict()
                r.update(measure=m, which=rank_name, value=da.at[i, m], neighbours_median=nb_med[i])
                ext.append(r)
        # outliers: log ratio for counts, difference for MAG and times
        if m.startswith("mag"):
            dev = (v - nb_med).abs()
            thr = 0.6
        elif m.endswith("_min"):
            dev = (v - nb_med).abs()
            thr = 20
        else:
            dev = np.abs(np.log((v + 1) / (nb_med + 1)))
            thr = np.log(4)
        flag = dev > thr
        for i in da.index[flag.fillna(False)]:
            r = da.loc[i, cols].to_dict()
            r.update(measure=m, value=da.at[i, m], neighbours_median=nb_med[i], deviation=dev[i])
            outl.append(r)
    pd.DataFrame(ext).to_csv(HERE / "extremes.csv", index=False)
    ol = pd.DataFrame(outl)
    ol.to_csv(HERE / "outliers.csv", index=False)
    out["outliers"] = {m: {"das": int((ol.measure == m).sum()), "people": int(ol.loc[ol.measure == m, "pop2021"].sum())}
                       for m in MEASURES} if len(ol) else {}

    # (3) origin placement
    q = qa[qa.car30_alt_km2.notna() & (qa.car30_alt_km2 > 0)].copy()
    q["ratio"] = q.car30_alt_km2 / q.car30_km2
    out["origin_placement"] = {
        "points_with_backup": int(len(q)),
        "median_alt_over_main_km2": float(q.ratio.median()),
        "share_differ_over_20pct": float(((q.ratio < 1 / 1.2) | (q.ratio > 1.2)).mean()),
        "share_differ_over_20pct_qa_sample_only": float(((q[q.in_qa_sample == 1].ratio < 1 / 1.2) |
                                                         (q[q.in_qa_sample == 1].ratio > 1.2)).mean()),
        "car_maps_replaced": int((pts.car_file != "car_30.tif").sum()),
    }

    # (4) StatCan SAM 2024, peak
    sam = pd.read_csv(DATA / "sam" / "sam_transit_da_gta.csv", dtype={"DAUID": str})
    s = da.merge(sam[["DAUID", "s2024_peak_emp", "s2024_peak_gs1_min", "s2024_peak_hf"]], on="DAUID", how="left")
    s[["DAUID", "CDNAME", "pop2021", "tr60_jobs", "s2024_peak_emp", "tr_near_groc_min", "s2024_peak_gs1_min",
       "tr30_pop", "s2024_peak_hf"]].to_csv(HERE / "sam_comparison.csv", index=False)
    rho_j, n_j = spearman(s.tr60_jobs, s.s2024_peak_emp)
    rho_g, n_g = spearman(s.tr_near_groc_min, s.s2024_peak_gs1_min)
    sam_cmp = {"jobs_vs_sam_emp_spearman": rho_j, "n": n_j,
               "near_grocery_vs_sam_gs1_spearman": rho_g, "n_grocery": n_g, "by_region": {}}
    for cd, gg in s.groupby("CDNAME"):
        sam_cmp["by_region"][cd] = {"jobs": spearman(gg.tr60_jobs, gg.s2024_peak_emp)[0],
                                    "grocery": spearman(gg.tr_near_groc_min, gg.s2024_peak_gs1_min)[0]}
    # biggest disagreements in rank (jobs)
    m = s.tr60_jobs.notna() & s.s2024_peak_emp.notna()
    s.loc[m, "rank_diff_jobs"] = (s.loc[m, "tr60_jobs"].rank(pct=True) - s.loc[m, "s2024_peak_emp"].rank(pct=True))
    sam_cmp["jobs_rank_gap_over_0.4_das"] = int((s.rank_diff_jobs.abs() > 0.4).sum())
    sam_cmp["jobs_rank_gap_over_0.4_by_region"] = s[s.rank_diff_jobs.abs() > 0.4].CDNAME.value_counts().to_dict()
    out["sam"] = sam_cmp

    # (5) sensitivity: share of residents whose access class changes
    w = da.pop2021.to_numpy(float)
    sens = {}
    base, _ = access_class(da.mag_pop, w, True)
    for c in ["mag_pop_f100", "mag_pop_f170", "mag_pop_t0", "mag_pop_t8", "mag_pop_p25", "mag_km2"]:
        vc, _ = access_class(da[c], w, True)
        sens[c] = float(da.pop2021[vc != base].sum() / da.pop2021.sum())
    for a, b, hib in [("tr60_jobs", "tr60_jobs_p25", True), ("tr30_groc", "tr30_groc_p25", True),
                      ("tr_near_groc_min", "tr_near_groc_min_p75", False), ("tr_near_ed_min", "tr_near_ed_min_p75", False),
                      ("tr30_pop", "tr30_pop_p25", True)]:
        b0, _ = access_class(da[a], w, hib)
        b1, _ = access_class(da[b], w, hib)
        sens[b] = float(da.pop2021[b1 != b0].sum() / da.pop2021.sum())
    out["sensitivity_share_of_residents_changing_class"] = sens
    out["stable_share_of_residents"] = {c: float(da.pop2021[da[c] == 1].sum() / da.pop2021.sum())
                                        for c in da.columns if c.startswith("stable_")}
    out["median_mag_by_car_case"] = {c: float(np.nanmedian(da[c])) for c in da.columns if c.startswith("mag_pop_") and "nbr" not in c}

    # (6) 45-minute sample
    p45 = pts[pts.in_45_sample == 1]
    out["sample45"] = {
        "points": int(len(p45)),
        "spearman_pop45_vs_pop30": spearman(p45.tr45_pop, p45.tr30_pop)[0],
        "spearman_jobs45_vs_jobs60": spearman(p45.tr45_jobs, p45.tr60_jobs)[0],
        "spearman_groc45_vs_groc30": spearman(p45.tr45_groc, p45.tr30_groc)[0],
        "median_pop45_over_pop30": float((p45.tr45_pop / p45.tr30_pop.replace(0, np.nan)).median()),
        "median_jobs45_over_jobs60": float((p45.tr45_jobs / p45.tr60_jobs.replace(0, np.nan)).median()),
    }

    # (7) departure reliability
    out["reliability"] = {
        "median_ratio_pop30_p25_over_median": float((pts.tr30_pop_p25 / pts.tr30_pop.replace(0, np.nan)).median()),
        "median_ratio_jobs60_p25_over_median": float((pts.tr60_jobs_p25 / pts.tr60_jobs.replace(0, np.nan)).median()),
        "share_points_p25_below_half_median_pop30": float(((pts.tr30_pop_p25 / pts.tr30_pop.replace(0, np.nan)) < 0.5).mean()),
    }

    # (8) edge test
    e = pts.edge_car.astype(bool) | pts.edge_tr60.astype(bool)
    out["edge"] = {
        "points_flagged": int(e.sum()), "points_car": int(pts.edge_car.sum()), "points_transit60": int(pts.edge_tr60.sum()),
        "people_flagged": int(pts.weight[e].sum()),
        "das_any_flag": int((da[["edge_car_share", "edge_tr60_share"]].max(axis=1) > 0).sum()),
        "flagged_by_region": da.loc[da[["edge_car_share", "edge_tr60_share"]].max(axis=1) > 0, "CDNAME"].value_counts().to_dict(),
    }

    # (9) 200 m rule
    fb = json.loads((P3 / "points_scores_fallback_destinations.json").read_text())
    out["fallback_200m"] = {"grocery_stores_ever": len(fb["groc"]), "eds_ever": len(fb["ed"]),
                            "point_lookups_pop": int(pts.fallback_pop.sum()),
                            "point_lookups_groc": int(pts.fallback_groc.sum()),
                            "point_lookups_ed": int(pts.fallback_ed.sum()),
                            "point_lookups_jobs": int(pts.fallback_jobs.sum())}

    # (10) real behaviour: transit mode share by home zone (TTS 2022 trips)
    out["tts_mode_share"] = mode_share_check(da)

    (HERE / "checks_summary.json").write_text(json.dumps(out, indent=1, default=float))
    print(json.dumps(out, indent=1, default=float))


if __name__ == "__main__":
    main()
