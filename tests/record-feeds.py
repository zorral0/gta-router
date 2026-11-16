"""Checks for scripts/record-feeds.py. No network and no real recordings.

    python3 tests/record-feeds.py
"""
import importlib.util
import io
import os
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
spec = importlib.util.spec_from_file_location(
    "record_feeds", os.path.join(ROOT, "scripts", "record-feeds.py"))
rec = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rec)

from pbwire import emit  # noqa: E402

LOTS_FREE = lambda _: rec.MIN_FREE_BYTES + 1  # noqa: E731


def feed(stamp, *entities):
    """A minimal FeedMessage: a header holding stamp, then the entities."""
    raw = emit(rec.F_HEADER, 2, emit(3, 0, stamp))
    for e in entities:
        raw += emit(rec.F_ENTITY, 2, e)
    return raw


def poll(state, out, raw, **kw):
    kw.setdefault("free_bytes", LOTS_FREE)
    rec.poll_once("demo", "http://x", state, out, "run", fetcher=lambda _: raw, **kw)


def saved_records(out):
    found = []
    for folder, _, files in os.walk(os.path.join(out, "feeds")):
        for f in sorted(files):
            found += list(rec.read_records(os.path.join(folder, f)))
    return found


def test_saves_raw_bytes_and_reads_them_back(out):
    state = rec.new_state(15)
    a, b = feed(1, b"one"), feed(2, b"two")
    poll(state, out, a)
    poll(state, out, b)
    assert [r[1] for r in saved_records(out)] == [a, b]
    assert state["saved"] == 2 and state["failed"] == 0


def test_only_the_header_changing_is_not_saved_again(out):
    state = rec.new_state(15)
    poll(state, out, feed(1, b"same"))
    poll(state, out, feed(2, b"same"))
    assert state["saved"] == 1 and state["unchanged"] == 1


def test_a_feed_with_no_entities_is_still_valid(out):
    state = rec.new_state(15)
    poll(state, out, feed(1))
    assert state["saved"] == 1 and state["failed"] == 0


def test_an_error_page_is_rejected_and_not_saved(out):
    for bad in (b"<html>Service unavailable</html>", b"", b'{"error": "nope"}'):
        state = rec.new_state(15)
        poll(state, out, bad)
        assert state["failed"] == 1 and state["saved"] == 0, bad
    assert saved_records(out) == []


def test_the_key_never_reaches_the_status(out):
    def boom(_):
        raise OSError("could not open https://x/?key=SECRET123")
    state = rec.new_state(15)
    rec.poll_once("demo", "http://x", state, out, "run", "SECRET123", fetcher=boom)
    assert "SECRET123" not in state["last_error"] and "KEY" in state["last_error"]


def test_a_low_disk_stops_saving_and_shows_up(out):
    state = rec.new_state(15)
    poll(state, out, feed(1, b"x"), free_bytes=lambda _: 1)
    assert state["saved"] == 0 and "disk" in state["last_error"]
    assert saved_records(out) == []


def test_a_recovered_feed_clears_its_error(out):
    state = rec.new_state(15)
    poll(state, out, b"<html>")
    assert state["fails_in_a_row"] == 1
    poll(state, out, feed(1, b"x"))
    assert state["fails_in_a_row"] == 0 and state["last_error"] is None


def test_failing_feeds_wait_longer_up_to_the_limit(out):
    assert rec.backoff(15, 1) == 30 and rec.backoff(15, 2) == 60
    assert rec.backoff(15, 500) == rec.MAX_BACKOFF_SECONDS


def test_a_damaged_tail_keeps_the_earlier_snapshots(out):
    path = os.path.join(out, "x.gz")
    a, b = feed(1, b"one"), feed(2, b"two")
    rec.save_record(path, a, 100)
    rec.save_record(path, b, 200)
    with open(path, "rb") as fh:
        whole = fh.read()
    with open(path, "wb") as fh:
        fh.write(whole[:-5])
    assert list(rec.read_records(path)) == [(100.0, a)]


def test_files_are_split_by_utc_hour_and_run(out):
    # 2026-11-03 00:30 UTC is still Nov 2 in Toronto; the folder must use UTC
    path = rec.record_path(out, "demo", 1793665800, "r1")
    assert path.endswith(os.path.join("feeds", "demo", "2026-11-03", "00-r1.gz")), path


def gtfs_zip(body):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("stops.txt", body)
    return buf.getvalue()


def test_a_schedule_is_kept_only_when_it_changes(out):
    a, b = gtfs_zip("a"), gtfs_zip("b")
    assert rec.save_schedule(out, a, 1793665800)
    assert rec.save_schedule(out, a, 1793665800 + 86400) is None
    assert rec.save_schedule(out, b, 1793665800 + 86400)
    assert len([f for f in os.listdir(out) if f.endswith(".zip")]) == 2
    assert not [f for f in os.listdir(out) if f.endswith(".tmp")]


def test_a_broken_schedule_download_is_rejected(out):
    for bad in (b"<html>not a zip</html>", _zip_without_stops()):
        try:
            rec.save_schedule(out, bad, 1793665800)
        except Exception:
            pass
        else:
            raise AssertionError("a broken schedule was accepted")
    assert os.listdir(out) == []


def _zip_without_stops():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("readme.txt", "x")
    return buf.getvalue()


def test_every_recorded_schedule_has_an_address(out):
    assert {n for n, _ in rec.schedule_urls()} == set(rec.SCHEDULES)


def test_health_verdicts(out):
    s = rec.new_state(15)
    assert rec.feed_health(s, 1000) == "starting"
    s["last_ok"] = 1000
    assert rec.feed_health(s, 1010) == "ok"
    assert rec.feed_health(s, 2000) == "PROBLEM"
    s["last_ok"], s["fails_in_a_row"], s["last_error"] = 1000, 3, "HTTP 500"
    assert rec.feed_health(s, 1010) == "PROBLEM"
    # one failure with no success yet, like a schedule that came back broken
    s = rec.new_state(86400)
    s["fails_in_a_row"], s["last_error"] = 1, "no stops.txt"
    assert rec.feed_health(s, 1000) == "PROBLEM"


def test_a_frozen_fast_feed_is_stale_but_quiet_alerts_are_fine(out):
    hours = 3600
    s = rec.new_state(rec.VEHICLES)
    s["last_ok"], s["last_saved"] = 100 * hours, 100 * hours
    assert rec.feed_health(s, 100 * hours + 60) == "ok"
    s["last_ok"] = 110 * hours          # still answering, nothing new for 10 h
    assert rec.feed_health(s, 110 * hours + 10) == "STALE"
    s["last_ok"] = 105 * hours          # a quiet night is not long enough
    assert rec.feed_health(s, 105 * hours + 10) == "ok"
    alerts = rec.new_state(rec.SLOW)
    alerts["last_ok"], alerts["last_saved"] = 500 * hours, 100 * hours
    assert rec.feed_health(alerts, 500 * hours + 10) == "ok"


def main():
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_")]
    for name, fn in tests:
        with tempfile.TemporaryDirectory() as out:
            fn(out)
        print("ok", name)
    print(f"{len(tests)} passed")


if __name__ == "__main__":
    main()
