"""Build GTA subsets of Statistics Canada's Spatial Access Measures (SAM),
public transit peak and off-peak, for both published vintages (2022 and 2024).

Outputs (in research/data/sam/):
  sam_transit_db_gta.csv  one row per 2021 dissemination block in CDs 3518/3519/3520/3521/3524
  sam_transit_da_gta.csv  one row per 2021 dissemination area, population-weighted from DBs

Re-run:  research/.venv/bin/python research/data/sam/build_sam.py
Raw downloads are cached in research/data/sam/raw/ (git-ignored).
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import requests

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"
RAW.mkdir(exist_ok=True)

GTA_CDS = {"3518": "Durham", "3519": "York", "3520": "Toronto", "3521": "Peel", "3524": "Halton"}

SAM_BASE = "https://www150.statcan.gc.ca/n1/pub/27-26-0001/2023001/zip/"
DOWNLOADS = {
    "sam-msa2022-eng.zip": SAM_BASE + "sam-msa2022-eng.zip",
    "sam-msa2024-eng.zip": SAM_BASE + "sam-msa2024-eng.zip",
    "2021_92-151_X.zip": "https://www12.statcan.gc.ca/census-recensement/2021/geo/aip-pia/"
    "attribute-attribs/files-fichiers/2021_92-151_X.zip",
}
# member path prefix inside each SAM zip
SAM_VINTAGES = {"2022": ("sam-msa2022-eng.zip", "sam-msa-eng/"), "2024": ("sam-msa2024-eng.zip", "")}
PERIODS = {"peak": "acs_public_transit_peak.csv", "offpeak": "acs_public_transit_offpeak.csv"}

# SAM column -> short name used in our outputs
IDX_COLS = {
    "acs_idx_emp": "emp",   # employment
    "acs_idx_hf": "hf",     # healthcare facilities
    "acs_idx_ef": "ef",     # public primary and secondary (K-12) education
    "acs_idx_psef": "psef", # public post-secondary education
    "acs_idx_srf": "srf",   # sports and recreation facilities
    "acs_idx_caf": "caf",   # culture and arts facilities
    "acs_idx_ccf": "ccf",   # child care facilities (2024 vintage only)
}
GS_COLS = {"acs_lvl_gs-1": "gs1_min", "acs_lvl_gs-3": "gs3_min", "acs_lvl_gs-5": "gs5_min"}


def fetch(name: str) -> Path:
    path = RAW / name
    if path.exists() and path.stat().st_size > 0 and zipfile.is_zipfile(path):
        return path
    print(f"downloading {DOWNLOADS[name]}")
    with requests.get(DOWNLOADS[name], stream=True, timeout=600) as r:
        r.raise_for_status()
        with open(path, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    if not zipfile.is_zipfile(path):
        raise RuntimeError(f"{name} is not a zip file (StatCan may have returned an HTML page)")
    return path


def read_csv_bytes(b: bytes, **kw) -> pd.DataFrame:
    # 2024 files are UTF-8 with a BOM; 2022 files are Windows-1252 (accented CSD names)
    try:
        text = b.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = b.decode("cp1252")
    return pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False, **kw)


def load_geo_attributes() -> pd.DataFrame:
    z = zipfile.ZipFile(fetch("2021_92-151_X.zip"))
    member = z.namelist()[0]
    cols = {
        "DBUID_IDIDU": "DBUID",
        "DAUID_ADIDU": "DAUID",
        "CDUID_DRIDU": "CDUID",
        "CDNAME_DRNOM": "CDNAME",
        "CSDUID_SDRIDU": "CSDUID",
        "CSDNAME_SDRNOM": "CSDNAME",
        "DBPOP2021_IDPOP2021": "DBPOP2021",
    }
    with z.open(member) as fh:
        geo = pd.read_csv(fh, dtype=str, usecols=list(cols), encoding="latin-1", keep_default_na=False)
    geo = geo.rename(columns=cols)
    geo = geo[geo.CDUID.isin(GTA_CDS)].copy()
    geo["DBPOP2021"] = pd.to_numeric(geo.DBPOP2021, errors="coerce")
    return geo


def load_sam(vintage: str, period: str) -> pd.DataFrame:
    zname, prefix = SAM_VINTAGES[vintage]
    z = zipfile.ZipFile(fetch(zname))
    df = read_csv_bytes(z.read(prefix + PERIODS[period]))
    df["DBUID"] = df.DBUID.str.strip().str.zfill(11)
    df = df[df.DBUID.str[:4].isin(GTA_CDS)].copy()
    if df.DBUID.duplicated().any():
        raise RuntimeError(f"duplicate DBUIDs in SAM {vintage} {period}")
    out = pd.DataFrame({"DBUID": df.DBUID})
    pre = f"s{vintage}_{period}_"
    # ".." in an index column marks a DB with no published value at all
    idx_present = [c for c in IDX_COLS if c in df.columns]
    missing_all = (df[idx_present] == "..").all(axis=1)
    out[pre + "missing"] = missing_all.astype(int)
    for c in idx_present:
        out[pre + IDX_COLS[c]] = pd.to_numeric(df[c].where(df[c] != ".."), errors="coerce")
    for c, short in GS_COLS.items():
        v = pd.to_numeric(df[c].where(df[c] != ".."), errors="coerce")
        out[pre + short] = v
        # 1 = nth store reached within SAM's cut-off, 0 = not reached, blank = DB has no SAM values
        reached = v.notna().astype(float)
        reached[missing_all.values] = np.nan
        out[pre + short.replace("_min", "_reached")] = reached
    return out


def weighted_da(db: pd.DataFrame, value_cols: list[str], reached_cols: list[str]) -> pd.DataFrame:
    rows = []
    for dauid, g in db.groupby("DAUID", sort=True):
        pop = g.DBPOP2021.fillna(0).to_numpy(float)
        rec = {
            "DAUID": dauid,
            "CDUID": g.CDUID.iloc[0],
            "CDNAME": g.CDNAME.iloc[0],
            "CSDUID": g.CSDUID.iloc[0],
            "CSDNAME": g.CSDNAME.iloc[0],
            "da_pop2021_from_db": pop.sum(),
            "n_db": len(g),
            "n_db_with_pop": int((pop > 0).sum()),
            "weight_method": "population" if pop.sum() > 0 else "unweighted_zero_pop",
        }
        for col in value_cols:
            v = g[col].to_numpy(float)
            ok = ~np.isnan(v)
            if pop.sum() > 0:
                w = pop * ok
                rec[col] = float((v[ok] * pop[ok]).sum() / w.sum()) if w.sum() > 0 else np.nan
                rec[col + "_popcov"] = float(w.sum() / pop.sum())
            else:
                rec[col] = float(v[ok].mean()) if ok.any() else np.nan
                rec[col + "_popcov"] = np.nan
        for col in reached_cols:
            r = g[col].to_numpy(float)
            ok = ~np.isnan(r)
            if pop.sum() > 0:
                rec[col + "_popshare"] = float((r[ok] * pop[ok]).sum() / pop.sum())
            else:
                rec[col + "_popshare"] = float(r[ok].mean()) if ok.any() else np.nan
        rows.append(rec)
    return pd.DataFrame(rows)


def main() -> None:
    geo = load_geo_attributes()
    print(f"geographic attribute file: {len(geo)} GTA DBs, pop {geo.DBPOP2021.sum():,.0f}")

    db = geo[["DBUID", "DAUID", "CDUID", "CDNAME", "CSDUID", "CSDNAME", "DBPOP2021"]].copy()
    for vintage in SAM_VINTAGES:
        for period in PERIODS:
            s = load_sam(vintage, period)
            only_geo = set(db.DBUID) - set(s.DBUID)
            only_sam = set(s.DBUID) - set(db.DBUID)
            print(f"SAM {vintage} {period}: {len(s)} GTA DBs; in attribute file but not SAM: "
                  f"{sorted(only_geo)[:5]} ({len(only_geo)}); in SAM but not attribute file: {len(only_sam)}")
            db = db.merge(s, on="DBUID", how="left")
            db[f"s{vintage}_{period}_in_file"] = db[f"s{vintage}_{period}_missing"].notna().astype(int)

    # checks that the ID columns kept their leading zeros
    assert db.DBUID.str.len().eq(11).all() and db.DAUID.str.len().eq(8).all()
    assert db.DBUID.str[:8].eq(db.DAUID).all()

    db = db.sort_values("DBUID")
    db.to_csv(HERE / "sam_transit_db_gta.csv", index=False, float_format="%.6g")
    print(f"wrote sam_transit_db_gta.csv: {len(db)} rows, {db.shape[1]} columns")

    value_cols = [c for c in db.columns if c.startswith("s20") and
                  (c.split("_", 2)[2] in IDX_COLS.values() or c.endswith("_min"))]
    reached_cols = [c for c in db.columns if c.endswith("_reached")]
    da = weighted_da(db, value_cols, reached_cols)
    da.to_csv(HERE / "sam_transit_da_gta.csv", index=False, float_format="%.6g")
    print(f"wrote sam_transit_da_gta.csv: {len(da)} rows, {da.shape[1]} columns; "
          f"DAs with zero DB population: {(da.weight_method != 'population').sum()}")

    # quick summaries for SOURCE.md
    print("DBs by CD:", db.groupby("CDUID").size().to_dict())
    print("DAs by CD:", da.groupby("CDUID").size().to_dict())
    for v in SAM_VINTAGES:
        for p in PERIODS:
            m = db[f"s{v}_{p}_missing"]
            print(f"  {v} {p}: DBs with no SAM values '..': {int((m == 1).sum())} "
                  f"(pop {db.loc[m == 1, 'DBPOP2021'].sum():,.0f}); not in file: {int(m.isna().sum())}")
    corr = db[["s2022_peak_emp", "s2024_peak_emp", "s2024_offpeak_emp"]].corr(method="spearman")
    print("Spearman DB employment index:\n", corr.round(3))
    print(da[[c for c in da.columns if c.endswith(("_emp", "_hf"))]].describe().round(4).T)


if __name__ == "__main__":
    main()
