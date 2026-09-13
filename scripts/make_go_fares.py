"""
Extract GO Transit's station-to-station fare table.

GO publishes its exact adult fares inside its GTFS feed (fare_rules.txt and
fare_attributes.txt, keyed by stop zone). This script converts them to
web/go-fares.json, which the web app uses instead of estimating fares from
distance.

Re-run after every fresh GO download (setup.sh and refresh.sh do this).

Usage:  python3 scripts/make_go_fares.py
"""

import csv
import io
import json
import os
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEED = os.path.join(ROOT, "engine", "go-gtfs.zip")
OUT = os.path.join(ROOT, "web", "go-fares.json")


def rows(z, name):
    return csv.DictReader(io.TextIOWrapper(z.open(name), encoding="utf-8-sig"))


def main():
    with zipfile.ZipFile(FEED) as z:
        zones = {s["stop_id"]: s["zone_id"] for s in rows(z, "stops.txt")
                 if s.get("zone_id")}
        price = {f["fare_id"]: float(f["price"])
                 for f in rows(z, "fare_attributes.txt")}
        fares = {}
        for r in rows(z, "fare_rules.txt"):
            p = price.get(r["fare_id"])
            if p is not None:
                fares[r["origin_id"] + "|" + r["destination_id"]] = p

    with open(OUT, "w") as f:
        json.dump({"zones": zones, "fares": fares}, f, separators=(",", ":"))
    print(f"Wrote {OUT}: {len(zones)} stops, {len(fares)} zone-pair fares")


if __name__ == "__main__":
    main()
