"""Car slowdown calibration: engine free-flow time vs Google Maps typical
Tuesday 8 AM time for 15 GTA trips.

The engine's "free flow" already includes intersection delay (city trips run
22 to 30 km/h), so a published congestion factor cannot be applied directly.
Instead: factor = Google typical 8 AM time / engine time, median over trips.

The owner fills the google_* columns in research/data/traffic/calibration_trips.csv
by hand (Google Maps, Driving, Depart at Tuesday 8:00 AM).

    research/.venv/bin/python research/pilot/calibrate_car.py
"""
import csv
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from pilot import snap_to_roads  # noqa: E402

GQL = "http://localhost:8090/otp/routers/default/index/graphql"
OUT = Path(__file__).parent.parent / "data" / "traffic" / "calibration_trips.csv"

# (trip id, from name, from lat, from lon, to name, to lat, to lon)
TRIPS = [
    (1, "Union Station", 43.6453, -79.3806, "Yonge & Eglinton", 43.7066, -79.3985),
    (2, "Kensington Market", 43.6547, -79.4005, "Pape & Danforth", 43.6797, -79.3446),
    (3, "Jane & Finch", 43.7580, -79.5190, "Yorkdale Shopping Centre", 43.7254, -79.4521),
    (4, "Scarborough Town Centre", 43.7756, -79.2578, "Kennedy Station", 43.7324, -79.2637),
    (5, "Square One Shopping Centre", 43.5933, -79.6425, "Port Credit GO", 43.5553, -79.5870),
    (6, "Mount Joy GO", 43.9004, -79.2627, "CF Markville", 43.8690, -79.2890),
    (7, "Oakville GO", 43.4553, -79.6823, "Oakville Place", 43.4695, -79.6870),
    (8, "Brampton GO", 43.6868, -79.7627, "Bramalea City Centre", 43.7162, -79.7225),
    # Trips 9, 13, 15 corrected 2026-09-14 to GTFS stop locations (old points were
    # off-terminal, ~800 m from Milton GO, ~2 km from the hospital).
    (9, "Union Station", 43.6453, -79.3806, "Pearson Airport Terminal 1", 43.6822, -79.6133),
    (10, "Oshawa Centre", 43.8890, -78.8820, "Whitby GO", 43.8648, -78.9384),
    (11, "Vaughan Metropolitan Centre", 43.7942, -79.5273, "Yorkdale Shopping Centre", 43.7254, -79.4521),
    (12, "Scarborough Town Centre", 43.7756, -79.2578, "Fairview Mall", 43.7778, -79.3445),
    (13, "Milton GO", 43.5236, -79.8672, "Square One Shopping Centre", 43.5933, -79.6425),
    (14, "Richmond Hill Centre (Yonge & Hwy 7)", 43.8420, -79.4270, "CF Markville", 43.8690, -79.2890),
    (15, "Burlington GO", 43.3406, -79.8093, "Oakville Trafalgar Memorial Hospital", 43.4488, -79.7664),
]

Q = """{ plan(from:{lat:%f,lon:%f}, to:{lat:%f,lon:%f}, date:"2026-09-22", time:"08:00",
  transportModes:[{mode:CAR}], numItineraries:1) { itineraries { legs { mode distance duration } } } }"""


def main():
    pts = [(f"{t[0]}a", t[2], t[3], "", "") for t in TRIPS] + [(f"{t[0]}b", t[5], t[6], "", "") for t in TRIPS]
    snapped = {s[0]: s for s in snap_to_roads([p[:4] for p in pts])}
    rows = []
    for tid, fname, _, _, tname, _, _ in TRIPS:
        a, b = snapped[f"{tid}a"], snapped[f"{tid}b"]
        j = requests.post(GQL, json={"query": Q % (a[1], a[2], b[1], b[2])}, timeout=120).json()
        its = j["data"]["plan"]["itineraries"]
        car = [l for l in its[0]["legs"] if l["mode"] == "CAR"] if its else []
        km = sum(l["distance"] for l in car) / 1000
        mins = sum(l["duration"] for l in car) / 60
        rows.append({
            "trip": tid, "from": fname, "to": tname,
            "engine_km": round(km, 1) if car else "", "engine_min": round(mins, 1) if car else "",
            "engine_kmh": round(km / (mins / 60), 1) if car else "",
            "google_min_low": "", "google_min_high": "", "notes": "" if car else "engine found no car route",
        })
        print(rows[-1], flush=True)
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
