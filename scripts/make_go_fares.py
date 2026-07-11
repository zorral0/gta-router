"""
GTA Router - extract GO Transit's real fare table.

GO publishes its exact station-to-station adult fares inside its GTFS
feed (fare_rules.txt + fare_attributes.txt, keyed by stop zone). This
script converts them to web/go-fares.json, which both the web app and
costs.py use instead of guessing fares from distance.

Re-run after every fresh GO download (setup.sh does this).

Usage:  python3 make_go_fares.py
"""

import csv
import io
import json
import zipfile

FEED = "go-gtfs.zip"
OUT = "web/go-fares.json"


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
