# Grocery Store Dataset Source and Methods

## Sources

**Primary data source:** OpenStreetMap via gta.osm.pbf (local file `gta.osm.pbf` in the repository folder, downloaded by `setup.sh`)
- Data extracted: 2026-09-12
- Features queried: all elements (nodes, ways, relations) tagged with shop=supermarket, shop=grocery, shop=greengrocer, shop=wholesale, or shop=department_store

**Boundary data:** Statistics Canada 2021 Census Division Cartographic Boundary File
- URL: https://www12.statcan.gc.ca/census-recensement/2021/geo/sip-pis/boundary-limites/files-fichiers/lcd_000b21a_e.zip
- File: lcd_000b21a_e.zip (downloaded 2026-09-12)
- Accessed: 2026-09-12
- Licence: Statistics Canada, Crown Copyright
- Census divisions clipped to: 3518 (Durham), 3519 (York), 3520 (Toronto), 3521 (Peel), 3524 (Halton)

**Processing tool:** osmium (homebrew installation at /opt/homebrew/bin/osmium)

## Inclusion and Exclusion Rules

All rules are implemented in build_grocery.py and applied during classification of each OSM feature. A feature is included only if it passes one of the following conditions:

### Supermarket (shop=supermarket)
- Included by default unless it matches a specialty/convenience name pattern AND has no known chain brand
- **Excluded patterns (specialty/convenience):** bulk barn, source bulk, bulk food, rabba, dollar stores, pharmacies, drug mart, shoppers, variety stores, convenience stores, gas stations/petro/esso/shell/circle k/mac's/7-eleven, bakeries, butchers, meat shops, spice shops, nut shops, candy, liquor stores, lcbo, beer store, low-carb, kitchen express

### Wholesale (shop=wholesale)
- Included only if brand matches: Costco or Wholesale Club
- All other wholesale stores are excluded

### Department Store (shop=department_store)
- Included only if brand matches: Walmart
- All other department stores are excluded

### Grocery or Greengrocer (shop=grocery or shop=greengrocer)
- Included if: brand matches one of the known chain patterns, OR
- Name contains supermarket-scale indicator text (e.g., supermarket, super market, super mart, food mart, food market, fresh market, foods centre/center/market, farmers market, fine foods, food cooperative, international foods, eataly, pusateri) AND does not contain small shop indicators (variety, halal meat, meat, spice, nuts, cheese, takeout, bakery, farm, farms, orchard, blueberry, garden centre, produce, importers, low carb, dried)
- Otherwise excluded

### Other Filters
- Entrance nodes (shop=* with entrance=*) are excluded
- All features outside the GTA study area are excluded (500 m buffer zone used for initial filter)

### Known Chains Recognized
Loblaws, No Frills, Real Canadian Superstore, Fortinos, Zehrs, Your Independent Grocer, Wholesale Club, Metro, Food Basics, Sobeys, FreshCo, Longo's, Foodland, Walmart, T&T, Farm Boy, Costco, Whole Foods Market, Adonis, H Mart, Starsky, Pusateri's

## Deduplication Method

Two-stage deduplication process:

### Stage 1: Node Inside Polygon
If a point-tagged feature (node) falls inside or on the boundary of a polygon-tagged feature (way/relation) of the same store (name match after normalization), the node is dropped and the polygon is retained. This removes redundant node mappings that are part of a larger building footprint.

### Stage 2: Nearby Duplicate Store Names
Features with the same normalized store name within 100 m distance are deduplicated. When multiple features match:
1. Preference given to polygon-mapped features over point-mapped features
2. Among features of the same geometry type, preference given to features with more OSM tags
3. The preferred feature is retained; others are dropped

Duplicate pairs are logged in grocery_dedup_log.csv with their OSM IDs and reason codes.

## Row Counts per Census Division

| Census Division | CDUID | Count |
|-----------------|-------|-------|
| Durham          | 3518  | 96    |
| York            | 3519  | 166   |
| Toronto         | 3520  | 467   |
| Peel            | 3521  | 197   |
| Halton          | 3524  | 83    |
| **GTA Total**   |       | **1,009** |

## Completeness and Data Quality Notes

### Category Breakdown
The 1,009 records are classified into four categories:

- **Supermarket (961 records, 95.2%):** Stores tagged as shop=supermarket, covering large-scale full-service grocery retailers
- **Warehouse Club (23 records, 2.3%):** Costco and Wholesale Club locations
- **Grocery Substantial (17 records, 1.7%):** Stores tagged as shop=grocery or shop=greengrocer that meet supermarket-scale naming criteria
- **General Merchandise with Grocery (8 records, 0.8%):** Walmart locations classified as department stores with significant grocery sections

### Deduplication Summary
- Total OSM features extracted: approximately 1,354 features (before inclusion filtering)
- Features dropped during deduplication: 11 pairs
  - Node-inside-polygon (7 pairs): removed redundant node mappings of known store polygons
  - Nearby duplicates (4 pairs): removed stores with identical names within 100 m

### Exclusions
418 features were excluded based on the classification rules:
- Department stores without grocery (Canadian Tire, outlet stores, etc.)
- Specialty grocery shops (bakeries, butchers, produce stands, etc.)
- Convenience stores and variety stores
- Pharmacies and drug stores

### Known Limitations
1. **Independent / Other stores (486 records):** These are primarily independent supermarkets and smaller grocery retailers without a recognized chain affiliation. Many are captured correctly; some specialty shops may have evaded the exclusion patterns.

2. **OSM data recency and completeness:** The dataset reflects OSM state as of extraction date. Closed or recently opened stores may not be reflected. OSM data quality varies by region (generally higher in Toronto and adjacent areas).

3. **Point vs. Polygon:** Some stores are mapped as building polygons (especially larger chains) while others exist only as point nodes. Centroids for polygon features may not precisely reflect the main entrance location.

4. **Multilocation clusters:** In some urban areas with dense grocery options, the 100 m deduplication radius may not fully catch all legitimate separate locations of the same chain.

5. **Area calculation:** Area_m2 field in the GeoPackage reflects the building footprint for polygon-mapped stores; point-mapped stores have null area values.

### Output Format
- **grocery_gta.gpkg:** GeoPackage format, EPSG:4326, spatial point geometries
- **grocery_gta.csv:** CSV table with coordinates (lon, lat)
- **grocery_chain_counts_osm.csv:** Pivot table showing count of stores by chain and census division
- **grocery_dedup_log.csv:** Log of removed duplicate features with reasons
- **grocery_excluded_review.csv:** Full list of excluded features for validation

### Methods and Tools
- Extraction: osmium tags-filter and export (GeoJSON seq format)
- Processing: GeoPandas, Shapely, Pandas
- Coordinate system: EPSG:3347 (StatCan Lambert Conformal Conic) for spatial operations; EPSG:4326 (WGS 84) for output
