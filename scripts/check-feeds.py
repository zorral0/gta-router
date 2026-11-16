#!/usr/bin/env python3
"""
GTA Router - say which schedule feeds have run out, or are about to.

The app silently finds no trips for an agency whose schedule has run out,
and once a refresh downloaded a feed whose service only started 8 days
later, which made that agency vanish for a week. This reads every schedule
zip in engine/ (the list comes from scripts/feeds.sh, the same list
setup.sh and refresh.sh use), finds the first and last day each one has
service, and prints one plain line per feed:

    ok               fine
    EXPIRES SOON     14 days or fewer left
    EXPIRED          the last service day is in the past
    NOT STARTED YET  the first service day is still ahead
    MISSING          no zip, or one that cannot be read

"Today" is Toronto's date. The exit code is 0 when everything is ok or only
expiring soon, and 1 when any feed is EXPIRED, NOT STARTED YET or MISSING.

    python3 scripts/check-feeds.py
    python3 scripts/check-feeds.py --dir some/other/folder
    python3 scripts/check-feeds.py --date 2026-12-01     pretend it is that day

Standard library only, like the rest of scripts/.
"""
import argparse
import csv
import io
import os
import re
import sys
import zipfile
from datetime import date, datetime
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOON_DAYS = 14

OK, SOON, EXPIRED = "ok", "EXPIRES SOON", "EXPIRED"
NOT_STARTED, MISSING = "NOT STARTED YET", "MISSING"
BAD = (EXPIRED, NOT_STARTED, MISSING)


def feed_names(root=ROOT):
    """The feed names, in order, from the one list setup.sh and refresh.sh use."""
    with open(os.path.join(root, "scripts", "feeds.sh")) as fh:
        return re.findall(r'"([a-z0-9]+)-gtfs\.zip \S+"', fh.read())


def _day(text):
    try:
        return datetime.strptime(text.strip(), "%Y%m%d").date()
    except ValueError:
        return None


def _rows(zf, name):
    """The rows of one file in the zip as dicts; [] when the file is absent.
    utf-8-sig drops the byte-order mark some agencies put at the start."""
    if name not in zf.namelist():
        return []
    text = zf.read(name).decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(text)))


def feed_range(path):
    """(first, last): the earliest and latest service day in a GTFS zip, as
    dates, or None when it has no service days at all. Raises OSError or
    zipfile.BadZipFile when the file is missing or is not a zip."""
    days = []
    with zipfile.ZipFile(path) as zf:
        for row in _rows(zf, "calendar.txt"):
            days += [_day(row.get("start_date") or ""), _day(row.get("end_date") or "")]
        for row in _rows(zf, "calendar_dates.txt"):
            if (row.get("exception_type") or "").strip() == "1":
                days.append(_day(row.get("date") or ""))
    days = [d for d in days if d]
    return (min(days), max(days)) if days else None


def verdict(first, last, today):
    """The plain verdict for a feed whose service runs first..last."""
    if first > today:
        return NOT_STARTED
    if last < today:
        return EXPIRED
    if (last - today).days <= SOON_DAYS:
        return SOON
    return OK


def check_one(path, today):
    """(first, last, days_left, verdict, note) for one zip. A zip that is
    absent or unreadable is MISSING, with a note saying which."""
    if not os.path.exists(path):
        return None, None, None, MISSING, "no file"
    try:
        found = feed_range(path)
    except (OSError, zipfile.BadZipFile):
        return None, None, None, MISSING, "not a readable zip"
    if not found:
        return None, None, None, MISSING, "no service dates in it"
    first, last = found
    return first, last, (last - today).days, verdict(first, last, today), ""


def toronto_today():
    return datetime.now(ZoneInfo("America/Toronto")).date()


def summary(results):
    """One plain sentence on what to do. results: list of (name, verdict)."""
    total = len(results)
    count = lambda v: sum(1 for _, x in results if x == v)  # noqa: E731
    problems = []
    if count(EXPIRED):
        problems.append(f"{count(EXPIRED)} of {total} feeds have run out")
    if count(NOT_STARTED):
        problems.append(f"{count(NOT_STARTED)} of {total} feeds have not started yet")
    if count(MISSING):
        problems.append(f"{count(MISSING)} of {total} feeds are missing or unreadable")
    how = "Follow docs/runbooks.md, 'Refresh the schedules'."
    if problems:
        text = ". ".join(problems) + ". " + how
        if count(NOT_STARTED):
            text += (" A feed that has not started yet would break today's"
                     " trips, so do not build the graph with it until its first day.")
        return text
    if count(SOON):
        return f"{count(SOON)} of {total} feeds run out within {SOON_DAYS} days. Plan a refresh. {how}"
    return f"All {total} feeds are good."


def main(argv=None):
    ap = argparse.ArgumentParser(description="Check which schedule feeds have run out.")
    ap.add_argument("--dir", default=os.path.join(ROOT, "engine"),
                    help="folder holding the <name>-gtfs.zip files (default: engine/)")
    ap.add_argument("--date", help="pretend today is this day, YYYY-MM-DD (for testing)")
    args = ap.parse_args(argv)

    try:
        today = date.fromisoformat(args.date) if args.date else toronto_today()
    except ValueError:
        print("--date must look like 2026-12-01")
        return 2

    names = feed_names()
    if not names:
        print("Could not read the feed list from scripts/feeds.sh.")
        return 2

    print(f"Schedule feeds in {args.dir}, checked for {today} (Toronto date)")
    print(f"  {'feed':10} {'first day':10}  {'last day':10}  {'days left':>9}  verdict")
    results = []
    for name in names:
        path = os.path.join(args.dir, f"{name}-gtfs.zip")
        first, last, left, v, note = check_one(path, today)
        results.append((name, v))
        if first is None:
            print(f"  {name:10} {'-':10}  {'-':10}  {'-':>9}  {v} ({note})")
        else:
            print(f"  {name:10} {first.isoformat():10}  {last.isoformat():10}  {left:>9}  {v}")
    print()
    print(summary(results))
    return 1 if any(v in BAD for _, v in results) else 0


if __name__ == "__main__":
    sys.exit(main())
