"""Step 5: which neighbourhoods have no scheduled stop within walking distance.

No GTA agency publishes its on-demand zone outlines as data (PDF maps only,
checked 2026-11-14), so the report marks the places the schedules do not
reach instead, which is where on-demand service matters.

For every populated GTA block: straight-line distance to the nearest stop
with at least one scheduled departure on the study morning (Tue 2026-09-22,
07:30 to 08:30), over the ten GTA feeds. Per DA: share of residents within
800 m (about a ten-minute walk). A DA is flagged when fewer than half its
residents are within 800 m.

Writes research/phase5/da_no_stop.csv (DAUID, pop, share_800m, no_stop).
Run: research/.venv/bin/python research/phase5/no_stop_check.py
"""
import csv
import io
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import shapely
from pyproj import Transformer

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
ENGINE = RESEARCH.parent / "engine"
FEEDS = ["ttc", "go", "up", "miway", "brampton", "yrt", "drt", "oakville", "burlington", "milton"]
DATE, DOW = "20260922", "tuesday"
T0, T1 = 7 * 3600 + 30 * 60, 8 * 3600 + 30 * 60
WALK_M, MIN_SHARE = 800, 0.5


def read(z, name):
    with z.open(name) as f:
        yield from csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))


def services_on(z):
    on, names = set(), z.namelist()
    if "calendar.txt" in names:
        for r in read(z, "calendar.txt"):
            if r["start_date"] <= DATE <= r["end_date"] and r[DOW] == "1":
                on.add(r["service_id"])
    if "calendar_dates.txt" in names:
        for r in read(z, "calendar_dates.txt"):
            if r["date"] == DATE:
                (on.add if r["exception_type"] == "1" else on.discard)(r["service_id"])
    return on


def secs(t):
    h, m, s = t.strip().split(":")
    return int(h) * 3600 + int(m) * 60 + int(s)


def served_stops(feed):
    z = zipfile.ZipFile(ENGINE / f"{feed}-gtfs.zip")
    on = services_on(z)
    trips = {t["trip_id"] for t in read(z, "trips.txt") if t["service_id"] in on}
    hit = set()
    for st in read(z, "stop_times.txt"):
        t = st.get("departure_time") or st.get("arrival_time")
        if t and st["trip_id"] in trips and T0 <= secs(t) < T1:
            hit.add(st["stop_id"])
    pts = [(float(s["stop_lon"]), float(s["stop_lat"])) for s in read(z, "stops.txt")
           if s["stop_id"] in hit and s.get("stop_lat")]
    print(f"{feed}: {len(on)} services on {DATE}, {len(trips):,} trips, {len(pts):,} stops with a departure in the hour")
    return pts


def main():
    stops = [p for f in FEEDS for p in served_stops(f)]
    tf = Transformer.from_crs(4326, 3161, always_xy=True)
    sx, sy = tf.transform(*zip(*stops))
    tree = shapely.STRtree(shapely.points(sx, sy))
    b = pd.read_csv(RESEARCH / "data" / "buffer" / "blocks_buffer.csv", dtype={"DAUID": str, "DBUID": str})
    b = b[b.in_gta == 1]
    bx, by = tf.transform(b.lon.to_numpy(), b.lat.to_numpy())
    _, d = tree.query_nearest(shapely.points(bx, by), return_distance=True, all_matches=False)
    b = b.assign(near=d <= WALK_M)
    b["pop_near"] = b["pop"] * b.near
    da = b.groupby("DAUID").agg(pop=("pop", "sum"), pop_near=("pop_near", "sum")).reset_index()
    da["share_800m"] = (da.pop_near / da["pop"]).round(3)
    da["no_stop"] = (da.share_800m < MIN_SHARE).astype(int)
    da[["DAUID", "pop", "share_800m", "no_stop"]].to_csv(HERE / "da_no_stop.csv", index=False)
    tot = b["pop"].sum()
    print(f"{len(stops):,} served stops; {len(b):,} blocks, {tot:,} people")
    print(f"residents beyond {WALK_M} m of any served stop: {tot - b.pop_near.sum():,.0f} ({1 - b.pop_near.sum() / tot:.1%})")
    print(f"DAs flagged: {da.no_stop.sum():,} of {len(da):,}, {da.loc[da.no_stop == 1, 'pop'].sum():,} people")


if __name__ == "__main__":
    main()
