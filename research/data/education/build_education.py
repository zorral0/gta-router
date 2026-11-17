"""
Build education_gta.gpkg for the GTA transit gaps study.

Reads raw data already downloaded into raw/ (see SOURCE.md for exact
provenance of every file) and produces one point layer with columns:
    id, name, type, operator_or_board, is_private, sources, cdname, geometry

type is one of: secondary_school, post_secondary_campus, public_library_branch

Re-runnable: run this script again any time raw/ changes; it always
rewrites education_gta.gpkg from scratch.

Usage:
    research/.venv/bin/python build_education.py
"""

import csv
import hashlib
import json
import os
import re
import sys

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point, shape
from shapely.geometry.base import BaseGeometry


def _to_point(geom_dict):
    """OSM extracts sometimes give a school/library as a way (polygon) or
    even a multipolygon. Convert anything non-point to its centroid."""
    geom = shape(geom_dict)
    if geom.geom_type != "Point":
        geom = geom.centroid
    return geom
from shapely.ops import unary_union

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "raw")
sys.path.insert(0, HERE)
from _xlsx_reader import read_xlsx_sheet  # noqa: E402

CD_CODES = {"3518", "3519", "3520", "3521", "3524"}

# Cities we treat as inside the GTA study area when a dataset only gives a
# city/town name and no coordinates to spatially filter with. Not used for
# anything that has lat/long -- those are always filtered against the real
# CD polygons below.
GTA_TOWNS = {
    "toronto", "north york", "etobicoke", "scarborough", "york", "east york",
    "mississauga", "brampton", "caledon",
    "vaughan", "markham", "richmond hill", "newmarket", "aurora",
    "king city", "king", "east gwillimbury", "holland landing",
    "georgina", "keswick", "sutton west",
    "whitchurch-stouffville", "stouffville",
    "oshawa", "whitby", "ajax", "pickering", "clarington", "bowmanville",
    "courtice", "uxbridge", "scugog", "port perry", "brock", "beaverton",
    "cannington",
    "oakville", "burlington", "milton", "halton hills", "georgetown", "acton",
}


def make_id(*parts):
    h = hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()
    return h[:16]


def load_cd_polygons():
    """Load the 5 census divisions, reprojected to EPSG:4326."""
    gdf = gpd.read_file(os.path.join(RAW, "cd", "lcd_000a21a_e.shp"))
    gdf["CDUID"] = gdf["CDUID"].astype(str).str.zfill(4)
    gdf = gdf[gdf["CDUID"].isin(CD_CODES)].to_crs(4326)
    return gdf[["CDUID", "CDNAME", "geometry"]].reset_index(drop=True)


def assign_cdname(points_gdf, cd_gdf):
    """Spatial join to find which CD each point falls in; drop points outside all five."""
    joined = gpd.sjoin(points_gdf, cd_gdf, how="left", predicate="within")
    joined = joined.dropna(subset=["CDNAME"])
    joined = joined.rename(columns={"CDNAME": "cdname"})
    joined = joined.drop(columns=[c for c in ["index_right", "CDUID"] if c in joined.columns])
    return joined


# ---------------------------------------------------------------------------
# 1. Secondary schools
# ---------------------------------------------------------------------------

def load_sif_secondary():
    """Public/Catholic/Protestant-separate secondary schools from the Ontario
    School Information Finder (SIF) file. SIF has no private schools and no
    combined elem/sec levels in the GTA boards (checked: Grade Range never
    spans both elementary and secondary grades in this file)."""
    path = os.path.join(RAW, "sif_2024_25_en.xlsx")
    rows = read_xlsx_sheet(path)
    header = [rows[0][0].get(i) for i in range(rows[0][1] + 1)]
    idx = {h: i for i, h in enumerate(header)}

    recs = []
    for rowdata, maxcol in rows[1:]:
        def g(col):
            return rowdata.get(idx[col]) if col in idx else None

        level = (g("School Level") or "").strip()
        if level != "Secondary":
            continue
        lat, lon = g("Latitude"), g("Longitude")
        if not lat or not lon:
            continue
        try:
            lat, lon = float(lat), float(lon)
        except (TypeError, ValueError):
            continue
        recs.append({
            "name": (g("School Name") or "").strip(),
            "type": "secondary_school",
            "operator_or_board": (g("Board Name") or "").strip(),
            "is_private": False,
            "sources": "SIF 2024-25 (Ontario school information finder)",
            "geometry": Point(lon, lat),
        })
    return recs


def load_osm_private_secondary():
    """Private secondary schools from OSM (SIF has no private schools).
    Filters amenity=school, operator:type=private, isced:level containing 3
    (secondary) or a combined range that includes 3 (e.g. '0;1;2;3')."""
    path = os.path.join(RAW, "osm_schools.geojsonseq")
    recs = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            props = d.get("properties", {})
            if props.get("amenity") != "school":
                continue
            if props.get("operator:type") != "private":
                continue
            lvl = (props.get("isced:level") or "")
            levels = [x.strip() for x in lvl.split(";") if x.strip()]
            if "3" not in levels:
                continue
            name = props.get("name")
            if not name:
                continue
            recs.append({
                "name": name,
                "type": "secondary_school",
                "operator_or_board": props.get("operator") or "",
                "is_private": True,
                "sources": "OpenStreetMap (gta.osm.pbf extract), operator:type=private, isced:level includes 3",
                "geometry": _to_point(d["geometry"]),
            })
    return recs


# ---------------------------------------------------------------------------
# 2. Post-secondary campuses
# ---------------------------------------------------------------------------


def load_odef_postsecondary():
    """Post-secondary campuses in Ontario from Statistics Canada's ODEF
    v2.1. ISCED4Plus == '1' is ODEF's own flag for "post-secondary
    non-tertiary and above" and is a cleaner filter than Facility_Type:
    it also catches the 222 Ontario "Private Institution" rows (private
    career colleges), which the Facility_Type-only filter used in an
    earlier draft of this script missed. Spatial filter to the 5 CDs
    happens after, in main()."""
    path = os.path.join(RAW, "odef", "ODEF_v2.1_EN", "ODEF_v2_1.csv")
    recs = []
    with open(path, encoding="latin-1") as f:
        r = csv.DictReader(f)
        for row in r:
            if row.get("Prov_Terr") != "ON":
                continue
            if row.get("ISCED4Plus") != "1":
                continue
            lat, lon = row.get("Latitude"), row.get("Longitude")
            if not lat or not lon or lat == ".." or lon == "..":
                continue
            try:
                lat, lon = float(lat), float(lon)
            except ValueError:
                continue
            recs.append({
                "name": (row.get("Facility_Name") or "").strip(),
                "type": "post_secondary_campus",
                "operator_or_board": (row.get("Authority_Name") or "").strip(),
                "is_private": row.get("Facility_Type") == "Private Institution",
                "sources": "Statistics Canada ODEF v2.1",
                "geometry": Point(lon, lat),
            })
    return recs


# Large multi-campus institutions where OSM tags many individual buildings
# (libraries, faculties, federated colleges, athletic centres) as their own
# amenity=college/university node. ODEF already gives one point for the
# institution's main campus, so any OSM point naming one of these operators
# within `radius_m` of that anchor is a building on the SAME campus, not a
# distinct one, and is dropped. A point far enough away (e.g. UTSC, UTM,
# Glendon, a genuine out-of-town college's "Toronto Campus") survives.
POSTSEC_ANCHORS = {
    "university of toronto": (43.66820693, -79.40013339, 2500),
    "toronto metropolitan university": (43.6574729, -79.38011654, 900),
    "ryerson university": (43.6574729, -79.38011654, 900),
    "york university": (43.77425029, -79.49391309, 3000),
}

# OSM amenity=college is also used for driving/forklift schools, ambulance
# training, LINC (language) classes and similar non-post-secondary
# facilities that have no ISCED tag and no recognizable institution name.
POSTSEC_OSM_BLACKLIST = (
    "ambulance", "forklift", "pizza", " linc", "kollel", "worksafe",
)


def _haversine_m(lat1, lon1, lat2, lon2):
    from math import radians, sin, cos, asin, sqrt
    r = 6371000.0
    p1, p2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlmb = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(p1) * cos(p2) * sin(dlmb / 2) ** 2
    return 2 * r * asin(sqrt(a))


def load_osm_postsecondary():
    """University / college points from OSM, as a supplement to ODEF for
    real satellite campuses ODEF does not carry (e.g. McMaster's Toronto
    campus, whose ODEF record sits in Hamilton, outside the study area).
    Buildings on a campus ODEF already anchors, and non-institutional
    "college" tags, are filtered out here; true duplicates of the same
    campus are removed later by dedup()."""
    path = os.path.join(RAW, "osm_edu_lib.geojsonseq")
    recs = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            props = d.get("properties", {})
            am = props.get("amenity")
            if am not in ("university", "college"):
                continue
            name = props.get("name")
            if not name:
                continue
            low = name.lower()
            if any(b in low for b in POSTSEC_OSM_BLACKLIST):
                continue
            operator = props.get("operator") or ""
            geom = _to_point(d["geometry"])
            # Any OSM university/college point within radius of one of these
            # big-campus anchors is treated as a building on that campus
            # (federated college, faculty, library, athletics centre, etc.),
            # already represented by the ODEF point for the main institution
            # -- regardless of what its own `operator` tag says.
            on_a_big_campus = any(
                _haversine_m(geom.y, geom.x, alat, alon) <= radius_m
                for alat, alon, radius_m in POSTSEC_ANCHORS.values()
            )
            if on_a_big_campus:
                continue
            recs.append({
                "name": name,
                "type": "post_secondary_campus",
                "operator_or_board": operator,
                "is_private": props.get("operator:type") == "private",
                "sources": "OpenStreetMap (gta.osm.pbf extract), amenity=" + am,
                "geometry": geom,
            })
    return recs


# ---------------------------------------------------------------------------
# 3. Public library branches
# ---------------------------------------------------------------------------

def _load_muni_library_geojson(fname, source_label, name_fields):
    """name_fields: ordered list of property keys to try for the branch
    name, specific to each municipality's own schema (checked by hand
    against a sample of the file -- see SOURCE.md)."""
    path = os.path.join(RAW, fname)
    with open(path) as f:
        d = json.load(f)
    recs = []
    for feat in d["features"]:
        props = feat.get("properties", {})
        if feat.get("geometry") is None:
            continue  # non-physical service entries (bookmobile, phone line, etc.)
        if "PhysicalBranch" in props and str(props.get("PhysicalBranch")) == "0":
            continue
        name = None
        for k in name_fields:
            v = props.get(k)
            if v:
                name = str(v).strip()
                break
        if not name:
            continue  # no usable name in this source; skip rather than guess
        geom = shape(feat["geometry"])
        if geom.geom_type == "MultiPoint":
            geom = Point(geom.geoms[0].coords[0])
        elif geom.geom_type != "Point":
            geom = geom.centroid
        recs.append({
            "name": name,
            "type": "public_library_branch",
            "operator_or_board": source_label,
            "is_private": False,
            "sources": source_label + " open data",
            "geometry": geom,
        })
    return recs


def load_tpl():
    return _load_muni_library_geojson(
        "tpl_branches_4326.geojson", "Toronto Public Library", ["BranchName"])


def load_mississauga_lib():
    return _load_muni_library_geojson(
        "mississauga_city_libraries.geojson", "Mississauga Library", ["LANDMARKNAME"])


def load_brampton_lib():
    return _load_muni_library_geojson(
        "brampton_libraries.geojson", "Brampton Library", ["FACILITY_NAME"])


# Burlington's open-data point layer (raw/burlington_libraries.geojson) has
# no name field at all (every "NAME" property is null) -- see SOURCE.md. So
# Burlington branches are NOT loaded from it; they come from OSM instead,
# which has all 7 named (load_osm_libraries below).


# Academic, school, hospital, law-society, corporate, and other non-public
# libraries that OSM tags amenity=library but that are not a public library
# system's branch. Checked by hand against the full OSM library extract for
# all five CDs (not just Toronto): academic federated-college/faculty
# libraries (University of Toronto, York University, Toronto Metropolitan
# University, George Brown College, Centennial College, Seneca College),
# a law society library, a hospital patient library, community "seed
# libraries" and resource centres that are not lending-library branches,
# and one secondary-school library (GDHS = Georgetown District High
# School). Matched on `operator` first (more reliable), falling back to a
# name-only check for records OSM left without an operator tag.
NOT_PUBLIC_LIBRARY_OPERATOR = re.compile(
    r"university|\bcollege\b|law society|ocad|mohawk|george brown|"
    r"chinese cultural centre", re.I)
NOT_PUBLIC_LIBRARY_NAME = re.compile(
    r"\bcollege library\b|\buniversity\b|law (library|association)|"
    r"seed library|learning commons|resource centre|patient.{0,4}family library|"
    r"\barquives\b|campus library|pop up library|"
    r"district high school|secondary school|collegiate|\bd\.?h\.?s\.?\s*library\b|"
    r"^gdhs library$|"
    # Earth Sciences Library (Noranda): University of Toronto, tagged
    # without an operator. Nellie Langford Rowell Library: York
    # University's Centre for Feminist Research library, also untagged.
    r"earth sciences library|nellie langford rowell|"
    # Ankara Library: an independent Turkish-community non-profit library
    # (ankarakitapligi.org), not part of any public library system.
    r"^ankara library$", re.I)

# Any OSM "library" already named/operated as Toronto Public Library is, by
# definition, redundant with the authoritative TPL source loaded separately
# in load_tpl() -- keeping it too would double-count a TPL branch under a
# slightly different geocoded position (checked: "Toronto Public Library -
# Eglinton Square" sits about 190 m from the official TPL point for the
# same branch, just outside dedup()'s normal distance tolerance, because
# the two sources geocoded the same shopping-centre address differently).
TPL_REDUNDANT = re.compile(r"toronto public library", re.I)


def load_osm_libraries():
    """All other GTA library branches (York Region towns, Durham Region
    towns, Halton towns other than Burlington, Peel's Caledon, and any
    genuinely new branch not yet in a municipality's own open-data file --
    e.g. Brampton's Claireville branch, opened 2025) come only from OSM: no
    dedicated open-data branch list was found for them (see known_problems
    in SOURCE.md). Academic, school, hospital, law-society, and other
    non-public libraries are filtered out here -- see
    NOT_PUBLIC_LIBRARY_OPERATOR/_NAME above."""
    path = os.path.join(RAW, "osm_edu_lib.geojsonseq")
    recs = []
    excluded = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            props = d.get("properties", {})
            if props.get("amenity") != "library":
                continue
            name = props.get("name")
            if not name:
                continue
            operator = props.get("operator") or ""
            if (NOT_PUBLIC_LIBRARY_OPERATOR.search(operator) or NOT_PUBLIC_LIBRARY_NAME.search(name)
                    or TPL_REDUNDANT.search(name)):
                excluded.append((name, operator))
                continue
            recs.append({
                "name": name,
                "type": "public_library_branch",
                "operator_or_board": operator,
                "is_private": False,
                "sources": "OpenStreetMap (gta.osm.pbf extract), amenity=library",
                "geometry": _to_point(d["geometry"]),
            })
    if excluded:
        print(f"Excluded {len(excluded)} non-public-library OSM 'library' records "
              "(academic/school/hospital/law/corporate):")
        for name, operator in excluded:
            print(f"  - {name!r} (operator={operator!r})")
    return recs


# ---------------------------------------------------------------------------
# Stale / confusing post-secondary names
# ---------------------------------------------------------------------------

# Exact-name fixes for institutions that have rebranded or whose ODEF/OSM
# name is confusing. Checked by hand (2026-09-12):
#  - Ryerson University was renamed Toronto Metropolitan University in 2022.
#  - "University of Toronto (Admission And Awards)" is ODEF/OSM's odd label
#    for U of T's main downtown campus; the plain, correct campus name is
#    "University of Toronto St. George".
#  - "Geroge Brown Theatre School" is a misspelling of George Brown.
STALE_NAME_FIXES = {
    "Ryerson University": "Toronto Metropolitan University",
    "University of Toronto (Admission And Awards)": "University of Toronto St. George",
    "Geroge Brown Theatre School": "George Brown Theatre School",
    # Humber College Institute of Technology & Advanced Learning rebranded to
    # Humber Polytechnic in 2024; these are the post-merge names for its
    # North and Lakeshore campuses (see merge_postsecondary_campuses).
    "Humber College Institute of Technology & Advanced Learning": "Humber Polytechnic - North Campus",
    "Humber Fashion Institute": "Humber Polytechnic - Lakeshore Campus",
    # Seneca College of Applied Arts & Technology rebranded to Seneca
    # Polytechnic in 2022; these are the post-merge names for its King,
    # Markham, and Newnham campuses.
    "Seneca College of Applied Arts & Technology- King Campus And Technology": "Seneca Polytechnic - King Campus",
    "Seneca College of Applied Arts & Technology- Markham Campus": "Seneca Polytechnic - Markham Campus",
    "Seneca College of Applied Arts & Technology- Newnham/Jane-Toronto": "Seneca Polytechnic - Newnham Campus",
}

# A post-secondary campus record found, during this fix, to be a real but
# now-closed facility -- not invented, just no longer operating, so it is
# dropped rather than reported as a current destination. Durham College and
# Centennial College jointly ran the Pickering Learning Site from 2012 and
# closed it permanently on 2020-09-01 (COVID-19 operational review); see
# SOURCE.md changelog for citations.
CLOSED_POSTSECONDARY_NAMES = {
    "Durham College - Pickering Learning Site",
    "Centennial College - Pickering Learning Site",
}


def fix_stale_names(gdf):
    fixed = gdf["name"].isin(STALE_NAME_FIXES)
    if fixed.any():
        print(f"Renaming {int(fixed.sum())} stale/confusing names:")
        for old, new in STALE_NAME_FIXES.items():
            if (gdf["name"] == old).any():
                print(f"  - {old!r} -> {new!r}")
        gdf = gdf.copy()
        gdf["name"] = gdf["name"].replace(STALE_NAME_FIXES)
    return gdf


# ---------------------------------------------------------------------------
# Post-secondary campus merge: same institution, same physical campus
# ---------------------------------------------------------------------------

# Words that don't help decide "is this the same institution" -- campus/
# location/legal-form filler shared across many different post-secondary
# names. Kept deliberately narrow: real distinguishing words (a person's
# name, a place name, a subject) are what keeps two different colleges from
# merging just because they're both a "College Of Business".
POSTSEC_STOP = set("""
college of university applied arts technology institute institution business
science sciences health healthcare career school schools canada inc the and
for campus advanced learning polytechnic information services training
centre center a an & - and's academy applied
""".split())


def _postsec_root_tokens(name):
    name = (name or "").lower().replace("&", " and ")
    name = re.sub(r"\(temporary\)", " ", name)
    name = re.sub(r"[^a-z0-9 ]+", " ", name)
    return {t for t in name.split() if t not in POSTSEC_STOP and len(t) > 1}


# Region/city names that show up in a lot of different institutions' campus
# labels ("... - Markham Campus", "... Scarborough", "Seneca College - York
# Campus" next to "York University"). A name match on one of these alone is
# NOT evidence of the same institution -- e.g. Seneca's "York Campus" sits
# right on York University's Keele campus grounds (a real, documented
# affiliation) but they are two different institutions and must stay two
# separate rows. At least one non-generic (institution-identifying) token
# must also overlap.
POSTSEC_GENERIC_PLACE = set("""
york toronto peel durham halton mississauga brampton scarborough etobicoke
north york richmond hill markham vaughan oakville burlington milton ajax
pickering oshawa whitby north south east west central downtown king
caledon newmarket etobicoke
""".split())


def _postsec_same_institution(a, b):
    ta, tb = _postsec_root_tokens(a), _postsec_root_tokens(b)
    if not ta or not tb:
        return False
    common = ta & tb
    if not (common - POSTSEC_GENERIC_PLACE):
        return False  # only a shared place-name, not evidence of the same institution
    overlap = len(common) / min(len(ta), len(tb))
    return overlap >= 0.5


_SOURCE_RANK = {"Statistics Canada ODEF v2.1": 0}


def merge_postsecondary_campuses(sub, radius_m=800):
    """Systematic same-institution + proximity pass over ALL
    post_secondary_campus records (not just the known Seneca King/Markham
    and Humber North cases): two records within `radius_m` of each other
    whose names share enough tokens to be the same institution (see
    _postsec_same_institution) are the same physical campus and are merged
    into one point. Two campuses of the same institution that are farther
    apart than `radius_m` (e.g. Humber North vs Humber Lakeshore, Sheridan
    Davis vs Sheridan Hazel McCallion) are correctly left as separate rows."""
    sub = sub.reset_index(drop=True)
    sub_m = sub.to_crs(3347)

    class DSU:
        def __init__(self, n):
            self.p = list(range(n))

        def find(self, x):
            while self.p[x] != x:
                self.p[x] = self.p[self.p[x]]
                x = self.p[x]
            return x

        def union(self, a, b):
            ra, rb = self.find(a), self.find(b)
            if ra != rb:
                self.p[max(ra, rb)] = min(ra, rb)

    dsu = DSU(len(sub_m))
    tree = sub_m.sindex
    left, right = tree.query(sub_m.geometry.buffer(radius_m), predicate="intersects")
    n_pairs = 0
    for li, ri in zip(left, right):
        if li >= ri:
            continue
        if _postsec_same_institution(sub_m.at[li, "name"], sub_m.at[ri, "name"]):
            dsu.union(li, ri)
            n_pairs += 1
    sub_m["cluster"] = [dsu.find(i) for i in range(len(sub_m))]
    n_before = len(sub_m)
    rows = []
    for _, c in sub_m.groupby("cluster", sort=False):
        if len(c) == 1:
            rows.append(c.iloc[0].to_dict())
            continue
        c = c.copy()
        c["rank"] = c["sources"].map(lambda s: _SOURCE_RANK.get(s, 1))
        # prefer an ODEF (authoritative StatCan) name, then the shortest
        # name (the old, wordier legal names -- e.g. "Seneca College of
        # Applied Arts & Technology- King Campus And Technology" vs
        # "Seneca College - King Campus" -- tend to be longer)
        c = c.assign(namelen=c["name"].str.len()).sort_values(["rank", "namelen"])
        best = c.iloc[0]
        row = best.to_dict()
        row["name"] = best["name"]
        merged_from = sorted(set(c["name"]) - {best["name"]})
        if merged_from:
            print(f"  merged into {best['name']!r} ({best['cdname']}): {merged_from}")
        rows.append(row)
    out = gpd.GeoDataFrame(rows, geometry="geometry", crs=3347)
    out = out.drop(columns=[c for c in ["cluster", "rank", "namelen"] if c in out.columns])
    print(f"post_secondary_campus same-institution merge: {n_before} records, "
          f"{n_pairs} nearby-same-institution pairs found -> {len(out)} campuses")
    return out.to_crs(4326)


# ---------------------------------------------------------------------------
# Dedup
# ---------------------------------------------------------------------------

def dedup(records, tolerance_m=120):
    """Drop later duplicates that share a normalized name and sit within
    tolerance_m metres of an earlier record of the same type. Records are
    processed in the order given, so put authoritative sources first."""
    gdf = gpd.GeoDataFrame(records, geometry="geometry", crs=4326)
    gdf_m = gdf.to_crs(3347)  # metric CRS (Statistics Canada Lambert)

    def norm(n):
        return "".join(ch for ch in n.lower() if ch.isalnum())

    kept_geoms = {}  # type -> list of (norm_name, geom)
    keep_mask = []
    for i, row in gdf_m.iterrows():
        t = row["type"]
        nm = norm(row["name"])
        bucket = kept_geoms.setdefault(t, [])
        is_dup = False
        for onm, ogeom in bucket:
            if onm == nm and row.geometry.distance(ogeom) <= tolerance_m:
                is_dup = True
                break
            # also treat as dup if same type, very close, and one name
            # contains the other (handles "TPL - X" vs "X Branch")
            if row.geometry.distance(ogeom) <= 60 and (onm in nm or nm in onm) and nm and onm:
                is_dup = True
                break
            # two points of the same type essentially on top of each other
            # are almost certainly the same physical building, whatever
            # their names say (handles an authoritative source's official
            # name vs. OSM's, e.g. "Mississauga Library - Cooksville" vs.
            # an OSM tag that spells the branch name differently)
            if row.geometry.distance(ogeom) <= 70:
                is_dup = True
                break
        if is_dup:
            keep_mask.append(False)
        else:
            keep_mask.append(True)
            bucket.append((nm, row.geometry))
    return gdf[keep_mask].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    cd_gdf = load_cd_polygons()
    print("CDs loaded:", cd_gdf["CDNAME"].tolist())

    all_recs = []

    # Secondary schools: authoritative public source first, then OSM privates.
    sif = load_sif_secondary()
    print("SIF secondary schools (all Ontario):", len(sif))
    all_recs.extend(sif)

    osm_priv_sec = load_osm_private_secondary()
    print("OSM private secondary schools (all extract):", len(osm_priv_sec))
    all_recs.extend(osm_priv_sec)

    # Post-secondary: ODEF first (authoritative StatCan), then OSM supplement.
    odef = load_odef_postsecondary()
    print("ODEF post-secondary (all Ontario):", len(odef))
    all_recs.extend(odef)

    osm_post = load_osm_postsecondary()
    print("OSM university/college points (all extract):", len(osm_post))
    all_recs.extend(osm_post)

    # Libraries: authoritative municipal open data first, then OSM for the rest.
    tpl = load_tpl()
    print("Toronto Public Library branches:", len(tpl))
    all_recs.extend(tpl)

    miss = load_mississauga_lib()
    print("Mississauga library branches:", len(miss))
    all_recs.extend(miss)

    bram = load_brampton_lib()
    print("Brampton library branches:", len(bram))
    all_recs.extend(bram)

    osm_lib = load_osm_libraries()
    print("OSM library points (all extract):", len(osm_lib))
    all_recs.extend(osm_lib)

    print("Total candidate records before spatial filter/dedup:", len(all_recs))

    gdf = gpd.GeoDataFrame(all_recs, geometry="geometry", crs=4326)

    # Spatial filter to the 5 CDs + attach cdname
    gdf = assign_cdname(gdf, cd_gdf)
    print("After spatial filter to the 5 CDs:", len(gdf))

    # Dedup within each type. Order matters: earlier rows in `all_recs` win,
    # and we built all_recs with authoritative sources first for each type.
    gdf = gdf.sort_values("type", kind="stable")
    # process each type block separately, preserving original insertion order within it
    out_parts = []
    for t in ["secondary_school", "post_secondary_campus", "public_library_branch"]:
        sub = gdf[gdf["type"] == t].copy()
        # restore original all_recs order within this type by using geometry identity
        # (sjoin can reorder); re-sort by a stable key we didn't drop: use index
        sub = sub.sort_index()
        if t == "post_secondary_campus":
            n_before_closed = len(sub)
            sub = sub[~sub["name"].isin(CLOSED_POSTSECONDARY_NAMES)].copy()
            if len(sub) < n_before_closed:
                print(f"Dropped {n_before_closed - len(sub)} record(s) for a confirmed-closed "
                      f"campus: {sorted(CLOSED_POSTSECONDARY_NAMES)}")
            sub = merge_postsecondary_campuses(sub)
        deduped = dedup(sub.to_dict("records"))
        out_parts.append(deduped)
        print(f"{t}: {len(sub)} in area -> {len(deduped)} after dedup")

    final = pd.concat(out_parts, ignore_index=True)
    final = gpd.GeoDataFrame(final, geometry="geometry", crs=4326)
    final = fix_stale_names(final)

    final["id"] = [
        make_id(row["type"], row["name"], round(row.geometry.x, 5), round(row.geometry.y, 5))
        for _, row in final.iterrows()
    ]

    final = final[["id", "name", "type", "operator_or_board", "is_private", "sources", "cdname", "geometry"]]
    final["is_private"] = final["is_private"].astype(bool)

    out_path = os.path.join(HERE, "education_gta.gpkg")
    if os.path.exists(out_path):
        os.remove(out_path)
    final.to_file(out_path, driver="GPKG", layer="education_gta")
    print("Wrote", out_path, "rows:", len(final))

    print("\nBreakdown by type:")
    print(final["type"].value_counts())
    print("\nBreakdown by CD:")
    print(final.groupby(["cdname", "type"]).size())
    print("\nPrivate secondary schools found:", int((final["is_private"] & (final["type"] == "secondary_school")).sum()))


if __name__ == "__main__":
    main()
