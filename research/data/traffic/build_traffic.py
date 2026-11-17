#!/usr/bin/env python3
"""
Build the car slowdown factor table for the GTA transit-gaps study.

Slowdown factor = typical travel time / free-flow travel time.
The routing engine (OpenTripPlanner) computes free-flow car time from each
OSM way's tagged or class-default speed limit and length. It does not know
about measured traffic. This script applies a published slowdown factor on
top of that free-flow time, for three periods: weekday 8 AM, weekday 9 PM,
Sunday 11 AM.

Inputs used (see SOURCE.md for full citations and access dates):
  raw/statcan_urban_mobility_toronto.html
      Statistics Canada / Transport Canada archived corridor-level Travel
      Time Index (TTI) table for Toronto, AM peak (6:00-9:59) and PM peak
      (15:00-18:59), monthly Jul/Aug/Sep 2018-2020.
  raw/toronto_backgroundfile-*.txt
      Four City of Toronto Congestion Management Plan reports (2023, 2025,
      2026 spring update, 2026-2028 plan), which quote the City's own
      citywide and downtown TTI for the PM peak hour (5-6 pm).
  inputs/tomtom_2025_hourly_traveltime.csv
      Pre-existing local file, hour-by-day-of-week travel time (mm:ss) for
      a fixed distance, "city" and "metro" areas. FLAGGED: its source URL
      and access date are not documented anywhere in this folder, and we
      could not find a public API on the live TomTom Traffic Index Toronto
      page that reproduces it, so we cannot independently confirm it came
      from TomTom. Used only for weekday 9 PM and Sunday 11 AM, the two
      periods no approved official source covers, and flagged low-confidence
      in SOURCE.md and known_problems.

Also fetched live (permitted: TomTom / INRIX pages) on 2026-09-12:
  https://www.tomtom.com/traffic-index/city/toronto/
  which serves https://www.tomtom.com/traffic-index/city/toronto/2025/center/comparison.json
  with explicit am (8 am) and pm (5 pm) congestion figures for 2025.

Run: research/.venv/bin/python build_traffic.py
Writes: slowdown.csv
"""
import csv
import re
import statistics
from pathlib import Path

HERE = Path(__file__).parent
RAW = HERE / "raw"
INPUTS = HERE / "inputs"


def parse_statcan_corridor_tti():
    """Return list of (am_or_pm, [values across corridor-direction-months])."""
    html = (RAW / "statcan_urban_mobility_toronto.html").read_text(
        encoding="utf-8", errors="ignore"
    )
    rows = re.findall(r"<tr.*?</tr>", html, re.S)
    # Columns after the AM/PM marker are: Jul2018 Jul2019 Jul2020 Aug2018
    # Aug2019 Aug2020 Sep2018 Sep2019 Sep2020. Keep only pre-pandemic
    # (2018, 2019) columns; 2020 is pandemic-suppressed traffic and would
    # bias a "typical" estimate low.
    keep_idx = [0, 1, 3, 4, 6, 7]
    am_vals, pm_vals = [], []
    for r in rows[1:-1]:
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S)
        cells = [re.sub("<[^>]+>", "", c).strip() for c in cells]
        cells = [c for c in cells if c != ""]
        if "AM" in cells:
            idx = cells.index("AM")
            am_vals += [float(cells[idx + 1 + i]) for i in keep_idx]
        elif "PM" in cells:
            idx = cells.index("PM")
            pm_vals += [float(cells[idx + 1 + i]) for i in keep_idx]
    return am_vals, pm_vals


def to_seconds(mmss):
    m, s = mmss.split(":")
    return int(m) * 60 + int(s)


def parse_local_tomtom_csv():
    """
    Return dict[area][hour][day] = seconds, plus the factor (vs that area's
    weekly minimum travel time, used as a free-flow stand-in) for the two
    periods no official source covers: weekday 9 pm and Sunday 11 am.
    """
    path = INPUTS / "tomtom_2025_hourly_traveltime.csv"
    data = {}
    with path.open() as f:
        for row in csv.DictReader(f):
            area = row["area"]
            hour = int(row["hour"])
            data.setdefault(area, {})[hour] = {
                d: to_seconds(row[d])
                for d in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            }

    out = {}
    for area, by_hour in data.items():
        all_vals = [v for hourvals in by_hour.values() for v in hourvals.values()]
        freeflow = min(all_vals)
        wd9pm = statistics.mean(by_hour[21][d] for d in ["Tue", "Wed", "Thu"])
        sun11am = by_hour[11]["Sun"]
        out[area] = {
            "freeflow_s": freeflow,
            "weekday_9pm_factor": round(wd9pm / freeflow, 3),
            "sunday_11am_factor": round(sun11am / freeflow, 3),
        }
    return out


def main():
    am_vals, pm_vals = parse_statcan_corridor_tti()
    am_mean = round(statistics.mean(am_vals), 3)
    pm_mean = round(statistics.mean(pm_vals), 3)
    print(f"StatCan/Transport Canada corridor TTI, pre-pandemic 2018-2019:")
    print(f"  AM peak (6-9:59am) mean={am_mean} min={min(am_vals)} max={max(am_vals)} n={len(am_vals)}")
    print(f"  PM peak (3-6:59pm) mean={pm_mean} min={min(pm_vals)} max={max(pm_vals)} n={len(pm_vals)}")

    local = parse_local_tomtom_csv()
    print("\nLocal file inputs/tomtom_2025_hourly_traveltime.csv (unverified source):")
    for area, d in local.items():
        print(f"  {area}: weekday 9pm factor={d['weekday_9pm_factor']}, "
              f"Sunday 11am factor={d['sunday_11am_factor']}")

    print("\nLive TomTom Traffic Index, Toronto, 2025 (fetched 2026-09-12 from")
    print("https://www.tomtom.com/traffic-index/city/toronto/2025/center/comparison.json):")
    print("  city scope, 8am: congestion 62.2% -> factor 1.62 (speed 20.6 vs free-flow 33.5 km/h)")
    print("  city scope, 5pm: congestion 79.3% -> factor 1.79 (speed 17.6 vs free-flow 31.6 km/h)")
    print("  highways scope, 8am: congestion 112.6% -> factor 2.13 (speed 42.3 vs free-flow 89.9 km/h)")

    # Recommended factors. See SOURCE.md for the full reasoning behind each
    # low/central/high choice; these are a synthesis across the sources
    # above, not a single quoted number, except where noted.
    rows = [
        {
            "period": "weekday_8am",
            "factor_low": 1.4,
            "factor_central": 1.6,
            "factor_high": 2.1,
            "basis": (
                "Central 1.6 rounds the live TomTom Traffic Index 2025 Toronto "
                "(city scope) 8am congestion figure of 62.2% (factor 1.62); "
                "consistent with StatCan/Transport Canada archived AM-peak "
                "(6-9:59am) corridor TTI, pre-pandemic 2018-2019 mean "
                f"{am_mean}, and City of Toronto CMP 2023-26 report's 'TTI "
                "fluctuating around 1.65 to 1.75' for peak periods in 2023. "
                "Low 1.4 allows for arterial/suburban roads below the sampled "
                "expressway-corridor average. High 2.1 reflects downtown/"
                "expressway conditions: TomTom highways-scope 8am factor "
                "2.13, and City of Toronto's own downtown PM-peak TTI of "
                "1.95 (2025) to 2.12 (2024)."
            ),
        },
        {
            "period": "weekday_9pm",
            "factor_low": round(min(local["metro"]["weekday_9pm_factor"], local["city"]["weekday_9pm_factor"]), 2),
            "factor_central": round(statistics.mean([local["metro"]["weekday_9pm_factor"], local["city"]["weekday_9pm_factor"]]), 2),
            "factor_high": round(max(local["metro"]["weekday_9pm_factor"], local["city"]["weekday_9pm_factor"]), 2),
            "basis": (
                "No source in the approved list (City of Toronto CMP reports, "
                "the StatCan/Transport Canada corridor table, or the live "
                "TomTom Traffic Index Toronto page) publishes a 9 PM figure: "
                "the City and StatCan sources only define AM (6-9:59am) and "
                "PM (3-6:59pm, or 5-6pm) peak windows, and the live TomTom "
                "page exposes only one morning and one evening rush-hour "
                "number, not a full hourly breakdown. The only number "
                "available for 9 PM is the pre-existing local file "
                "inputs/tomtom_2025_hourly_traveltime.csv (city and metro "
                "scope), whose own source URL and access date are not "
                "documented anywhere in this folder and could not be "
                "confirmed against the live TomTom site. LOW CONFIDENCE: "
                "flagged in known_problems, treat as provisional."
            ),
        },
        {
            "period": "sunday_11am",
            "factor_low": round(min(local["metro"]["sunday_11am_factor"], local["city"]["sunday_11am_factor"]), 2),
            "factor_central": round(statistics.mean([local["metro"]["sunday_11am_factor"], local["city"]["sunday_11am_factor"]]), 2),
            "factor_high": round(max(local["metro"]["sunday_11am_factor"], local["city"]["sunday_11am_factor"]), 2),
            "basis": (
                "Same gap as weekday 9 PM: no official source in the "
                "approved list covers Sunday. Only number available is the "
                "pre-existing local file inputs/tomtom_2025_hourly_"
                "traveltime.csv (city and metro scope), unverified source. "
                "LOW CONFIDENCE: flagged in known_problems, treat as "
                "provisional."
            ),
        },
    ]

    out_path = HERE / "slowdown.csv"
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["period", "factor_low", "factor_central", "factor_high", "basis"])
        w.writeheader()
        w.writerows(rows)
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
