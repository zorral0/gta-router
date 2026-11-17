# Census data: sources, steps, and known problems

Topic folder: research/data/census/
Access date used for this note: 2026-09-12
Study area: 2021 census divisions 3518 Durham, 3519 York, 3520 Toronto,
3521 Peel, 3524 Halton (2021 census geography).

This folder was picked up partway through a previous run. The three raw
files below were already sitting in raw/ before this session started, so
the exact download links and the exact time they were fetched were not
recorded by that earlier run. What is written below is the best-known
public source for each file (catalogue number and product page), not a
confirmed link this session clicked through itself. That gap is called
out again in "Known problems."

## 1. Raw files used

### a. Census Profile, 2021 (98-401-X2021006), Ontario, all geography levels
- File in raw/: `98-401-X2021006_Ontario_eng_CSV.zip` (757 MB)
- Publisher: Statistics Canada
- Best-known source: Statistics Canada catalogue no. 98-401-X2021006,
  "Census Profile, 2021 Census of Population", product page
  https://www150.statcan.gc.ca/n1/en/catalogue/98-401-X2021006
  (download portal: https://www12.statcan.gc.ca/census-recensement/2021/dp-pd/prof/index.cfm?Lang=E,
  "Download" tab, Ontario, all geographic levels down to dissemination area, CSV)
- Licence: Statistics Canada Open Licence
- Contains: one row per (geography, characteristic). Every geography's
  block is exactly 2631 rows long, characteristic IDs 1 to 2631 in a
  fixed order (confirmed by inspecting the Canada and Ontario blocks
  directly). Value is always in the C1_COUNT_TOTAL column regardless of
  whether the characteristic is a count, a percentage, or a dollar
  figure (confirmed against sample rows for characteristics 1, 50, 243,
  345, 2605).
- Row count used: 8,508 dissemination areas in the 5 GTA CDs (out of
  57,932 DAs in the DA boundary file for Ontario, 20,468 of which are
  Ontario DAs listed in the profile's geography index).
- Characteristic IDs pulled (found by reading the Canada-level block and
  matching names, since the same order and IDs apply to every geography
  in this file):
  - 1: Population, 2021
  - 50: Total private households (by household size, 100% data)
  - 243: Median total income of household in 2020 ($)
  - 345: Prevalence of low income based on the Low-income measure, after
    tax (LIM-AT) (%)
  - 2605 to 2610: main mode of commuting, employed labour force with a
    usual place of work or no fixed workplace address (25% sample data):
    car/truck/van as driver, as passenger, public transit, walked,
    bicycle, other method

### b. 2021 Census geographic attribute file (GAF)
- File in raw/: `2021_92-151_X.zip` (9.8 MB zipped, 299 MB csv)
- Publisher: Statistics Canada
- Best-known source: Statistics Canada catalogue no. 92-151-X, "Census
  geographic attribute file, 2021 Census of Population". The exact
  product-page suffix for the 2021 edition was not independently
  re-verified this session; search https://www150.statcan.gc.ca/n1/en/catalogue/92-151-X
  for the 2021 vintage.
- Licence: Statistics Canada Open Licence
- Contains one row per dissemination block (DB), with the CD name, CSD
  name, DA representative point (DARPLAT/DARPLONG), and DB population
  (DBPOP2021), among other fields. 498,786 DB rows nationally; 8,508
  distinct DAs (all of them) fall in the 5 GTA CDs.
- Important limitation: this file gives a representative point **per DA**
  (repeated on every DB row belonging to that DA), not a separate point
  per DB. See "Known problems" below.

### c. 2021 Dissemination Area boundary file
- File in raw/: `lda_000b21a_e.zip` (197 MB), extracted to raw/lda/
- Publisher: Statistics Canada
- Best-known source: Statistics Canada 2021 Census Boundary files,
  catalogue no. 92-160-X, "Dissemination Areas, 2021", page
  https://www12.statcan.gc.ca/census-recensement/2021/geo/sip-pis/boundary-limites/index2021-eng.cfm?year=21
- Licence: Statistics Canada Open Licence
- Original CRS: EPSG:3347 (Statistics Canada Lambert). Reprojected to
  EPSG:4326 for all outputs here.
- LANDAREA field is in square kilometres (StatCan boundary-file
  convention; sanity-checked: median DA in the study area is 0.13 km2,
  consistent with a typical urban DA).
- 57,932 DAs in Ontario; 8,508 fall in the 5 GTA CDs (DAUID's first 4
  digits equal the CDUID).

## 2. How the outputs were built

Script: `build_census.py` in this folder. Re-running it regenerates all
four outputs from raw/ (it extracts the GAF and profile-geography-index
files from their zips if not already extracted, but does not otherwise
touch raw/).

1. Load the DA boundary shapefile, keep DAs whose DAUID starts with one
   of the 5 CD codes, reproject to EPSG:4326.
2. Stream the GAF csv (498,786 DB rows) in chunks, keep rows in the 5
   CDs, and build: DA representative point, DB count per DA, CSD name
   per DA, CD name per CD, and a DB-population sum per DA (used only as
   a cross-check, see below).
3. Because the Census Profile's per-geography block is a fixed 2631
   rows long and in a fixed characteristic order, the exact file line
   holding each of the 10 characteristics above is computed for every
   GTA DA from the profile's own `Geo_starting_row` index. The 757 MB
   profile csv is then streamed exactly once, decompressed from the zip
   on the fly, and only those ~85,000 target lines are parsed (the rest
   are counted and skipped, not held in memory). This avoids ever
   loading the 8.7 GB uncompressed profile into memory or into pandas.
4. Suppressed, not-applicable or too-unreliable cells (StatCan symbols
   `..`, `...`, `x`, `F`) become missing (`NaN`/empty), never zero.
5. Outputs are written: da_gta.gpkg, da_origins.csv, da_profile.csv,
   gta_boundary.gpkg (see file descriptions below).
6. As a cross-check, the DA population from the Census Profile
   (characteristic 1) was compared with the sum of DB populations for
   that DA from the GAF file: **0 of 8,508 DAs differ by more than 5
   people.** The two independent sources agree.

## 3. Output files

### da_gta.gpkg (layer "da_gta"), EPSG:4326, 8,508 rows
DAUID, CDUID, CSDNAME (census subdivision name), landarea_km2, pop2021,
geometry (DA polygon).

### da_origins.csv, 8,488 rows
DAUID, lat, lon, pop2021, n_blocks.
- lat/lon is the DA's StatCan-supplied representative point (see the
  DA-vs-DB limitation below).
- pop2021 and n_blocks come from the same sources as above.
- **20 DAs were dropped** for having zero or missing 2021 population
  (mostly industrial land, parkland, or airport lands with no
  residents). These are real DAs, not a data error: the boundary file
  has 8,508 GTA DAs and the profile confirms 0 population for these 20.

### da_profile.csv, 8,508 rows
DAUID, population, private_households, median_hh_income, lim_at_pct,
mode_driver, mode_passenger, mode_transit, mode_walk, mode_bicycle,
mode_other.
Missing-value counts (suppressed or not applicable, left blank, not 0):
private_households 23, median_hh_income 210, lim_at_pct 350, each
commuting-mode column 36. These are almost all very small DAs where
StatCan suppresses the number to protect confidentiality.

### gta_boundary.gpkg (layer "gta_boundary"), EPSG:4326, 5 rows
CDUID, CDNAME, geometry: each of the 5 census divisions, built by
dissolving its own DA polygons together (not a separately downloaded CD
boundary file).

## 4. Known problems

- **Exact download links not re-verified.** As noted above, the three
  raw files were already in raw/ when this run started, and this run
  did not itself download them. The catalogue numbers and product pages
  given above are the standard public StatCan pages for these products,
  but the precise "Download" link, and the exact date they were pulled,
  could not be confirmed independently. If this matters for the
  write-up's citations, someone should re-download one file from the
  page above and confirm it matches (e.g. same row counts, same
  DBPOP2021 total).
- **DA origin point is not a true population-weighted centroid of DB
  points.** The task asked for the DA origin to be a population-weighted
  point built from DB representative points weighted by DB population.
  The GAF file does not actually contain a representative point per DB;
  it contains one representative point per DA (DARPLAT/DARPLONG),
  repeated on every DB row that belongs to that DA. There is no DB point
  layer in raw/ to compute a true weighted centroid from. da_origins.csv
  therefore uses StatCan's own DA representative point as the origin,
  and reports pop2021 and n_blocks (count of DBs in the DA) alongside
  it, but this is StatCan's point, not one this pipeline weighted
  itself. If a true DB-weighted centroid is required, the 2021
  Dissemination Block boundary/point file (catalogue 92-169-X or the DB
  boundary file, not currently in raw/) would need to be downloaded.
- **May 2021 COVID commuting problem.** The main-mode-of-commuting
  counts in da_profile.csv (mode_driver through mode_other) come from
  the 2021 Census, collected in May 2021, during COVID-19 public health
  restrictions in Ontario. Many usual commuters were working from home
  or not commuting at all that month, so these counts almost certainly
  understate normal-times car, transit, and active-transport commuting,
  especially transit. Per the research plan (PLAN.md, section 4C), the
  gap score's "transit-dependent" measure should use the Transportation
  Tomorrow Survey (TTS) for commute mode, not this Census figure. These
  Census commuting counts are included here as requested for
  completeness and cross-checking, not as the primary commute-mode
  source for the study's dependency measure.
- **Suppressed values.** Values StatCan marks `x` (suppressed) or `F`
  (too unreliable) are left blank in da_profile.csv, not zero. Do not
  treat a blank cell as "no low income" or "no commuters"; it means the
  number was too small or unreliable to publish for that DA.
- **CDUID/CSDNAME join.** CD and CSD names come from the GAF file, keyed
  by joining on the DA's own ID (the first 4 digits of DAUID for CDUID).
  This is a standard, lossless join since DAs nest inside CSDs inside
  CDs by construction, but it was not cross-checked against a separate
  CSD boundary file since none was requested.
