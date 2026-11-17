"""Hand-check support for the neighbourhood stories: the real scheduled service.

For a story's DAs, lists every transit stop within 800 m (straight line) of
where people live (populated block points), the routes serving those stops
on the study morning (Tue 2026-09-22, departures 07:30 to 08:30), how often
they run, and how many residents live within 400 m / 800 m of a stop with any
morning service and of a frequent route (4+ trips in the hour). Reads the
GTFS zips in engine/ (the ones the research graph was built from; TTC was
refreshed on 2026-09-19, after the build, so TTC lines are indicative).

Run: research/.venv/bin/python research/phase5/route_check.py <story>
"""
import csv
import io
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
ENGINE = RESEARCH.parent / "engine"
DATE, DOW = "20260922", "tuesday"
T0, T1 = 7 * 3600 + 30 * 60, 8 * 3600 + 30 * 60

STORIES = {  # story: (shortlist measure, a substring of the place label or municipality, feeds)
    "oshawa": ("jobs60", "Oshawa", ["drt", "go"]),
    "malton": ("groc30", "Mississauga", ["miway", "brampton", "go", "ttc"]),
    "richmondhill": ("mag_pop", "Richmond Hill", ["yrt", "go"]),
    "oakville": ("jobs60", "Oakville", ["oakville", "go"]),
    "newtonbrook": ("near_ed", "Bishop", ["ttc", "yrt", "go"]),
}


def read(z, name):
    with z.open(name) as f:
        yield from csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))


def services_on(z):
    on = set()
    names = z.namelist()
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
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + int(s)


def main(story):
    measure, key, feeds = STORIES[story]
    sl = pd.read_csv(HERE / "shortlist.csv", dtype=str)
    sl = sl[(sl.measure == measure) & (sl.municipality.str.contains(key) | sl.place.str.contains(key))]
    row = sl.assign(p=sl.people.astype(int)).sort_values("p", ascending=False).iloc[0]
    das = set(row.dauids.split())
    b = pd.read_csv(RESEARCH / "data" / "buffer" / "blocks_buffer.csv", dtype={"DAUID": str, "DBUID": str})
    b = b[b.DAUID.isin(das)]
    print(f"{story}: {row.place} ({row.municipality}), {len(das)} DAs, {int(b['pop'].sum()):,} people in {len(b)} blocks")
    blat, blon, bpop = b.lat.to_numpy(), b.lon.to_numpy(), b["pop"].to_numpy()
    lat0 = blat.mean()

    def dist(lat, lon):  # metres from every block to one point
        return np.hypot((blat - lat) * 111000, (blon - lon) * 111320 * np.cos(np.radians(lat0)))

    routes = defaultdict(lambda: {"trips": set(), "stops": set(), "name": "", "feed": "",
                                  "at_stop": defaultdict(set)})  # (stop, direction) -> trips
    stop_min_d = {}
    for feed in feeds:
        z = zipfile.ZipFile(ENGINE / f"{feed}-gtfs.zip")
        near = {}
        for s in read(z, "stops.txt"):
            if not s.get("stop_lat"):
                continue
            d = dist(float(s["stop_lat"]), float(s["stop_lon"]))
            if d.min() <= 800:
                near[s["stop_id"]] = d
        if not near:
            continue
        on = services_on(z)
        rname = {r["route_id"]: (r.get("route_short_name") or "") + " " + (r.get("route_long_name") or "") for r in read(z, "routes.txt")}
        trip_route, trip_dir = {}, {}
        for t in read(z, "trips.txt"):
            if t["service_id"] in on:
                trip_route[t["trip_id"]] = t["route_id"]
                trip_dir[t["trip_id"]] = t.get("direction_id", "")
        for st in read(z, "stop_times.txt"):
            if st["stop_id"] in near and st["trip_id"] in trip_route and st.get("departure_time"):
                if T0 <= secs(st["departure_time"]) < T1:
                    rid = trip_route[st["trip_id"]]
                    k = f"{feed}:{rid}"
                    routes[k]["trips"].add(st["trip_id"])
                    routes[k]["stops"].add(st["stop_id"])
                    routes[k]["at_stop"][(st["stop_id"], trip_dir[st["trip_id"]])].add(st["trip_id"])
                    routes[k]["name"], routes[k]["feed"] = rname.get(rid, rid).strip(), feed
                    stop_min_d[(feed, st["stop_id"])] = near[st["stop_id"]]
    rows = []
    for k, r in routes.items():
        dmin = np.min([stop_min_d[(r["feed"], s)] for s in r["stops"]], axis=0)
        r["per_dir"] = max(len(v) for v in r["at_stop"].values())  # busiest stop, one direction
        rows.append({"route": f"{r['feed'].upper()} {r['name']}", "trips_0730_0830": len(r["trips"]),
                     "busiest_stop_one_direction": r["per_dir"],
                     "people_within_400m": int(bpop[dmin <= 400].sum()), "people_within_800m": int(bpop[dmin <= 800].sum())})
    out = pd.DataFrame(rows).sort_values("busiest_stop_one_direction", ascending=False) if rows else pd.DataFrame()
    print(out.to_string(index=False) if len(out) else "no scheduled departures 07:30-08:30 within 800 m")
    if len(out):
        any_d = np.min(list(stop_min_d.values()), axis=0)
        freq_stops = [stop_min_d[(r["feed"], s)] for r in routes.values() if r["per_dir"] >= 4 for s in r["stops"]]
        freq_d = np.min(freq_stops, axis=0) if freq_stops else np.full(len(bpop), np.inf)
        tot = bpop.sum()
        print(f"residents within 400 m of a stop with morning service: {bpop[any_d <= 400].sum() / tot:.0%}; "
              f"800 m: {bpop[any_d <= 800].sum() / tot:.0%}")
        print(f"residents within 400 m of a route with 4+ departures in one direction 07:30-08:30 (every 15 min or better): {bpop[freq_d <= 400].sum() / tot:.0%}; "
              f"800 m: {bpop[freq_d <= 800].sum() / tot:.0%}")
    out.to_csv(HERE / f"routes_{story}.csv", index=False)


if __name__ == "__main__":
    main(sys.argv[1])
