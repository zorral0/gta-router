# Healthcare destinations, GTA

Access date for all sources: 2026-09-12.

## What this builds

`healthcare_gta.gpkg` (layer `healthcare_gta`, EPSG:4326, point geometry) and
`healthcare_gta.csv` (same rows, with lon/lat columns instead of geometry).

**Government lists only.** Every record comes from Statistics Canada's ODHF
or the Ontario Ministry of Health's MOHSERLO service-provider list, so
coverage is consistent across all five census divisions. OpenStreetMap is
NOT a source of records: it is used only to try to confirm the location of
a government-listed record (see `osm_location_check` below), never to add a
place that isn't already in ODHF or MOHSERLO.

Types kept:
- `hospital_emergency`: an acute-care hospital site with a full emergency
  department
- `urgent_care`: an urgent care centre, or a hospital-operated site that is
  not a full emergency department (see "Emergency status" below)
- `walk_in_clinic`: a walk-in clinic that is not part of a hospital
- `organized_primary_care`: family health teams, community health centres
  (CHCs), nurse-practitioner-led clinics, Indigenous primary health care
  organizations, family health organizations where MOHSERLO/ODHF list them

Excluded on purpose: solo/small family-doctor offices not part of an
organized primary-care model, pharmacies, dentists, labs and specimen
collection, imaging/diagnostic, long-term care and retirement homes,
specialist-only practices (cardiology, dermatology, oncology, etc.),
rehab-only, mental-health/addiction-only, and complex continuing care
hospitals, physiotherapy, chiropractic, optometry, and similar allied-health
or non-primary-care services. Every excluded record and why is in
`excluded_records.csv` (records kept as `urgent_care` but flagged for manual
review are also logged there, prefixed `KEPT AS URGENT_CARE, FLAGGED:`).

**Important limitation: `walk_in_clinic` is effectively empty.** Neither
MOHSERLO nor ODHF has a service-type category for walk-in clinics -- Ontario
walk-in clinics are typically OHIP-billing family-doctor offices with no
separate government registration as "walk-in", unlike Family Health Teams or
CHCs, which are registered organizational models. Under the government-only
rule, this type cannot be populated from these two sources; the previous
version of this dataset (see Known problems) filled it from OpenStreetMap,
which is no longer allowed to contribute records. This is reported rather
than worked around by guessing.

Study area: 2021 census divisions 3518 Durham, 3519 York, 3520 Toronto,
3521 Peel, 3524 Halton. A record is kept if its point falls inside one of
these five census divisions (2021 CD boundaries), with a 250 m nearest-CD
fallback for points that miss every CD by a small margin (coastline/edge
generalization in the boundary file).

## Sources

1. **Statistics Canada, Open Database of Healthcare Facilities (ODHF) v1.1**
   - URL: https://www150.statcan.gc.ca/n1/en/pub/13-26-0001/2020001/ODHF_v1.1.zip
   - Landing page: https://www.statcan.gc.ca/en/lode/databases/odhf
   - Publisher: Statistics Canada
   - Licence: Statistics Canada Open Licence
   - Data currency: collected Nov 2019-Mar 2020 (initial), updated May-Jun 2020
     for v1.1. This is the oldest source used here (about 6 years old at the
     study date), so ODHF-only hospital/urgent-care records that do not also
     appear in the current MOHSERLO list are treated as possibly closed or
     renamed and dropped after matching (see Known problems).
   - Already in `raw/ODHF_v1.1.zip`, reused as-is (not re-downloaded this
     session). Extracted to `raw/odhf/ODHF_v1.1/odhf_v1.1.csv`.
   - Ontario rows (Pruid == 35): 2,652 with usable coordinates (43 dropped
     for missing lat/long).

2. **Ontario Ministry of Health, Service Provider Locations (MOHSERLO)**
   - Source: Ontario GeoHub / Land Information Ontario (LIO) ArcGIS REST
     service, layer `LIO_Open09/MapServer/26`
   - Query URL used by the build script:
     https://ws.lioservices.lrc.gov.on.ca/arcgis2/rest/services/LIO_OPEN_DATA/LIO_Open09/MapServer/26/query
   - Publisher: Government of Ontario, Ministry of Health
   - Licence: Open Government Licence - Ontario
   - Already downloaded to `raw/mohserlo.geojson` (11,625 Ontario records,
     all service types), reused as-is (not re-downloaded this session).
   - Covers hospitals and organized primary-care models (Family Health
     Teams, CHCs, NP-led clinics, Indigenous primary health care
     organizations). It does not include solo/small family-doctor practices
     that are not part of one of those organized models, and it has no
     separate category for walk-in clinics (see limitation above).

3. **Ontario Health, "Time Spent in Emergency Departments" hospital list**
   - URL: https://www.ontariohealth.ca/system/reporting/performance/time-spent-in-emergency-departments
   - Publisher: Ontario Health (data underlying it: NACRS, Canadian Institute
     for Health Information)
   - Used only to decide which hospital sites (from MOHSERLO/ODHF) have a
     full emergency department, since MOHSERLO's own fields (`SERVICE_TYPE`
     / `SERVICE_TYPE_DETAIL`) only say "Hospital" / "Corporation" or "Site"
     and do not say whether a site has an ED.
   - The full list of ~175 reporting hospital site names, scraped from the
     page's "Compare results across hospitals" table on 2026-09-12, is
     hardcoded into `build_healthcare.py` as `ER_REPORTING_HOSPITALS`
     (`ER_REPORTING_URL` in the script points back to this page). A hospital
     name is matched against this list by normalized token overlap
     (`matches_er_list`).
   - This list is a good but imperfect proxy for "has a full ER": a few
     sites publicly report ED wait times without running what their own
     operator calls a full emergency department. Four such cases were found
     for this study area and are hardcoded overrides
     (`KNOWN_NOT_FULL_ER`) -- see "Emergency status" below.

4. **OpenStreetMap**, from the repo's `gta.osm.pbf` (already downloaded for
   the router, not fetched by this task), used only for location
   confirmation, never to add or classify a record.
   - Extracted with osmium (`/opt/homebrew/bin/osmium`) to
     `raw/osm_health.osm.pbf` (tags-filter on `amenity=hospital,clinic,doctors`
     and any `healthcare=*` tag), then exported to GeoJSON Seq
     (`raw/osm_health_ids.geojsonseq`, regenerated by the build script).
   - Licence: OpenStreetMap contributors, Open Database Licence (ODbL)
   - For every kept ODHF/MOHSERLO record, the script looks for an OSM
     healthcare feature within 300 m with a similar name
     (`osm_location_check` column: `confirmed_by_osm` / `no_osm_match`).
     No record's coordinates were changed from a "correction" this run --
     see Known problems.

5. **Statistics Canada, 2021 Census Divisions boundary file**
   (`lcd_000b21a_e.zip`), used only to clip points to the five study CDs and
   to attach `cdname`/`cduid`.
   - URL: https://www12.statcan.gc.ca/census-recensement/2021/geo/sip-pis/boundary-limites/files-fichiers/lcd_000b21a_e.zip
   - Publisher: Statistics Canada
   - Licence: Statistics Canada Open Licence
   - Already in `raw/lcd_000b21a_e.zip` and extracted to `raw/cd/`, reused
     as-is.

## Emergency status: how hospital_emergency vs urgent_care is decided

1. Classify every MOHSERLO/ODHF "Hospital" record into scope using the same
   specialist/rehab/psychiatric/mental-health exclusion rules as before
   (`SPECIALIST_HOSPITAL`). Sites excluded here never become a health
   destination in this dataset (e.g. Ontario Shores, CAMH, Bridgepoint,
   Baycrest, Lakeridge Health - Whitby, Unity Health Toronto - Providence).
2. Match the remaining name against the Ontario Health ED-reporting list
   (source 3 above). A match -> `hospital_emergency`. No match ->
   `urgent_care` (the record is still a real, government-listed hospital
   site, just not one with a public full-ED wait-time report).
3. Four sites are hardcoded overrides to `urgent_care` even though the
   automatic match would say otherwise, based on checking each one
   individually against its own operator's public statements (2026-09-12):
   - **William Osler Health System - Peel Memorial** (Brampton): matches
     the Ontario Health list, but William Osler's own emergency-and-urgent-
     care page states Peel Memorial "currently has no emergency department"
     and runs a 24/7 Urgent Care Centre instead; a new ED is a future
     redevelopment plan, not yet open.
     (https://www.williamoslerhs.ca/en/areas-of-care/emergency-and-urgent-care.aspx)
   - **Women's College Hospital** (Toronto): does not match the Ontario
     Health list at all. Has no emergency department; its former Urgent
     Care Centre is closed, replaced by a referral-only Acute Ambulatory
     Care Unit. Kept as `urgent_care` as the closest of the four allowed
     types (flagged in `excluded_records.csv` for review, since "referral-
     only, no walk-in" does not perfectly fit `urgent_care` either).
   - **Humber River Health - York Finch** (Toronto, a.k.a. the Finch/Church
     Street site): does not match the list. Operates as an Urgent Care and
     Ambulatory Care centre; the hospital's 24/7 ED is at the Wilson site
     only.
   - **Lakeridge Health - Jerry Coughlan** (Ajax-Pickering's Jerry Coughlan
     Health and Wellness Centre, Durham): does not match the list. A day-
     surgery and urgent-care building, not a full ED site.

No other GTA acute hospital site in MOHSERLO/ODHF was found missing from the
Ontario Health list once the above four are accounted for. One list entry,
"Mackenzie Health-Jane Street Site", has no MOHSERLO/ODHF match under that
exact name; research shows it is the Ontario Health reporting system's
legacy/alternate label for what MOHSERLO now lists as "MacKenzie Health -
Cortellucci Vaughan Hospital" (same physical hospital, at Jane St. and Major
Mackenzie Dr., not a second missing hospital).

### Mount Sinai Hospital (600 University Ave, Toronto)

Previously missing a `hospital` record (only its Family Health Team was
captured). Root cause: **a deduplication bug, not a classification bug.**
The old dedup step merged any hospital-type record within 300 m of an OSM
hospital-campus polygon into that polygon's cluster with no name-similarity
check. Mount Sinai's MOHSERLO point sits close enough to the OSM polygon for
University Health Network's Toronto General Hospital (they are across the
street from each other on University Ave) that Mount Sinai's record was
silently absorbed into the "Toronto General" cluster and its name and
identity were discarded, even though `classify_moh` correctly tagged it as
a hospital all along.

Fix: OpenStreetMap no longer contributes or merges hospital records at all
(see "Government lists only" above), so this polygon-merge step and its
no-name-check bug are gone entirely. Mount Sinai Hospital ("Sinai Health
System - Mount Sinai" in MOHSERLO, matched to "Sinai Health System-Mount
Sinai Site" in the Ontario Health list) now appears as its own
`hospital_emergency` row, confirmed present in the output.

## Method (see `build_healthcare.py`, re-runnable)

1. Load ODHF and MOHSERLO, classify each record into `hospital_emergency` /
   `urgent_care` / `organized_primary_care` / not in scope, using name-text
   exclusion rules, each source's own type fields, and the Ontario Health
   ED-reporting list (see above).
2. Clip every classified record to the five study CDs (measurements and
   distance buffers use EPSG:3161, NAD83 / Ontario MNR Lambert, metres).
3. Deduplicate across ODHF and MOHSERLO: records of the same type within
   75 m (`organized_primary_care`), 150 m (`urgent_care`/`walk_in_clinic`),
   or 300 m (`hospital_emergency`, since campuses are large) with similar
   names (token overlap or fuzzy string match) are merged into one place.
   The kept name/location favours MOHSERLO, then ODHF; the `sources` column
   lists every source that had a matching record.
4. Drop ODHF-only hospital/urgent-care records that have no match in
   MOHSERLO (ODHF is the oldest source; an unmatched ODHF-only record is
   treated as possibly closed, renamed, or reclassified since 2020).
5. For every surviving record, check OSM for a same-named feature within
   300 m and record `confirmed_by_osm` / `no_osm_match` in
   `osm_location_check`. This never adds, removes, or classifies a record;
   it is purely an annotation for later manual spot-checking.
6. Write the GeoPackage and CSV, plus `excluded_records.csv` (every dropped
   or flagged source record and the reason).

Re-run with:
`research/.venv/bin/python research/data/healthcare/build_healthcare.py`

## Row counts (this run, 2026-09-12)

Source records after clipping to the five CDs, and how many were kept:
- ODHF: 745 in the five CDs, 86 kept (55 organized_primary_care,
  23 hospital_emergency, 8 urgent_care)
- MOHSERLO: 4,567 in the five CDs, 180 kept (145 organized_primary_care,
  31 hospital_emergency, 4 urgent_care)
- Total before dedup: 266 kept records -> 204 places after dedup
- 6 ODHF-only hospital/urgent-care records dropped as stale (no MOHSERLO
  match): Blue Hills Child and Family Centre (York), Markham Stouffville
  Hospital - Uxbridge Site (Durham, now MOHSERLO's Oak Valley Health -
  Uxbridge), St. Michael's Hospital - Bond St. Site (Toronto, now Unity
  Health Toronto - St. Michael's), the Scarborough Hospital - General
  Campus and - Grace Campus (Toronto, now Scarborough Health Network sites),
  Toronto East General Hospital (Toronto, now Michael Garron Hospital).
- Excluded (out of scope, all sources, all of Ontario before clipping,
  logged in `excluded_records.csv`): mostly pharmacies, mental health and
  addiction organizations, retirement/long-term care homes, labs, and
  various specialist/allied-health services not in MOHSERLO's organized
  primary-care categories.

**Final `healthcare_gta.gpkg`: 198 rows.**

By type:
- `hospital_emergency`: 31
- `urgent_care`: 4 (Peel Memorial, Women's College Hospital, Humber River -
  York Finch, Lakeridge Health - Jerry Coughlan -- see overrides above)
- `walk_in_clinic`: 0 (see limitation above)
- `organized_primary_care`: 163

By census division:
| CD | hospital_emergency | urgent_care | walk_in_clinic | organized_primary_care | Total |
|---|---|---|---|---|---|
| Durham | 5 | 1 | 0 | 10 | 16 |
| Halton | 4 | 0 | 0 | 8 | 12 |
| Peel | 3 | 1 | 0 | 18 | 22 |
| Toronto | 15 | 2 | 0 | 110 | 127 |
| York | 4 | 0 | 0 | 17 | 21 |
| **Total** | **31** | **4** | **0** | **163** | **198** |

`osm_location_check`: 96 `confirmed_by_osm`, 102 `no_osm_match` (a
`no_osm_match` is expected for many organized-primary-care sites, since
OSM's family-doctor/clinic tagging is uneven; it is not evidence the
government-listed record is wrong).

## Known problems

- **Row count dropped sharply from the previous (OSM-inclusive) build**
  (1,049 rows) to 198, almost entirely because `organized_primary_care`
  (163) no longer includes the roughly 795 solo-doctor/OSM-only clinics
  that used to make up most of `family_practice_or_community_health`, and
  `walk_in_clinic` went from 112 (OSM-derived) to 0. This is the direct,
  expected consequence of the "government lists only" decision, not a bug:
  MOHSERLO/ODHF simply do not register solo family doctors or walk-in
  clinics as such. If per-area primary-care or walk-in-clinic access is a
  key output of the study, this is worth revisiting with the study owner,
  since coverage is now consistent across CDs but much sparser than the
  real number of storefront clinics.
- **Classification is rule-based (regex on names and source type codes),
  not manually checked record by record**, apart from the four hardcoded
  ER overrides and the Mount Sinai fix, which were individually verified.
  With ~200 final records there may be some remaining misclassifications.
- **The Ontario Health ED-reporting list is a proxy, not a legal register
  of "which hospitals have an ER."** It is possible other sites in the list
  (beyond the four checked here) also don't run a full ED, or that a site
  without list membership does run one under a different reporting name;
  only Peel Memorial, Women's College, Humber River - York Finch, and Jerry
  Coughlan were individually checked against outside sources for this
  study, because they were flagged by the study owner. A `hospital` record
  classified as `urgent_care` for "not on the ED list" (rather than by an
  explicit override) is tagged with a reason in `excluded_records.csv`
  starting `KEPT AS URGENT_CARE, FLAGGED:` so they can be spot-checked.
- **ODHF is from 2020, about 6 years old.** Its hospital/urgent-care records
  were cross-checked by name/location against MOHSERLO (current) and
  unmatched ODHF-only ones were dropped, but ODHF-only
  `organized_primary_care` records that were NOT dropped (only
  hospital/urgent-care records get this stale check) could still be closed
  or moved.
- **No location "corrections" were made this run.** OSM location-checking
  only annotates (`osm_location_check`); no coordinates were changed based
  on an OSM mismatch. A future pass could compare `no_osm_match` records by
  hand and, where OSM clearly shows a different real-world location for the
  same named facility, use that to correct the point -- none of this run's
  mismatches were reviewed closely enough to justify an automatic change.
- **Deduplication is approximate.** The 75 m / 150 m / 300 m radius and
  name-similarity rule will occasionally merge two genuinely separate
  nearby clinics that share a similar name, or fail to merge two records of
  the same clinic if the name differs a lot between sources.
  `n_source_records` and `source_ids` in the output let you check any given
  row's merge.
- **"organized_primary_care" is a broad bucket.** It mixes large
  multi-physician Family Health Teams, small CHCs, and NP-led clinics with
  no size or capacity information, so a simple count per area treats a
  20-physician FHT the same as a 2-person NP-led clinic.
- **No manual field verification of coordinates.** Both sources can contain
  address or geocoding errors; points were not checked against a map or a
  phone book by a person in this run, beyond the OSM proximity check above.

## Changelog

- 2026-09-12: Switched to a government-lists-only model (MOHSERLO + ODHF).
  Removed OpenStreetMap as a record source; OSM is now used only to
  annotate whether a government-listed record's location is corroborated
  nearby (`osm_location_check`). Renamed/redefined types to
  `hospital_emergency`, `urgent_care`, `walk_in_clinic`,
  `organized_primary_care`. Added an Ontario Health ED-reporting-list check
  to decide `hospital_emergency` vs `urgent_care`, with documented
  overrides for Peel Memorial, Women's College Hospital, Humber River -
  York Finch, and Lakeridge Health - Jerry Coughlan. Fixed the
  deduplication bug that had silently merged Mount Sinai Hospital into
  University Health Network - Toronto General Hospital's cluster (no
  name-similarity check on the old OSM-polygon merge rule); Mount Sinai now
  appears as its own `hospital_emergency` record. Noted that
  `walk_in_clinic` cannot be populated under the government-only rule
  (neither source has a walk-in-clinic category).
