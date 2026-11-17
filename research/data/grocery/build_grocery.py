"""Build a point layer of full-service grocery stores in the GTA from OpenStreetMap.

Re-runnable. Steps:
  1. Download the StatCan 2021 census division cartographic boundary file (if missing).
  2. Filter gta.osm.pbf with osmium to shop-related features and export as GeoJSON seq.
  3. Apply the inclusion rule (see SOURCE.md and classify() below).
  4. Turn areas into centroids, remove duplicates (node inside the polygon of the same
     store, or the same store mapped twice within 100 m).
  5. Clip to the five GTA census divisions (3518, 3519, 3520, 3521, 3524).
  6. Write grocery_gta.gpkg (EPSG:4326) plus CSVs for review and chain counts.

Run with: research/.venv/bin/python research/data/grocery/build_grocery.py
"""
import json
import re
import subprocess
import unicodedata
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import shape

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"
RAW.mkdir(exist_ok=True)
REPO = HERE.parents[2]
PBF = REPO / "gta.osm.pbf"
OSMIUM = "/opt/homebrew/bin/osmium"

CD_URL = ("https://www12.statcan.gc.ca/census-recensement/2021/geo/sip-pis/"
          "boundary-limites/files-fichiers/lcd_000b21a_e.zip")
CD_ZIP = RAW / "lcd_000b21a_e.zip"
CD_SHP = RAW / "lcd" / "lcd_000b21a_e.shp"
GTA_CDS = ["3518", "3519", "3520", "3521", "3524"]
WORK_CRS = "EPSG:3347"  # StatCan Lambert, metres

# ---------------------------------------------------------------- inclusion rule
# Chains we treat as full-service grocery (matched on brand, else name).
CHAIN_PATTERNS = [
    ("Loblaws", r"^loblaws?\b|^loblaws city market"),
    ("No Frills", r"no ?frills"),
    ("Real Canadian Superstore", r"real canadian superstore|^superstore$"),
    ("Fortinos", r"fortino"),
    ("Zehrs", r"zehrs"),
    ("Your Independent Grocer", r"independent grocer|valu-?mart"),
    ("Wholesale Club", r"wholesale club"),
    ("Metro", r"^metro( plus)?$|^metro\b(?!.*(station|pcs|by t-mobile))"),
    ("Food Basics", r"food basics"),
    ("Sobeys", r"sobeys"),
    ("FreshCo", r"fresh ?co\b"),
    ("Longo's", r"^longo'?s\b|^longos\b"),
    ("Foodland", r"^foodland"),
    ("Walmart", r"wal-?mart"),
    ("T&T", r"t ?& ?t|t and t supermarket"),
    ("Farm Boy", r"farm boy"),
    ("Costco", r"costco"),
    ("Whole Foods Market", r"whole foods"),
    ("Adonis", r"adonis"),
    ("H Mart", r"^h ?mart"),
    ("Starsky", r"starsky"),
    ("Pusateri's", r"pusateri"),
]

# shop=supermarket features that are not full-service grocery stores.
SUPERMARKET_EXCLUDE = re.compile(
    r"bulk barn|source bulk|bulk food|\brabba\b|dollar|pharma|drug ?mart|shoppers|"
    r"variety|convenience|gas bar|petro|esso|shell\b|circle k|mac'?s\b|7-eleven|"
    r"bakery|butcher|meat shop|spice|nuts\b|candy|liquor|lcbo|beer store|"
    r"low carb|kitchen express", re.I)

# shop=grocery/greengrocer: included only when the name says it is a supermarket-scale
# food store, or it is a known chain.
SUBSTANTIAL_NAME = re.compile(
    r"supermarket|super market|super ?mart|food ?mart|food market|fresh market|"
    r"foods? (centre|center|market)|farmers'? market|fine foods|food cooperative|"
    r"international foods|eataly|pusateri", re.I)
SMALL_NAME = re.compile(
    r"variety|halal meat|meat\b|spice|nuts|cheese|takeout|bakery|farm\b|farms\b|"
    r"orchard|blueberr|garden centre|produce$|importers|low carb|dried", re.I)
# greengrocers named "... Fruit Market" are mostly small produce shops: excluded.

# Features in these categories are only kept if they match a chain.
WHOLESALE_CHAINS = {"Costco", "Wholesale Club"}
DEPT_STORE_CHAINS = {"Walmart"}


def norm(s):
    if not isinstance(s, str) or not s:
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = s.lower().replace("’", "'")
    return re.sub(r"\s+", " ", s).strip()


def chain_of(brand, name):
    for txt in (brand, name):
        t = norm(txt)
        if not t:
            continue
        for label, pat in CHAIN_PATTERNS:
            if re.search(pat, t):
                return label
    return None


def classify(p):
    """Return (keep, category, rule) for one OSM feature's tags."""
    shop = p.get("shop")
    name = p.get("name") or ""
    brand = p.get("brand") or ""
    chain = chain_of(brand, name)
    label = f"{brand} {name}"
    if p.get("entrance"):
        return False, None, "entrance node, not a store"
    if shop == "supermarket":
        if SUPERMARKET_EXCLUDE.search(label) and chain is None:
            return False, None, "supermarket tag but specialty/convenience name"
        return True, "supermarket", "shop=supermarket"
    if shop == "wholesale":
        if chain in WHOLESALE_CHAINS:
            return True, "warehouse_club", "shop=wholesale, grocery warehouse chain"
        return False, None, "wholesale, not a grocery warehouse club"
    if shop == "department_store":
        if chain in DEPT_STORE_CHAINS:
            return True, "general_merchandise_with_grocery", "shop=department_store, Walmart"
        return False, None, "department store"
    if shop in ("grocery", "greengrocer"):
        if chain is not None and chain not in ("Walmart",):
            return True, "grocery_substantial", f"shop={shop}, known chain"
        if SUBSTANTIAL_NAME.search(name) and not SMALL_NAME.search(name):
            return True, "grocery_substantial", f"shop={shop}, supermarket-scale name"
        return False, None, f"shop={shop}, small or specialty"
    return False, None, "not a grocery tag"


# ---------------------------------------------------------------- steps
def get_cd():
    if not CD_SHP.exists():
        if not CD_ZIP.exists():
            print("downloading", CD_URL)
            with requests.get(CD_URL, stream=True, timeout=600) as r:
                r.raise_for_status()
                with open(CD_ZIP, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
        with zipfile.ZipFile(CD_ZIP) as z:
            z.extractall(RAW / "lcd")
    where = "CDUID IN (%s)" % ",".join(f"'{c}'" for c in GTA_CDS)
    cd = gpd.read_file(CD_SHP, where=where)
    cd["CDUID"] = cd["CDUID"].astype(str).str.zfill(4)
    assert sorted(cd["CDUID"]) == GTA_CDS, cd["CDUID"].tolist()
    return cd.to_crs(WORK_CRS)[["CDUID", "CDNAME", "geometry"]]


def extract_osm():
    pbf = RAW / "shops.osm.pbf"
    seq = RAW / "shops.geojsonseq"
    subprocess.run([OSMIUM, "tags-filter", "-O", "-o", str(pbf), str(PBF),
                    "nwr/shop=supermarket,grocery,greengrocer,wholesale,department_store"],
                   check=True)
    subprocess.run([OSMIUM, "export", "-O", "-f", "geojsonseq",
                    "--geometry-types=point,polygon", "-a", "type,id",
                    "-o", str(seq), str(pbf)], check=True)
    rows = []
    for line in open(seq, encoding="utf-8"):
        f = json.loads(line.lstrip("\x1e"))
        p = f["properties"]
        if "shop" not in p:
            continue
        rows.append({
            "osm_type": p["@type"], "osm_num": p["@id"],
            "osm_id": f"{p['@type'][0]}{p['@id']}",
            "name": p.get("name"), "brand": p.get("brand"), "shop": p.get("shop"),
            "entrance": p.get("entrance"), "tags": p, "geometry": shape(f["geometry"]),
        })
    return gpd.GeoDataFrame(rows, crs="EPSG:4326").to_crs(WORK_CRS)


def main():
    cd = get_cd()
    osm = extract_osm()
    print("OSM features with a matching shop tag:", len(osm))
    cls = osm["tags"].apply(classify)
    osm["keep"] = [c[0] for c in cls]
    osm["category"] = [c[1] for c in cls]
    osm["rule"] = [c[2] for c in cls]
    osm["chain"] = [chain_of(b, n) for b, n in zip(osm["brand"], osm["name"])]
    osm["is_area"] = osm.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    osm["area_m2"] = osm.geometry.area.where(osm["is_area"]).round(0)

    # restrict everything (kept and dropped) to the GTA so review files are relevant
    gta_union = cd.union_all()
    pts = osm.geometry.where(~osm["is_area"], osm.geometry.representative_point())
    osm = osm[pts.within(gta_union.buffer(500))].copy()

    dropped = osm[~osm["keep"]]
    kept = osm[osm["keep"]].copy()
    print("in GTA (500 m buffer): candidates", len(osm), "kept by rule", len(kept))

    # ---- dedup 1: node inside the polygon of the same store
    kept["key"] = [norm(c or b or n) for c, b, n in zip(kept["chain"], kept["brand"], kept["name"])]
    areas = kept[kept["is_area"]]
    nodes = kept[~kept["is_area"]]
    j = gpd.sjoin(nodes[["osm_id", "key", "geometry"]],
                  areas[["osm_id", "key", "geometry"]].buffer(0).to_frame("geometry")
                  .join(areas[["osm_id", "key"]]),
                  predicate="within", how="inner", lsuffix="n", rsuffix="a")
    same = j[(j["key_n"] == j["key_a"]) | (j["key_n"] == "") | (j["key_a"] == "")]
    dup1 = set(same["osm_id_n"])
    dedup_log = [{"dropped_osm_id": r.osm_id_n, "kept_osm_id": r.osm_id_a,
                  "reason": "node inside polygon of same store"} for r in same.itertuples()]
    kept = kept[~kept["osm_id"].isin(dup1)].copy()

    # ---- centroids for areas
    poly = kept.geometry.copy()
    cent = poly.centroid
    # a centroid can fall outside an odd-shaped polygon; use a point on the surface then
    use_rep = kept["is_area"] & ~cent.within(poly)
    kept["centroid_moved_inside"] = use_rep
    kept["geometry"] = poly.where(~kept["is_area"], cent)
    kept.loc[use_rep, "geometry"] = poly[use_rep].representative_point()
    print("area centroids moved inside polygon:", int(use_rep.sum()))

    # ---- dedup 2: same store key mapped twice within 100 m (prefer area, then more tags)
    kept["ntags"] = kept["tags"].apply(len)
    kept = kept.sort_values(["is_area", "ntags"], ascending=False).reset_index(drop=True)
    drop2 = set()
    sidx = kept.sindex
    for i, r in kept.iterrows():
        if r["osm_id"] in drop2 or not r["key"]:
            continue
        for k in sidx.query(r.geometry.buffer(100)):
            o = kept.iloc[k]
            if k != i and o["osm_id"] not in drop2 and o["key"] == r["key"] and k > i:
                drop2.add(o["osm_id"])
                dedup_log.append({"dropped_osm_id": o["osm_id"], "kept_osm_id": r["osm_id"],
                                  "reason": "same store name within 100 m"})
    kept = kept[~kept["osm_id"].isin(drop2)].copy()

    # ---- clip to census divisions (points up to 500 m outside the cartographic
    # shoreline, e.g. on waterfront fill, go to the nearest division)
    inside = gpd.sjoin(kept, cd, predicate="within", how="left").drop(columns="index_right")
    miss = inside["CDUID"].isna()
    if miss.any():
        near = gpd.sjoin_nearest(kept[miss.values], cd, max_distance=500, how="left")
        inside.loc[miss, ["CDUID", "CDNAME"]] = near[["CDUID", "CDNAME"]].values
    inside = inside[inside["CDUID"].notna()].copy()
    inside = inside.rename(columns={"CDUID": "cduid", "CDNAME": "cdname", "shop": "shop_tag"})

    out = inside[["osm_id", "name", "brand", "shop_tag", "chain", "category", "rule",
                  "is_area", "area_m2", "cduid", "cdname", "geometry"]].copy()
    out["cduid"] = out["cduid"].astype(str)
    out = out.sort_values(["cduid", "chain", "name"], na_position="last").to_crs("EPSG:4326")
    gpkg = HERE / "grocery_gta.gpkg"
    if gpkg.exists():
        gpkg.unlink()
    out.to_file(gpkg, layer="grocery_gta", driver="GPKG")
    print("wrote", gpkg, len(out))

    # review tables
    o2 = out.copy()
    o2["lon"] = o2.geometry.x.round(6)
    o2["lat"] = o2.geometry.y.round(6)
    o2.drop(columns="geometry").to_csv(HERE / "grocery_gta.csv", index=False)
    d = dropped.to_crs("EPSG:4326")
    d = d.assign(lon=d.geometry.representative_point().x.round(6),
                 lat=d.geometry.representative_point().y.round(6))
    d[["osm_id", "name", "brand", "shop", "rule", "lon", "lat"]].sort_values(
        ["shop", "name"]).to_csv(HERE / "grocery_excluded_review.csv", index=False)
    pd.DataFrame(dedup_log).to_csv(HERE / "grocery_dedup_log.csv", index=False)

    counts = (out.assign(chain=out["chain"].fillna("(independent / other)"))
              .pivot_table(index="chain", columns="cdname", values="osm_id",
                           aggfunc="count", fill_value=0, margins=True, margins_name="GTA total"))
    counts.to_csv(HERE / "grocery_chain_counts_osm.csv")
    print(counts.to_string())
    print(out.groupby(["category"]).size().to_string())
    print("dedup dropped:", len(dedup_log))


if __name__ == "__main__":
    main()
