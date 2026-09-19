"""
Would a wider fan-out actually help, and how often?

route-audit.py found options the app misses. This measures what one specific
change would buy, across every audit trip, so the decision rests on a spread
rather than on the single trip that prompted it.

The change under test, both parts needed together:
  1. a tenth mode mix, CAR_PARKING access with CAR_PICKUP egress: park at a
     station near home, get picked up at the far end. The app fires "drive to
     a station" and "get picked up at the end" but never both at once.
  2. carReluctance 4 and 8 added to DRIVE_RELUCTANCE. The existing 30/2/1
     ladder was measured for which PARKING LOT the engine picks, before
     two-car-leg trips were possible. The mid band is where the pickup
     surfaces: at 4 and 5 it comes back as a normal kept result, at 30/20
     only as an itinerary OTP deleted, and at 12/8/3/2/1 not at all.

Both sides apply the app's real 15 km drive cap, so nothing is counted that
the page would not actually display.

Usage (with the engine running):
    python3 tests/combo-proposal.py

Standard library only.
"""

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib.util

spec = importlib.util.spec_from_file_location(
    "audit", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "route-audit.py"))
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)

EXTRA_COMBO = {"key": "Drive to station, picked up at the end",
               "access": ["CAR_PARKING"], "egress": ["WALK", "CAR_PICKUP"],
               "drive": True, "needsLeg": "CAR"}
EXTRA_RELUCTANCE = [8.0, 4.0]


def best(trip, combos, reluctances, pool):
    jobs = []
    for combo in combos:
        if combo.get("drive"):
            jobs += [(combo, r) for r in reluctances]
        else:
            jobs.append((combo, None))

    def run(job):
        combo, r = job
        try:
            return combo, audit.keep(combo, audit.ask(
                trip, audit.modes_for(combo), audit.APP_FIRST,
                audit.prefs_for(combo, r)))
        except Exception:
            return combo, []

    found = {}
    for combo, itins in pool.map(run, jobs):
        for it in itins:
            if combo.get("drive") and audit.car_distance(it) > audit.MAX_DRIVE_M:
                continue
            found.setdefault(audit.signature(it), it)
    if not found:
        return None
    return min(found.values(), key=audit.arrival)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    trips = []
    for name in ("benchmarks.json", "audit-trips.json"):
        with open(os.path.join(here, name)) as fh:
            trips += json.load(fh)["trips"]
    seen, unique = set(), []
    for t in trips:
        if t["id"] not in seen:
            seen.add(t["id"])
            unique.append(t)

    print(f"{len(unique)} trips. Positive minutes = the wider fan-out gets "
          f"you there earlier.\n")
    print(f"{'trip':<38} {'now':>7} {'proposed':>9} {'gain':>6}")
    print("-" * 63)
    gains = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for trip in unique:
            now = best(trip, audit.APP_COMBOS, audit.DRIVE_RELUCTANCE, pool)
            prop = best(trip, audit.APP_COMBOS + [EXTRA_COMBO],
                        audit.DRIVE_RELUCTANCE + EXTRA_RELUCTANCE, pool)
            if now is None or prop is None:
                print(f"{trip['id']:<38} {'-':>7} {'-':>9} {'-':>6}")
                continue
            gain = round((audit.arrival(now) - audit.arrival(prop)) / 60)
            gains.append((gain, trip["id"], now, prop))
            mark = "  <==" if gain >= 5 else ""
            print(f"{trip['id']:<38} {round(now['duration']/60):>5} m "
                  f"{round(prop['duration']/60):>7} m {gain:>5}{mark}")

    print()
    helped = [g for g in gains if g[0] >= 5]
    hurt = [g for g in gains if g[0] < 0]
    print(f"{len(helped)} of {len(gains)} trips improve by 5 min or more.")
    if hurt:
        print(f"{len(hurt)} got WORSE, which should be impossible: "
              f"the proposal only adds queries.")
    for gain, tid, now, prop in sorted(helped, reverse=True):
        print(f"\n  {tid}: {gain} min earlier")
        print(f"     now:      {audit.describe(now)}")
        print(f"     proposed: {audit.describe(prop)}")


if __name__ == "__main__":
    main()
