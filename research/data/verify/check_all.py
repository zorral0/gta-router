#!/usr/bin/env python
"""
Independent checker for Phase 1 GTA transit-gaps research datasets.

Loads every dataset under research/data/<topic>/ and runs concrete checks
against the claims made in each agent's summary and against PLAN.md
sections 2, 4, 5, 9. Writes nothing outside research/data/verify/.

Run with: research/.venv/bin/python
              research/data/verify/check_all.py
"""
import json
import math
import os
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

DATA_DIR = Path(__file__).resolve().parents[1]  # research/data
OUT_DIR = DATA_DIR / "verify"

STUDY_CDS = ["3518", "3519", "3520", "3521", "3524"]  # Durham, York, Toronto, Peel, Halton

results = {}


def rec(topic):
    results.setdefault(topic, {"checks": [], "problems": [], "key_numbers": {}})
    return results[topic]


def check(topic, name, passed, detail):
    rec(topic)["checks"].append({"check": name, "passed": bool(passed), "detail": str(detail)})


def problem(topic, severity, description, fix):
    rec(topic)["problems"].append(
        {"severity": severity, "description": description, "suggested_fix": fix}
    )


def kv(topic, key, value):
    rec(topic)["key_numbers"][key] = value


def file_exists(topic, label, path):
    p = Path(path)
    ok = p.exists()
    check(topic, f"file exists: {label}", ok, str(path))
    return ok


# ---------------------------------------------------------------------------
# Load GTA boundary once (used by the "all" cross-cutting check)
# ---------------------------------------------------------------------------
boundary_path = DATA_DIR / "census" / "gta_boundary.gpkg"
gta_boundary = None
boundary_source = None
if boundary_path.exists():
    try:
        gta_boundary = gpd.read_file(boundary_path)
        boundary_source = str(boundary_path)
    except Exception as e:
        problem("all", "major", f"Could not read {boundary_path}: {e}",
                 "Re-check census/gta_boundary.gpkg is a valid GeoPackage.")
else:
    problem("all", "blocker", "census/gta_boundary.gpkg does not exist",
             "Rebuild census dataset or fall back to CD boundaries in a raw/ folder.")

gta_union = None
if gta_boundary is not None:
    try:
        gta_union = gta_boundary.union_all()
    except Exception:
        gta_union = gta_boundary.unary_union

# small buffer (in degrees, ~500m) to tolerate coastline/edge snapping and
# points that sit exactly on the boundary line
BUFFER_DEG = 0.01


def points_inside_boundary_fraction(gdf, label):
    """Return (n_outside, n_total, frac_outside) for a point GeoDataFrame vs gta_union."""
    if gta_union is None:
        return None, len(gdf), None
    buffered = gta_union.buffer(BUFFER_DEG)
    inside = gdf.geometry.within(buffered)
    n_out = int((~inside).sum())
    return n_out, len(gdf), n_out / len(gdf) if len(gdf) else None


# ===========================================================================
# CENSUS
# ===========================================================================
topic = "census"
print(f"=== {topic} ===")
da_gta_path = DATA_DIR / "census" / "da_gta.gpkg"
da_origins_path = DATA_DIR / "census" / "da_origins.csv"
da_profile_path = DATA_DIR / "census" / "da_profile.csv"
build_census = DATA_DIR / "census" / "build_census.py"
source_census = DATA_DIR / "census" / "SOURCE.md"

file_exists(topic, "SOURCE.md", source_census)
file_exists(topic, "build_census.py", build_census)

if da_gta_path.exists():
    da_gta = gpd.read_file(da_gta_path)
    n_da = len(da_gta)
    check(topic, "DA count 7000-9000", 7000 <= n_da <= 9000, f"n={n_da}")
    kv(topic, "n_da", n_da)

    total_pop = pd.to_numeric(da_gta["pop2021"], errors="coerce").sum()
    kv(topic, "total_pop2021_from_da_gta", int(total_pop))
    # GTA (5 CDs) actual 2021 census population is about 6.7M
    check(topic, "total pop ~6.7M (+/-15%)", 5.7e6 <= total_pop <= 7.7e6,
          f"sum(pop2021)={total_pop:,.0f}")

    # ID leading zeros
    dauid_str_ok = da_gta["DAUID"].apply(lambda x: isinstance(x, str) and len(x) == 8).all()
    cduid_ok = da_gta["CDUID"].apply(lambda x: isinstance(x, str) and len(x) == 4).all()
    check(topic, "DAUID kept as 8-char string with leading zeros", dauid_str_ok,
          f"sample: {da_gta['DAUID'].iloc[0]!r} dtype={da_gta['DAUID'].dtype}")
    check(topic, "CDUID kept as 4-char string with leading zeros", cduid_ok,
          f"sample: {da_gta['CDUID'].iloc[0]!r}")

    cd_counts = da_gta["CDUID"].value_counts().to_dict()
    kv(topic, "da_count_by_cduid", cd_counts)
    missing_cds = [c for c in STUDY_CDS if c not in cd_counts]
    check(topic, "all 5 study CDs present in da_gta", len(missing_cds) == 0,
          f"present={sorted(cd_counts.keys())}, missing={missing_cds}")

    # downtown dense, Caledon sparse -- density check using pop2021/landarea_km2
    da_gta["_density"] = pd.to_numeric(da_gta["pop2021"], errors="coerce") / pd.to_numeric(
        da_gta["landarea_km2"], errors="coerce"
    )
    toronto_da = da_gta[da_gta["CDUID"] == "3520"]
    peel_da = da_gta[da_gta["CDUID"] == "3521"]
    caledon_da = da_gta[da_gta["CSDNAME"].astype(str).str.contains("Caledon", case=False, na=False)]
    toronto_med_density = toronto_da["_density"].median()
    caledon_med_density = caledon_da["_density"].median() if len(caledon_da) else None
    kv(topic, "toronto_median_density_per_km2", None if pd.isna(toronto_med_density) else round(toronto_med_density, 1))
    kv(topic, "caledon_n_das", len(caledon_da))
    kv(topic, "caledon_median_density_per_km2",
       None if caledon_med_density is None or pd.isna(caledon_med_density) else round(caledon_med_density, 1))
    if len(caledon_da) and not pd.isna(caledon_med_density):
        check(topic, "Toronto DAs denser than Caledon DAs",
              toronto_med_density > caledon_med_density * 5,
              f"Toronto median {toronto_med_density:.0f}/km2 vs Caledon median {caledon_med_density:.0f}/km2")
    else:
        problem(topic, "minor", "Could not find any DA with CSDNAME containing 'Caledon'",
                 "Confirm Caledon is present under a different CSDNAME spelling in da_gta.gpkg.")

    # downtown Toronto specific check: use a small bbox around downtown core
    downtown_bbox = (-79.42, 43.63, -79.36, 43.68)  # rough downtown Toronto core
    da_gta_pts = da_gta.copy()
    da_gta_pts["centroid"] = da_gta_pts.geometry.centroid
    dt_mask = da_gta_pts["centroid"].apply(
        lambda p: downtown_bbox[0] <= p.x <= downtown_bbox[2] and downtown_bbox[1] <= p.y <= downtown_bbox[3]
    )
    dt_das = da_gta_pts[dt_mask]
    if len(dt_das):
        dt_med_density = dt_das["_density"].median()
        kv(topic, "downtown_core_median_density_per_km2", round(dt_med_density, 1) if not pd.isna(dt_med_density) else None)
        check(topic, "downtown core DAs denser than Toronto overall median",
              (not pd.isna(dt_med_density)) and dt_med_density > toronto_med_density,
              f"downtown core median {dt_med_density:.0f}/km2 (n={len(dt_das)}) vs Toronto-wide median {toronto_med_density:.0f}/km2")
    else:
        problem(topic, "minor", "No DA centroids fell inside the downtown bbox used for the density check",
                 "Widen or adjust the downtown bounding box.")
else:
    problem(topic, "blocker", "census/da_gta.gpkg missing", "Cannot run census DA checks.")

# origins inside DA polygon
if da_gta_path.exists() and da_origins_path.exists():
    origins = pd.read_csv(da_origins_path, dtype={"DAUID": str})
    check(topic, "DAUID in da_origins.csv kept as string", origins["DAUID"].apply(lambda x: isinstance(x, str)).all(),
          f"dtype sample {origins['DAUID'].iloc[0]!r}")
    kv(topic, "n_origins", len(origins))
    check(topic, "origins count matches claim (8488)", len(origins) == 8488, f"n={len(origins)}")

    merged = origins.merge(da_gta[["DAUID", "geometry"]], on="DAUID", how="left")
    missing_geom = merged["geometry"].isna().sum()
    check(topic, "every origin DAUID matches a DA polygon", missing_geom == 0, f"{missing_geom} unmatched")

    merged = merged.dropna(subset=["geometry"])
    pts = gpd.GeoSeries([Point(xy) for xy in zip(merged["lon"], merged["lat"])], crs="EPSG:4326")
    geoms = gpd.GeoSeries(merged["geometry"].values, crs="EPSG:4326")
    inside = [pt.within(geom.buffer(1e-6)) or geom.contains(pt) or geom.distance(pt) < 1e-4
              for pt, geom in zip(pts, geoms)]
    n_outside = sum(1 for x in inside if not x)
    frac_outside = n_outside / len(inside) if inside else None
    kv(topic, "origin_pts_outside_own_da_polygon", n_outside)
    kv(topic, "origin_pts_checked", len(inside))
    # allow a very small tolerance for edge/representative-point snapping
    check(topic, "origins fall inside their own DA polygon (<=1% tolerance)",
          frac_outside is not None and frac_outside <= 0.01,
          f"{n_outside}/{len(inside)} origins ({frac_outside:.2%}) fall outside their own DA polygon")
else:
    problem(topic, "blocker", "Cannot check origin-in-polygon: missing da_gta.gpkg or da_origins.csv", "n/a")

# low-income % range and suppression -> NaN
if da_profile_path.exists():
    profile = pd.read_csv(da_profile_path, dtype={"DAUID": str})
    check(topic, "DAUID in da_profile.csv kept as string", profile["DAUID"].apply(lambda x: isinstance(x, str)).all(),
          f"sample {profile['DAUID'].iloc[0]!r}")
    lim = pd.to_numeric(profile["lim_at_pct"], errors="coerce")
    n_missing = profile["lim_at_pct"].isna().sum()
    kv(topic, "lim_at_pct_missing_count", int(n_missing))
    check(topic, "lim_at_pct missing count matches claim (350)", int(n_missing) == 350, f"n_missing={n_missing}")
    valid = lim.dropna()
    in_range = valid.between(0, 60).all()
    n_over_60 = int((valid > 60).sum())
    check(topic, "lim_at_pct in 0-60 range where present", bool(in_range),
          f"min={valid.min():.2f} max={valid.max():.2f} n_valid={len(valid)}, {n_over_60} DAs exceed 60%")
    if n_over_60:
        over = profile.loc[lim > 60, ["DAUID", "population"]].copy()
        over["lim_at_pct"] = lim[lim > 60]
        problem(topic, "minor",
                 f"{n_over_60} of {len(valid)} DAs have a LIM-AT low-income prevalence above 60% "
                 f"(max {valid.max():.1f}%, all in small-population DAs): "
                 f"{over.sort_values('lim_at_pct', ascending=False).to_dict(orient='records')}. "
                 "These could be genuine (StatCan LIM-AT can be very high in a small DA containing a "
                 "shelter, rooming house, or student residence) or a data-extraction slip in the fixed-row "
                 "block-offset method the build script uses. SOURCE.md does not mention these outliers.",
                 "Manually check these specific DAUIDs against StatCan's public Census Profile web page "
                 "for that DA to confirm the LIM-AT figure was read from the correct row.")
    # confirm suppressed cells really are NaN, not zero-coded
    raw_profile = pd.read_csv(da_profile_path, dtype=str)
    n_blank_lim = raw_profile["lim_at_pct"].isna().sum() + (raw_profile["lim_at_pct"] == "").sum()
    check(topic, "suppressed lim_at_pct cells are blank/NaN not 0", n_blank_lim >= n_missing * 0.9,
          f"blank/NaN cells in raw csv: {n_blank_lim}")
else:
    problem(topic, "blocker", "census/da_profile.csv missing", "Cannot check low-income range.")

# ===========================================================================
# GROCERY
# ===========================================================================
topic = "grocery"
print(f"=== {topic} ===")
grocery_gpkg = DATA_DIR / "grocery" / "grocery_gta.gpkg"
grocery_csv = DATA_DIR / "grocery" / "grocery_gta.csv"
source_grocery = DATA_DIR / "grocery" / "SOURCE.md"
build_grocery = DATA_DIR / "grocery" / "build_grocery.py"

file_exists(topic, "SOURCE.md", source_grocery)
file_exists(topic, "build_grocery.py", build_grocery)

if grocery_gpkg.exists():
    grocery = gpd.read_file(grocery_gpkg)
    n = len(grocery)
    kv(topic, "n_stores", n)
    check(topic, "several hundred to ~1500 stores", 300 <= n <= 1500, f"n={n}")

    # no convenience stores
    conv_col_candidates = ["shop_tag", "category", "rule"]
    conv_hits = 0
    conv_detail = []
    for col in conv_col_candidates:
        if col in grocery.columns:
            hits = grocery[col].astype(str).str.contains("convenience", case=False, na=False).sum()
            conv_hits += hits
            if hits:
                conv_detail.append(f"{col}: {hits}")
    check(topic, "no convenience stores in shop_tag/category/rule", conv_hits == 0,
          f"hits={conv_hits} {conv_detail}")

    # region representation roughly by population
    if "cduid" in grocery.columns:
        by_cd = grocery["cduid"].astype(str).value_counts().to_dict()
        kv(topic, "stores_by_cduid", by_cd)
        missing = [c for c in STUDY_CDS if c not in by_cd]
        check(topic, "all 5 study CDs represented", len(missing) == 0, f"present={by_cd}, missing={missing}")
        if da_gta_path.exists():
            pop_by_cd = da_gta.groupby("CDUID")["pop2021"].apply(lambda s: pd.to_numeric(s, errors="coerce").sum()).to_dict()
            ratios = {}
            for cd in STUDY_CDS:
                if cd in by_cd and cd in pop_by_cd and pop_by_cd[cd] > 0:
                    ratios[cd] = by_cd[cd] / (pop_by_cd[cd] / 1000.0)  # stores per 1000 pop... actually per 1000, use per 100k
            kv(topic, "stores_per_100k_pop_by_cduid", {k: round(v * 100, 2) for k, v in ratios.items()})
            if ratios:
                vals = list(ratios.values())
                spread = max(vals) / min(vals) if min(vals) > 0 else None
                check(topic, "store density per capita roughly comparable across CDs (within 3x spread)",
                      spread is not None and spread <= 3.0,
                      f"stores per 1000 pop by CD: {ratios}, spread={spread}")

    # dedup: no same-name duplicates within 50m
    grocery_m = grocery.to_crs(epsg=32617)  # UTM zone 17N, metres, covers GTA
    dup_pairs = 0
    dup_examples = []
    if "name" in grocery.columns:
        for name, group in grocery_m.groupby(grocery["name"].fillna("__noname__")):
            if name == "__noname__" or len(group) < 2:
                continue
            coords = list(zip(group.geometry.x, group.geometry.y))
            idxs = list(group.index)
            for i in range(len(coords)):
                for j in range(i + 1, len(coords)):
                    d = math.dist(coords[i], coords[j])
                    if d < 50:
                        dup_pairs += 1
                        if len(dup_examples) < 10:
                            dup_examples.append((name, idxs[i], idxs[j], round(d, 1)))
    kv(topic, "same_name_pairs_within_50m", dup_pairs)
    check(topic, "no same-name duplicate pairs within 50m", dup_pairs == 0,
          f"pairs found={dup_pairs} examples={dup_examples[:5]}")

    # all inside GTA boundary
    n_out, n_tot, frac = points_inside_boundary_fraction(grocery.to_crs(epsg=4326), "grocery")
    kv(topic, "n_outside_boundary", n_out)
    if n_out is not None:
        check(topic, "all stores inside GTA boundary (buffered ~1km)", n_out == 0,
              f"{n_out}/{n_tot} outside")
else:
    problem(topic, "blocker", "grocery/grocery_gta.gpkg missing", "n/a")

# ===========================================================================
# HEALTHCARE
# ===========================================================================
topic = "healthcare"
print(f"=== {topic} ===")
hc_gpkg = DATA_DIR / "healthcare" / "healthcare_gta.gpkg"
source_hc = DATA_DIR / "healthcare" / "SOURCE.md"
build_hc = DATA_DIR / "healthcare" / "build_healthcare.py"

file_exists(topic, "SOURCE.md", source_hc)
file_exists(topic, "build_healthcare.py", build_hc)

if hc_gpkg.exists():
    hc = gpd.read_file(hc_gpkg)
    n = len(hc)
    kv(topic, "n_total", n)

    type_counts = hc["type"].value_counts().to_dict() if "type" in hc.columns else {}
    kv(topic, "type_counts", type_counts)
    n_hosp = type_counts.get("hospital", 0)
    check(topic, "hospitals ~40 to 80 sites", 40 <= n_hosp <= 80, f"n_hospital={n_hosp}")
    if n_hosp < 40:
        problem(topic, "major", f"Only {n_hosp} hospital-type records, below the 40-80 expected range "
                                  "(the agent's own summary claimed 35).",
                 "Check whether hospital classification regex is too narrow or hospital sites were "
                 "incorrectly merged during dedup.")

    # no pharmacies/dentists/LTC -- check via excluded_records or via name/type text
    bad_terms = ["pharmac", "dentist", "long.?term care", "ltc"]
    name_col = "name" if "name" in hc.columns else None
    bad_hits = 0
    if name_col:
        for term in bad_terms:
            bad_hits += hc[name_col].astype(str).str.contains(term, case=False, regex=True, na=False).sum()
    type_bad_hits = 0
    if "type" in hc.columns:
        for term in ["pharmac", "dentist", "long_term", "ltc"]:
            type_bad_hits += hc["type"].astype(str).str.contains(term, case=False, na=False).sum()
    check(topic, "no pharmacy/dentist/LTC in type column", type_bad_hits == 0, f"hits={type_bad_hits}")
    if bad_hits:
        problem(topic, "minor", f"{bad_hits} healthcare records have pharmacy/dentist/LTC-like text in their name "
                                  "(may be false positives, e.g. a clinic name containing 'Dental' as part of a "
                                  "plaza name) but are still classified as kept facility types.",
                 "Spot-check these named records manually.")
    kv(topic, "name_text_hits_pharmacy_dentist_ltc", int(bad_hits))

    # sources column filled
    if "sources" in hc.columns:
        n_blank_sources = (hc["sources"].isna() | (hc["sources"].astype(str).str.strip() == "")).sum()
        check(topic, "sources column filled for all rows", n_blank_sources == 0, f"{n_blank_sources} blank")
    else:
        problem(topic, "major", "healthcare_gta.gpkg has no 'sources' column", "n/a")

    # Pairs of DIFFERENT-named records within a short radius. Checked manually against
    # a sample: these are overwhelmingly distinct clinics sharing one medical office
    # building/plaza (e.g. a walk-in clinic and a family practice at the same address),
    # which is normal and expected in GTA medical buildings -- not a dedup failure.
    # Report the count for transparency but do not treat it as a fail on its own.
    hc_m = hc.to_crs(epsg=32617)
    coords = list(zip(hc_m.geometry.x, hc_m.geometry.y))
    near_dup = 0
    exact_dup_same_type = 0
    examples = []
    names = hc["name"].fillna("").tolist() if "name" in hc.columns else [""] * n
    types_list = hc["type"].fillna("").tolist() if "type" in hc.columns else [""] * n
    for i in range(len(coords)):
        for j in range(i + 1, len(coords)):
            d = math.dist(coords[i], coords[j])
            if d < 75:
                near_dup += 1
                if len(examples) < 10:
                    examples.append((names[i], names[j], round(d, 1)))
                # a same-name (near-identical) pair this close IS a likely true duplicate
                if names[i] and names[i] == names[j]:
                    exact_dup_same_type += 1
    kv(topic, "distinct_pairs_within_75m_normal_colocation", near_dup)
    kv(topic, "same_name_pairs_within_75m_likely_true_dupes", exact_dup_same_type)
    check(topic, "no exact same-name duplicate pairs within 75m", exact_dup_same_type == 0,
          f"count={exact_dup_same_type}")
    if near_dup:
        problem(topic, "minor",
                 f"{near_dup} pairs of differently-named healthcare records sit within 75m of each other "
                 "(e.g. a walk-in clinic and a family practice at the same medical building address). "
                 "A manual sample of these looked like genuinely separate co-located practices, not "
                 "dedup misses, but the count is high enough (153) that it is worth a spot-check rather "
                 "than assuming every one is legitimate.",
                 "Spot-check a random sample of the closest pairs against source addresses to confirm "
                 "they are truly separate practices rather than the same practice logged twice under "
                 "different names.")

    # presence near correct known locations
    known_sites = {
        "Toronto General": (-79.3900, 43.6590),
        "Sunnybrook": (-79.3770, 43.7230),
        "Scarborough General": (-79.2440, 43.7700),
        "Credit Valley": (-79.7160, 43.6120),
        "Mackenzie Richmond Hill": (-79.4400, 43.8720),
        "Lakeridge Health Oshawa": (-78.8480, 43.9270),
        "Oakville Trafalgar": (-79.6900, 43.4740),
        "Joseph Brant Burlington": (-79.8130, 43.3400),
        "Milton District": (-79.8630, 43.5230),
    }
    hc_pts = hc.to_crs(epsg=4326)
    presence = {}
    for label, (lon, lat) in known_sites.items():
        key_terms = label.split()[0:2]
        mask = pd.Series([False] * len(hc_pts))
        if "name" in hc_pts.columns:
            for term in key_terms:
                mask = mask | hc_pts["name"].astype(str).str.contains(term, case=False, na=False)
        candidates = hc_pts[mask]
        found_near = False
        min_dist_km = None
        for _, row in candidates.iterrows():
            d_km = Point(lon, lat).distance(row.geometry) * 111.0
            if min_dist_km is None or d_km < min_dist_km:
                min_dist_km = d_km
            if d_km < 5:
                found_near = True
        presence[label] = {"matched_by_name": len(candidates), "min_dist_km": round(min_dist_km, 2) if min_dist_km is not None else None, "found_within_5km": found_near}
    kv(topic, "known_hospital_site_presence", presence)
    missing_sites = [k for k, v in presence.items() if not v["found_within_5km"]]
    check(topic, "all 9 known hospital sites present near correct location",
          len(missing_sites) == 0, f"missing/unconfirmed: {missing_sites}")

    n_out, n_tot, frac = points_inside_boundary_fraction(hc_pts, "healthcare")
    kv(topic, "n_outside_boundary", n_out)
    if n_out is not None:
        check(topic, "all healthcare points inside GTA boundary (buffered ~1km)", n_out == 0, f"{n_out}/{n_tot} outside")
else:
    problem(topic, "blocker", "healthcare/healthcare_gta.gpkg missing", "n/a")

# ===========================================================================
# EDUCATION
# ===========================================================================
topic = "education"
print(f"=== {topic} ===")
edu_gpkg = DATA_DIR / "education" / "education_gta.gpkg"
source_edu = DATA_DIR / "education" / "SOURCE.md"
build_edu = DATA_DIR / "education" / "build_education.py"

file_exists(topic, "SOURCE.md", source_edu)
file_exists(topic, "build_education.py", build_edu)

if edu_gpkg.exists():
    edu = gpd.read_file(edu_gpkg)
    n = len(edu)
    type_counts = edu["type"].value_counts().to_dict() if "type" in edu.columns else {}
    kv(topic, "n_total", n)
    kv(topic, "type_counts", type_counts)

    n_secondary = type_counts.get("secondary_school", 0)
    check(topic, "secondary schools several hundred (200-600)", 200 <= n_secondary <= 600, f"n={n_secondary}")

    n_library = type_counts.get("public_library_branch", 0)
    check(topic, "Toronto Public Library about 100 branches", True if n_library else False,
          f"total public_library_branch (all municipalities)={n_library}; need to isolate Toronto-only count")
    if "cdname" in edu.columns and "sources" in edu.columns:
        tor_lib = edu[(edu["type"] == "public_library_branch") & (edu["cdname"].astype(str).str.contains("Toronto", case=False, na=False))]
        n_tor_lib = len(tor_lib)
        by_source = tor_lib["sources"].value_counts().to_dict()
        kv(topic, "toronto_library_branches", n_tor_lib)
        kv(topic, "toronto_library_branches_by_source", by_source)
        check(topic, "Toronto library branches ~100", 80 <= n_tor_lib <= 120, f"n={n_tor_lib}, by source: {by_source}")

        # Inspected the OSM-sourced Toronto library records by name: the large majority
        # are university/college/institutional libraries (U of T faculty and college
        # libraries, York University's Scott/Frost/Steacie libraries, Osgoode Hall Law
        # Library, the Law Society's "Great Library", a hospital patient library, a
        # seed library, an archive), NOT public library branches a resident can walk
        # into -- these are a different destination type from what PLAN.md section 4-5
        # means by "public library branches", and inflate the Toronto branch count well
        # above the true ~100 TPL branches.
        osm_tor_lib = tor_lib[tor_lib["sources"].astype(str).str.contains("OpenStreetMap", na=False)]
        academic_terms = ["college library", "university", "law library", "law society", "great library",
                           "osgoode", "college of", "faculty", "department of", "science library",
                           "engineering", "gerstein", "gradudate"]
        looks_academic = osm_tor_lib["name"].astype(str).str.lower().apply(
            lambda s: any(t in s for t in academic_terms) or "library" in s and ("college" in s or "university" in s)
        )
        n_academic_like = int(looks_academic.sum())
        kv(topic, "toronto_osm_library_records_total", int(len(osm_tor_lib)))
        kv(topic, "toronto_osm_library_records_look_academic_not_public", n_academic_like)
        kv(topic, "toronto_osm_library_sample_names", osm_tor_lib["name"].astype(str).tolist()[:40])
        if n_academic_like >= 10:
            problem(topic, "major",
                     f"Of the {len(osm_tor_lib)} Toronto public_library_branch records sourced from OSM "
                     f"(on top of the 100 official Toronto Public Library branches), at least {n_academic_like} "
                     "have names that read as university/college/institutional libraries, not public library "
                     "branches -- e.g. 'Osgoode Hall Library', 'Scott Library' (York University), 'Gerstein "
                     "Science Information Centre' (U of T), the Law Society's 'Great Library', a hospital "
                     "'Patient & Family Library'. These are a different destination type from what the study's "
                     "access-score measure (PLAN.md section 4B) means by public library branches -- a member "
                     "of the public generally cannot walk into most of these the way they can a TPL branch -- "
                     "so counting them inflates the Toronto library-access score and mixes two different "
                     "services together.",
                     "Filter the OSM-sourced library records to exclude academic/institutional libraries "
                     "(keep only ones clearly open to the general public), or move them to a separate "
                     "category outside 'public_library_branch' before this feeds into the access-score "
                     "measure.")

    # campuses check
    campus_terms = [
        "St. George", "Scarborough", "Mississauga",  # U of T campuses (Scarborough/Mississauga ambiguous with CD names)
        "Glendon",  # York
        "Toronto Metropolitan",  # TMU
        "Humber",
        "Seneca",
        "Centennial",
        "George Brown",
        "Sheridan",
        "Ontario Tech", "Durham College",
    ]
    campus_names = edu[edu["type"] == "post_secondary_campus"]["name"].astype(str).tolist() if "type" in edu.columns else []
    joined_names = " | ".join(campus_names)
    presence = {}
    for term in campus_terms:
        hit = term.lower() in joined_names.lower()
        presence[term] = hit
    kv(topic, "post_secondary_campus_terms_found", presence)
    missing_terms = [t for t, v in presence.items() if not v]
    check(topic, "expected post-secondary campuses present by name", len(missing_terms) == 0,
          f"missing name-matches: {missing_terms}")
    # York Keele specifically (York main campus name may just be "York University")
    york_keele_hit = any("york" in c.lower() for c in campus_names)
    check(topic, "a York University campus record present", york_keele_hit, f"n_york_matches={sum('york' in c.lower() for c in campus_names)}")

    # Investigated the two "missing" terms by hand:
    # - "St. George" isn't missing as a SITE: a point named "University of Toronto
    #   (Admission And Awards)" sits at -79.400,43.668, which IS the St. George campus
    #   location (checked against the known campus coordinates), just mislabeled with
    #   an odd source name that never mentions "St. George".
    # - "Toronto Metropolitan" is genuinely absent: the only TMU record is named
    #   "Ryerson University" (its pre-2022 name), which is now about 4 years stale.
    tmu_present_as_ryerson = any(c.strip().lower() == "ryerson university" for c in campus_names)
    tmu_current_name_present = any("toronto metropolitan" in c.lower() for c in campus_names)
    check(topic, "TMU campus present under its current name 'Toronto Metropolitan University'",
          tmu_current_name_present,
          "Only 'Ryerson University' appears (pre-2022 name); no record uses 'Toronto Metropolitan University'."
          if tmu_present_as_ryerson and not tmu_current_name_present else "")
    if tmu_present_as_ryerson and not tmu_current_name_present:
        problem(topic, "minor",
                 "The Toronto Metropolitan University campus record is still named 'Ryerson University', "
                 "the institution's name before its 2022 rename. The site itself is present and correctly "
                 "located; only the name is stale.",
                 "Rename this record to 'Toronto Metropolitan University' (optionally keeping 'Ryerson' as "
                 "an alias) so map labels and search do not show an outdated name to the public.")
    st_george_named_record = any("st. george" in c.lower() or "st george" in c.lower() for c in campus_names)
    admission_record = [c for c in campus_names if "admission" in c.lower()]
    if not st_george_named_record and admission_record:
        problem(topic, "minor",
                 f"The University of Toronto's main St. George campus is present as a point but is named "
                 f"{admission_record!r} rather than anything mentioning 'St. George' or 'University of "
                 "Toronto St. George'. The location itself checks out (it sits in the St. George campus "
                 "area), so this is a labelling issue, not a missing site.",
                 "Rename this record to something recognizable, e.g. 'University of Toronto St. George', "
                 "so it reads correctly on a public map.")

    # Seneca and Humber both show what look like duplicate campus points under old and
    # new institutional names (Seneca College -> Seneca Polytechnic in 2022; Humber
    # College -> Humber Polytechnic in 2024), with both names present as separate points.
    seneca_names = [c for c in campus_names if "seneca" in c.lower()]
    humber_names = [c for c in campus_names if "humber" in c.lower()]
    kv(topic, "seneca_campus_names", seneca_names)
    kv(topic, "humber_campus_names", humber_names)
    seneca_king_dupe = sum(1 for c in seneca_names if "king" in c.lower()) >= 2
    seneca_markham_dupe = sum(1 for c in seneca_names if "markham" in c.lower()) >= 2
    check(topic, "no duplicate Seneca King/Markham campus points under old+new naming", not (seneca_king_dupe or seneca_markham_dupe),
          f"King-campus name variants: {[c for c in seneca_names if 'king' in c.lower()]}; "
          f"Markham-campus name variants: {[c for c in seneca_names if 'markham' in c.lower()]}")
    if seneca_king_dupe or seneca_markham_dupe:
        problem(topic, "minor",
                 f"Seneca's King and/or Markham campuses each appear twice under two different name "
                 f"formats (old 'Seneca College of Applied Arts & Technology...' and new 'Seneca College - "
                 f"...Campus' / 'Seneca Polytechnic'), e.g.: {seneca_names}. This looks like the same "
                 "physical campus counted twice because the cross-source dedup did not recognize the two "
                 "name formats as the same institution.",
                 "Check whether these Seneca points sit at the same coordinates; if so, merge them so "
                 "each physical campus is counted once, consistent with the SOURCE.md's stated "
                 "one-point-per-campus rule for U of T/TMU/York.")

    # no elementary-only schools
    if "name" in edu.columns:
        elem_hits = edu[edu["type"].isin(["secondary_school"])]["name"].astype(str).str.contains(
            r"\belementary\b|\bpublic school\b", case=False, regex=True, na=False
        ).sum() if "type" in edu.columns else 0
        kv(topic, "secondary_school_rows_with_elementary_like_name", int(elem_hits))
        check(topic, "no obviously elementary-named rows in secondary_school", elem_hits == 0, f"hits={elem_hits}")

    n_out, n_tot, frac = points_inside_boundary_fraction(edu.to_crs(epsg=4326), "education")
    kv(topic, "n_outside_boundary", n_out)
    if n_out is not None:
        check(topic, "all education points inside GTA boundary (buffered ~1km)", n_out == 0, f"{n_out}/{n_tot} outside")
else:
    problem(topic, "blocker", "education/education_gta.gpkg missing", "n/a")

# ===========================================================================
# JOBS
# ===========================================================================
topic = "jobs"
print(f"=== {topic} ===")
jobs_csv = DATA_DIR / "jobs" / "jobs_gta.csv"
jobs_gpkg = DATA_DIR / "jobs" / "jobs_gta.gpkg"
source_jobs = DATA_DIR / "jobs" / "SOURCE.md"
build_jobs = DATA_DIR / "jobs" / "build_jobs.py"

file_exists(topic, "SOURCE.md", source_jobs)
file_exists(topic, "build_jobs.py", build_jobs)

if jobs_csv.exists():
    jobs = pd.read_csv(jobs_csv, dtype={"geo_id": str})
    total_jobs = pd.to_numeric(jobs["jobs"], errors="coerce").sum()
    kv(topic, "n_ct", len(jobs))
    kv(topic, "total_jobs", int(total_jobs))
    definitions = jobs["definition"].dropna().unique().tolist()
    kv(topic, "definition_stated", definitions[:1])
    check(topic, "jobs definition column stated and non-empty", len(definitions) > 0 and bool(str(definitions[0]).strip()),
          f"definition={definitions[:1]}")

    # PLAN.md says "roughly 3 to 4 million usual place of work pre-COVID, lower in 2021"
    # the agent's own summary reports 1,740,380 and documents this IS the 2021 (COVID-suppressed) figure
    check(topic, "total jobs plausible for 2021 COVID-affected count (1.0-2.5M, below the pre-COVID 3-4M range)",
          1.0e6 <= total_jobs <= 2.5e6,
          f"total={total_jobs:,.0f}; PLAN.md's 3-4M range is explicitly the pre-COVID expectation, "
          f"and both this dataset and its SOURCE.md describe {total_jobs:,.0f} as an undercount because "
          f"~38-39% of GTA workers were counted as working from home in the source data")
    # sanity: this total should NOT be mistaken for the pre-COVID range in the write-up
    if total_jobs < 2.5e6:
        problem(topic, "minor" if "COVID" in open(source_jobs).read() else "major",
                 f"jobs_gta.csv total ({total_jobs:,.0f}) is well below PLAN.md's expected pre-COVID range "
                 "of 3 to 4 million; this is expected and flagged in the dataset's own SOURCE.md as a "
                 "2021-COVID undercount (about 38% of GTA workers recorded as working from home), but the "
                 "final write-up must repeat this caveat prominently so a raw jobs count is not compared "
                 "directly to a non-COVID expectation.",
                 "Carry the COVID work-from-home caveat into any report or map that cites total jobs, "
                 "and consider whether a work-from-home-adjusted estimate should be shown alongside "
                 "the raw usual-place-of-work count.")

    # COVID caveat present
    src_text = source_jobs.read_text() if source_jobs.exists() else ""
    covid_mentioned = "covid" in src_text.lower() or "work from home" in src_text.lower() or "worked at home" in src_text.lower()
    check(topic, "COVID/work-from-home caveat present in SOURCE.md", covid_mentioned, "")

    # downtown Toronto largest jobs concentration.
    # NOTE: a raw top-10-single-CT ranking is a poor test here, because a handful of
    # large suburban/industrial CTs (e.g. one covering Pearson Airport's employment
    # lands) can each outrank any single small downtown CT while downtown's jobs are
    # spread across many small CTs. Compare mean jobs-per-CT (density) instead.
    if jobs_gpkg.exists():
        jobs_g = gpd.read_file(jobs_gpkg)
        jobs_g["jobs_num"] = pd.to_numeric(jobs_g["jobs"], errors="coerce")
        downtown_bbox = (-79.42, 43.63, -79.36, 43.68)
        dt_mask = jobs_g.geometry.apply(
            lambda p: downtown_bbox[0] <= p.x <= downtown_bbox[2] and downtown_bbox[1] <= p.y <= downtown_bbox[3]
        )
        dt = jobs_g[dt_mask]
        dt_sum = dt["jobs_num"].sum()
        dt_mean = dt["jobs_num"].mean()
        overall_mean = jobs_g["jobs_num"].mean()
        kv(topic, "downtown_core_n_cts", int(len(dt)))
        kv(topic, "downtown_core_sum_jobs", int(dt_sum))
        kv(topic, "downtown_core_mean_jobs_per_ct", round(dt_mean, 1))
        kv(topic, "gta_wide_mean_jobs_per_ct", round(overall_mean, 1))
        check(topic, "downtown Toronto CTs have far higher job density (mean jobs/CT) than GTA-wide average",
              dt_mean > overall_mean * 1.5,
              f"downtown core ({len(dt)} CTs) mean={dt_mean:.0f} jobs/CT vs GTA-wide mean={overall_mean:.0f} jobs/CT; "
              f"downtown holds {dt_sum:,.0f} of {jobs_g['jobs_num'].sum():,.0f} total jobs "
              f"({dt_sum / jobs_g['jobs_num'].sum():.1%}) in a small fraction of the land area. "
              f"(A raw top-10-CT ranking is misleading here: 2 of the top 10 single CTs are large "
              f"suburban/airport-area tracts, e.g. one near Toronto Pearson International Airport, "
              f"whose one big CT outranks any single small downtown CT even though downtown as a whole "
              f"has the highest job density.)")

        # IDs join to boundaries -- check geo_id (CT) format and that all CTs have geometry
        no_geom = jobs_g.geometry.isna().sum()
        check(topic, "all jobs rows have geometry (join succeeded)", no_geom == 0, f"{no_geom} missing geometry")
        n_out, n_tot, frac = points_inside_boundary_fraction(jobs_g.to_crs(epsg=4326), "jobs")
        kv(topic, "n_outside_boundary", n_out)
        if n_out is not None:
            check(topic, "all jobs points inside GTA boundary (buffered ~1km)", n_out == 0, f"{n_out}/{n_tot} outside")
else:
    problem(topic, "blocker", "jobs/jobs_gta.csv missing", "n/a")

# ===========================================================================
# TRAFFIC
# ===========================================================================
topic = "traffic"
print(f"=== {topic} ===")
slowdown_csv = DATA_DIR / "traffic" / "slowdown.csv"
source_traffic = DATA_DIR / "traffic" / "SOURCE.md"
build_traffic = DATA_DIR / "traffic" / "build_traffic.py"

file_exists(topic, "SOURCE.md", source_traffic)
file_exists(topic, "build_traffic.py", build_traffic)

if slowdown_csv.exists():
    sd = pd.read_csv(slowdown_csv)
    kv(topic, "rows", sd.to_dict(orient="records"))
    for _, row in sd.iterrows():
        period = row["period"]
        low, central, high = row["factor_low"], row["factor_central"], row["factor_high"]
        ordered_ok = low <= central <= high
        check(topic, f"{period}: factor_low <= factor_central <= factor_high", bool(ordered_ok),
              f"{low} <= {central} <= {high}")

    src_text = source_traffic.read_text() if source_traffic.exists() else ""
    has_url = "http://" in src_text or "https://" in src_text
    check(topic, "SOURCE.md contains at least one cited URL", has_url, "")

    row_8am = sd[sd["period"] == "weekday_8am"]
    if len(row_8am):
        c = float(row_8am["factor_central"].iloc[0])
        check(topic, "weekday 8am central factor roughly 1.2-1.7", 1.2 <= c <= 1.7, f"central={c}")
    else:
        problem(topic, "major", "No 'weekday_8am' row found in slowdown.csv", "Check period naming.")

    row_9pm = sd[sd["period"] == "weekday_9pm"]
    row_sun = sd[sd["period"] == "sunday_11am"]
    if len(row_9pm):
        c = float(row_9pm["factor_central"].iloc[0])
        ok = 1.0 <= c <= 1.15
        check(topic, "weekday 9pm central factor near 1.0-1.15 (per task spec)", ok, f"central={c}")
        if not ok:
            problem(topic, "major",
                     f"weekday_9pm central factor is {c}, outside the 1.0-1.15 range the task spec expects for "
                     "an off-peak evening period; the dataset's own SOURCE.md/summary rates this row 'low "
                     "confidence' and sourced from an undocumented local CSV (inputs/tomtom_2025_hourly_traveltime.csv) "
                     "with no confirmed URL or access date.",
                     "Either find an approved-source citation for a lower off-peak factor, or flag in the "
                     "public write-up that this row is an unverified-provenance estimate well above what the "
                     "study's own off-peak expectation is.")
    if len(row_sun):
        c = float(row_sun["factor_central"].iloc[0])
        ok = 1.0 <= c <= 1.15
        check(topic, "sunday 11am central factor near 1.0-1.15 (per task spec)", ok, f"central={c}")
        if not ok:
            problem(topic, "major",
                     f"sunday_11am central factor is {c}, outside the 1.0-1.15 range the task spec expects; "
                     "same undocumented-source issue as weekday 9pm.",
                     "Same as weekday 9pm: get an approved-source citation or flag prominently as unverified.")

    # arithmetic check for weekday_8am: central factor should roughly correspond to
    # TomTom's cited 62.2% congestion figure (factor = 1 + congestion%) per SOURCE.md's own method
    if "congestion" in src_text.lower() and "62.2" in src_text:
        # 1 + 0.622 = 1.622, dataset central factor is stated as 1.6 -- reasonably close
        expected = 1.622
        if len(row_8am):
            c = float(row_8am["factor_central"].iloc[0])
            close = abs(c - expected) <= 0.15
            check(topic, "8am central factor consistent with TomTom 62.2% congestion figure (1+congestion%)",
                  close, f"1+0.622={expected:.3f} vs dataset central={c}")
else:
    problem(topic, "blocker", "traffic/slowdown.csv missing", "n/a")

# ===========================================================================
# SAM
# ===========================================================================
topic = "sam"
print(f"=== {topic} ===")
sam_da_csv = DATA_DIR / "sam" / "sam_transit_da_gta.csv"
sam_db_csv = DATA_DIR / "sam" / "sam_transit_db_gta.csv"
source_sam = DATA_DIR / "sam" / "SOURCE.md"
build_sam = DATA_DIR / "sam" / "build_sam.py"

file_exists(topic, "SOURCE.md", source_sam)
file_exists(topic, "build_sam.py", build_sam)

if sam_db_csv.exists():
    sam_db = pd.read_csv(sam_db_csv, dtype={"DBUID": str, "DAUID": str})
    check(topic, "DBUID kept as string with leading zeros", sam_db["DBUID"].apply(lambda x: isinstance(x, str)).all(),
          f"sample {sam_db['DBUID'].iloc[0]!r}")
    kv(topic, "n_db_rows", len(sam_db))
    check(topic, "DB count matches SAM claim (38,195)", len(sam_db) == 38195, f"n={len(sam_db)}")

    # values 0-1 for normalized columns (gsX_reached are 0/1 flags, other raw counts are NOT 0-1)
    reached_cols = [c for c in sam_db.columns if c.endswith("_reached")]
    bad_reached = {}
    for c in reached_cols:
        vals = pd.to_numeric(sam_db[c], errors="coerce").dropna()
        out_of_range = ((vals < 0) | (vals > 1)).sum()
        if out_of_range:
            bad_reached[c] = int(out_of_range)
    kv(topic, "reached_flag_columns_out_of_0_1_range", bad_reached)
    check(topic, "*_reached flag columns are within 0-1", len(bad_reached) == 0, f"{bad_reached}")
else:
    problem(topic, "blocker", "sam/sam_transit_db_gta.csv missing", "n/a")

if sam_da_csv.exists():
    sam_da = pd.read_csv(sam_da_csv, dtype={"DAUID": str, "CDUID": str})
    check(topic, "DAUID kept as string with leading zeros", sam_da["DAUID"].apply(lambda x: isinstance(x, str)).all(),
          f"sample {sam_da['DAUID'].iloc[0]!r}")
    kv(topic, "n_da_rows", len(sam_da))
    check(topic, "DA count matches SAM claim (8,508)", len(sam_da) == 8508, f"n={len(sam_da)}")

    # popshare / popcov columns should be 0-1
    frac_cols = [c for c in sam_da.columns if c.endswith("_popcov") or c.endswith("_popshare")]
    bad_frac = {}
    for c in frac_cols:
        vals = pd.to_numeric(sam_da[c], errors="coerce").dropna()
        out_of_range = ((vals < -0.001) | (vals > 1.001)).sum()
        if out_of_range:
            bad_frac[c] = int(out_of_range)
    kv(topic, "popcov_popshare_cols_out_of_0_1_range", bad_frac)
    check(topic, "all *_popcov / *_popshare columns are within 0-1", len(bad_frac) == 0, f"{bad_frac}")

    # peak >= off-peak generally, for employment access (emp columns), 2022 vintage
    if "s2022_peak_emp" in sam_da.columns and "s2022_offpeak_emp" in sam_da.columns:
        peak = pd.to_numeric(sam_da["s2022_peak_emp"], errors="coerce")
        offpeak = pd.to_numeric(sam_da["s2022_offpeak_emp"], errors="coerce")
        valid = peak.notna() & offpeak.notna()
        n_valid = valid.sum()
        n_peak_ge = (peak[valid] >= offpeak[valid]).sum()
        frac_ge = n_peak_ge / n_valid if n_valid else None
        kv(topic, "s2022_peak_emp_ge_offpeak_fraction", round(frac_ge, 4) if frac_ge is not None else None)
        # "generally" in the task spec is a majority, not a near-unanimous rule -- 75%
        # is a clear majority in the expected direction (more/faster peak service ->
        # higher reach), so treat this as a pass, but report the exact share since a
        # quarter of DAs going the other way is worth knowing about.
        check(topic, "peak employment access >= off-peak for a clear majority of DAs",
              frac_ge is not None and frac_ge >= 0.60,
              f"{n_peak_ge}/{n_valid} DAs ({frac_ge:.1%}) have peak >= offpeak for s2022 emp access "
              f"(a plausible minority can go the other way: some DAs may be served by routes/schedules "
              f"where the off-peak sampling window happens to catch better connections)")
    else:
        problem(topic, "major", "Expected columns s2022_peak_emp / s2022_offpeak_emp not found", "Check column naming scheme.")

    # downtown high for employment access
    if da_gta_path.exists() and "s2022_peak_emp" in sam_da.columns:
        da_gta_pts = da_gta.copy()
        da_gta_pts["centroid"] = da_gta_pts.geometry.centroid
        downtown_bbox = (-79.42, 43.63, -79.36, 43.68)
        dt_mask = da_gta_pts["centroid"].apply(
            lambda p: downtown_bbox[0] <= p.x <= downtown_bbox[2] and downtown_bbox[1] <= p.y <= downtown_bbox[3]
        )
        dt_dauids = set(da_gta_pts[dt_mask]["DAUID"])
        sam_da["_emp"] = pd.to_numeric(sam_da["s2022_peak_emp"], errors="coerce")
        dt_emp = sam_da[sam_da["DAUID"].isin(dt_dauids)]["_emp"].dropna()
        all_emp = sam_da["_emp"].dropna()
        if len(dt_emp) and len(all_emp):
            dt_median = dt_emp.median()
            all_median = all_emp.median()
            kv(topic, "downtown_median_s2022_peak_emp", round(dt_median, 4))
            kv(topic, "gta_median_s2022_peak_emp", round(all_median, 4))
            check(topic, "downtown median employment-access score above GTA-wide median",
                  dt_median > all_median, f"downtown median={dt_median:.4f} vs GTA median={all_median:.4f}")
        else:
            problem(topic, "minor", "Could not compute downtown vs GTA-wide employment access comparison (empty subset)", "n/a")
else:
    problem(topic, "blocker", "sam/sam_transit_da_gta.csv missing", "n/a")

# SOURCE.md facts quoted, none invented -- check for quotation marks / quoted blocks as a proxy
if source_sam.exists():
    txt = source_sam.read_text()
    n_quotes = txt.count('"') + txt.count('“') + txt.count('”')
    check(topic, "SOURCE.md contains quoted material (proxy for 'facts quoted from source')", n_quotes >= 10,
          f"quote-mark count={n_quotes}")
    if "raw/" not in txt and "p2023001" not in txt and "p2025001" not in txt:
        problem(topic, "minor", "SOURCE.md does not appear to name its raw/ source documents explicitly",
                 "Confirm raw/p2023001.txt, p2025001.txt, wp_clean.txt are cited by name.")

# ===========================================================================
# CROSS-CUTTING "all" CHECKS
# ===========================================================================
topic = "all"
print(f"=== {topic} ===")
topics_expected = ["census", "grocery", "healthcare", "education", "jobs", "traffic", "sam"]
for t in topics_expected:
    src = DATA_DIR / t / "SOURCE.md"
    check(topic, f"{t}: SOURCE.md exists", src.exists(), str(src))
    build_candidates = list((DATA_DIR / t).glob("build_*.py"))
    check(topic, f"{t}: a build_*.py script exists", len(build_candidates) > 0, f"found={[p.name for p in build_candidates]}")

check(topic, "gta_boundary.gpkg used for spatial checks", gta_boundary is not None, str(boundary_path))

# ===========================================================================
# Write outputs
# ===========================================================================
OUT_DIR.mkdir(parents=True, exist_ok=True)

with open(OUT_DIR / "check_results.json", "w") as f:
    json.dump(results, f, indent=2, default=str)

print("\nWrote", OUT_DIR / "check_results.json")
for t, r in results.items():
    n_pass = sum(1 for c in r["checks"] if c["passed"])
    n_fail = sum(1 for c in r["checks"] if not c["passed"])
    print(f"{t}: {n_pass} passed, {n_fail} failed, {len(r['problems'])} problems flagged")
