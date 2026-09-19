"""
Is there a hole in DRIVE_RELUCTANCE?

carReluctance is the only knob that changes which parking lot OTP returns,
and each value yields the one lot that is optimal at it, so the ladder in
index.html decides which lots the app can ever see. The current ladder,
[30, 2, 1], was measured for which LOT gets picked. This asks a different
question: which ladder gets you there EARLIEST.

It prices every candidate ladder in a single run. Each drive combo is asked
once per reluctance value, the non-drive combos once, and every ladder's
result is then the best over its own subset. So adding a candidate costs no
extra queries.

The app's 15 km drive cap is applied throughout, so nothing is counted that
the page would not display.

Usage (with the engine running):
    python3 tests/reluctance-ladder.py

Standard library only.
"""

import json
import os
import sys
import importlib.util
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "audit", os.path.join(HERE, "route-audit.py"))
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)

RELUCTANCES = [30.0, 12.0, 8.0, 5.0, 4.0, 2.0, 1.0]

CANDIDATES = {
    "[30,2,1] today": [30.0, 2.0, 1.0],
    "[30,8,2,1]":     [30.0, 8.0, 2.0, 1.0],
    "[30,5,2,1]":     [30.0, 5.0, 2.0, 1.0],
    "[30,8,4,2,1]":   [30.0, 8.0, 4.0, 2.0, 1.0],
    "[30,12,8,5,4,2,1] everything": RELUCTANCES,
}


def measure(trip, pool):
    """Best arrival per (combo, reluctance), plus the non-drive baseline."""
    jobs = []
    for combo in audit.APP_COMBOS:
        if combo.get("drive"):
            jobs += [(combo, r) for r in RELUCTANCES]
        else:
            jobs.append((combo, None))

    def run(job):
        combo, r = job
        try:
            return combo, r, audit.keep(combo, audit.ask(
                trip, audit.modes_for(combo), audit.APP_FIRST,
                audit.prefs_for(combo, r)))
        except Exception:
            return combo, r, []

    by_rel, baseline = {}, None
    for combo, r, itins in pool.map(run, jobs):
        for it in itins:
            if combo.get("drive") and audit.car_distance(it) > audit.MAX_DRIVE_M:
                continue
            a = audit.arrival(it)
            if r is None:
                baseline = a if baseline is None else min(baseline, a)
            else:
                by_rel[r] = a if r not in by_rel else min(by_rel[r], a)
    return by_rel, baseline


def main():
    trips = []
    for name in ("benchmarks.json", "audit-trips.json"):
        with open(os.path.join(HERE, name)) as fh:
            trips += json.load(fh)["trips"]
    seen, unique = set(), []
    for t in trips:
        if t["id"] not in seen:
            seen.add(t["id"])
            unique.append(t)

    names = list(CANDIDATES)
    print(f"{len(unique)} trips. Minutes EARLIER than the ladder in use today.")
    print("Higher is better. 0 means that ladder changes nothing.\n")
    header = f"{'trip':<38}" + "".join(f"{n.split()[0]:>14}" for n in names)
    print(header)
    print("-" * len(header))

    totals = {n: 0 for n in names}
    wins = {n: 0 for n in names}
    with ThreadPoolExecutor(max_workers=8) as pool:
        for trip in unique:
            by_rel, baseline = measure(trip, pool)
            best = {}
            for n, ladder in CANDIDATES.items():
                vals = [by_rel[r] for r in ladder if r in by_rel]
                if baseline is not None:
                    vals.append(baseline)
                best[n] = min(vals) if vals else None
            today = best[names[0]]
            row = f"{trip['id']:<38}"
            for n in names:
                if best[n] is None or today is None:
                    row += f"{'-':>14}"
                    continue
                gain = round((today - best[n]) / 60)
                totals[n] += max(gain, 0)
                if gain >= 5:
                    wins[n] += 1
                row += f"{(str(gain) if gain else '.'):>14}"
            print(row)

    print()
    print(f"{'ladder':<34}{'trips helped 5min+':>20}{'total min saved':>18}")
    for n in names:
        print(f"{n:<34}{wins[n]:>20}{totals[n]:>18}")


if __name__ == "__main__":
    main()
