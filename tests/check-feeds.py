"""Checks for scripts/check-feeds.py. No network and no real schedules.

    python3 tests/check-feeds.py
"""
import contextlib
import importlib.util
import io
import os
import sys
import tempfile
import zipfile
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location(
    "check_feeds", os.path.join(ROOT, "scripts", "check-feeds.py"))
cf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cf)

TODAY = date(2026, 11, 16)
CAL = "service_id,monday,start_date,end_date\n"


def make_zip(path, calendar=None, dates=None, bom=False):
    """A tiny GTFS zip. calendar is (start, end) as YYYYMMDD; dates is a list
    of (YYYYMMDD, exception_type)."""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("stops.txt", "stop_id\n1\n")
        if calendar:
            text = CAL + f"a,1,{calendar[0]},{calendar[1]}\n"
            zf.writestr("calendar.txt", ("﻿" if bom else "") + text)
        if dates:
            text = "service_id,date,exception_type\n"
            text += "".join(f"a,{d},{t}\n" for d, t in dates)
            zf.writestr("calendar_dates.txt", text)


def run(folder, *extra):
    """Run main() and return (exit code, printed text)."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cf.main(["--dir", folder, "--date", "2026-11-16", *extra])
    return code, out.getvalue()


def test_every_verdict(folder):
    d = date
    assert cf.verdict(d(2026, 9, 1), d(2027, 3, 1), TODAY) == "ok"
    assert cf.verdict(d(2026, 9, 1), d(2026, 11, 30), TODAY) == "EXPIRES SOON"
    assert cf.verdict(d(2026, 9, 1), d(2026, 11, 16), TODAY) == "EXPIRES SOON"  # last day is today
    assert cf.verdict(d(2026, 9, 1), d(2026, 11, 15), TODAY) == "EXPIRED"
    assert cf.verdict(d(2026, 11, 17), d(2027, 1, 1), TODAY) == "NOT STARTED YET"
    assert cf.verdict(d(2026, 11, 16), d(2027, 1, 1), TODAY) == "ok"  # starts today


def test_the_14_day_edge(folder):
    d = date
    assert cf.verdict(d(2026, 9, 1), d(2026, 11, 30), TODAY) == "EXPIRES SOON"  # 14 left
    assert cf.verdict(d(2026, 9, 1), d(2026, 12, 1), TODAY) == "ok"             # 15 left


def test_range_from_calendar(folder):
    p = os.path.join(folder, "a.zip")
    make_zip(p, calendar=("20260906", "20261031"))
    assert cf.feed_range(p) == (date(2026, 9, 6), date(2026, 10, 31))


def test_a_byte_order_mark_is_ignored(folder):
    p = os.path.join(folder, "a.zip")
    make_zip(p, calendar=("20260906", "20261031"), bom=True)
    assert cf.feed_range(p) == (date(2026, 9, 6), date(2026, 10, 31))


def test_calendar_dates_only_feed(folder):
    p = os.path.join(folder, "a.zip")
    # exception_type 2 means service removed, so it must not count
    make_zip(p, dates=[("20261101", 1), ("20261220", 1), ("20270201", 2)])
    assert cf.feed_range(p) == (date(2026, 11, 1), date(2026, 12, 20))


def test_calendar_dates_extend_the_calendar(folder):
    p = os.path.join(folder, "a.zip")
    make_zip(p, calendar=("20260906", "20261031"), dates=[("20261105", 1), ("20260901", 1)])
    assert cf.feed_range(p) == (date(2026, 9, 1), date(2026, 11, 5))


def test_a_zip_with_no_service_days(folder):
    p = os.path.join(folder, "a.zip")
    make_zip(p)
    assert cf.feed_range(p) is None
    assert cf.check_one(p, TODAY)[3] == "MISSING"


def test_missing_and_broken_files_are_missing(folder):
    assert cf.check_one(os.path.join(folder, "nope.zip"), TODAY)[3] == "MISSING"
    bad = os.path.join(folder, "bad.zip")
    with open(bad, "wb") as fh:
        fh.write(b"<html>error page</html>")
    assert cf.check_one(bad, TODAY)[3] == "MISSING"
    empty = os.path.join(folder, "empty.zip")
    with open(empty, "wb") as fh:
        fh.write(b"PK\x05\x06" + b"\0" * 18)  # a valid but empty zip, 22 bytes
    assert cf.check_one(empty, TODAY)[3] == "MISSING"


def test_feed_names_come_from_feeds_sh(folder):
    names = cf.feed_names()
    assert "ttc" in names and "go" in names and len(names) == 10
    assert "grt" not in names and "barrie" not in names  # research-only zips


def good_folder(folder):
    for n in cf.feed_names():
        make_zip(os.path.join(folder, f"{n}-gtfs.zip"), calendar=("20260901", "20270301"))


def test_exit_0_when_all_ok(folder):
    good_folder(folder)
    code, text = run(folder)
    assert code == 0 and "All 10 feeds are good." in text, text


def test_exit_0_when_only_expiring_soon(folder):
    good_folder(folder)
    make_zip(os.path.join(folder, "ttc-gtfs.zip"), calendar=("20260901", "20261125"))
    code, text = run(folder)
    assert code == 0 and "EXPIRES SOON" in text and "run out within 14 days" in text, text


def test_exit_1_when_expired(folder):
    good_folder(folder)
    make_zip(os.path.join(folder, "ttc-gtfs.zip"), calendar=("20260901", "20261031"))
    code, text = run(folder)
    assert code == 1 and "EXPIRED" in text, text
    assert "1 of 10 feeds have run out. Follow docs/runbooks.md, 'Refresh the schedules'." in text


def test_exit_1_when_not_started(folder):
    good_folder(folder)
    make_zip(os.path.join(folder, "ttc-gtfs.zip"), calendar=("20261124", "20270101"))
    code, text = run(folder)
    assert code == 1 and "NOT STARTED YET" in text and "have not started yet" in text, text


def test_exit_1_when_a_zip_is_missing(folder):
    good_folder(folder)
    os.remove(os.path.join(folder, "go-gtfs.zip"))
    code, text = run(folder)
    assert code == 1 and "MISSING" in text and "missing or unreadable" in text, text


def test_a_bad_date_option_is_refused(folder):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert cf.main(["--dir", folder, "--date", "tomorrow"]) == 2


def main():
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_")]
    for name, fn in tests:
        with tempfile.TemporaryDirectory() as folder:
            fn(folder)
        print("ok", name)
    print(f"{len(tests)} passed")


if __name__ == "__main__":
    main()
