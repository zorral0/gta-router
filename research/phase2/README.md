# Phase 2: travel-time maps from every starting point (version 2)

This folder asks the research routing engine how far you can get from each
starting point and saves the answers to disk. Version 2 covers the
**weekday morning only** (Tuesday 2026-09-22). Version 1 is kept as
`run_reach_v1.py` for reference; its outputs (`surfaces_v1/`) must not be
mixed with version 2.

## What changed from version 1

- **Engine:** the research graph with a 40 km buffer around the GTA
  (`engine/research-buffer`), served on port 8091. It includes Hamilton
  (HSR), Waterloo Region (GRT) and Barrie Transit, and runs on published
  schedules only (no live updates).
- **Time limits:** transit at 30 and 60 minutes; 45 minutes on a fixed 10%
  sample.
- **Starting points:** `research/data/census/origin_points_v2.csv`. One point
  per DA up to 2 km2; one point per populated block in larger DAs. Every file
  and log uses `origin_id` (a DAUID or a block's DBUID) and records its DA.
- **Far-north DAs are included** (the buffer map covers them).

## Before a run

1. Build the starting points once (already done if the CSV exists):

       research/.venv/bin/python research/data/census/build_origin_points.py

2. Stop `run.sh` (the Mac cannot run both engines), then start the research
   engine from the `gta-router` folder:

       java -Xmx6G -jar engine/otp25.jar --load engine/research-buffer --port 8091

   Its log should say `OTP UPDATERS INITIALIZED (0 updaters)`.
3. Plug the Mac in and leave the lid open.

## What it saves per starting point

| File | What it is |
|------|------------|
| `am_30_0735.tif` | walk + transit, up to 30 min, leaving 07:35 (13 departures, 07:30 to 08:30) |
| `am_60_0735.tif` | walk + transit, up to 60 min, same departures |
| `car_30.tif` | car, up to 30 min, leaving 08:00 |
| `am_45_0735.tif` | up to 45 min, same departures (1 in 10 points only) |
| `car_30_alt.tif` | car from the backup start point (flagged points and a 5% sample) |

Files live in `surfaces_v2/<origin_id>/`. Read a 30-minute threshold only from
`_30_` maps, 60 minutes only from `_60_` maps, and 45 minutes only from `_45_`
maps: a bigger requested cut-off gives slightly smaller areas.

## Commands

    research/.venv/bin/python research/phase2/run_reach.py --dry-run   # plan and time estimate, no engine
    research/.venv/bin/python research/phase2/run_reach.py --pilot     # 20 test points, measures the pace
    research/phase2/run_overnight.sh                                   # the full job
    tail -f research/phase2/run_v2.log                                 # progress, in another window
    research/.venv/bin/python research/phase2/run_reach.py --summary   # areas for finished points
    research/.venv/bin/python research/phase2/test_run_reach.py        # offline tests

Stop with Ctrl+C. Run the same command again to carry on: saved maps are
skipped. If the engine stops answering, the job pauses and checks every 30
seconds.

## Quality checks

Every starting point is moved onto the nearest drivable road
(`origins_snapped_v2.csv`: distance `snap_m`, road class `snap_highway`,
and a backup point on a different road). A point is flagged from its inputs
only: moved more than 300 m, or no backup point. Flagged points and a fixed
5% sample also get a car map from the backup point. Both car areas are
written to `qa_flags_v2.csv`; the job never swaps one for the other.

## Files it writes

| File | What it is |
|------|------------|
| `surfaces_v2/<origin_id>/*.tif` | the saved maps |
| `surfaces_v2/<origin_id>/_done_v2_am` | marker: this point is complete |
| `origins_snapped_v2.csv` | starting points on roads, road class, backup point |
| `errors_v2.csv` | requests that failed 4 times in a row (running again retries them) |
| `qa_flags_v2.csv` | flags and both car areas per finished point |
| `run_v2.log` | everything the overnight job printed |
