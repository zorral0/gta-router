"""Build the v2 starting-point list for the reach run.

DAs up to 2 km2 keep one starting point: Statistics Canada's DA representative
point (da_origins.csv). DAs larger than 2 km2 instead get one starting point per
populated dissemination block, at the block's representative point (a point
guaranteed to be inside the block polygon). Weights are 2021 populations, so a
large DA's result can later be averaged over its blocks by population.

Inputs (all in this folder):
  da_origins.csv, da_gta.gpkg                     built by build_census.py
  raw/2021_92-151_X.zip                           Geographic Attribute File (block populations)
  raw/ldb_000b21a_e.zip                           2021 dissemination block boundaries (cartographic)
Output:
  origin_points_v2.csv   origin_id, DAUID, kind (da | block), weight, lat, lon

Run: research/.venv/bin/python research/data/census/build_origin_points.py
"""
import csv
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"
THRESH_KM2 = 2.0
GTA_CDS = ("3518", "3519", "3520", "3521", "3524")
OUT = HERE / "origin_points_v2.csv"


def col(columns, prefix):
    hits = [c for c in columns if c.upper().startswith(prefix)]
    if not hits:
        raise SystemExit(f"no column starting with {prefix} in {list(columns)[:20]}")
    return hits[0]


def main():
    da = gpd.read_file(HERE / "da_gta.gpkg")[["DAUID", "landarea_km2", "pop2021"]]
    da = da[da.pop2021 > 0]
    big = set(da.loc[da.landarea_km2 > THRESH_KM2, "DAUID"])
    pts = pd.read_csv(HERE / "da_origins.csv", dtype={"DAUID": str})
    print(f"DAs with population: {len(da)}; larger than {THRESH_KM2:g} km2: {len(big)} "
          f"({int(da.loc[da.DAUID.isin(big), 'pop2021'].sum()):,} people)")

    # Block populations for the large DAs, from the Geographic Attribute File.
    zf = zipfile.ZipFile(RAW / "2021_92-151_X.zip")
    gaf_name = [n for n in zf.namelist() if n.lower().endswith(".csv")][0]
    pops = []
    for ch in pd.read_csv(zf.open(gaf_name), encoding="latin-1", chunksize=200_000, dtype=str):
        dau, dbu, dbp = col(ch.columns, "DAUID"), col(ch.columns, "DBUID"), col(ch.columns, "DBPOP")
        ch = ch[ch[dau].isin(big)]
        pops.append(ch[[dbu, dau, dbp]].rename(columns={dbu: "DBUID", dau: "DAUID", dbp: "pop"}))
    blocks_pop = pd.concat(pops).drop_duplicates("DBUID")
    blocks_pop["pop"] = pd.to_numeric(blocks_pop["pop"], errors="coerce").fillna(0).astype(int)
    blocks_pop = blocks_pop[blocks_pop["pop"] > 0]

    # Block polygons, Ontario only, then keep the populated blocks of large DAs.
    bz = RAW / "ldb_000b21a_e.zip"
    shp = [n for n in zipfile.ZipFile(bz).namelist() if n.lower().endswith(".shp")][0]
    print(f"reading block boundaries ({shp}) ...", flush=True)
    geo = gpd.read_file(f"zip://{bz}!{shp}", where="PRUID = '35'")
    dbcol = col(geo.columns, "DBUID")
    geo = geo[geo[dbcol].isin(set(blocks_pop.DBUID))][[dbcol, "geometry"]].rename(columns={dbcol: "DBUID"})
    rep = gpd.GeoSeries(geo.geometry.representative_point(), crs=geo.crs).to_crs(4326)
    geo = geo.assign(lat=rep.y.round(6).values, lon=rep.x.round(6).values).merge(blocks_pop, on="DBUID")

    missing = set(blocks_pop.DBUID) - set(geo.DBUID)
    if missing:
        print(f"WARNING: {len(missing)} populated blocks have no boundary polygon; their DAs fall back to one point")

    rows = []
    with_blocks = set(geo.DAUID)
    for r in pts.itertuples():
        if r.DAUID in with_blocks:
            continue
        rows.append(dict(origin_id=r.DAUID, DAUID=r.DAUID, kind="da", weight=int(r.pop2021), lat=r.lat, lon=r.lon))
    for r in geo.sort_values("DBUID").itertuples():
        rows.append(dict(origin_id=r.DBUID, DAUID=r.DAUID, kind="block", weight=int(r.pop), lat=r.lat, lon=r.lon))
    rows.sort(key=lambda x: (x["DAUID"], x["origin_id"]))

    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["origin_id", "DAUID", "kind", "weight", "lat", "lon"])
        w.writeheader()
        w.writerows(rows)

    out = pd.DataFrame(rows)
    blk = out[out.kind == "block"]
    check = blk.groupby("DAUID").weight.sum().rename("block_pop").to_frame().join(
        da.set_index("DAUID").pop2021)
    gap = (check.block_pop - check.pop2021).abs()
    print(f"wrote {OUT.name}: {len(out)} starting points = {int((out.kind == 'da').sum())} DA points "
          f"+ {len(blk)} block points in {blk.DAUID.nunique()} large DAs")
    print(f"population covered: {int(out.weight.sum()):,} (DA total {int(da.pop2021.sum()):,}); "
          f"large DAs where block populations differ from the DA total by more than 5 people: {int((gap > 5).sum())}")


if __name__ == "__main__":
    main()
