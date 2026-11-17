"""
Build census layer files for the GTA transit gaps study.

Study area: 2021 census divisions
  3518 Durham, 3519 York, 3520 Toronto, 3521 Peel, 3524 Halton

Inputs (in raw/, already downloaded):
  - lda_000b21a_e.zip           2021 DA boundary file (StatCan)
  - 2021_92-151_X.zip           2021 Geographic Attribute File (GAF), DB level
  - 98-401-X2021006_Ontario_eng_CSV.zip   2021 Census Profile, Ontario, all
                                          geography levels down to DA

Outputs (in this folder):
  - da_gta.gpkg        DA polygons in the 5 CDs, EPSG:4326
  - da_origins.csv      one representative origin point per DA
  - da_profile.csv      DA-level population / income / commute-mode table
  - gta_boundary.gpkg   the 5 CDs, dissolved from their DAs

Re-run safe: every step reads from raw/ or re-derives from it. No step
mutates raw/ except extracting the two zip files it needs (idempotent).
"""

import csv
import io
import os
import subprocess
import sys
import zipfile
from collections import defaultdict

import geopandas as gpd
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "raw")

GTA_CDS = ["3518", "3519", "3520", "3521", "3524"]
CD_NAMES_FALLBACK = {
    "3518": "Durham",
    "3519": "York",
    "3520": "Toronto",
    "3521": "Peel",
    "3524": "Halton",
}

PROFILE_ZIP = os.path.join(RAW, "98-401-X2021006_Ontario_eng_CSV.zip")
PROFILE_CSV_NAME = "98-401-X2021006_English_CSV_data_Ontario.csv"
GEO_START_NAME = "98-401-X2021006_Geo_starting_row_Ontario.CSV"
GAF_ZIP = os.path.join(RAW, "2021_92-151_X.zip")
GAF_CSV = os.path.join(RAW, "2021_92-151_X.csv")
LDA_SHP = os.path.join(RAW, "lda", "lda_000b21a_e.shp")

# Characteristic IDs used from the Census Profile (98-401-X2021006).
# Found by reading the fixed per-geography block (2631 rows) for "Canada"
# and matching characteristic names; each DA's block uses the same order.
CHAR_IDS = {
    1: "population",
    50: "private_households",
    243: "median_hh_income",
    345: "lim_at_pct",
    2605: "mode_driver",
    2606: "mode_passenger",
    2607: "mode_transit",
    2608: "mode_walk",
    2609: "mode_bicycle",
    2610: "mode_other",
}
BLOCK_SIZE = 2631  # rows per geography in this profile table, confirmed empirically


def ensure_extracted():
    if not os.path.exists(GAF_CSV):
        print("Extracting GAF csv...")
        with zipfile.ZipFile(GAF_ZIP) as z:
            z.extractall(RAW)
    geo_start_path = os.path.join(RAW, GEO_START_NAME)
    if not os.path.exists(geo_start_path):
        print("Extracting geo starting-row index...")
        with zipfile.ZipFile(PROFILE_ZIP) as z:
            z.extract(GEO_START_NAME, RAW)
    return geo_start_path


def load_gaf_gta():
    """Read the GAF (DB-level) csv, keep only rows in the 5 GTA CDs.

    Returns:
      da_point:   DAUID -> (lat, lon)   (DA representative point, repeated
                  per DB row in the source file; StatCan assigns this once
                  per DA, not per DB -- see SOURCE.md)
      da_nblocks: DAUID -> count of DB rows under that DA
      da_csd:     DAUID -> CSD name
      cd_name:    CDUID -> CD name
      da_gaf_pop: DAUID -> sum of DB population (cross-check only)
    """
    usecols = [
        "CDUID_DRIDU", "CDNAME_DRNOM",
        "CSDUID_SDRIDU", "CSDNAME_SDRNOM",
        "DAUID_ADIDU", "DARPLAT_ADLAT", "DARPLONG_ADLONG",
        "DBUID_IDIDU", "DBPOP2021_IDPOP2021",
    ]
    da_point = {}
    da_nblocks = defaultdict(int)
    da_csd = {}
    cd_name = {}
    da_gaf_pop = defaultdict(int)

    chunksize = 300_000
    total_rows = 0
    for chunk in pd.read_csv(
        GAF_CSV, usecols=usecols, dtype=str, encoding="latin-1",
        chunksize=chunksize, low_memory=False,
    ):
        total_rows += len(chunk)
        chunk = chunk[chunk["CDUID_DRIDU"].isin(GTA_CDS)]
        if chunk.empty:
            continue
        for row in chunk.itertuples(index=False):
            dauid = row.DAUID_ADIDU
            cduid = row.CDUID_DRIDU
            if dauid not in da_point:
                try:
                    lat = float(row.DARPLAT_ADLAT)
                    lon = float(row.DARPLONG_ADLONG)
                except (TypeError, ValueError):
                    lat = lon = None
                da_point[dauid] = (lat, lon)
                da_csd[dauid] = row.CSDNAME_SDRNOM
            cd_name.setdefault(cduid, row.CDNAME_DRNOM)
            da_nblocks[dauid] += 1
            try:
                pop = int(float(row.DBPOP2021_IDPOP2021))
            except (TypeError, ValueError):
                pop = 0
            da_gaf_pop[dauid] += pop
    print(f"GAF: scanned {total_rows} DB rows, kept {len(da_point)} GTA DAs")
    return da_point, da_nblocks, da_csd, cd_name, da_gaf_pop


def load_profile_gta(geo_start_path):
    """Stream the big Census Profile csv once, pulling only the rows we need
    for GTA DAs, using the fixed 2631-row-per-geography block layout.
    """
    # 1. figure out, for every GTA DA, which absolute file line holds
    #    characteristic id 1 (the block start).
    da_start_line = {}
    with open(geo_start_path, encoding="latin-1") as f:
        r = csv.reader(f)
        next(r)  # header
        for code, _name, line in r:
            if len(code) == 17 and code[:9] == "2021S0512":
                dauid = code[9:]
                cduid = dauid[:4]
                if cduid in GTA_CDS:
                    da_start_line[dauid] = int(line)
    print(f"Geo index: {len(da_start_line)} GTA DAs located in profile csv")

    # 2. build the set of target absolute line numbers -> (dauid, field)
    target = {}
    for dauid, start in da_start_line.items():
        for cid, field in CHAR_IDS.items():
            target[start + (cid - 1)] = (dauid, field)

    max_line = max(target) if target else 0
    print(f"Streaming profile csv up to line {max_line} "
          f"({len(target)} target rows out of that)")

    data = defaultdict(dict)
    proc = subprocess.Popen(
        ["unzip", "-p", PROFILE_ZIP, PROFILE_CSV_NAME],
        stdout=subprocess.PIPE,
    )
    text_stream = io.TextIOWrapper(proc.stdout, encoding="latin-1", newline="")
    reader = csv.reader(text_stream)
    next(reader)  # header, this is file line 1
    line_no = 1
    found = 0
    for row in reader:
        line_no += 1
        if line_no > max_line:
            break
        hit = target.get(line_no)
        if hit is None:
            continue
        dauid, field = hit
        value_raw = row[11]
        symbol = row[12]
        value = parse_value(value_raw, symbol)
        data[dauid][field] = value
        found += 1
    proc.stdout.close()
    proc.wait()
    print(f"Profile: matched {found} of {len(target)} target cells")
    return data


def parse_value(raw, symbol):
    """Suppressed / not-applicable / too-unreliable values become missing
    (None), never zero. Symbols: '..' not available, '...' not applicable,
    'x' suppressed for confidentiality, 'F' too unreliable to publish.
    """
    raw = (raw or "").strip()
    if symbol in ("F", "x"):
        return None
    if raw in ("", "..", "...", "x", "F"):
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def build_da_gta_gpkg(gdf_gta, cd_name, da_csd, profile_pop):
    gdf = gdf_gta.copy()
    gdf["CDUID"] = gdf["DAUID"].str[:4]
    gdf["CSDNAME"] = gdf["DAUID"].map(da_csd)
    gdf["pop2021"] = gdf["DAUID"].map(lambda d: profile_pop.get(d, {}).get("population"))
    gdf = gdf.rename(columns={"LANDAREA": "landarea_km2"})
    gdf = gdf[["DAUID", "CDUID", "CSDNAME", "landarea_km2", "pop2021", "geometry"]]
    out = os.path.join(HERE, "da_gta.gpkg")
    gdf.to_file(out, layer="da_gta", driver="GPKG")
    print(f"Wrote {out}: {len(gdf)} DAs")
    return gdf


def build_da_origins_csv(da_ids, da_point, da_nblocks, profile_pop):
    rows = []
    dropped_zero_pop = 0
    for dauid in da_ids:
        pt = da_point.get(dauid)
        pop = profile_pop.get(dauid, {}).get("population")
        nblocks = da_nblocks.get(dauid, 0)
        if pt is None or pt[0] is None:
            continue
        lat, lon = pt
        if pop is None or pop == 0:
            dropped_zero_pop += 1
            continue
        rows.append({
            "DAUID": dauid,
            "lat": lat,
            "lon": lon,
            "pop2021": int(pop),
            "n_blocks": nblocks,
        })
    df = pd.DataFrame(rows)
    out = os.path.join(HERE, "da_origins.csv")
    df.to_csv(out, index=False)
    print(f"Wrote {out}: {len(df)} origins, dropped {dropped_zero_pop} zero/missing-pop DAs")
    return dropped_zero_pop


def build_da_profile_csv(da_ids, profile_pop):
    cols = ["DAUID"] + list(CHAR_IDS.values())
    rows = []
    for dauid in da_ids:
        rec = profile_pop.get(dauid, {})
        row = {"DAUID": dauid}
        for field in CHAR_IDS.values():
            row[field] = rec.get(field)
        rows.append(row)
    df = pd.DataFrame(rows, columns=cols)
    # population and private_households are 100% counts -> int where present
    for intcol in ("population", "private_households",
                   "mode_driver", "mode_passenger", "mode_transit",
                   "mode_walk", "mode_bicycle", "mode_other"):
        df[intcol] = df[intcol].astype("Int64")
    out = os.path.join(HERE, "da_profile.csv")
    df.to_csv(out, index=False)
    print(f"Wrote {out}: {len(df)} DAs")
    return df


def build_gta_boundary_gpkg(gdf_gta, cd_name):
    gdf = gdf_gta.copy()
    gdf["CDUID"] = gdf["DAUID"].str[:4]
    dissolved = gdf.dissolve(by="CDUID").reset_index()
    dissolved["CDNAME"] = dissolved["CDUID"].map(
        lambda c: cd_name.get(c, CD_NAMES_FALLBACK.get(c, c))
    )
    dissolved = dissolved[["CDUID", "CDNAME", "geometry"]]
    out = os.path.join(HERE, "gta_boundary.gpkg")
    dissolved.to_file(out, layer="gta_boundary", driver="GPKG")
    print(f"Wrote {out}: {len(dissolved)} CD polygons")
    return dissolved


def main():
    geo_start_path = ensure_extracted()

    print("Loading DA boundary shapefile...")
    gdf = gpd.read_file(LDA_SHP)
    gdf_gta = gdf[gdf["DAUID"].str.startswith(tuple(GTA_CDS))].copy()
    gdf_gta = gdf_gta.to_crs(epsg=4326)
    da_ids = sorted(gdf_gta["DAUID"].tolist())
    print(f"DA boundary file: {len(gdf)} DAs total in Ontario, {len(gdf_gta)} in the 5 GTA CDs")

    print("Reading GAF (DB population + DA representative points)...")
    da_point, da_nblocks, da_csd, cd_name, da_gaf_pop = load_gaf_gta()

    print("Reading Census Profile for GTA DAs (population, income, commute mode)...")
    profile_pop = load_profile_gta(geo_start_path)

    build_da_gta_gpkg(gdf_gta, cd_name, da_csd, profile_pop)
    dropped = build_da_origins_csv(da_ids, da_point, da_nblocks, profile_pop)
    build_da_profile_csv(da_ids, profile_pop)
    build_gta_boundary_gpkg(gdf_gta, cd_name)

    # cross-check: GAF DB-population sum vs Census Profile DA population
    mismatches = 0
    for dauid in da_ids:
        p_profile = profile_pop.get(dauid, {}).get("population")
        p_gaf = da_gaf_pop.get(dauid)
        if p_profile is not None and p_gaf is not None and abs(p_profile - p_gaf) > 5:
            mismatches += 1
    print(f"Cross-check: {mismatches} of {len(da_ids)} DAs differ by >5 people "
          f"between GAF DB-population sum and Census Profile DA population")
    print(f"da_origins.csv dropped {dropped} zero/missing-population DAs")


if __name__ == "__main__":
    sys.exit(main())
