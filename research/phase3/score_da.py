"""Phase 3, step 2: neighbourhood (DA) scores, need, and access-by-need classes.

Reads research/phase3/points_scores.csv (from score_points.py) and writes:

  da_scores.csv     one row per populated GTA DA: every measure, the need
                    indicators, terciles, bivariate classes and stability flags
  class_people.csv  people living in each of the 9 low-income x access
                    combinations, for every access measure
  summary.json      headline numbers for the check-in

How points become a DA (plan v2, section 5.3): a DA with one starting point
takes that point's values. A DA larger than 2 km2 has one point per populated
block; counts are averaged weighted by block population. Travel times are
combined with a population-weighted MEDIAN instead of a mean, because some
blocks are "more than 60 minutes" (censored) and a mean cannot use them.

Measure A uses the modal accessibility gap (Kwok and Yeh 2004) on residents
reachable in 30 minutes: MAG = (T - C) / (T + C), from -1 (only the car
reaches anyone) to +1. It is computed from the DA's averaged T and C.

Bivariate classes: low-income share and each access measure are split into
GTA-wide population-weighted terciles (1 = lowest third of residents, 3 =
highest). For access, class 1 is always the WORST access. A DA is "stable" for
a measure when its access class stays the same in every sensitivity case
(terciles recomputed within each case).

Run: research/.venv/bin/python research/phase3/score_da.py
"""
import json
from io import StringIO
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
DATA = RESEARCH / "data"

COUNT_COLS_PREFIX = ("tr30_", "tr45_", "tr60_", "car_")
TIME_COLS = ["tr_near_groc_s", "tr_near_groc_s_p75", "tr_near_ed_s", "tr_near_ed_s_p75"]
CENSOR_S = 3600.0
CAR_CASES = ["main", "f100", "f170", "t0", "t8"]

# access measures for the bivariate maps: name -> (column, higher_is_better)
ACCESS = {
    "mag_pop": ("mag_pop", True),            # Measure A
    "transit_pop30": ("tr30_pop", True),     # absolute transit reach, shown next to A
    "jobs60": ("tr60_jobs", True),
    "groc30": ("tr30_groc", True),
    "near_groc": ("tr_near_groc_min", False),
    "near_ed": ("tr_near_ed_min", False),
}


def wmedian(values, weights):
    v = np.asarray(values, float)
    w = np.asarray(weights, float)
    o = np.argsort(v)
    v, w = v[o], w[o]
    c = np.cumsum(w)
    return v[np.searchsorted(c, c[-1] / 2.0)]


def weighted_terciles(x, w):
    """Class 1-3 by population-weighted terciles of x (NaN stays NaN)."""
    s = pd.Series(x, dtype=float)
    ok = s.notna()
    v, ww = s[ok].to_numpy(), np.asarray(w, float)[ok.to_numpy()]
    o = np.argsort(v, kind="stable")
    cum = np.cumsum(ww[o]) / ww.sum()
    cut1 = v[o][np.searchsorted(cum, 1 / 3)]
    cut2 = v[o][np.searchsorted(cum, 2 / 3)]
    cls = pd.Series(np.nan, index=s.index)
    cls[ok] = np.where(s[ok] <= cut1, 1, np.where(s[ok] <= cut2, 2, 3))
    return cls, (float(cut1), float(cut2))


def access_class(x, w, higher_is_better):
    """Access class: 1 = worst third of residents, 3 = best."""
    v = pd.Series(x, dtype=float)
    if not higher_is_better:
        v = -v
    return weighted_terciles(v, w)


def mag(t, c):
    t, c = np.asarray(t, float), np.asarray(c, float)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(t + c > 0, (t - c) / (t + c), np.nan)


def read_tts_table(path):
    lines = open(path, encoding="utf-8").read().splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith(","))
    return pd.read_csv(StringIO("\n".join(lines[start:])), index_col=0)


def zero_car_by_da():
    """TTS 2022 zero-vehicle household share, zone -> DA via block population."""
    hh = read_tts_table(DATA / "tts" / "raw" / "tts2022_households_zone_vehicles.csv")
    hh = hh[pd.to_numeric(hh.index, errors="coerce").notna()]
    hh.index = hh.index.astype(int)
    total = hh.sum(axis=1)
    zone = pd.DataFrame({"hh_total": total, "hh_zero": hh["0"]})
    zone["zero_share"] = zone.hh_zero / zone.hh_total
    z = gpd.read_file(DATA / "tts" / "raw" / "zones2022" / "tts2022_v1_1_shapefile.shp").to_crs(4326)
    b = pd.read_csv(DATA / "buffer" / "blocks_buffer.csv", dtype={"DBUID": str, "DAUID": str})
    b = b[b.in_gta == 1]
    bg = gpd.GeoDataFrame(b, geometry=gpd.points_from_xy(b.lon, b.lat), crs=4326)
    j = gpd.sjoin(bg, z[["TTS2022", "geometry"]], predicate="within", how="left")
    j = j[~j.index.duplicated()]
    j = j.merge(zone, left_on="TTS2022", right_index=True, how="left")
    j = j[j.zero_share.notna()]
    g = j.groupby("DAUID").apply(lambda d: np.average(d.zero_share, weights=d["pop"]), include_groups=False)
    return (100 * g).rename("pct_zero_car_tts").round(2)


def main():
    pts = pd.read_csv(HERE / "points_scores.csv", dtype={"origin_id": str, "DAUID": str})
    count_cols = [c for c in pts.columns if c.startswith(COUNT_COLS_PREFIX)
                  and not c.endswith("_n_reached") and c not in ("car_file", "car_budget_s")]
    for c in TIME_COLS:
        pts[c] = pts[c].fillna(np.inf)  # blank = more than 60 minutes
    # Car maps that failed to start but were not caught by the 50 km2 rule
    # (Phase 4 found them: far below their 10 nearest neighbours). Their car
    # numbers are left out until they are re-requested.
    pending = RESEARCH / "phase4" / "car_pending.csv"
    pts["car_pending"] = 0
    if pending.exists():
        ids = set(pd.read_csv(pending, dtype={"origin_id": str}).origin_id)
        fixed = RESEARCH / "phase4" / "car_fix_oct.csv"
        if fixed.exists():  # after the re-check, only the ones still broken stay out
            f = pd.read_csv(fixed, dtype={"origin_id": str})
            ids -= set(f.loc[f.verdict != "still_broken", "origin_id"])
        car_cols = [c for c in pts.columns if c.startswith("car_") and c not in ("car_file", "car_budget_s", "car_pending")]
        hit = pts.origin_id.isin(ids)
        pts.loc[hit, car_cols] = np.nan
        pts.loc[hit, "car_pending"] = 1

    rows = []
    for dauid, g in pts.groupby("DAUID"):
        w = g.weight.to_numpy(float)
        r = {"DAUID": dauid, "n_points": len(g), "pop_points": w.sum()}
        for c in count_cols:
            vals = g[c]
            ok = vals.notna()
            r[c] = np.average(vals[ok], weights=w[ok.to_numpy()]) if ok.any() and w[ok.to_numpy()].sum() > 0 else np.nan
        for c in TIME_COLS:
            r[c] = wmedian(g[c], w) if w.sum() > 0 else np.nan
        for c in ("edge_car", "edge_tr30", "edge_tr60"):
            r[c + "_share"] = float(np.average(g[c], weights=w)) if w.sum() > 0 else float(g[c].max())
        r["downtown"] = int(g.downtown.max())
        r["car_pending_share"] = float(np.average(g.car_pending, weights=w)) if w.sum() > 0 else float(g.car_pending.max())
        r["car_replaced_share"] = float(np.average(g.car_file != "car_30.tif", weights=w)) if w.sum() > 0 else 0.0
        rows.append(r)
    da = pd.DataFrame(rows)

    for c in TIME_COLS:
        m = c.replace("_s", "_min")
        da[m] = np.where(np.isfinite(da[c]), da[c] / 60.0, np.nan)
        da[m + "_over60"] = (~np.isfinite(da[c])).astype(int)
        da = da.drop(columns=c)

    # Measure A
    for case in CAR_CASES:
        da[f"mag_pop_{case}"] = mag(da.tr30_pop, da[f"car_{case}_pop"])
    da["mag_pop"] = da.mag_pop_main
    da["mag_pop_p25"] = mag(da.tr30_pop_p25, da.car_main_pop)
    da["mag_km2"] = mag(da.tr30_km2, da.car_main_km2)
    da["mag_groc"] = mag(da.tr30_groc, da.car_main_groc)
    da["mag_ed"] = mag(da.tr30_ed, da.car_main_ed)
    da["car_over_transit_pop"] = np.where(da.tr30_pop > 0, da.car_main_pop / da.tr30_pop, np.nan)

    # census, need
    geo = gpd.read_file(DATA / "census" / "da_gta.gpkg")
    keep = [c for c in ("DAUID", "CDUID", "CDNAME", "CSDNAME", "landarea_km2", "pop2021") if c in geo.columns]
    base = pd.DataFrame(geo[keep])
    base["CDNAME"] = base.CDUID.astype(str).map(
        {"3518": "Durham", "3519": "York", "3520": "Toronto", "3521": "Peel", "3524": "Halton"})
    prof = pd.read_csv(DATA / "census" / "da_profile.csv", dtype={"DAUID": str})
    extra = pd.read_csv(DATA / "census" / "da_need_extra.csv", dtype={"DAUID": str})
    da = (base.merge(da, on="DAUID", how="inner")
          .merge(prof[["DAUID", "private_households", "median_hh_income", "lim_at_pct"]], on="DAUID", how="left")
          .merge(extra, on="DAUID", how="left"))
    da = da.merge(zero_car_by_da(), left_on="DAUID", right_index=True, how="left")
    da = da[da.pop2021 > 0].copy()
    da["density_per_km2"] = da.pop2021 / da.landarea_km2

    # genuinely cut off both ways: no Measure A
    cut = (da.tr30_pop <= 0) & (da.car_main_pop <= 0)
    da.loc[cut, [c for c in da.columns if c.startswith("mag_")]] = np.nan
    da["no_reach_either_way"] = cut.astype(int)

    # terciles and classes
    w = da.pop2021.to_numpy(float)
    cuts = {}
    da["need_class"], cuts["lim_at_pct"] = weighted_terciles(da.lim_at_pct, w)
    for name, (col, hib) in ACCESS.items():
        da[f"acc_{name}"], cuts[name] = access_class(da[col], w, hib)
        da[f"biv_{name}"] = da.need_class.astype("Int64").astype(str) + "-" + da[f"acc_{name}"].astype("Int64").astype(str)

    # stability across sensitivity cases (terciles recomputed in each case)
    variants = {
        # The area version (km2) is reported as a sensitivity check but is not part of
        # the stability rule: the study measures people reached, not land (owner's decision, 2026-10-18).
        "mag_pop": [f"mag_pop_{c}" for c in CAR_CASES if c != "main"] + ["mag_pop_p25"],
        "transit_pop30": ["tr30_pop_p25"],
        "jobs60": ["tr60_jobs_p25"],
        "groc30": ["tr30_groc_p25"],
        "near_groc": ["tr_near_groc_min_p75"],
        "near_ed": ["tr_near_ed_min_p75"],
    }
    for name, cols in variants.items():
        hib = ACCESS[name][1]
        stable = pd.Series(True, index=da.index)
        for c in cols:
            vc, _ = access_class(da[c], w, hib)
            stable &= (vc == da[f"acc_{name}"])
        da[f"stable_{name}"] = stable.astype(int)

    # low income, car-owning, low transit access (plan v2, 7.3)
    zc_med = np.nanmedian(da.pct_zero_car_tts)
    da["low_income_car_owning_low_access"] = ((da.need_class == 3) & (da.acc_mag_pop == 1)
                                              & (da.pct_zero_car_tts < zc_med)).astype(int)

    da.to_csv(HERE / "da_scores.csv", index=False)

    # people per class
    out = []
    for name in ACCESS:
        t = da.groupby([da.need_class, da[f"acc_{name}"]]).agg(people=("pop2021", "sum"), das=("DAUID", "count"),
                                                                stable_people=("pop2021", lambda s: s[da.loc[s.index, f"stable_{name}"] == 1].sum()))
        t = t.reset_index().rename(columns={"need_class": "low_income_class", f"acc_{name}": "access_class"})
        t.insert(0, "measure", name)
        out.append(t)
    cp = pd.concat(out)
    cp.to_csv(HERE / "class_people.csv", index=False)

    pop = da.pop2021.sum()
    summ = {
        "das": int(len(da)), "people": int(pop),
        "tercile_cuts": cuts,
        "median_tr30_pop": float(wmedian(da.tr30_pop, w)),
        "median_car_pop": float(wmedian(da.car_main_pop, w)),
        "median_mag_pop": float(wmedian(da.mag_pop.fillna(-1), w)),
        "median_jobs60": float(wmedian(da.tr60_jobs, w)),
        "people_near_groc_over60": int(da.loc[da.tr_near_groc_min_over60 == 1, "pop2021"].sum()),
        "people_near_ed_over60": int(da.loc[da.tr_near_ed_min_over60 == 1, "pop2021"].sum()),
        "people_no_groc_30": int(da.loc[da.tr30_groc < 0.5, "pop2021"].sum()),
        "people_edge_any": int((da.pop2021 * da[["edge_car_share", "edge_tr60_share"]].max(axis=1)).sum()),
        "people_high_need_low_mag": int(da.loc[(da.need_class == 3) & (da.acc_mag_pop == 1), "pop2021"].sum()),
        "people_high_need_low_mag_stable": int(da.loc[(da.need_class == 3) & (da.acc_mag_pop == 1) & (da.stable_mag_pop == 1), "pop2021"].sum()),
        "people_high_need_low_jobs": int(da.loc[(da.need_class == 3) & (da.acc_jobs60 == 1), "pop2021"].sum()),
        "people_low_income_car_owning_low_access": int(da.loc[da.low_income_car_owning_low_access == 1, "pop2021"].sum()),
        "das_no_reach_either_way": int(cut.sum()),
    }
    by_region = {}
    for cd, g in da.groupby("CDNAME"):
        gw = g.pop2021.to_numpy(float)
        by_region[cd] = {
            "people": int(g.pop2021.sum()),
            "median_tr30_pop": float(wmedian(g.tr30_pop, gw)),
            "median_car_pop": float(wmedian(g.car_main_pop, gw)),
            "median_mag_pop": float(wmedian(g.mag_pop.fillna(-1), gw)),
            "median_jobs60": float(wmedian(g.tr60_jobs, gw)),
            "median_near_groc_min": float(wmedian(g.tr_near_groc_min.fillna(99), gw)),
            "median_near_ed_min": float(wmedian(g.tr_near_ed_min.fillna(99), gw)),
            "share_high_need_low_mag": float(g.loc[(g.need_class == 3) & (g.acc_mag_pop == 1), "pop2021"].sum() / g.pop2021.sum()),
        }
    summ["by_region"] = by_region
    (HERE / "summary.json").write_text(json.dumps(summ, indent=1))
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    main()
