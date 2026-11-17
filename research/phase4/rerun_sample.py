"""Phase 4 reproducibility check: re-request a fixed 2% of starting points.

Sends exactly the same requests as the overnight run (run_reach.request_plan)
for a fixed 2% sample, saves them to research/phase4/rerun_surfaces/ (never
into surfaces_v2/), and compares each new map with the saved one: first
byte for byte, then, if bytes differ, cell by cell.

Needs the research buffer engine on :8091 (see research/phase2/README.md),
with run.sh stopped so the Mac is not short of memory.

Run: research/.venv/bin/python research/phase4/rerun_sample.py [--workers 8]
"""
import argparse
import csv
import hashlib
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import requests

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
sys.path.insert(0, str(RESEARCH / "phase2"))
import run_reach as rr  # noqa: E402
from surface import read_surface  # noqa: E402

API = "http://localhost:8091"
OUT = HERE / "rerun_surfaces"
SAVED = RESEARCH / "phase2" / "surfaces_v2"


def in_sample(oid):
    return int(hashlib.sha256(f"repro:{oid}".encode()).hexdigest()[:8], 16) % 50 == 0


def compare(a, b):
    if a.read_bytes() == b.read_bytes():
        return "identical", 0, 0
    wa, ha, va, ta = read_surface(a)
    wb, hb, vb, tb = read_surface(b)
    if (wa, ha, ta) != (wb, hb, tb):
        return "different_grid", -1, -1
    x, y = np.frombuffer(va, np.int32), np.frombuffer(vb, np.int32)
    diff = x != y
    return "values_differ", int(diff.sum()), int(np.abs(x[diff].astype(np.int64) - y[diff]).max())


def one(o):
    d = OUT / o["origin_id"]
    d.mkdir(parents=True, exist_ok=True)
    rows = []
    s = requests.Session()
    for req in rr.request_plan(o):
        lat, lon = (o["snap_lat"], o["snap_lon"]) if req.start == "main" else (o["alt_lat"], o["alt_lon"])
        f = d / f"{req.name}.tif"
        if not f.exists():
            r = s.get(API + "/otp/traveltime/surface", timeout=(10, 300),
                      params={"location": f"{lat},{lon}", "time": req.when, "modes": req.modes, "cutoff": req.cutoff})
            r.raise_for_status()
            f.write_bytes(r.content)
        saved = SAVED / o["origin_id"] / f.name
        status, ncells, maxdiff = compare(f, saved) if saved.exists() else ("no_saved_file", -1, -1)
        rows.append({"origin_id": o["origin_id"], "file": f.name, "status": status,
                     "cells_differ": ncells, "max_diff_s": maxdiff})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    requests.get(API + "/otp", timeout=10).raise_for_status()
    with open(RESEARCH / "phase2" / "origins_snapped_v2.csv", newline="") as f:
        origins = [o for o in csv.DictReader(f) if in_sample(o["origin_id"])]
    print(f"{len(origins)} points in the 2% sample")
    rows = []
    with ThreadPoolExecutor(a.workers) as ex:
        for i, r in enumerate(ex.map(one, origins), 1):
            rows += r
            if i % 25 == 0:
                print(f"{i}/{len(origins)}", flush=True)
    with open(HERE / "rerun_results.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    from collections import Counter
    print(Counter(r["status"] for r in rows))


if __name__ == "__main__":
    main()
