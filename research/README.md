# Research: where GTA transit serves people worst

This folder is the code behind a study that uses the GTA Router's engine to
ask one question: across the Greater Toronto Area, who can get the least done
by transit, and do they live in the places that need it most?

From 13,460 starting points (one per neighbourhood, or one per populated
block in neighbourhoods larger than 2 km²), the engine maps how far you can get by walking
and transit in 30 and 60 minutes on a weekday morning, and how far you could
drive in the same time. Each neighbourhood is then scored on what those maps
reach: jobs, full-service grocery stores, hospital emergency departments, and
other people. The scores are compared with low income, and checked against
Statistics Canada's own transit access measures and against how people
actually travel.

**Status:** the analysis is finished and checked. The written report is not
published yet. Until it is, numbers in this folder's notes are working
numbers, not findings.

## What is here

| Folder | What it does |
|--------|--------------|
| `data/` | One folder per input (census, grocery, healthcare, jobs, traffic, `sam` = Statistics Canada's Spatial Access Measures, and more). Each has a build script and a `SOURCE.md` saying exactly where every file came from and what was decided about it. `data/verify/check_all.py` re-checks them all independently. |
| `data/grocery/` | Also the hand audit: every store the automatic rules were unsure about, checked one by one (`AUDIT.md` and the CSVs). |
| `pilot/` | The first test on 20 hand-picked places, and the car traffic calibration against Google Maps typical times. |
| `phase2/` | The overnight run that asks the engine for every travel-time map, the pre-run tests, and the fixes for car starts that landed on roads a car cannot use. `phase2/README.md` explains the run. |
| `phase3/` | Scores each starting point, then each neighbourhood, and sorts neighbourhoods into low-income by access groups. |
| `phase4/` | Checks: extremes and outliers, a re-run of a 2% sample to prove the results repeat, and comparisons with outside measures. |
| `phase5/` | The neighbourhood shortlist, the hand checks of real bus service for the story areas, the data files for the report page, and fact-check scripts for the headline numbers. |
| `preview/` | Rough maps drawn the morning after the first run, before the final measures existed. |

## What is not here, and why

- **The data itself** (about 9 GB): downloads and outputs are rebuilt by the
  build scripts, and each `SOURCE.md` gives the download links. A few small
  tables that were entered or reviewed by hand are included, because no
  script can rebuild them.
- **Travel survey numbers.** Some checks use the Transportation Tomorrow
  Survey (Data Management Group, University of Toronto), which needs an
  account. Those exports, and the notes describing them, stay off GitHub
  until the survey's publication terms are confirmed.
- **Working notes and drafts**: the planning notebook, review drafts and the
  paper drafts. The methods will be published with the report.

## Running it

The scripts were run on a Mac with Python 3.14, from the repository folder:

```bash
python3 -m venv research/.venv
research/.venv/bin/pip install -r research/requirements.txt
```

The routing steps need the study's own engine: OpenTripPlanner 2.5 with a
40 km buffer around the GTA, built from the schedules of the week of
2026-09-22 and served on port 8091 (see `phase2/README.md`). It is a separate
build from the trip planner's, so refreshing the planner's schedules never
changes the study.

Rough order: the `data/*/build_*.py` scripts (census first), then `pilot/`,
`phase2/pretest.py` and `phase2/run_reach.py`, then `phase3/score_points.py`
and `phase3/score_da.py`, then `phase4/checks.py`, then `phase5/`.

`phase2/test_surface.py` needs nothing but Python and runs on every push.
`phase2/test_run_reach.py` also runs without the engine, once the census
build has made the starting-point list.
