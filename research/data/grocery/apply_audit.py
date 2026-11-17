"""Apply the manual grocery audit on top of build_grocery.py output.

Run after build_grocery.py. Reads grocery_gta.csv (automatic rules) and
grocery_audit_draft.csv (reviewed decisions for excluded stores), adds the
stores marked keep, removes duplicates, and writes grocery_gta_v1.csv/.gpkg,
the store list used by the study. The automatic outputs are left untouched.
"""
import re
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

HERE = Path(__file__).parent
UTM = "EPSG:32617"


GENERIC = {"grocery", "groceries", "grocer", "grocers", "meat", "meats", "fish", "market", "markets",
           "fruit", "fruits", "vegetables", "food", "foods", "fresh", "halal", "farm", "farms", "store",
           "supermarket", "super", "mart", "the", "and", "ltd", "inc", "fine", "international"}


def tokens(s):
    """Distinctive name words; generic grocery words and missing names give an empty set."""
    if not isinstance(s, str):
        return set()
    return {t for t in re.findall(r"[a-z0-9]+", s.lower()) if len(t) > 2 and t not in GENERIC}


def same_store(a_name, b_name, dist_m):
    """Same place: identical distinctive words nearby, or no usable name and almost the same spot."""
    ta, tb = tokens(a_name), tokens(b_name)
    if ta and tb:
        return dist_m <= 100 and bool(ta & tb)
    return dist_m <= 30


def main():
    base = pd.read_csv(HERE / "grocery_gta.csv", dtype={"osm_id": str, "cduid": str})
    audit = pd.read_csv(HERE / "grocery_audit_draft.csv", dtype={"osm_id": str})
    excl = pd.read_csv(HERE / "grocery_excluded_review.csv", dtype={"osm_id": str})
    unsure = audit[audit.decision.eq("unsure")]
    if len(unsure):
        raise SystemExit(f"{len(unsure)} audit rows still unsure: {unsure.name.tolist()}")
    keep = audit[audit.decision.eq("keep")].merge(excl[["osm_id", "brand", "lon", "lat"]], on="osm_id", how="left")

    g_base = gpd.GeoDataFrame(base, geometry=[Point(x, y) for x, y in zip(base.lon, base.lat)], crs=4326).to_crs(UTM)
    g_keep = gpd.GeoDataFrame(keep, geometry=[Point(x, y) for x, y in zip(keep.lon, keep.lat)], crs=4326).to_crs(UTM)

    added, dup_log = [], []
    for r in g_keep.itertuples():
        dist = g_base.geometry.distance(r.geometry)
        near = g_base[dist <= 100]
        clash = [n for n in near.itertuples()
                 if n.osm_id == r.osm_id or same_store(n.name, r.name, n.geometry.distance(r.geometry))]
        clash += [a for a in added if same_store(a.name, r.name, a.geometry.distance(r.geometry))]
        if clash:
            dup_log.append((r.osm_id, r.name, clash[0].name))
            continue
        added.append(r)

    b = gpd.read_file(HERE.parent / "census" / "gta_boundary.gpkg").to_crs(UTM)
    new = gpd.GeoDataFrame(
        {"osm_id": [a.osm_id for a in added], "name": [a.name for a in added],
         "brand": [a.brand for a in added], "shop_tag": [a.shop for a in added],
         "category": "Audit keep", "rule": [f"manual audit: {a.reason}" for a in added],
         "lon": [a.lon for a in added], "lat": [a.lat for a in added]},
        geometry=[a.geometry for a in added], crs=UTM)
    cd_cols = [c for c in b.columns if c.lower() in ("cduid", "cdname")]
    new = gpd.sjoin(new, b[cd_cols + ["geometry"]], how="left", predicate="within").drop(columns="index_right")
    new.columns = [c.lower() if c.lower() in ("cduid", "cdname") else c for c in new.columns]

    out = pd.concat([base, pd.DataFrame(new.drop(columns="geometry"))], ignore_index=True)
    out["source"] = ["automatic rules"] * len(base) + ["manual audit 2026-09-14"] * len(new)
    out.to_csv(HERE / "grocery_gta_v1.csv", index=False)
    gpd.GeoDataFrame(out, geometry=[Point(x, y) for x, y in zip(out.lon, out.lat)], crs=4326).to_file(
        HERE / "grocery_gta_v1.gpkg", layer="grocery_gta_v1", driver="GPKG")
    pd.DataFrame(dup_log, columns=["osm_id", "name", "duplicate_of"]).to_csv(HERE / "grocery_audit_duplicates.csv", index=False)

    print(f"automatic: {len(base)}  audit keeps: {len(keep)}  added: {len(new)}  skipped as duplicates: {len(dup_log)}  total: {len(out)}")
    for d in dup_log:
        print("  duplicate:", d[1], "->", d[2])
    print(out.groupby("cdname").size().to_string())


if __name__ == "__main__":
    main()
