"""
GTA Router - inject subway interchange transfers into the TTC feed.

The TTC's published schedule data has no transfers.txt, so the router
doesn't know Bloor-Yonge, St George, etc. are internal transfers - it
routes you out to the sidewalk and back in, which makes every subway
transfer look slower than it is and skews rankings toward streetcars.

This script adds a transfers.txt to ttc-gtfs.zip declaring a minimum
transfer time between the subway platforms of each interchange station.
Re-run it after every fresh TTC download (setup.sh does this).

Usage:  python3 patch_ttc_transfers.py    (then rebuild the graph)
"""

import csv
import io
import zipfile

FEED = "ttc-gtfs.zip"
TRANSFER_SECONDS = 180  # 3 min: realistic for stairs between platforms

# Platforms are matched by stop_name prefix. Stations that interchange
# with each other are grouped; every subway platform in a group gets a
# transfer to every other platform in that group (and to itself, which
# covers changing direction).
INTERCHANGES = [
    # Line 1 <-> Line 2 at Bloor-Yonge (two GTFS station names, one building)
    ["Bloor Station", "Yonge Station"],
    ["St George Station"],       # Line 1 <-> Line 2
    ["Spadina Station"],         # Line 1 <-> Line 2
    ["Sheppard-Yonge Station"],  # Line 1 <-> Line 4
    ["Kennedy Station"],         # Line 2 terminal interchange
]


def main():
    with zipfile.ZipFile(FEED) as z:
        stops = list(csv.DictReader(io.TextIOWrapper(z.open("stops.txt"),
                                                     encoding="utf-8-sig")))
        already_patched = "transfers.txt" in z.namelist()

    rows = []
    for group in INTERCHANGES:
        platforms = [s["stop_id"] for s in stops
                     if "Platform" in s["stop_name"]
                     and any(s["stop_name"].startswith(name) for name in group)]
        names = [s["stop_name"] for s in stops if s["stop_id"] in platforms]
        print(f"{' + '.join(group)}: {len(platforms)} platforms")
        for a in platforms:
            for b in platforms:
                if a != b:
                    rows.append((a, b, 2, TRANSFER_SECONDS))

    if already_patched:
        print("transfers.txt already present - rewriting it.")
        # zipfile can't replace in place; rewrite the archive without it.
        import os
        import shutil
        with zipfile.ZipFile(FEED) as zin, \
             zipfile.ZipFile(FEED + ".tmp", "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename != "transfers.txt":
                    zout.writestr(item, zin.read(item.filename))
        shutil.move(FEED + ".tmp", FEED)

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["from_stop_id", "to_stop_id", "transfer_type",
                     "min_transfer_time"])
    writer.writerows(rows)
    with zipfile.ZipFile(FEED, "a", zipfile.ZIP_DEFLATED) as z:
        z.writestr("transfers.txt", out.getvalue())
    print(f"Wrote {len(rows)} transfer rules into {FEED}/transfers.txt")


if __name__ == "__main__":
    main()
