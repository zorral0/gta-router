# Grocery exclusion audit

This audits the 209 rows in `grocery_excluded_review.csv` whose original exclusion
rule was one of:

- `shop=greengrocer, small or specialty` (116 rows)
- `shop=grocery, small or specialty` (8 rows)
- `supermarket tag but specialty/convenience name` (85 rows)

Department stores, wholesale/warehouse clubs, and the one entrance-node row were
out of scope and were not touched.

## Question being answered

For each row: could a household plausibly do most of its regular grocery
shopping there? This includes independent, ethnic, halal, Asian, Caribbean,
Latin American and South Asian supermarkets, and large fruit/produce markets.
It excludes single-category specialty shops (bakery, butcher-only, bulk foods,
candy, tea/coffee, nuts, spices, cheese-only, dollar/variety/convenience
stores, health-supplement shops, prepared-food counters) even if the raw OSM
data made them look larger than they are.

## Evidence used

1. **Name, brand, and shop tag** from `grocery_excluded_review.csv`.
2. **Building footprint area in square metres.** Buildings were extracted from
   `engine/gta.osm.pbf` with osmium (`tags-filter ... w/building`), narrowed to
   buildings near the 209 points, converted to UTM zone 17N, and joined to each
   point by point-in-polygon containment. A footprint was found for 201 of the
   209 rows (96%). The other 8 points did not fall inside any mapped building
   footprint; for those, footprint area was left blank and the decision relied
   on the name alone.
3. Known local chain identity where the name alone is decisive (see below).

## Decision rule, in order of priority

1. **Known chain overrides.** A short list of repeated or well-known chain
   names was decided once and applied consistently, because for these chains
   the OSM building footprint is unreliable (see limitations) or the name
   alone is well known locally:
   - **Bulk Barn** (49 rows) and **The Source Bulk Foods** (2 rows): dropped.
     These sell bulk dry goods (candy, grains, spices, nuts) by weight, not a
     general grocery range.
   - **Rabba** (23 rows, tagged `shop=supermarket`): kept. Rabba Fine Foods is
     a Toronto small-format grocery chain that many downtown residents without
     cars use as their nearest and most-used grocery store. This is a
     judgment call flagged for the study owner to confirm; several Rabba rows
     are in the spot-check file.
   - **Vince's Market** and **Agincourt Fruit Market**: kept. Both are
     established, large-format grocery businesses in the Toronto area,
     confirmed by very large footprints (67,237 m2 and 26,405 m2, these are
     mapped as whole shopping-plaza buildings, but the businesses themselves
     are genuinely large-format grocers).
   - A handful of other one-off names (Healthy Planet, The Low Carb Grocery,
     Your Dollar Store, Walmart Produce, bakeries, a butcher shop, a spice
     shop, an herbalist shop, etc.) were decided individually because the
     name made the category unambiguous. Each has its own reason in the
     `reason` column of the draft file.

2. **Footprint-based rule**, applied to everything not covered by an override:
   - Footprint **under 250 m2**: treated as a small specialty shop and
     dropped, unless the name explicitly uses the word "grocery/groceries" in
     which case it is marked **unsure** for manual review (a small shop can
     still call itself a grocery).
   - Footprint **600 m2 or more**: treated as a substantial grocer and kept,
     unless the name is single-category specialty (bakery, cheese, deli-only,
     bulk foods, spice, nuts) with no grocery wording, in which case it is
     dropped, because very large footprints in this dataset are frequently a
     whole shared plaza building rather than the store's real size.
   - Footprint **250 to 600 m2** (mid-range): decided mostly by name.
     - For `shop=greengrocer` specifically, the tag itself signals a
       produce-focused shop, so mid-range greengrocers were dropped unless
       the name explicitly contains "grocery/groceries/grocer".
     - For other shop tags, a name with explicit grocery wording ("grocery",
       "supermarket", "mart", "halal meat & grocery", "world foods", "farm
       market") was kept; a name that is clearly single-category specialty
       was dropped; anything genuinely ambiguous was marked unsure.
   - **No footprint found**: decided by name only, using the same
     grocery-word test, with confidence capped at "low" or "medium" since
     there is no size evidence.

3. Multi-category names (for example "fruit, vegetable & flower market" or
   "fruits & deli") were treated as broader than a single-item specialty shop
   and evaluated on footprint rather than being auto-dropped for containing
   one specialty-sounding word.

## Results

Overall: **77 keep, 129 drop, 3 unsure** (of 209 audited rows).

By original rule:

| original rule | keep | drop | unsure |
|---|---|---|---|
| shop=greengrocer, small or specialty (116) | 48 | 65 | 3 |
| shop=grocery, small or specialty (8) | 3 | 5 | 0 |
| supermarket tag but specialty/convenience name (85) | 26 | 59 | 0 |

A footprint was found for 201 of 209 rows (96%). Bulk Barn (49 rows) and
Rabba (23 rows) together account for 72 of the 85 "supermarket tag" rows;
their brand-level decisions (drop and keep respectively) drive most of that
column.

Notable kept examples: Vince's Market, Agincourt Fruit Market, Al-Marwa
Grocery & Halal Meat Shop, Julimay African & Caribbean Continental Groceries,
Apna Farm, Dostana Grocers, Rabba (all locations).

Notable dropped examples: all Bulk Barn locations, The Source Bulk Foods,
Healthy Planet, The Low Carb Grocery, Your Dollar Store, numerous small
"[Name] Fruit Market" stands under 250 m2, bakeries, a butcher shop, a
Portuguese herbalist shop mistakenly readable as a grocer by name.

## Limitations

- **Shared building footprints.** Many of these shops sit inside strip malls
  or plazas that OSM maps as one building polygon covering several
  businesses. This inflates the recorded footprint for the shop that
  happens to be inside that polygon and can make a small unit look like a
  huge store. This is why footprint alone was not trusted for well-known
  single-category chains (Bulk Barn especially) and why it was cross-checked
  against the name and chain identity rather than used mechanically.
- **8 rows had no matched building footprint** at all (not inside any mapped
  building), so those decisions rest on the name only and carry low
  confidence.
- **Rabba is a genuine judgment call.** It is tagged `shop=supermarket` in
  OSM and functions as a small-format grocery store, but it is smaller and
  has a narrower selection than a typical big-box supermarket. This audit
  chose to keep it because of its role as a primary grocery source for many
  car-free Toronto residents, but the study owner may reasonably disagree;
  several Rabba rows are included in the spot-check file for that reason.
- **No street-view or business-listing verification was used** (per task
  scope, no web scraping). All decisions rest on OSM tags, names, and
  building footprints only. The google_maps_link column in the draft file is
  provided so the study owner can open each location and verify manually.
- **This audit does not re-run the main pipeline.** It only produces a
  recommendation file; `build_grocery.py` and the existing outputs
  (`grocery_gta.csv`, `grocery_gta.gpkg`) were left untouched, as instructed.

## Owner decisions and final merge (2026-09-14)

Rules set by the study owner after reviewing the draft:

1. Farm markets and orchard stores count only if open year-round. Checked
   against store websites and listings: kept Algoma Orchards, Farmer Jack's,
   Apna Farm, Bill's Farm, MacMillan Orchards; dropped Little Bee Farmer's
   Market (storefront open two days a week), Baily's Farm & Market,
   Country Farms Market. A.J. Lanzarotta kept (walk-in shoppers accepted).
2. Produce-only fruit markets count if the building is over about 350 m2;
   smaller stands are dropped.
3. All 23 Rabba locations kept.

Manual overrides: Tavazo Dried Nuts & Fruits dropped (specialty), Walmart
Produce dropped (section of a Walmart already counted), duplicate Algoma
Orchards node dropped, Diana Grocery and Fairway Market Variety & Grocery
dropped (small produce or variety stores).

`apply_audit.py` adds the kept stores to the automatic list, skips any
within 100 m of an existing store sharing a name word, and writes
`grocery_gta_v1.csv` and `grocery_gta_v1.gpkg`, the store list used by the
study. Skipped duplicates are listed in `grocery_audit_duplicates.csv`.

Duplicate matching detail: a kept store is treated as already present if
it is within 100 m of an existing store and shares a distinctive name word
(generic words such as grocery, meat, fish, fruit, market, foods, fresh,
halal and farm are ignored), or, when either store has no name, if it is
within 30 m. Result: 79 audit keeps, 77 added, 2 unnamed shops skipped as
duplicates of Domino's Fine Foods. `grocery_gta_v1` has 1,086 stores:
Toronto 512, Peel 219, York 169, Durham 99, Halton 87.
