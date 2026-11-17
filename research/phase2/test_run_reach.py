"""Offline tests for run_reach.py, version 2 (no engine needed). Run:

    research/.venv/bin/python research/phase2/test_run_reach.py

Checks the request plan (names, times, cutoffs, samples), the --dry-run
output, and that a re-run skips files already saved and valid.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_reach as rr  # noqa: E402

SAMPLE = (HERE / "test_data" / "sample_transit_45M.tif").read_bytes()
HHMM = "0730 0735 0740 0745 0750 0755 0800 0805 0810 0815 0820 0825 0830".split()


def origin(oid, snap_m=50.0, alt=True):
    return dict(origin_id=oid, DAUID=oid[:8], kind="da", weight="500", lat="43.7", lon="-79.4",
                snap_lat="43.7", snap_lon="-79.4", snap_m=str(snap_m),
                alt_lat="43.701" if alt else "", alt_lon="-79.401" if alt else "", alt_m="60", alt_how="second_road",
                snap_highway="residential", alt_highway="residential")


def find_ids(pred, n=1):
    out, i = [], 0
    while len(out) < n:
        if pred(str(i)):
            out.append(str(i))
        i += 1
    return out


def test_plan():
    assert rr.DESIGN == "v2" and rr.TRANSIT_CUTOFFS == (30, 60) and rr.SENSITIVITY_CUTOFF == 45
    plain = find_ids(lambda x: not rr.in_sensitivity_sample(x) and not rr.in_qa_sample(x))[0]
    p = rr.request_plan(origin(plain))
    names = [r.name for r in p]
    assert len(p) == 27, len(p)
    assert names[:13] == [f"am_30_{h}" for h in HHMM], names
    assert names[13] == "car_30" and names[14] == "am_60_0730" and names[-1] == "am_60_0830"
    assert all(r.cutoff == "30M" for r in p[:13]) and all(r.cutoff == "60M" for r in p[14:])
    assert p[0].when == "2026-09-22T07:30:00-04:00" and p[-1].when == "2026-09-22T08:30:00-04:00"
    assert p[13].modes == "CAR" and p[13].cutoff == "30M" and p[13].when == "2026-09-22T08:00:00-04:00"

    sens = find_ids(lambda x: rr.in_sensitivity_sample(x) and not rr.in_qa_sample(x))[0]
    p = rr.request_plan(origin(sens))
    assert len(p) == 40 and [r.name for r in p][-13:] == [f"am_45_{h}" for h in HHMM]
    assert all(r.cutoff == "45M" for r in p[-13:])

    # backup-point car: input flags or the 5% sample
    assert rr.request_plan(origin(plain, snap_m=301))[-1].name == "car_30_alt"
    assert rr.request_plan(origin(plain, snap_m=301))[-1].start == "alt"
    assert rr.request_plan(origin(plain, snap_m=300))[-1].name != "car_30_alt"
    assert rr.input_flags(origin(plain, alt=False)) == ["no_backup_point"]
    assert "car_30_alt" not in [r.name for r in rr.request_plan(origin(plain, alt=False))]
    qa = find_ids(lambda x: rr.in_qa_sample(x) and not rr.in_sensitivity_sample(x))[0]
    assert [r.name for r in rr.request_plan(origin(qa))].count("car_30_alt") == 1

    ids = [str(3500000000 + i) for i in range(20000)]
    s10 = sum(map(rr.in_sensitivity_sample, ids)) / len(ids)
    s5 = sum(map(rr.in_qa_sample, ids)) / len(ids)
    assert 0.09 < s10 < 0.11 and 0.04 < s5 < 0.06, (s10, s5)

    p = rr.request_plan(origin(plain), rr.parse_periods("sun,am,pm"))
    names = [r.name for r in p]
    assert len(p) == 79 and names.count("car_30") == 1
    assert "pm_30_2030" in names and "pm_60_2130" in names and "sun_30_1030" in names and "sun_60_1130" in names
    assert not any(n.startswith(("pm_45", "sun_45")) for n in names)
    assert rr.done_marker(Path("x"), ["am"]).name == "_done_v2_am"
    print("ok  request plan")


def test_dry_run():
    out = subprocess.run([sys.executable, str(HERE / "run_reach.py"), "--dry-run"], capture_output=True, text=True,
                         check=True).stdout
    assert "no engine calls" in out and "Design v2" in out, out[:500]
    n = int(out.split("Full job: ")[1].split()[0])
    assert 13000 < n < 14000, n
    assert f"base          27 per origin x {n} = {27 * n}" in out, out
    total = int(out.split("  total ")[1].split()[0])
    hours = float(out.split("  estimate ")[1].split()[0])
    assert abs(hours - total * rr.SEC_PER_REQUEST / 3600) < 0.06, (total, hours)
    print(f"ok  dry run: {n} starting points, {total} requests, {hours} h (lower bound)")


def test_resume():
    tmp = Path(tempfile.mkdtemp())
    try:
        calls = []
        args = SimpleNamespace(api="http://unused", timeout=1, periods=["am"])
        runner = rr.Runner(args, tmp / "surfaces_v2", tmp / "errors_v2.csv", tmp / "qa_flags_v2.csv")
        runner.fetch = lambda lat, lon, when, modes, cutoff: calls.append((lat, when, cutoff)) or SAMPLE
        o = origin(find_ids(lambda x: not rr.in_sensitivity_sample(x) and not rr.in_qa_sample(x))[0], snap_m=400)
        ok, fetched = runner.do_origin(o)
        d = tmp / "surfaces_v2" / o["origin_id"]
        assert ok and fetched == 28 == len(calls) and rr.done_marker(d, ["am"]).exists()
        assert calls[-1][0] == "43.701"  # car_30_alt comes from the backup point
        ok, fetched = runner.do_origin(o)
        assert ok and fetched == 0 and len(calls) == 28
        (d / "am_60_0800.tif").unlink()
        (d / "am_30_0735.tif").write_bytes(b"II*\x00short")
        ok, fetched = runner.do_origin(o)
        assert ok and fetched == 2 and sorted(c[1][11:16] + c[2] for c in calls[28:]) == ["07:3530M", "08:0060M"]
        rows = (tmp / "qa_flags_v2.csv").read_text().splitlines()
        assert len(rows) == 2 and rows[0].split(",") == rr.QA_COLS and rr.QA_COLS[0] == "origin_id", rows
        print("ok  resume skips saved files and refetches missing or broken ones")
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    test_plan()
    test_dry_run()
    test_resume()
    print("all run_reach tests passed")
