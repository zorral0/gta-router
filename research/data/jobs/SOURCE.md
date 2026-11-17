# Jobs data: sources, method, and known problems

Access date: 2026-09-12

## What this table is for

The study needs a jobs count per zone, so that measure B (access score) can
count "how many jobs can this origin reach in 45 minutes". This file
documents where that jobs number comes from, what geography it is at, and a
serious limitation: the 2021 Census count of workers is depressed by
pandemic work-from-home, which spreads unevenly across the GTA.

## Table chosen and why

**Statistics Canada table 98-10-0498-01**, "Employment income groups by
place of work status: Census metropolitan areas, tracted census
agglomerations and census tracts of work", 2021 Census, 25% sample data.

- Publisher: Statistics Canada
- URL: https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=9810049801
- Licence: Statistics Canada Open Licence
- File used: `raw/98100498.csv` (downloaded earlier in this project, already
  present when this task started; not re-downloaded)

This was the only one of the three place-of-work tables in `raw/` that
actually had row-level data downloaded (98100493 and 98100496 only had
their metadata JSON saved, no CSV, so they were not usable). Table 98100498
also happens to be tabulated by **place of work**, i.e. by census tract of
the workplace, not by home census tract, which is exactly what a jobs-by-
zone count needs. Its "Place of work status" breakdown (Total / Worked at
home / Usual place of work) is also what lets the work-from-home problem
below be measured directly from the same file.

We treat "Usual place of work" x "Total - Employment income" as the jobs
count for the CT. This is the total number of workers aged 15+ (2021 Census
25% sample) whose usual workplace is in that census tract, regardless of
whether they reported any employment income. It excludes people who worked
mainly from home (their workplace-status row is "Worked at home", tied to
their home CT, not to any job location) and people with no fixed workplace
address (delivery drivers, tradespeople, etc.), because those two groups
cannot be placed at a single work location.

## Geography

**Census tracts (CTs), 2021 boundaries.** This is finer than a census
division or census subdivision, but coarser than a dissemination area (the
unit the rest of the study uses for origins). CTs only exist inside census
metropolitan areas (CMAs) and tracted census agglomerations; StatCan does
not subdivide rural, low-density areas into tracts.

Boundary file used: `raw/lct_000b21a_e.zip` ("Census Tracts, 2021, cartographic
boundary file"), Statistics Canada, EPSG:3347 (Statistics Canada Lambert),
downloaded already present in `raw/`.

To keep only CTs inside the five study CDs (3518 Durham, 3519 York, 3520
Toronto, 3521 Peel, 3524 Halton), we used the census subdivision (CSD)
boundary file `raw/lcsd000b21a_e.zip` (StatCan, valid download, 5,161 CSDs)
to build the union of all CSDs whose first 4 digits (the CDUID) match one of
the five study CDs (27 CSDs). A CT is kept if at least half of its area
falls inside that union. This is a CD-based filter, not a CMA-based one, so
it correctly includes census tracts in **both** the Toronto CMA (535) and
the Oshawa CMA (532), since part of Durham Region (Clarington and points
east) belongs to the Oshawa CMA rather than the Toronto CMA.

Note: `raw/lcd_000b21a_e.zip` (census division cartographic boundary file)
in this folder is a **truncated/corrupt download** (`unzip` reports "cannot
find zipfile directory", i.e. an incomplete file). It was not needed for
this build because the CSD file gives CDUID directly, but it should be
re-downloaded if a future script in this folder needs CD polygons directly.

**Coverage:** the kept census tracts cover about **87% of the land area**
of the five study CDs. The remaining 13% is mostly the rural, low-density
fringe (parts of northern Durham, York, Peel and Halton, e.g. Brock,
Scugog, Uxbridge, Caledon's rural areas, Halton Hills' rural areas) that
StatCan does not divide into tracts. Jobs located in that fringe are not
counted at all in this table; there is no finer StatCan geography that
covers them for place of work. This is disclosed here, not silently
dropped: `needs_from_user` below.

## Files produced

- **`jobs_gta.csv`**: `geo_id` (CTUID, string), `geo_type` ("CT"), `jobs`
  (float, worker count, blank if suppressed), `year` (2021), `definition`
  (plain-language description of what the number is). 1,339 rows (1,339
  census tracts kept; one row per tract).
- **`jobs_gta.gpkg`**: same columns plus a `geometry` point per tract
  (EPSG:4326). The point is `representative_point()` of the tract polygon,
  which is guaranteed to fall inside the polygon (unlike a plain centroid,
  which can land outside an oddly shaped tract).

Of the 1,339 tracts, **15 have a blank `jobs` value** because Statistics
Canada suppressed the cell (marked "x" in the source CSV, likely low
population counts, e.g. the Toronto Islands, Pearson Airport lands, and
similar industrial/park tracts with almost no resident or working
population). These are left blank rather than guessed at zero.

Total jobs captured across all non-suppressed tracts: **1,740,380**. This
is a workforce count (workers with a usual workplace there), not an
establishment-based jobs count, and it is a lower bound because of the
work-from-home problem below and the 13% of land area with no tract-level
data.

## The May 2021 work-from-home undercount

The 2021 Census was taken in May 2021, during COVID-19 public health
restrictions, when a large share of the labour force was working from home
rather than travelling to their usual workplace. Table 98100498's own
"Worked at home" row shows how large this effect was, right in the GTA:

| CMA | Total workers | Worked at home | Share worked at home |
|---|---|---|---|
| Toronto CMA (535) | 2,664,205 | 1,028,180 | 38.6% |
| Oshawa CMA (532) | 133,960 | 50,985 | 38.1% |

(Computed directly from `raw/98100498.csv`, CMA-level rows, "Total -
Place of work status" and "Worked at home" rows, `Total - Employment
income` column.)

For comparison, Statistics Canada's national 2021 Census release reports
that **24.3%** of the Canadian working population worked most of their
hours from home in May 2021, versus **7.4%** at the time of the 2016
Census (StatCan, "Working from home: Productivity and preferences",
https://www150.statcan.gc.ca/n1/pub/45-28-0001/2021001/article/00012-eng.htm,
and related 2021 Census labour release commentary). The Toronto CMA's
38.6% is well above that national figure, which is expected: the region has
a large share of office, finance, professional and tech jobs, the
occupations most able to shift to remote work during the pandemic.

We were **not able to retrieve a directly comparable 2016 figure at the
Toronto-CMA or census-tract level** in this session: the 2016 Census Profile
page for Toronto CMA that would carry it
(www12.statcan.gc.ca/census-recensement/2016/dp-pd/prof/...) returned "File
not found" when fetched on 2026-09-12 (the page may have been retired from
StatCan's site). Only the national 7.4% vs 24.3% figures above could be
confirmed from a live StatCan source. A CMA-level or CT-level 2016 "place of
work status" table likely still exists as a StatCan custom tabulation or
CODR table, but locating and downloading it was not done here; see
`needs_from_user`.

**What this means for the study:** the jobs count in `jobs_gta.csv` almost
certainly **undercounts true job locations**, because a very large share of
GTA workers (about 2 in 5, per the table above) were counted at their home
address rather than their workplace in May 2021. This undercount is not
uniform across the GTA: it is worst in census tracts with many
office/professional jobs (e.g. downtown Toronto, North York Centre,
Mississauga City Centre) and least severe in tracts with manufacturing,
warehousing, retail, and other on-site-only jobs, which would have kept
more of their workers going in. So this table likely **understates job
totals in white-collar employment centres relative to industrial and
retail zones**, and any access-to-jobs score built on it will be biased in
that direction. This should be stated plainly in the study's "limits of
this study" section (Plan section 8, item 4 / section 7 known problems).

## Known problems (full list)

1. 2021 Census place-of-work counts are taken in May 2021, during COVID-19
   restrictions; workers who worked mainly from home are not counted at
   their workplace location. See quantification above. This affects every
   number in `jobs_gta.csv`, unevenly across the region.
2. Table 98100498 only reports at census tract granularity, not
   dissemination area. This is coarser than the DA-level origins used
   elsewhere in the study; each origin's isochrone will pick up whichever
   whole or partial CTs it overlaps, not DA-level job detail.
3. Census tracts only exist inside CMAs/tracted CAs. About 13% of the
   five-CD land area (mostly rural fringe) has no CT and so no jobs figure
   at all in this table.
4. 15 of 1,339 kept census tracts have a suppressed ("x") cell in the
   source table and are left blank in `jobs_gta.csv` rather than guessed.
5. `raw/lcd_000b21a_e.zip` (CD boundary file) in this folder is a corrupt/
   incomplete download and was not used; CSD boundaries were used instead
   to build the 5-CD filter.
6. This is a workforce head-count (persons), not a distinct "number of
   jobs" in the labour-market sense of job openings/positions; for most
   purposes (someone employed full-time in one place) the two are close,
   but a small share of workers hold more than one job, which this table
   does not capture.
7. The 2016-vs-2021 comparison above is at the national level only; a
   directly comparable Toronto-CMA or CT-level 2016 figure was not
   retrieved in this session (see needs_from_user).

## needs_from_user

- **TTS 2022 zone employment** is pending the owner's registration with the
  U of T Data Management Group (iDRS access) per the research plan. If it
  arrives, it may offer a finer or more current employment-by-zone number
  than this Census-based one, and would not have the May-2021 COVID
  distortion (TTS is collected in fall).
- If a finer StatCan geography for jobs by place of work becomes available
  (e.g. a dissemination-block or dissemination-area level custom
  tabulation), it would improve on the census-tract granularity used here.
- If the owner wants the CMA-level 2016 vs 2021 work-from-home comparison at
  finer than the national level, someone would need to track down the
  2016 equivalent of table 98100498 (or the 2016 Census Profile's "Journey
  to work" section for Toronto CMA) from Statistics Canada; the specific
  page tried on 2026-09-12 no longer resolves.
