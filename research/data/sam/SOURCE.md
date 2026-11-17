# Statistics Canada Spatial Access Measures: GTA Subset

**Source**: Statistics Canada Spatial Access Measures (SAM)
**Publisher**: Statistics Canada, in partnership with Housing, Infrastructure and Communities Canada
**Access date**: 2026-09-12
**Licence**: Statistics Canada Open Licence Agreement
**Catalogue**: 27-26-0001
**Data URLs**: 
- 2022 SAM: https://www150.statcan.gc.ca/n1/pub/27-26-0001/2023001/zip/sam-msa2022-eng.zip
- 2024 SAM: https://www150.statcan.gc.ca/n1/pub/27-26-0001/2023001/zip/sam-msa2024-eng.zip

## Reference Data and Timeline

**Data vintage and release dates**:
- 2022 SAM released in 2023 (data vintage: 2022)
- 2024 SAM released July 21, 2025 (data vintage: 2024)

**GTFS schedule collection**:
"Transit travel times were ultimately computed for each minute from 7:00 AM to 9:00 AM (2:00 PM to 4:00 PM for off-peak hours) on several different Thursdays in the 2021-2022 calendar year to ensure peak hours were covered and the median duration represented final estimates."

"Within each transit region, however, schedule dates of some GTFS sources presented some inconsistencies due to variance in the frequency at which transit providers updated their schedules or routes. This meant that each GTFS source was valid for a given period of time ranging from around 3 months to over a year."

Overall schedule date range: "schedule dates range from May 2017 to January 2022, with 66% of sources including transit data between 2020-2022."

**Business Register data year**: "For this project, the 2021 records from the BR were used."

**Census geography**: 2021 Census dissemination blocks and dissemination areas

## Peak and Off-Peak Hours

Peak hours: 7:00 AM to 9:00 AM
Off-peak hours: 2:00 PM to 4:00 PM

## Access Formula and Gravity Model

**Primal (Gravity) Model** (used for all amenities except grocery stores):

The access level (AL) is computed as: ALi = Sum over j in J of f(dij) * mj

Where:
- i = origin dissemination block
- j = destination dissemination block
- dij = travel duration between i and j
- mj = destination mass
- f(dij) = decay or impedance function

"The decay or impedance function, which is expressed as f(dij), is applied to account for the variation in willingness to travel to different types of amenities. It makes use of the complementary exponential cumulative distribution function, commonly used in transit literature... f(dij) = 1 - (1 - exp(-dij/lambda))"

"Median durations of travel per each type of service or amenity were determined from the General Social Survey (GSS), 2015."

Median trip durations by destination type (in minutes):
- Cultural and Arts: 15 (transit), 15 (cycling), 10 (walking)
- K-12 Educational: 20 (transit), 20 (cycling), 10 (walking)
- Post-Secondary Educational: 20 (transit), 20 (cycling), 20 (walking)
- Recreational: 15 (transit), 15 (cycling), 10 (walking)
- Place of employment: 20 (transit), 20 (cycling), 15 (walking)
- Healthcare: 15 (transit), 15 (cycling), 10 (walking)
- Grocery Store: 15 (transit), 15 (cycling), 10 (walking)

**Dual Model** (grocery stores only):

"The dual or reciprocal of the accessibility model (Cui & Levinson, 2020), solves for the travel duration or cost to reach a minimum number of opportunities."

"This model is only used for the grocery stores measure and the mass used is the count of grocery stores in a DB. The output of this model is the duration of travel in minutes to reach the nth closest amenity."

"This approach was chosen for two reasons, firstly, the distance to the nearest grocery stores is more relevant than the size of a grocery store grocery stores and secondly, being able to quantify whether there are a variety of grocery stores within a short duration of travel is important in identifying food deserts."

## Normalization

"All transit access measures presented in this study can then be expressed in relative terms, as rescaled indices. That is, the access level AL is transformed into an index, hereafter referred to as the Spatial Access Measure, SAM, by rescaling its values to a range between 0 and 1."

Formula: SAMi = (ALi - min(AL)) / (max(AL) - min(AL))

"The rescaling is done at the national level which is to say that min(AL) corresponds to the lowest access level in Canada and max(AL) corresponds to the highest. In this study, both the access levels and indices are provided."

## Destination Mass Sources

**Employment** (from Business Register):
"The masses for places of employment... are derived from BR employment data."
"All BR based masses are derived from a data set of all active businesses from 2021 that were extracted from the BR. Masses for BR entities were derived in the same fashion as in Alasia et al. (2021). That is, when necessary, enterprise-level reporting was allocated proportionally to the local-level using the BR allocation factors; entities with PO Boxes as addresses or unreliable geocoordinates were removed; and self-employed businesses with revenue under $30,000 were removed."

**Healthcare Facilities** (Business Register + Open Database of Healthcare Facilities):
"Healthcare facilities: 6211 (Offices of physicians), 6212 (Offices of dentists), 6213 (Offices of other health practitioners), 621494 (Community health centres), and 622 (Hospitals)."
"BR data on health care facilities was supplemented with facilities contained in the ODHF using a deduplication approach to remove facilities in common to both data sets. Furthermore, the ODHF records had their employment bin imputed using a random forest classifier."
Masses derived from employment data.

**Grocery Stores** (Business Register):
"Grocery stores: 445110 (Supermarkets and other grocery [except convenience] stores)"
"The mass for grocery store is simply a uniform mass. That is, the total mass of a DB is the sum of the masses of the grocery stores within in."

**Public K-12 Education Facilities** (Open Database of Educational Facilities):
"The ODEF was collected between 2019-2021 and contains over 18,500 records of educational facilities."
Uniform mass (count of facilities).

**Public Post-Secondary Education Facilities** (Open Database of Educational Facilities):
Same source as K-12, subset for post-secondary only.

**Sports and Recreation Facilities** (OpenStreetMap):
"An extract of all OSM data within Canada with an 'amenity' or 'leisure' key was downloaded from GeoFabrik on October 20, 2022. From this extract, all features with one of the sports and recreation facility tags were kept for computing the access measures."
"Sports and recreation facilities which were partitioned into 3 bins ([1-4), [4-6), 6+) for which the numerical categorical code, ranging from one to three, was used as a mass."

**Cultural and Art Facilities** (Open Database of Cultural and Art Facilities):
"The ODCAF was collected in 2020 and contains nearly 8,000 records of art or cultural facilities."
Uniform mass (count of facilities).

## Routing Parameters

**Public Transit**:
"A commuting duration threshold of 90-minutes was applied with the default walking speed of 3.6 km/hr and a max walking distance from and to transit stops of 1000-meter were assumed."

Routing engine: "Conveyal's Rapid Realistic Routing on Real-world and Reimagined networks (R5)" via r5r package.
"RAPTOR is efficient yet 'realistic' because it computes durations every minute within a specified time window parameter to account for the varying nature of public transportation systems, notably transit routes and schedules change based on the time of day, day of week, and time of year."

**Active Transportation** (cycling and walking):
Routing engine: Valhalla (open-source)
Cycling speeds: 18 kph (for both vintages)
Walking speed: 3.6 kph

## DB-to-DA Aggregation (as implemented in build_sam.py)

The aggregation from dissemination block (DB) to dissemination area (DA) level uses population weighting:

1. **For index columns** (s20XX_peak_emp, s20XX_peak_hf, etc.):
   - When DA has population > 0: weighted average using DB population as weights
     - Formula: sum(index_value[i] * pop[i] for i with data) / sum(pop[i] for i with data)
     - Also records population coverage: sum(pop[i] where data exists) / total DA population
   - When DA has zero population: unweighted mean of available DB values

2. **For grocery store "reached" columns** (s20XX_peak_gs1_reached, etc.):
   - When DA has population > 0: population share (sum of pop[i] * reached[i]) / total DA population
   - When DA has zero population: unweighted mean of available values
   - These columns indicate whether the nth grocery store (1st, 3rd, or 5th) was reachable within the time threshold

3. **Metadata columns**:
   - n_db: count of DBs within DA
   - n_db_with_pop: count of DBs with population > 0
   - da_pop2021_from_db: sum of DB population
   - weight_method: "population" (if pop > 0) or "unweighted_zero_pop" (if pop = 0)

## Column Naming Scheme

**Geographic identifiers** (in both DB and DA files):
- DBUID: 11-digit dissemination block identifier (2021 Census), zero-padded string
- DAUID: 8-digit dissemination area identifier (2021 Census), zero-padded string
- CDUID: 4-digit census division identifier, zero-padded string
- CDNAME: Census division name
- CSDUID: 7-digit census subdivision identifier, zero-padded string
- CSDNAME: Census subdivision name
- DBPOP2021: DB population from 2021 Census (DB file only)

**SAM index columns** (DB file: gravity model amenities):
Naming pattern: s{VINTAGE}_{PERIOD}_{SHORTNAME}

Where:
- VINTAGE: 2022 or 2024
- PERIOD: peak or offpeak
- SHORTNAME: emp (employment), hf (healthcare facilities), ef (education K-12), psef (post-secondary education), srf (sports/recreation), caf (culture/arts), ccf (child care, 2024 only)

Example: s2022_peak_emp, s2024_offpeak_hf

**SAM grocery store columns** (DB file: dual model):
Naming pattern: s{VINTAGE}_{PERIOD}_gs{N}_min and s{VINTAGE}_{PERIOD}_gs{N}_reached

Where:
- N: 1, 3, or 5 (minimum number of grocery stores)
- _min: travel time in minutes to reach the Nth closest grocery store
- _reached: binary indicator (0 or 1, or NaN) whether Nth grocery store is reachable

Example: s2022_peak_gs1_min, s2024_offpeak_gs5_reached

**Metadata columns** (DB file):
- s{VINTAGE}_{PERIOD}_missing: 1 if all index values are ".." (missing) for this DB, 0 otherwise
- s{VINTAGE}_{PERIOD}_in_file: 1 if this DB appears in the SAM file, 0 otherwise (NaN if missing)

**DA file aggregated columns**:
Naming pattern: s{VINTAGE}_{PERIOD}_{SHORTNAME} for index values
Additional: s{VINTAGE}_{PERIOD}_{SHORTNAME}_popcov (population coverage ratio) and s{VINTAGE}_{PERIOD}_{SHORTNAME}_popshare (for reached columns)

## Data Coverage

**GTA subset extracted**:
- 38,195 dissemination blocks (2021 Census)
- 8,508 dissemination areas (2021 Census)
- Census divisions: 3518 (Durham), 3519 (York), 3520 (Toronto), 3521 (Peel), 3524 (Halton)

**Completeness notes**:
- Not all DBs have SAM values; missing values indicated by ".." in original data or NaN in processed output
- Missing values most common in rural areas outside of the 54 defined transit regions
- GTFS data collected from 106 accessible sources (out of 143 identified)
- "Around 72.4 percent of the Canadian population lives in a dissemination block with at least one transit stop, using the collected GTFS data."

## Known Problems and Limitations

- Static GTFS snapshot does not account for seasonal service variations or COVID-19 schedule changes
- Routing network based on OSM data which may contain misclassifications, particularly in areas with fewer contributors
- Origin points (DB centroids) determined by building footprint density, which may not represent true population centers
- Access measures are based on GSS 2015 median travel durations and assume uniform commuter profile across Canada
- Cycling measures do not represent access for all ages and abilities (certain infrastructure excluded based on comfort thresholds)
- Some areas outside 54 defined transit regions have no public transit access values
- Child care facilities (ccf) only available in 2024 SAM vintage
- For 2022 vintage: grocery store dual model may not have values for all DBs
- Destination masses for employment and healthcare based on 2021 Business Register data; open-source facility data collected 2019-2022

## Download and Processing Steps

1. Downloaded SAM zip files from Statistics Canada
2. Extracted CSV files for both 2022 and 2024 vintages (peak and off-peak transit)
3. Filtered geographic data to 5 GTA census divisions
4. Extracted numeric values (converted ".." to NaN)
5. Short-named columns for brevity and consistency
6. Aggregated DB values to DA level using population-weighted means
7. Output as GeoPackage EPSG:4326 (not applicable; saved as CSV for tabular data)
8. Maintained leading zeros in all ID columns (DBUID, DAUID, CDUID)

## References

- Statistics Canada. (2023). Spatial Access Measures, 2022. Catalogue no. 27-26-0001. https://www150.statcan.gc.ca/n1/pub/27-26-0001/2023001/index-eng.html
- Statistics Canada. (2024). Active and Public Transportation Spatial Accessibility Measures: Methodology and Key Results. Reports on Special Business Projects. Released November 20, 2024. https://www150.statcan.gc.ca/n1/pub/18-001-x/18-001-x2024001-eng.html
- Statistics Canada. (2025). Spatial Access Measures 2024 Update Report. Released July 21, 2025.
- Alasia, A., Giunta, C., Hobbs, K., Birkett Francis Demers, S., & Newstead, N. (2021). Proximity Measures Database methodology. Statistics Canada. (Referenced in working paper)
- Cui, L., & Levinson, D. (2020). Modeling the relationship between accessibility and economic growth [Referenced for dual model]
