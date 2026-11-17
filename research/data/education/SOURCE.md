# Education and libraries: sources and build notes

Topic folder: research/data/education/
Access date for everything below: 2026-09-12
Study area: 2021 census divisions 3518 Durham, 3519 York, 3520 Toronto,
3521 Peel, 3524 Halton.

Output: education_gta.gpkg, layer "education_gta", EPSG:4326, point geometry.
Columns: id, name, type, operator_or_board, is_private, sources, cdname,
geometry. type is one of secondary_school, post_secondary_campus,
public_library_branch. Build script: build_education.py (re-run it any
time raw/ changes; it always rewrites the GeoPackage from scratch).

Row counts in the final file (2026-09-12 run, after the academic-library
removal, post-secondary merge, and stale-name fixes described below):
- secondary_school: 352 (339 from SIF, 13 private schools from OSM)
- post_secondary_campus: 204 (after merging 37 same-institution/same-campus
  pairs and dropping 2 records for a confirmed-closed facility)
- public_library_branch: 216 (127 from municipal open data, 89 from OSM,
  after removing 53 academic/institutional/non-public OSM "library" records)
- Total: 772

By census division (post-sec/library/secondary): Toronto 121/100/152,
Peel 51/37/71, York 10/38/57, Durham 13/21/37, Halton 9/20/35.

---

## Files already in raw/ before this run (not downloaded by this pass)

These were placed in raw/ before this pass started. I did not re-download
them; I inspected each one's actual structure before using it (see notes
below, several needed a different treatment than a first glance suggests).

1. **sif_2024_25_en.xlsx** -- Ontario Ministry of Education, School
   Information Finder (SIF), school year 2024-25. Public/Catholic/
   Protestant-separate school locations, one row per school, includes
   Latitude/Longitude and "School Level" (Elementary/Secondary). Used for
   all non-private secondary schools. Source: Ontario open data
   ("School information and student demographics"), publisher Ontario
   Ministry of Education, licence Open Government Licence - Ontario.
   4947 data rows for all of Ontario. No private schools in this file.

2. **private_school_contact_information_eng.csv** -- Ontario Ministry of
   Education list of private schools with OSSD-credit status. 1675 rows.
   Publisher: Ontario Ministry of Education. **Has no coordinates**
   (address only), so it was NOT used to place points on the map. It was
   used only as a name cross-check while building the private-secondary
   list from OSM (see known_problems: some named private secondary
   schools in this file could not be placed).

3. **osm_schools.osm.pbf / osm_schools.geojsonseq** -- OpenStreetMap
   extract (from the router's gta.osm.pbf), amenity=school nodes/ways,
   converted to a GeoJSON sequence. 2582 amenity=school features in the
   extract before any filtering. Used only for private secondary schools
   (SIF has none), matched on operator:type=private and isced:level
   containing "3".

4. **osm_edu_lib.osm.pbf / osm_edu_lib.geojsonseq** -- OpenStreetMap
   extract, education- and library-related amenities (library, university,
   college, school, childcare, etc.), 1972 features. Used for: (a) public
   library branches everywhere the municipality does not publish its own
   branch list, (b) a supplement to ODEF for post-secondary campuses ODEF
   does not carry (see known_problems), (c) cross-check for library dedup.

5. **tpl_branches_4326.geojson** -- Toronto Public Library branch list,
   already reprojected to EPSG:4326. 112 features, 100 of which have
   PhysicalBranch=1 and real coordinates (the other 12 are non-physical
   services: Answerline, two Bookmobiles, Home Library Service, Interloan,
   Departmental Staff, Literacy Deposits, the Merril and Osborne special
   collections, the Automated Phone System, and the Virtual Library --
   correctly excluded, they are not branches you can walk into or reach a
   fixed point at). Source: City of Toronto Open Data ("Library Branch
   General Information"), publisher Toronto Public Library, licence Open
   Government Licence - Toronto.

6. **mississauga_city_libraries.geojson** -- City of Mississauga open
   data, "Libraries" layer, 18 features. Name field is `LANDMARKNAME`
   (an earlier draft of this script looked for `Name`/`BranchName` and
   silently mislabelled every Mississauga branch "branch" -- fixed).

7. **brampton_libraries.geojson** -- City of Brampton open data,
   9 features. Name field is `FACILITY_NAME`.

8. **burlington_libraries.geojson** -- City of Burlington open data,
   7 features. **Every feature's `NAME` property is null** -- this file
   has coordinates but no usable branch names at all. It is NOT used in
   the build; Burlington's 7-8 branches come from OSM instead, which has
   them properly named ("Burlington Public Library - Tansley Woods
   Branch", "- Central Branch", etc.). Kept in raw/ for reference only.

9. **lcd_000a21a_e.zip / raw/cd/*** -- Statistics Canada 2021 Census
   Divisions boundary file (cartographic boundary file, "lcda000a21a_e").
   Used to spatially filter every point layer to the 5 study CDs and to
   attach `cdname`.

---

## Downloaded in this pass (approved sources)

10. **odef/ODEF_v2.1.zip -> ODEF_v2.1_EN/** (already unzipped in raw/odef/
    before this pass). Statistics Canada, Open Database of Education
    Facilities (ODEF), version 2.1. National point file of education
    facilities with an ISCED-level flag per row. Publisher: Statistics
    Canada. Licence: Statistics Canada Open Licence.
    URL (package page): https://www150.statcan.gc.ca/n1/pub/27-26-0001/272600012022001-eng.htm
    Used for post-secondary campuses: filtered to Prov_Terr == "ON" and
    ISCED4Plus == "1" (ODEF's own post-secondary flag). 286 rows for all
    of Ontario before the spatial filter to the 5 CDs; 269 of those had
    usable coordinates.

11. **libstats_2024.xlsx** and **libstats_2023.csv** -- Ontario Public
    Library Statistics ("LibStats"), Ontario Ministry of Tourism, Culture
    and Gaming, via data.ontario.ca. Downloaded 2026-09-12 in this pass:
    - https://data.ontario.ca/dataset/363fff31-6a07-41eb-9922-e9b64192b08b/resource/c264e3ff-b076-48bb-affd-c3597a416ee3/download/opendata_2024_ontario_library_statistics.xlsx
    - https://data.ontario.ca/dataset/363fff31-6a07-41eb-9922-e9b64192b08b/resource/751b0de6-9dcf-46aa-a19b-69a62e222617/download/ontario_public_library_statistics_open_data_2023.csv
    Licence: Open Government Licence - Ontario.
    **Not used in the final GeoPackage.** This file has one row per
    *library system* (headquarters), with a mailing/street address but
    **no latitude/longitude column anywhere in its ~330 columns**. It was
    used only to build the list of 22+4 public library systems that serve
    the study area (one main address row each: Ajax, Aurora, Brampton,
    Beaverton/Brock, Burlington, Bowmanville/Clarington, Halton Hills,
    King City, Markham, Milton, Mississauga, Newmarket, Oakville, Oshawa,
    Pickering, Richmond Hill, Port Perry/Scugog, Toronto, Uxbridge,
    Vaughan, Whitby, Stouffville, plus East Gwillimbury and Georgina under
    different town names) -- as a check that OSM's library coverage (see
    below) has at least one branch for every system in the study area. No
    approved geocoding source was available to turn these addresses into
    points, so they were not added as rows.

No other files were downloaded. I looked for York Region, Durham Region,
Halton (other than Burlington), and Caledon branch-level open data and did
not find dedicated portals in the time available; see known_problems.

---

## Method (see build_education.py for the exact code)

1. Load the 5 CD boundary polygons (EPSG:4326) from lcd_000a21a_e.shp.
2. **Secondary schools**: SIF rows with School Level == "Secondary" (all
   public/Catholic/Protestant-separate boards; SIF has no combined
   elementary+secondary grade ranges in Ontario -- checked the full list
   of Grade Range values, none crosses grade 8/9). Private secondary
   schools come only from OSM: amenity=school, operator:type=private,
   isced:level containing "3".
3. **Post-secondary campuses**: ODEF rows with Prov_Terr == ON and
   ISCED4Plus == "1" (covers universities, colleges, and 222 "Private
   Institution" career colleges across Ontario). Supplemented with OSM
   amenity=university/college points, MINUS (a) a short blacklist of
   non-institutional "college" tags OSM also carries (a forklift-training
   business, St. John Ambulance, a pizza-making class, a LINC language
   class, etc.) and (b) any OSM point within a fixed radius of the
   University of Toronto, Toronto Metropolitan University (Ryerson), or
   York University main-campus coordinates -- those big campuses have
   dozens of individual buildings, libraries, and federated colleges each
   tagged as their own amenity=college/university node in OSM, and ODEF
   already gives one point for the institution. This keeps genuinely
   separate campuses (UTSC, UTM, Glendon, McMaster's Toronto campus, a
   community college's satellite "Toronto Campus") while dropping
   same-campus noise.
4. **Public library branches**: Toronto, Mississauga, and Brampton branch
   lists from their own open-data portals (authoritative, loaded first).
   Everywhere else -- Halton (except Burlington had no usable names, see
   above so it also comes from OSM), York Region's local systems, Durham
   Region's local systems, and Caledon -- comes from the OSM extract's
   amenity=library points, since no dedicated branch-level open dataset
   was found for them.
5. Spatial filter: every point is joined against the 5 CD polygons; points
   outside all five are dropped, and `cdname` is set from the join.
6. Dedup, separately for each of the three types, in source-authority
   order (municipal/StatCan/SIF sources first, OSM last): a later point is
   dropped if (a) it normalizes to the same name and sits within 120 m of
   an earlier point, or (b) it sits within 60 m and one name contains the
   other (handles "TPL - X" vs "X Branch" style differences), or (c) it
   sits within 70 m of an earlier point of the same type at all (handles
   cases where an authoritative source and OSM name the same building
   differently, e.g. "Mississauga Library - Courtneypark" vs "Courtneypark
   Library").
7. `id` is a stable hash of (type, name, rounded coordinates), so re-runs
   produce the same ids as long as the input data doesn't change.

---

## Known problems (plain language)

- **Library branch completeness is uneven across the GTA.** Toronto,
  Mississauga, and Brampton have full official branch lists. Everywhere
  else (Oakville, Milton, Halton Hills, Burlington, every York Region town
  -- Vaughan, Markham, Richmond Hill, Newmarket, Aurora, King, East
  Gwillimbury, Georgina, Whitchurch-Stouffville --, every Durham Region
  town -- Oshawa, Whitby, Ajax, Pickering, Clarington, Uxbridge, Scugog,
  Brock --, and Caledon) relies on OpenStreetMap. I checked OSM's coverage
  against the Ontario LibStats 2024 list of library systems that serve the
  study area and it has at least one named branch for each of those
  systems, but I did not verify branch-by-branch completeness or that
  every OSM location is current. A branch that isn't mapped in OSM,
  moved recently, or is mistagged would be missing or misplaced here.
- **No approved geocoder was available.** The Ontario LibStats file has
  every library system's main address but no coordinates, and I did not
  find an approved (StatCan/Ontario/municipal) geocoding service to turn
  addresses into points, so LibStats could not fill the gap above.
- **U of T / TMU / York campus consolidation is a judgment call.** Their
  federated colleges, faculties, and satellite buildings inside the main
  campus footprint (e.g. Trinity College, Victoria College, individual
  Faculty buildings) are folded into the single ODEF point for the parent
  institution rather than listed separately, so this file undercounts
  "buildings" at those three campuses relative to a literal OSM count,
  by design (the study's unit is "physical campus", not "building").
  Other large multi-site colleges (Humber, Centennial, George Brown,
  Seneca) were not folded the same way, so they may show more than one
  point where their sites are close together -- this was not fully
  reconciled given the time available for this pass.
- **Private secondary schools are undercounted.** SIF has none at all, so
  every private secondary school here comes from OpenStreetMap tagging
  (operator:type=private + isced:level 3), which found 13 in the study
  area. The Ontario private-school contact list (raw/
  private_school_contact_information_eng.csv) names roughly 1675 private
  schools province-wide but has no coordinates, so private schools named
  in that list but not tagged correctly in OSM are missing here.
- **ODEF's ISCED4Plus flag is used as-is.** I did not independently verify
  every one of the 269 ODEF post-secondary rows in the study area; a
  closed or renamed private career college in ODEF's snapshot would carry
  through here as a real one.
- **Combined elementary/secondary grade ranges**: checked directly in SIF
  (Grade Range never spans grade 8 to grade 9 in this file) so this does
  not affect the SIF-sourced rows. It is a real pattern among *private*
  schools (their own file lists "Elem/Sec" for some), but since private
  schools aren't placed from that file (no coordinates), it does not
  currently affect any point in the output either way.
- **Post-secondary same-institution merge is name-token based, not a
  verified list.** `merge_postsecondary_campuses()` merges two
  post_secondary_campus records within 800 m if their names share a
  non-generic token (region/city words like "york", "markham",
  "scarborough" alone don't count, precisely because Seneca's "York
  Campus" sits on York University's Keele campus grounds but is a
  different institution -- an earlier version of this pass wrongly merged
  them on that basis and was caught and fixed). With ~260 candidate rows
  covering hundreds of small private career colleges, there may be a few
  remaining under- or over-merges not individually checked.
- **OSM library duplicate detection is not perfect beyond the academic/
  institutional filter.** A few OSM points look like duplicates of an
  already-counted branch under a generic name (e.g. two unnamed-branch
  "Oakville Public Library" / "Vaughan Public Libraries" points, a
  standalone "Brampton Public Library" point alongside Brampton's 7 named
  branches) but were not confidently identified as exact duplicates in the
  time available and were left in `public_library_branch`.

## Changelog (2026-09-12, this pass)

1. **public_library_branch now excludes academic/institutional/private
   libraries in all five CDs**, not just the 18+ Toronto examples flagged
   (Osgoode Hall Library, York's Scott and Steacie libraries, U of T's
   Gerstein Science Information Centre, etc.). `build_education.py` now has
   `NOT_PUBLIC_LIBRARY_OPERATOR` / `NOT_PUBLIC_LIBRARY_NAME` regexes that
   drop any OSM "library" whose operator or name says university, college,
   Law Society of Ontario, a hospital patient library, a community "seed
   library", a "resource centre" run by a non-library organization, or a
   secondary-school library (Georgetown District High School's "GDHS
   Library"); plus two specific untagged cases found by inspection (U of
   T's "Earth Sciences Library (Noranda)", York's "Nellie Langford Rowell
   Library") and one independent community library not part of any public
   system ("Ankara Library"). 53 OSM records excluded in total this run
   (see the build's stdout for the full list with operators).
   Also fixed: an OSM-tagged "Toronto Public Library - Eglinton Square"
   point sat about 190 m from the official TPL point for the same branch
   (same shopping-centre address, geocoded differently by each source) --
   just outside `dedup()`'s distance tolerance, so it survived as a false
   extra. Any OSM "library" record naming Toronto Public Library is now
   excluded outright, since the authoritative TPL branch list is already
   loaded separately. **Toronto now has exactly 100 public_library_branch
   rows, all from the official TPL list; no OSM extras remain in Toronto.**
   OSM extras are kept in the other four CDs (89 rows: Durham, Halton
   outside Burlington, York Region's town libraries, and Peel's Caledon)
   because no dedicated municipal open-data branch list was found for
   those systems -- see "Library branch completeness is uneven" above.
2. **Merged duplicate post-secondary campuses.** Added
   `merge_postsecondary_campuses()`: a systematic same-institution
   (name-token overlap, ignoring generic campus/region words) + proximity
   (<=800 m) pass over all 260 candidate post_secondary_campus records
   before the general dedup step, run as its own pass rather than folded
   into the generic `dedup()` (which only merges near-exact names within
   120 m). 37 same-institution/same-campus pairs merged, including the
   flagged cases: Seneca College - King Campus (2 records, ~590 m apart),
   Seneca College - Markham Campus (2 records, ~200 m apart), and Humber's
   North campus (2 records, ~180 m apart, tagged "Humber College Institute
   of Technology & Advanced Learning" vs "Humber Polytechnic"), plus
   Humber's Lakeshore campus (3 records) and several dozen private career-
   college near-duplicates. One real false-merge risk was caught and fixed
   during this pass: an early version merged Seneca's "York Campus" into
   "York University" because both names contain "york" -- fixed by
   requiring at least one non-generic (institution-identifying) token to
   overlap, not just a shared place name (see Known problems).
   Also dropped 2 records for a confirmed-closed facility found during
   this check: Durham College and Centennial College's jointly-run
   "Pickering Learning Site" closed permanently 2020-09-01 (COVID-19
   operational review; opened 2012). Kept out rather than reported as a
   current destination -- see durhamcollege.ca's own "Pickering Learning
   Site" news post and the closure announcement covered by Durham Radio
   News and educationnewscanada.com.
3. **Fixed stale/confusing names** (`STALE_NAME_FIXES` in
   `build_education.py`): "Ryerson University" -> "Toronto Metropolitan
   University" (renamed 2022); "University of Toronto (Admission And
   Awards)" -> "University of Toronto St. George"; a misspelling "Geroge
   Brown Theatre School" -> "George Brown Theatre School"; and, found while
   checking for other stale names, Humber's and Seneca's post-2022/2024
   rebrands applied to their merged campus records: "Humber College
   Institute of Technology & Advanced Learning" -> "Humber Polytechnic -
   North Campus", the merged Lakeshore record -> "Humber Polytechnic -
   Lakeshore Campus", and the three merged Seneca campus records -> "Seneca
   Polytechnic - King Campus" / "- Markham Campus" / "- Newnham Campus".
4. Row counts above were regenerated from these changes; see the top of
   this file.
