"""Build a point layer of healthcare destinations in the GTA.

Output: research/data/healthcare/healthcare_gta.gpkg (layer healthcare_gta, EPSG:4326)
        research/data/healthcare/healthcare_gta.csv  (same rows, lon/lat columns)
        research/data/healthcare/excluded_records.csv (every GTA source record dropped, with the reason)

Types: hospital_emergency, urgent_care, walk_in_clinic, organized_primary_care.

GOVERNMENT LISTS ONLY: every record comes from Statistics Canada's ODHF or the
Ontario Ministry of Health's MOHSERLO service-provider list. OpenStreetMap is
NOT a source of records any more; it is used only to try to confirm (or flag
a possible problem with) the location of a government-listed record. Every
kept record carries an `osm_location_check` column saying what that check
found.

Sources (downloaded into raw/ if missing):
  1. Statistics Canada, Open Database of Healthcare Facilities (ODHF) v1.1
  2. Ontario Ministry of Health Service Provider Locations (MOHSERLO), Ontario open data
  3. Ontario Health, Time Spent in Emergency Departments (hospital list) -- hardcoded
     below, scraped from the official page (see ER_REPORTING_URL), used only to
     decide which hospital sites have a full emergency department.
  4. OpenStreetMap, from the repo's gta.osm.pbf (osmium) -- location confirmation only.
Clipped to the 2021 census divisions 3518, 3519, 3520, 3521, 3524.

Re-run: research/.venv/bin/python research/data/healthcare/build_healthcare.py
"""
import json
import re
import subprocess
import zipfile
from difflib import SequenceMatcher
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import requests

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"
RAW.mkdir(exist_ok=True)
REPO = HERE.parents[2]
OSM_PBF = REPO / "gta.osm.pbf"
OSMIUM = "/opt/homebrew/bin/osmium"

CD_URL = "https://www12.statcan.gc.ca/census-recensement/2021/geo/sip-pis/boundary-limites/files-fichiers/lcd_000b21a_e.zip"
ODHF_URL = "https://www150.statcan.gc.ca/n1/en/pub/13-26-0001/2020001/ODHF_v1.1.zip"
MOH_URL = "https://ws.lioservices.lrc.gov.on.ca/arcgis2/rest/services/LIO_OPEN_DATA/LIO_Open09/MapServer/26/query"

GTA_CDS = {"3518": "Durham", "3519": "York", "3520": "Toronto", "3521": "Peel", "3524": "Halton"}
METRIC = 3161  # NAD83 / Ontario MNR Lambert, metres
DEDUP_M = 75             # organized primary care
HOSPITAL_DEDUP_M = 300    # hospital_emergency campuses are large
URGENT_DEDUP_M = 150      # urgent_care / walk_in_clinic

HE, UC, WI, OPC = "hospital_emergency", "urgent_care", "walk_in_clinic", "organized_primary_care"
TYPE_DEDUP_M = {HE: HOSPITAL_DEDUP_M, UC: URGENT_DEDUP_M, WI: URGENT_DEDUP_M, OPC: DEDUP_M}

# ----------------------------------------------------------------------------------
# Ontario Health, "Time Spent in Emergency Departments" -- hospital comparison list.
# https://www.ontariohealth.ca/system/reporting/performance/time-spent-in-emergency-departments
# Data source per that page: NACRS, Canadian Institute for Health Information (CIHI).
# Scraped 2026-09-12 from the "Compare results across hospitals" table (site names as
# published there; the page updates monthly but the roster of reporting sites is
# stable). A site on this list publicly reports emergency-department wait times,
# i.e. it runs a full emergency department. IMPORTANT: this list is not perfectly
# reliable for "has a full ER" -- see PEEL_MEMORIAL note below, where the site
# appears on the list but its own operator says it has no emergency department.
ER_REPORTING_URL = "https://www.ontariohealth.ca/system/reporting/performance/time-spent-in-emergency-departments"
ER_REPORTING_HOSPITALS = """
Southlake Regional Health Centre
South Bruce Grey Health Centre-Durham
South Bruce Grey Health Centre-Chesley
Mackenzie Health-Richmond Hill Hospital
William Osler Health System-Etobicoke Site
Blanche River Health - Englehart
Unity Health Toronto - St. Joseph's
Haldimand War Memorial Hospital
Huron Perth Healthcare Alliance-Clinton
Quinte Health - Picton
Mattawa General Hospital
Bluewater Health-Charlotte Eleanor Englehart (Petrolia)
Haliburton Highlands Health Services Corp - Haliburton
North Shore Health Network - Thessalon Site
William Osler Health System-Peel Memorial
Mackenzie Health-Cortellucci Vaughan Hosp
Niagara Health System-Port Colborne Site
Scarborough Health Network-Birchmount Site
Mackenzie Health-Jane Street Site
North of Superior Healthcare Group - Wilson Memorial General Hospital
Espanola General Hospital
Wingham And District Hospital
St. Francis Memorial Hospital
Nipigon District Memorial Hospital
North Wellington Health Care - Palmerston
Niagara Health System-Fort Erie Douglas Site
St. Joseph's General Hospital
Dryden Regional Health Centre
Brightshores Health System-Lions Head Site
William Osler Health System-Civic Site
St. Joseph's Health Care System-Hamilton
Huron Perth Healthcare Alliance-Seaforth
St. Thomas-Elgin General Hospital
Riverside Health Care Facilities Inc. - Rainy River
Sensenbrenner Hospital
Manitoulin Health Centre - Little Current
Manitoulin Health Centre - Mindemoya Unit
Bingham Memorial Hospital
Perth And Smiths Falls District Hospital - Perth Site
North Shore Health Network - Blind River Site
South Huron Hospital
South Bruce Grey Health Centre-Walkerton
Brightshores Health System-Meaford Site
Strathroy Middlesex General Hospital
Lakeridge Health-Oshawa Site
Renfrew Victoria Hospital
Services De Sante De Chapleau Health Services
North York General Hospital
Centre For Addiction And Mental Health
St. Joseph's Health Care, London
Trillium Health Partners-Queensway Hlth
North Shore Health Network - Richards Landing
Alexandra Hospital
Brightshores Health System-Markdale Site
Scarborough Health Network-Centenary Site
Lakeridge Health-Port Perry Site
Collingwood General And Marine Hospital
Lady Dunn Health Centre
Anson General Hospital
Hamilton Health Sciences Corp-McMaster
West Haldimand General Hospital
Huron Perth Healthcare Alliance-St. Marys
Bluewater Health - Sarnia General Site
Riverside Health Care Facilities Inc. - La Verendrye
Brightshores Health System-Southampton Site
Brightshores Health System-Wiarton Site
Lakeridge Health-Bowmanville Site
The Red Lake Margaret Cochenour Memorial Hospital
North Wellington Health Care - Mount Forest
Thunder Bay Regional Hlth Sciences Ctr
Trillium Health Partners-Mississauga
Scarborough Health Network-Scar.Gen.Site
Kingston Health Sciences Centre-Hotel Dieu
Lakeridge Health-Ajax Site
Norfolk General Hospital
Manitouwadge General Hospital
Deep River And District Hospital
Oak Valley Health-Markham Stouffville Hospital
Geraldton District Hospital
Sinai Health System-Mount Sinai Site
Hospital for Sick Children (The)
Alexandra Marine and General Hospital
South Bruce Grey Health Centre-Kincardine
Quinte Health - Bancroft
Joseph Brant Hospital
Hanover And District Hospital
Tor. East Hlth Ntwrk-Michael Garron Hosp
Georgian Bay General Hosp-Midland Site
Muskoka Algonquin Healthcare-Huntsville
Muskoka Algonquin Healthcare-Bracebridge
University Health Network-Western Site
Campbellford Memorial Hospital
Timmins and District Hospital
Hopital Montfort
Headwaters Health Care Centre-Dufferin
Huron Perth Healthcare Alliance-Stratford
Hopital Notre Dame Hospital (Hearst)
Halton Healthcare Services Corp-Milton
Glengarry Memorial Hospital
Humber River Health-Wilson Site
Unity Health Toronto-St. Michael's
Ottawa Hospital (The)-Civic Site
Tillsonburg District Memorial Hospital
Erie Shores Healthcare
McCausland Hospital
Four Counties Health Services Corporation
Lake-of-the-Woods District Hospital
Perth & Smiths Falls Dist-Smiths Falls Site
Hamilton Health Sciences Corp-West Lincoln
University Health Network-General Site
Royal Victoria Regional Health Centre
Woodstock Hospital
Lennox and Addington County Gen Hospital
Orillia Soldiers' Memorial Hospital
West Nipissing General Hospital
St. Mary's General Hospital
Ottawa Hospital (The)-General Site
Chatham-Kent Health Alliance-Wallaceburg
Temiskaming Hospital
Hawkesbury And District General Hospital
Oak Valley Health-Uxbridge Hospital
Blanche River Health - Kirkland
Groves Memorial Community Hospital
Ross Memorial Hospital
Hamilton Health Sciences Corp-General
Stevenson Memorial Hospital Alliston
Halton Healthcare Services Corp-Georgetown
Sioux Lookout Meno-Ya-Win Health Centre - Cntr
Sault Area Hospital-Sault Ste. Marie
Guelph General Hospital
Halton Healthcare Services Corp-Oakville
West Parry Sound Health Centre
Chatham-Kent Health Alliance-Chatham
London Hlth Sciences Ctr-Victoria Hosp
Cornwall Community Hospital
Trillium Health Partners-Credit Valley
Niagara Health System-Welland County
Niagara Health System-Greater Niagara
Niagara Health System-St Catharines Gen
Brightshores Health System-Owen Sound
The Lady Minto Hospital
Arnprior Regional Health
Hamilton Health Sciences Corp-Juravinski
Quinte Health - Trenton
Grand River Hospital Corp-Waterloo Site
Health Sciences North-Laurentian
Kingston Health Sciences Centre-Kingston General
Almonte General Hospital
Carleton Place And District Memorial Hospital
Pembroke Regional Hospital Inc.
Northumberland Hills Hospital
Brant Community Healthcare Sys-Brantford
Windsor Regional Hospital - Ouellette Campus
Peterborough Regional Health Centre
Children's Hospital Of Eastern Ontario
Brockville General Hospital
Kemptville District Hospital
Winchester District Memorial Hospital
North Bay Regional Health Centre
Queensway-Carleton Hospital
Quinte Health - Belleville
Sunnybrook Health Sciences Centre
Windsor Regional Hospital-Metropolitan Campus
Cambridge Memorial Hospital
London Hlth Sciences Ctr-University Hosp
""".strip().splitlines()

# Sites that are on (or, for Women's College, near-miss the) the Ontario Health ED
# list above but are documented, by their own operator or Ontario news coverage, as
# NOT running a full emergency department. Checked individually (2026-09-12):
#  - William Osler Health System - Peel Memorial: Osler's own site says Peel Memorial
#    "currently has no emergency department" -- it runs a 24/7 Urgent Care Centre.
#    A new ED is planned as part of a future redevelopment, not open yet.
#    https://www.williamoslerhs.ca/en/areas-of-care/emergency-and-urgent-care.aspx
#  - Women's College Hospital: has no emergency department at all (its former Urgent
#    Care Centre closed; the Acute Ambulatory Care Unit that replaced it is referral
#    -only, not a public walk-in/urgent-care service). Kept as urgent_care here as
#    the closest of the four allowed types, flagged for review.
#    https://www.womenscollegehospital.ca/care-programs/acute-ambulatory-care-unit-aacu/
#  - Humber River Health - York Finch (a.k.a. "Church Street"/Finch site): operates
#    as an Urgent Care and Ambulatory Care centre; the 24/7 ED is at the Wilson site.
#  - Lakeridge Health - Jerry Coughlan (Ajax-Pickering's Jerry Coughlan Health and
#    Wellness Centre): a day-surgery and urgent-care building, not a full ED site.
#  - Trillium Health Partners - Queensway (Queensway Health Centre, Etobicoke): runs
#    an Urgent Care Centre; Trillium's EDs are at Credit Valley and Mississauga
#    Hospital. Added in Opus review 2026-09-12.
KNOWN_NOT_FULL_ER = {"peel memorial", "womens college hospital", "york finch",
                      "jerry coughlan", "queensway"}

# Hospitals that are not general acute care with an ER: specialist-only, rehab,
# complex continuing care, psychiatric, cancer-only, surgical-only, hospice, or
# ambulatory-specialist sites, plus mental-health/addiction-only and rehab-only
# facilities per the study's exclusion rules. Matched against normalised names
# from every source.
SPECIALIST_HOSPITAL = re.compile(
    r"addiction and mental health|\bcamh\b|ontario shores|holland bloorview|bloorview|"
    r"\brehab|bridgepoint|providence|bickle|runnymede|baycrest|bellwood|casey house|hospice|"
    r"surgical unit|kensington eye|shouldice|holland orthopaedic|holland centre|orthopaedic|"
    r"princess margaret|cancer|toronto grace|st\.? joseph'?s infirmary|cosmetic surgery|"
    r"reactivation|hillcrest|continuing care|west park|university centre|branson|"
    r"church \(memorial\)|church st\.? site|keele street site|york finch site|"
    r"mental health sciences|homewood|lyndhurst|rumsey|psychiatr|"
    r"lakeridge health.{0,3}whitby|whitby mental|whitby psychiatric", re.I)

# Not a family doctor / organized primary-care model: dentists, pharmacies, labs,
# imaging, allied health, cosmetic, and specialist-only practices, plus solo doctor
# offices (excluded on purpose -- see rule 2 in the task).
NOT_PRIMARY = re.compile(
    r"dental|dentist|denture|orthodont|pharmac|drug mart|rexall|shoppers|lifelabs|dynacare|"
    r"\blab\b|laborator|specimen|imaging|x-?ray|ultrasound|radiolog|\bmri\b|diagnostic|"
    r"physio|chiropract|massage|acupunct|naturopath|homeopath|osteopath|optometr|optical|"
    r"\beye\b|vision|ophthalm|retina|laser|cosmetic|aesthetic|botox|\bspa\b|skin|dermatolog|"
    r"hair|vein|fertility|\bivf\b|foot|podiat|chiropod|orthotic|hearing|audiolog|sleep|"
    r"weight loss|bariatric|pain|sports med|rehab|wellness|spine|travel|passport|vaccin|"
    r"blood donor|blood donation|canadian blood|veterinar|animal|pet |psycholog|psychother|"
    r"counsel|speech|cardio|heart|cancer|oncolog|allerg|endoscop|colonoscop|surgery|surgical|"
    r"plastic|urolog|gastro|orthop|fracture|kidney|dialysis|abortion|morgentaler|"
    r"long[\s\-]*term care|retirement|nursing home|hospice|midwi|birth|pregnan|"
    r"ear nose|\bent\b|paediatric|pediatric|obstetric|gynaec|gynec|women's health clinic|"
    r"medical imaging|dexa|mammogra|hormone|testosterone|men's health|circumcision|"
    r"mental health|addiction", re.I)

NOT_PRIMARY_SPECIALITY = re.compile(
    r"dent|orthodont|pharmac|laborator|blood|radiolog|physio|chiro|massage|acupunct|naturo|"
    r"optom|ophthal|dermat|plastic|surgery|cardio|oncol|fertil|podiat|psych|weight|travel|"
    r"vaccin|paediat|pediat|urolog|gastro|orthop|allerg|obstet|gynae|abortion|medical_spa|"
    r"laser|skincare|facial|physiatr|otolaryng|nephrol|neurol|rheumat|endocrin|radiother|"
    r"diagnostic|sleep|hearing|audiol|speech|occupational|pain", re.I)


def norm_er_tokens(name):
    """Normalise a hospital/site name for matching against ER_REPORTING_HOSPITALS."""
    ABBR = {"hlth": "health", "ctr": "centre", "ntwrk": "network", "corp": "corporation",
            "sys": "system", "gen": "general", "mem": "memorial", "hosp": "hospital",
            "svcs": "services", "dist": "district", "tor": "toronto", "reg": "regional"}
    STOP = set("the of and a an inc ltd limited corp corporation co centre center hospital "
               "hospitals health system network services service site sites".split())
    name = name.lower().replace("'", "")
    for ch in ".-()":
        name = name.replace(ch, " ")
    toks = [ABBR.get(t, t) for t in name.split()]
    return {t for t in toks if t not in STOP and len(t) > 1}


_ER_TOKENS = [(h, norm_er_tokens(h)) for h in ER_REPORTING_HOSPITALS]


def matches_er_list(name):
    """True if `name` names a site on the Ontario Health ED-reporting list (full
    token-set overlap on the smaller side -- see norm_er_tokens)."""
    nt = norm_er_tokens(name or "")
    if not nt:
        return False
    for _, et in _ER_TOKENS:
        if et and len(nt & et) / min(len(nt), len(et)) >= 1.0:
            return True
    return False


def er_override_key(name):
    n = (name or "").lower()
    if "peel memorial" in n:
        return "peel memorial"
    if "women" in n and "college" in n:
        return "womens college hospital"
    if "york finch" in n or ("finch" in n and "humber" in n):
        return "york finch"
    if "jerry coughlan" in n:
        return "jerry coughlan"
    if "queensway" in n and "trillium" in n:
        return "queensway"
    return None


OSM_EXCLUDED_HEALTHCARE = {
    "dentist", "pharmacy", "laboratory", "physiotherapist", "alternative", "optometrist",
    "psychotherapist", "counselling", "podiatrist", "audiologist", "rehabilitation",
    "hospice", "blood_donation", "blood_bank", "midwife", "birthing_centre",
    "occupational_therapist", "naturopath", "naturopathy", "speech_therapist", "psychotherapy",
    "massage", "medical_imaging", "vaccination_centre", "nursing_home", "osteopath", "foot",
    "home_care", "denture", "orthodontist", "sample_collection", "dialysis", "optician",
    "community_health_worker",
}


# ----------------------------------------------------------------- downloads
def fetch(url, dest):
    if dest.exists() and dest.stat().st_size > 0:
        return
    print("downloading", url)
    with requests.get(url, stream=True, timeout=600) as r:
        r.raise_for_status()
        tmp = dest.with_suffix(dest.suffix + ".part")
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
        tmp.rename(dest)


def load_cds():
    z = RAW / "lcd_000b21a_e.zip"
    shp = RAW / "cd" / "lcd_000b21a_e.shp"
    if not shp.exists():
        fetch(CD_URL, z)
        zipfile.ZipFile(z).extractall(RAW / "cd")
    cd = gpd.read_file(shp)
    cd = cd[cd.PRUID == "35"][["CDUID", "CDNAME", "geometry"]].to_crs(METRIC)
    return cd


def load_odhf():
    csv = RAW / "odhf" / "ODHF_v1.1" / "odhf_v1.1.csv"
    if not csv.exists():
        z = RAW / "ODHF_v1.1.zip"
        fetch(ODHF_URL, z)
        zipfile.ZipFile(z).extractall(RAW / "odhf")
    d = pd.read_csv(csv, encoding="latin-1", dtype=str)
    d = d[d.Pruid == "35"].copy()
    n_nocoord = d.latitude.isna().sum()
    d = d.dropna(subset=["latitude", "longitude"])
    g = gpd.GeoDataFrame(
        d, geometry=gpd.points_from_xy(d.longitude.astype(float), d.latitude.astype(float)), crs=4326)
    g["src"] = "odhf"
    g["src_id"] = "odhf:" + g["index"]
    g["name"] = g.facility_name
    g["raw_type"] = g.source_facility_type.fillna("") + " | " + g.odhf_facility_type.fillna("")
    print(f"ODHF Ontario rows with coordinates: {len(g)} (dropped {n_nocoord} without)")
    return g


def load_moh():
    path = RAW / "mohserlo.geojson"
    if not path.exists():
        feats, off = [], 0
        while True:
            r = requests.get(MOH_URL, params=dict(
                where="1=1", outFields="*", outSR=4326, f="geojson", resultOffset=off,
                resultRecordCount=2000, orderByFields="OBJECTID"), timeout=300)
            r.raise_for_status()
            f = r.json()["features"]
            feats += f
            off += len(f)
            if len(f) < 2000:
                break
        path.write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
    g = gpd.read_file(path)
    g["src"] = "mohserlo"
    g["src_id"] = "mohserlo:" + g.MOH_SERVICE_PROVIDER_IDENT.astype(str) + ":" + g.OBJECTID.astype(str)
    g["name"] = g.ENGLISH_NAME
    g["raw_type"] = g.SERVICE_TYPE.fillna("") + " | " + g.SERVICE_TYPE_DETAIL.fillna("")
    print(f"MOHSERLO rows (all Ontario): {len(g)}")
    return g


def load_osm_for_confirmation():
    """OSM is not a record source any more -- load it only to confirm/flag the
    location of government-listed records (rule: OSM may confirm or correct a
    location, never add a place on its own)."""
    pbf = RAW / "osm_health.osm.pbf"
    seq = RAW / "osm_health_ids.geojsonseq"
    if not seq.exists():
        subprocess.run([OSMIUM, "tags-filter", "-O", "-o", str(pbf), str(OSM_PBF),
                        "nwr/amenity=hospital,clinic,doctors", "nwr/healthcare"], check=True)
        subprocess.run([OSMIUM, "export", "-O", "-f", "geojsonseq", "-u", "type_id",
                        "--geometry-types=point,polygon", "-o", str(seq), str(pbf)], check=True)
    rows = []
    for line in open(seq):
        line = line.strip().lstrip("\x1e")
        if not line:
            continue
        f = json.loads(line)
        p = f["properties"]
        rows.append({"osm_id": f.get("id"), "tags": p, "geometry": f["geometry"]})
    g = gpd.GeoDataFrame.from_features(
        [{"type": "Feature", "geometry": r["geometry"],
          "properties": {"osm_id": r["osm_id"], "tags": json.dumps(r["tags"])}} for r in rows], crs=4326)
    g["geometry"] = g.geometry.representative_point()
    t = g.tags.map(json.loads)
    g["name"] = t.map(lambda x: x.get("name") or x.get("official_name") or x.get("brand") or "")
    g = g[g.name.str.len() > 0].copy()
    print(f"OSM healthcare features available for location confirmation: {len(g)}")
    return g


# ----------------------------------------------------------- classification
def classify_moh(r):
    st = (r.SERVICE_TYPE or "").strip()
    name = r["name"] or ""
    if st == "Hospital":
        if SPECIALIST_HOSPITAL.search(name):
            return None, "specialist-only, rehab, psychiatric, complex care, or mental health/addiction-only hospital"
        key = er_override_key(name)
        if key in KNOWN_NOT_FULL_ER:
            return UC, ""
        if matches_er_list(name):
            return HE, ""
        return UC, "hospital site not on the Ontario Health ED-reporting list; treated as urgent care, review by hand"
    if st in ("Family Health Team", "Community Health Centre", "Nurse Practitioner-Led Clinic",
              "Indigenous Primary Health Care Organization"):
        return OPC, ""
    return None, f"MOHSERLO service type not in scope: {st}"


ODHF_HOSP_OK = {"general", "active acute hospital", "hospital - site", "hospital - corporation",
                "pediatric", "active acute hospital, long term care"}


def classify_odhf(r):
    s = (r.source_facility_type or "").strip().lower()
    name = r["name"] or ""
    if s in ODHF_HOSP_OK:
        if SPECIALIST_HOSPITAL.search(name):
            return None, "specialist-only, rehab, psychiatric, complex care, or mental health/addiction-only hospital"
        key = er_override_key(name)
        if key in KNOWN_NOT_FULL_ER:
            return UC, ""
        if matches_er_list(name):
            return HE, ""
        return UC, "hospital site not on the Ontario Health ED-reporting list; treated as urgent care, review by hand"
    if s in ("family health team - contract", "community health centre",
             "nurse practitioner led clinic", "aboriginal health access centre"):
        return OPC, ""
    if s in ("psychiatric", "rehabilitation", "chronic care", "cancer", "orthopedic",
             "cardiology", "extended care", "mental health"):
        return None, f"specialist-only hospital type: {s}"
    return None, f"ODHF facility type not in scope: {s}"


def apply(g, fn):
    out = g.apply(lambda r: fn(r), axis=1, result_type="expand")
    g = g.copy()
    g["type"], g["reason"] = out[0], out[1]
    return g


# ------------------------------------------------------------------ clipping
def clip_to_gta(g, cd):
    g = g.to_crs(METRIC)
    j = gpd.sjoin(g[["src_id", "geometry"]], cd, predicate="within", how="left")
    j = j[~j.index.duplicated()]
    g["CDUID"], g["CDNAME"] = j.CDUID, j.CDNAME
    # points just off a cartographic shoreline: nearest Ontario CD within 250 m
    miss = g.CDUID.isna()
    if miss.any():
        n = gpd.sjoin_nearest(g.loc[miss, ["src_id", "geometry"]], cd, max_distance=250, how="left")
        n = n[~n.index.duplicated()]
        g.loc[miss, "CDUID"] = n.CDUID
        g.loc[miss, "CDNAME"] = n.CDNAME
    return g[g.CDUID.isin(GTA_CDS)].copy()


# ------------------------------------------------------------- deduplication
STOP = set("""the of and a an inc ltd limited corp corporation co centre center clinic clinics
medical medicine health healthcare care family team fht chc site campus hospital hospitals
services service system network group partners practice office offices dr drs md s st saint
community primary new main satellite location unit""".split())


def norm_tokens(name):
    name = (name or "").lower().replace("&", " and ")
    name = re.sub(r"[^a-z0-9 ]+", " ", name)
    return [t for t in name.split() if t not in STOP and len(t) > 1]


def similar(a, b):
    ta, tb = set(norm_tokens(a)), set(norm_tokens(b))
    if not ta or not tb:
        # at least one name is generic or blank: fall back to raw string similarity
        ra = re.sub(r"[^a-z0-9]", "", (a or "").lower())
        rb = re.sub(r"[^a-z0-9]", "", (b or "").lower())
        if not ra or not rb:
            return True  # an unnamed point at the same spot as a named one
        return SequenceMatcher(None, ra, rb).ratio() >= 0.8
    overlap = len(ta & tb) / min(len(ta), len(tb))
    if overlap >= 0.5:
        return True
    return SequenceMatcher(None, " ".join(sorted(ta)), " ".join(sorted(tb))).ratio() >= 0.75


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


SRC_RANK = {"mohserlo": 0, "odhf": 1}


def dedupe(allp):
    allp = allp.reset_index(drop=True)
    dsu = DSU(len(allp))
    pairs_checked = 0
    for t, sub in allp.groupby("type"):
        radius = TYPE_DEDUP_M[t]
        idx = sub.index.to_numpy()
        tree = sub.sindex
        left, right = tree.query(sub.geometry.buffer(radius), predicate="intersects")
        for li, ri in zip(left, right):
            i, j = idx[li], idx[ri]
            if i >= j:
                continue
            pairs_checked += 1
            if similar(allp.at[i, "name"], allp.at[j, "name"]):
                dsu.union(i, j)
    allp["cluster"] = [dsu.find(i) for i in range(len(allp))]
    allp["rank"] = allp.src.map(SRC_RANK)
    rows = []
    for _, c in allp.sort_values(["rank", "src_id"]).groupby("cluster", sort=False):
        best = c.iloc[0]
        named = c[c.name.fillna("").str.len() > 0]
        name = named.iloc[0]["name"] if len(named) else ""
        srcs = sorted(set(c.src), key=SRC_RANK.get)
        rows.append({
            "name": name,
            "type": best.type,
            "sources": ";".join(srcs),
            "source_ids": ";".join(c.src_id),
            "n_source_records": len(c),
            "cduid": best.CDUID,
            "cdname": best.CDNAME,
            "source_detail": " || ".join(sorted(set(c.raw_type))),
            "geometry": best.geometry,
        })
    print(f"dedupe: {len(allp)} records -> {len(rows)} places ({pairs_checked} nearby pairs checked)")
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=METRIC)


def osm_location_check(out, osm):
    """For each kept record, look for an OSM healthcare feature within 300 m with a
    similar name and note whether the location is confirmed. Never adds or moves
    records; only annotates."""
    out = out.to_crs(METRIC)
    osm_m = osm.to_crs(METRIC)
    tree = osm_m.sindex
    results = []
    for i, row in out.iterrows():
        cand_idx = tree.query(row.geometry.buffer(300), predicate="intersects")
        found = False
        for oi in cand_idx:
            if similar(row["name"], osm_m.iloc[oi]["name"]):
                found = True
                break
        results.append("confirmed_by_osm" if found else "no_osm_match")
    out["osm_location_check"] = results
    return out.to_crs(4326)


# ---------------------------------------------------------------------- main
def main():
    cd = load_cds()
    keep_cols = ["src", "src_id", "name", "raw_type", "type", "reason", "geometry"]

    odhf = clip_to_gta(apply(load_odhf(), classify_odhf), cd)
    moh = clip_to_gta(apply(load_moh(), classify_moh), cd)
    for nm, g in (("ODHF", odhf), ("MOHSERLO", moh)):
        # NOTE: use g["type"], never g.type -- GeoDataFrame.type is a built-in property
        # that returns the geometry type ("Point"), and silently shadows a "type" column.
        print(f"{nm} in GTA: {len(g)} records, kept {g['type'].notna().sum()}")
        print(g["type"].value_counts().to_string())

    excluded = pd.concat([g.loc[g["type"].isna(), ["src", "src_id", "name", "raw_type", "reason", "CDNAME"]]
                          for g in (odhf, moh)])
    excluded.to_csv(HERE / "excluded_records.csv", index=False)

    parts = []
    for g in (moh, odhf):
        k = g[g["type"].notna()].copy()
        parts.append(k[keep_cols + ["CDUID", "CDNAME"]])
    allp = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), geometry="geometry", crs=METRIC)

    # Records classified urgent_care with a "review by hand" reason are kept (not
    # dropped) but the reason travels into excluded_records.csv as an informational
    # note too, so it's easy to find them later.
    flagged = allp[allp.reason.fillna("") != ""][["src", "src_id", "name", "raw_type", "reason", "CDNAME"]]
    if len(flagged):
        flagged = flagged.rename(columns={"CDNAME": "CDNAME"})
        pd.concat([excluded, flagged.assign(reason="KEPT AS URGENT_CARE, FLAGGED: " + flagged.reason)]) \
            .to_csv(HERE / "excluded_records.csv", index=False)

    # ODHF is from 2020. ODHF hospital/urgent-care records that match nothing in the
    # newer MOHSERLO list are likely closed or renamed sites, so they are dropped
    # after deduplication.
    out = dedupe(allp)
    stale = (out.sources == "odhf") & (out["type"].isin([HE, UC]))
    if stale.any():
        print("dropping ODHF-only hospital/urgent-care records (not in MOHSERLO):")
        print(out.loc[stale, ["name", "cdname"]].to_string())
        ex = out.loc[stale, ["name", "source_ids", "cdname"]].rename(columns={"source_ids": "src_id", "cdname": "CDNAME"})
        ex["src"] = "odhf"
        ex["reason"] = "ODHF 2020 hospital/urgent-care record with no match in MOHSERLO (likely closed or renamed)"
        pd.concat([excluded, ex]).to_csv(HERE / "excluded_records.csv", index=False)
        out = out[~stale]

    osm = load_osm_for_confirmation()
    out = osm_location_check(out, osm)

    type_order = {HE: 0, UC: 1, WI: 2, OPC: 3}
    out = out.sort_values(["type", "cduid", "name"], key=lambda s: s.map(type_order) if s.name == "type" else s)
    out.insert(0, "id", [f"hc{i:05d}" for i in range(1, len(out) + 1)])
    out = out[["id", "name", "type", "sources", "cdname", "cduid", "source_ids",
               "n_source_records", "source_detail", "osm_location_check", "geometry"]].reset_index(drop=True)
    gpkg = HERE / "healthcare_gta.gpkg"
    if gpkg.exists():
        gpkg.unlink()
    out.to_file(gpkg, layer="healthcare_gta", driver="GPKG")
    csv = out.drop(columns="geometry").copy()
    csv["lon"] = out.geometry.x.round(7)
    csv["lat"] = out.geometry.y.round(7)
    csv.to_csv(HERE / "healthcare_gta.csv", index=False)

    print(f"\nwrote {len(out)} rows")
    print(pd.crosstab(out.cdname, out["type"], margins=True).to_string())
    print(out.sources.value_counts().to_string())
    print(pd.crosstab(out["type"], out.sources).to_string())
    print(out.osm_location_check.value_counts().to_string())

    mtsinai = out[out.name.str.contains("Sinai", case=False, na=False)]
    print("\nMount Sinai check:")
    print(mtsinai[["name", "type", "sources"]].to_string())


if __name__ == "__main__":
    main()
