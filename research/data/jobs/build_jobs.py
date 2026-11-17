"""
Build jobs_gta.csv and jobs_gta.gpkg for the GTA transit gap study.

Source: Statistics Canada table 98-10-0498-01, "Employment income groups by
place of work status: Census metropolitan areas, tracted census
agglomerations and census tracts of work" (2021 Census, 25% sample).

We use the "Usual place of work" row for each census tract (CT) inside the
Toronto Census Metropolitan Area (CMA 535). That row's "Total - Employment
income" count is the number of workers aged 15+ whose usual workplace is in
that CT (whether or not they reported employment income) -- this is the
finest geography available in raw/ for a place-of-work jobs count, and it is
used here as a proxy for "jobs located in that zone".

Geography: 2021 census tracts, restricted to the five study CDs (3518
Durham, 3519 York, 3520 Toronto, 3521 Peel, 3524 Halton) by intersecting CT
polygons with the union of census subdivisions (CSDs) belonging to those
CDs. A CT is kept if at least half its area falls inside that union.

Re-runnable: rerun this script any time; it only reads raw/ and (re)writes
jobs_gta.csv and jobs_gta.gpkg in this folder.
"""

import geopandas as gpd
import pandas as pd

RAW = "raw"
STUDY_CDS = ["3518", "3519", "3520", "3521", "3524"]

# ---------------------------------------------------------------------
# 1. Load the jobs table, keep 2021 CT-level "Usual place of work" rows
# ---------------------------------------------------------------------
df = pd.read_csv(f"{RAW}/98100498.csv", encoding="utf-8-sig")
df.columns = [c.strip() for c in df.columns]

jobs_col = "Employment income groups (18):Total - Employment income[1]"

# CT rows have a DGUID of the form 2021S0507<CTUID>, length 19.
# (CMA-total rows are 2021S0503<CMA code>, length 12, and are dropped.)
is_ct_row = df["DGUID"].str.len() == 19
df_ct = df[is_ct_row].copy()
df_ct["CTUID"] = df_ct["DGUID"].str[9:]

df_upow = df_ct[df_ct["Place of work status (3)"] == "Usual place of work"].copy()
df_upow["jobs"] = pd.to_numeric(df_upow[jobs_col], errors="coerce")

jobs_by_ct = df_upow[["CTUID", "jobs"]].dropna(subset=["CTUID"]).drop_duplicates("CTUID")
print(f"CT rows with usual-place-of-work jobs count: {len(jobs_by_ct)}")

# ---------------------------------------------------------------------
# 2. Load CT boundaries, and CSD boundaries to define the 5-CD study area
# ---------------------------------------------------------------------
ct = gpd.read_file(f"zip://{RAW}/lct_000b21a_e.zip")
csd = gpd.read_file(f"zip://{RAW}/lcsd000b21a_e.zip")
csd["CDUID"] = csd["CSDUID"].str[:4]

study_csd = csd[csd["CDUID"].isin(STUDY_CDS)].copy()
print(f"CSDs in the 5 study CDs: {len(study_csd)}")

study_area = study_csd.union_all()

# Keep a CT if at least half its area is inside the 5-CD union.
ct = ct.to_crs(study_csd.crs)
ct["area_total"] = ct.geometry.area
ct["area_in_study"] = ct.geometry.intersection(study_area).area
ct_gta = ct[ct["area_in_study"] / ct["area_total"] >= 0.5].copy()
print(f"CTs kept (>=50% inside the 5 study CDs): {len(ct_gta)}")

coverage_pct = 100 * ct_gta["area_in_study"].sum() / study_area.area
print(f"CT coverage of the 5-CD area: {coverage_pct:.1f}%")

# ---------------------------------------------------------------------
# 3. Join jobs counts to CT geometry, build a representative point
# ---------------------------------------------------------------------
merged = ct_gta.merge(jobs_by_ct, on="CTUID", how="left")
n_missing = merged["jobs"].isna().sum()
print(f"CTs in study area with no jobs figure in 98100498.csv: {n_missing}")

merged["geometry"] = merged.geometry.representative_point()
merged = merged.to_crs(4326)

out_gpkg = merged[["CTUID", "jobs", "geometry"]].copy()
out_gpkg["geo_type"] = "CT"
out_gpkg["year"] = 2021
out_gpkg["definition"] = (
    "Workers aged 15+ whose usual place of work is in this census tract, "
    "2021 Census (25% sample), StatCan table 98-10-0498-01. Excludes people "
    "who worked from home (their workplace status is 'worked at home', not "
    "assigned to a work location) and people with no fixed workplace address."
)
out_gpkg = out_gpkg.rename(columns={"CTUID": "geo_id"})
out_gpkg = out_gpkg[["geo_id", "geo_type", "jobs", "year", "definition", "geometry"]]
out_gpkg.to_file("jobs_gta.gpkg", driver="GPKG")

out_csv = out_gpkg.drop(columns="geometry")
out_csv.to_csv("jobs_gta.csv", index=False)

print("Wrote jobs_gta.csv and jobs_gta.gpkg")
print(out_csv["jobs"].describe())
print("Total jobs captured (sum over CTs, non-null):", out_csv["jobs"].sum())
