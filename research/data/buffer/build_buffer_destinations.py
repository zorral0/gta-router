"""Destinations and population in the 40 km buffer, for Phase 3 scoring.

Trips start only inside the GTA, but they can end outside it. This script
builds everything a trip can reach inside the routing map
(gta_buffer_40km.geojson), so GTA neighbourhoods near the edge are not
penalized:

  grocery_buffer.csv   grocery stores OUTSIDE the GTA, inside the buffer,
                       chosen by the same automatic rules as
                       data/grocery/build_grocery.py (no hand audit; disclosed).
                       Rabba is kept, following the owner's audit rule.
  ed_buffer.csv        hospital emergency departments OUTSIDE the GTA, inside
                       the buffer, chosen by the same rules as
                       data/healthcare/build_healthcare.py (MOH + ODHF lists,
                       Ontario Health ED-reporting list).
  blocks_buffer.csv    every populated 2021 dissemination block inside the
                       buffer (GTA included): DBUID, DAUID, pop, lat, lon,
                       in_gta. Block point = representative point.
  jobs_zones.csv       TTS 2022 jobs (full time + part time, usual workplace
                       outside the home) by TTS zone, zones touching the buffer.
  jobs_points.npz      the jobs spread evenly over each zone's area on a
                       100 m lattice (lat, lon, weight), so a zone counts in
                       proportion to the share of its area that is reached.
                       Zones too small for a lattice point get one point.

Run: research/.venv/bin/python research/data/buffer/build_buffer_destinations.py
"""
import importlib.util
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import shape

HERE = Path(__file__).resolve().parent
DATA = HERE.parent
REPO = DATA.parents[1]
BUFFER_PBF = REPO / "engine" / "research-buffer" / "buffer.osm.pbf"
OSMIUM = "/opt/homebrew/bin/osmium"
GTA_CDS = {"3518", "3519", "3520", "3521", "3524"}
METRIC = "EPSG:3161"  # NAD83 / Ontario MNR Lambert, metres
LATTICE_M = 100


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def buffer_polygon():
    g = gpd.read_file(HERE / "gta_buffer_40km.geojson")
    return g.to_crs(METRIC).geometry.iloc[0]


def gta_polygon():
    g = gpd.read_file(DATA / "census" / "gta_boundary.gpkg").to_crs(METRIC)
    return g.union_all()


# ------------------------------------------------------------------ grocery
def grocery(buf, gta):
    gb = load_module("build_grocery", DATA / "grocery" / "build_grocery.py")
    raw = HERE / "raw"
    raw.mkdir(exist_ok=True)
    pbf, seq = raw / "shops_buffer.osm.pbf", raw / "shops_buffer.geojsonseq"
    if not seq.exists():
        subprocess.run([OSMIUM, "tags-filter", "-O", "-o", str(pbf), str(BUFFER_PBF),
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
        rows.append({"osm_id": f"{p['@type'][0]}{p['@id']}", "name": p.get("name"),
                     "brand": p.get("brand"), "shop": p.get("shop"), "tags": p,
                     "geometry": shape(f["geometry"])})
    osm = gpd.GeoDataFrame(rows, crs="EPSG:4326").to_crs(METRIC)
    cls = osm["tags"].apply(gb.classify)
    osm["keep"] = [c[0] for c in cls]
    osm["category"] = [c[1] for c in cls]
    osm["chain"] = [gb.chain_of(b, n) for b, n in zip(osm["brand"], osm["name"])]
    # The owner's audit rule (2026-09-14): Rabba counts as an everyday grocer.
    rabba = osm["name"].fillna("").str.contains(r"\brabba\b", case=False) & (osm["shop"] == "supermarket")
    osm.loc[rabba, ["keep", "category"]] = [True, "supermarket"]
    osm = osm[osm["keep"]].copy()
    osm["is_area"] = osm.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    pt = osm.geometry.where(~osm["is_area"], osm.geometry.representative_point())
    osm["geometry"] = pt
    # outside the GTA (the GTA list already claims stores up to 500 m outside), inside the buffer
    osm = osm[osm.within(buf) & ~osm.within(gta.buffer(500))].copy()
    # same store mapped twice within 100 m (node + polygon): keep the polygon
    osm["key"] = [gb.norm(c or b or n) for c, b, n in zip(osm["chain"], osm["brand"], osm["name"])]
    osm = osm.sort_values("is_area", ascending=False).reset_index(drop=True)
    drop = set()
    sidx = osm.sindex
    for i, r in osm.iterrows():
        if i in drop:
            continue
        for k in sidx.query(r.geometry.buffer(100)):
            if k > i and (osm.at[k, "key"] == r["key"] or not osm.at[k, "key"] or not r["key"]):
                drop.add(k)
    osm = osm.drop(index=sorted(drop)).to_crs(4326)
    out = pd.DataFrame({"osm_id": osm.osm_id, "name": osm.name, "chain": osm.chain,
                        "category": osm.category, "lat": osm.geometry.y.round(6),
                        "lon": osm.geometry.x.round(6)})
    out.to_csv(HERE / "grocery_buffer.csv", index=False)
    print(f"grocery_buffer.csv: {len(out)} stores outside the GTA ({len(drop)} duplicates dropped)")


# ------------------------------------------------------------------- EDs
def emergency(buf):
    hc = load_module("build_healthcare", DATA / "healthcare" / "build_healthcare.py")
    cd = hc.load_cds()
    parts = []
    for g in (hc.apply(hc.load_odhf(), hc.classify_odhf), hc.apply(hc.load_moh(), hc.classify_moh)):
        g = g.to_crs(hc.METRIC)
        j = gpd.sjoin(g[["src_id", "geometry"]], cd, predicate="within", how="left")
        j = j[~j.index.duplicated()]
        g["CDUID"], g["CDNAME"] = j.CDUID, j.CDNAME
        g = g[g["type"].isin([hc.HE, hc.UC]) & ~g.CDUID.isin(GTA_CDS)]
        g = g[g.to_crs(METRIC).within(buf)]
        parts.append(g[["src", "src_id", "name", "raw_type", "type", "reason", "geometry", "CDUID", "CDNAME"]])
    allp = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), geometry="geometry", crs=hc.METRIC)
    out = hc.dedupe(allp)
    out = out[~((out.sources == "odhf") & out["type"].isin([hc.HE, hc.UC]))]  # stale ODHF-only sites
    out = out.to_crs(4326)
    # The Ontario Health list names "St. Joseph's Health Care System-Hamilton";
    # its ED is at the Charlton Campus (the King and West 5th sites have none),
    # but the token match misses the MOH site name. Checked by hand 2026-10-16.
    charlton = out.name.str.contains("Charlton Campus", case=False, na=False)
    out.loc[charlton, "type"] = hc.HE
    res = pd.DataFrame({"name": out.name, "type": out["type"], "sources": out.sources,
                        "cdname": out.cdname, "lat": out.geometry.y.round(6), "lon": out.geometry.x.round(6)})
    res.sort_values(["type", "cdname", "name"]).to_csv(HERE / "ed_buffer_review.csv", index=False)
    ed = res[res["type"] == hc.HE]
    ed.to_csv(HERE / "ed_buffer.csv", index=False)
    print(f"ed_buffer.csv: {len(ed)} emergency departments outside the GTA "
          f"(review list with urgent care: ed_buffer_review.csv, {len(res)} rows)")


# ---------------------------------------------------------------- blocks
def blocks(buf):
    craw = DATA / "census" / "raw"
    zf = zipfile.ZipFile(craw / "2021_92-151_X.zip")
    name = [n for n in zf.namelist() if n.lower().endswith(".csv")][0]
    pops = []
    for ch in pd.read_csv(zf.open(name), encoding="latin-1", chunksize=200_000, dtype=str):
        cols = {c.upper(): c for c in ch.columns}
        pr = [c for c in ch.columns if c.upper().startswith("PRUID")][0]
        ch = ch[ch[pr] == "35"]
        dbu = [c for c in ch.columns if c.upper().startswith("DBUID")][0]
        dau = [c for c in ch.columns if c.upper().startswith("DAUID")][0]
        dbp = [c for c in ch.columns if c.upper().startswith("DBPOP")][0]
        pops.append(ch[[dbu, dau, dbp]].rename(columns={dbu: "DBUID", dau: "DAUID", dbp: "pop"}))
    bp = pd.concat(pops).drop_duplicates("DBUID")
    bp["pop"] = pd.to_numeric(bp["pop"], errors="coerce").fillna(0).astype(int)
    bp = bp[bp["pop"] > 0]
    bz = craw / "ldb_000b21a_e.zip"
    shp = [n for n in zipfile.ZipFile(bz).namelist() if n.lower().endswith(".shp")][0]
    geo = gpd.read_file(f"zip://{bz}!{shp}", where="PRUID = '35'")
    dbcol = [c for c in geo.columns if c.upper().startswith("DBUID")][0]
    geo = geo[geo[dbcol].isin(set(bp.DBUID))][[dbcol, "geometry"]].rename(columns={dbcol: "DBUID"})
    rep = gpd.GeoSeries(geo.geometry.representative_point(), crs=geo.crs)
    inside = rep.to_crs(METRIC).within(buf).values
    geo, rep = geo[inside], rep[inside].to_crs(4326)
    out = pd.DataFrame({"DBUID": geo.DBUID.values, "lat": rep.y.round(6).values, "lon": rep.x.round(6).values})
    out = out.merge(bp, on="DBUID")
    out["in_gta"] = out.DAUID.str[:4].isin(GTA_CDS).astype(int)
    out[["DBUID", "DAUID", "pop", "lat", "lon", "in_gta"]].to_csv(HERE / "blocks_buffer.csv", index=False)
    g = out[out.in_gta == 1]
    print(f"blocks_buffer.csv: {len(out)} populated blocks, {int(out['pop'].sum()):,} people "
          f"(GTA {len(g)} blocks, {int(g['pop'].sum()):,}; outside {int(out.loc[out.in_gta == 0, 'pop'].sum()):,})")


# ------------------------------------------------------------------- jobs
def read_tts_table(path):
    lines = open(path, encoding="utf-8").read().splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith(","))
    from io import StringIO
    return pd.read_csv(StringIO("\n".join(lines[start:])), index_col=0)


def jobs(buf):
    traw = DATA / "tts" / "raw"
    t = read_tts_table(traw / "tts2022_workers_zone_employment.csv")
    t = t[pd.to_numeric(t.index, errors="coerce").notna()]
    t.index = t.index.astype(int)
    t["jobs"] = t["Full time"] + t["Part time"]
    z = gpd.read_file(traw / "zones2022" / "tts2022_v1_1_shapefile.shp").to_crs(METRIC)
    z["geometry"] = z.geometry.buffer(0)
    z = z[z.intersects(buf)].copy()
    z = z.merge(t[["jobs"]], left_on="TTS2022", right_index=True, how="left")
    z["jobs"] = z["jobs"].fillna(0)
    z["area_km2"] = z.geometry.area / 1e6
    z["share_in_buffer"] = z.geometry.intersection(buf).area / z.geometry.area
    z.drop(columns="geometry").to_csv(HERE / "jobs_zones.csv", index=False)
    lats, lons, wts, zid = [], [], [], []
    tf = gpd.GeoSeries([], crs=METRIC)
    for r in z[z.jobs > 0].itertuples():
        g = r.geometry
        x0, y0, x1, y1 = g.bounds
        xs = np.arange(np.floor(x0 / LATTICE_M) * LATTICE_M + LATTICE_M / 2, x1, LATTICE_M)
        ys = np.arange(np.floor(y0 / LATTICE_M) * LATTICE_M + LATTICE_M / 2, y1, LATTICE_M)
        X, Y = np.meshgrid(xs, ys)
        X, Y = X.ravel(), Y.ravel()
        import shapely
        m = shapely.contains_xy(g, X, Y)
        X, Y = X[m], Y[m]
        if len(X) == 0:
            p = g.representative_point()
            X, Y = np.array([p.x]), np.array([p.y])
        lats.append(Y); lons.append(X)
        wts.append(np.full(len(X), r.jobs / len(X)))
        zid.append(np.full(len(X), r.TTS2022))
    X, Y = np.concatenate(lons), np.concatenate(lats)
    pts = gpd.GeoSeries(gpd.points_from_xy(X, Y), crs=METRIC).to_crs(4326)
    w, zz = np.concatenate(wts), np.concatenate(zid)
    keep = gpd.GeoSeries(gpd.points_from_xy(X, Y), crs=METRIC).within(buf).values
    np.savez_compressed(HERE / "jobs_points.npz", lat=pts.y.values[keep], lon=pts.x.values[keep],
                        weight=w[keep], zone=zz[keep])
    gtaz = z[z.Reg_no.between(1, 5)]
    print(f"jobs_zones.csv: {len(z)} zones touching the buffer, {z.jobs.sum():,.0f} jobs "
          f"(GTA regions 1-5: {gtaz.jobs.sum():,.0f}); jobs_points.npz: {int(keep.sum()):,} points, "
          f"{w[keep].sum():,.0f} jobs inside the buffer")
    print(z.groupby("Reg_name").jobs.sum().sort_values(ascending=False).round(0).to_string())


if __name__ == "__main__":
    buf, gta = buffer_polygon(), gta_polygon()
    steps = sys.argv[1:] or ["grocery", "ed", "blocks", "jobs"]
    if "grocery" in steps:
        grocery(buf, gta)
    if "ed" in steps:
        emergency(buf)
    if "blocks" in steps:
        blocks(buf)
    if "jobs" in steps:
        jobs(buf)
