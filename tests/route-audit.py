"""
Best-route audit.

benchmark.py asks "is the answer sane?". This asks a harder question:
"could the engine have shown a BETTER answer than the app actually found?"

Two searches run for every trip.

  APP     - a faithful mirror of what web/index.html fires: the nine mode
            mixes in COMBOS, the three DRIVE_RELUCTANCE values on every
            drive combo, first:8, the same result filters, pooled and
            reduced to the same Pareto lead set.
  ORACLE  - the same trip asked far more expensively than any real page
            could afford: a wide reluctance ladder, a 3 hour search window,
            first:50, itineraryFilterDebugProfile LIST_ALL (which returns
            the itineraries OTP's own filters DELETED), and several mode
            mixes the app never fires at all.

If the oracle finds something meaningfully faster than the app's best, the
route existed and the app simply never asked the right question. That is a
bug in the fan-out, not in OTP.

Findings are split, because not every gap is a defect:

  MISSED  - faster, and shaped like something the app would legitimately
            show. A real bug.
  POLICY  - faster, but hidden on purpose (a pure ride past its effort cap,
            or a bike carried aboard, which GO bans at peak). Reported so
            the rule stays a decision rather than an accident.

Time and shape only. Money is graded separately: this script would have to
duplicate the fare model a third time to judge cost, and there are already
two copies to keep in sync.

Usage (with the engine running):
    python3 tests/route-audit.py              # every trip
    python3 tests/route-audit.py union        # trips whose id contains a word
    python3 tests/route-audit.py -v           # also print each search's best

Standard library only.
"""

import json
import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

OTP_URL = "http://localhost:8080/otp/gtfs/v1"

# A gap smaller than this is search-window jitter, not a missed route.
SIGNIFICANT_SEC = 120

# Options are ranked by when they get you THERE, not by how long the ride
# lasts. Ranking on duration alone called a 20 minute trip departing at 01:46
# "better" than a 64 minute trip departing at 22:22, which is nonsense: the
# waiting is part of the trip. Arrival time makes the comparison honest,
# because both searches start from the same requested departure.

# The drive slider's default (maxDriveM in index.html, and the value= on
# #driveRange). visibleIts() drops longer drives before they ever render, so
# an audit that ignores it would report options the user cannot actually see.
MAX_DRIVE_M = 15000

TRANSIT = {"BUS", "RAIL", "SUBWAY", "TRAM", "FERRY", "CABLE_CAR",
           "GONDOLA", "FUNICULAR", "COACH", "MONORAIL", "TROLLEYBUS"}

# ---------------------------------------------------------------- the app

# Mirror of COMBOS in web/index.html, with every "Using:" toggle on.
# Keep in step with that list: a combo missing here would be reported as a
# hole in the app that the app does not actually have.
APP_COMBOS = [
    {"key": "Transit only", "access": ["WALK"], "egress": ["WALK"]},
    {"key": "Bike to station", "access": ["BICYCLE_PARKING"], "egress": ["WALK"],
     "needsLeg": "BICYCLE"},
    {"key": "Bike Share at the start", "access": ["BICYCLE_RENTAL", "WALK"],
     "egress": ["WALK"], "rentStart": True, "walkReluctance": 6.0},
    # extraReluctance mirrors index.html: one more value, this combo only
    {"key": "Drive to station", "access": ["CAR_PARKING"], "egress": ["WALK"],
     "drive": True, "needsLeg": "CAR", "extraReluctance": [8.0]},
    {"key": "Drive at the end", "access": ["WALK"], "egress": ["WALK", "CAR_PICKUP"],
     "drive": True, "carAfter": True},
    {"key": "Bike Share at the end", "access": ["WALK"],
     "egress": ["WALK", "BICYCLE_RENTAL"], "rentEnd": True, "walkReluctance": 6.0},
    {"key": "Drive + Bike Share at the end", "access": ["CAR_PARKING"],
     "egress": ["WALK", "BICYCLE_RENTAL"], "drive": True, "needsLeg": "CAR",
     "rentEnd": True, "walkReluctance": 6.0},
    {"key": "Bike + Bike Share at the end", "access": ["BICYCLE_PARKING"],
     "egress": ["WALK", "BICYCLE_RENTAL"], "needsLeg": "BICYCLE",
     "rentEnd": True, "walkReluctance": 6.0},
    {"key": "Bike + drive at the end", "access": ["BICYCLE_PARKING"],
     "egress": ["WALK", "CAR_PICKUP"], "drive": True, "needsLeg": "BICYCLE",
     "carAfter": True},
    {"key": "Bike the whole way", "pure": "BICYCLE", "maxMin": 60},
    {"key": "Walk the whole way", "pure": "WALK", "maxMin": 45},
]
DRIVE_RELUCTANCE = [30.0, 2.0, 1.0]        # mirror of index.html
APP_FIRST = 8

# -------------------------------------------------------------- the oracle

# Every value the app uses plus the gaps between them and both extremes,
# because reluctance is the only knob that moves which lot OTP returns and
# each value yields exactly one optimal lot.
ORACLE_CAR_RELUCTANCE = [50.0, 30.0, 20.0, 12.0, 8.0, 5.0, 4.0, 3.0, 2.0,
                         1.5, 1.0, 0.7, 0.5, 0.3]
ORACLE_FIRST = 50
ORACLE_WINDOW = "PT3H"

# Mode mixes the app never fires. Some are legitimate options it could show
# (drive both ends, bike both ends); BICYCLE access is the carry-the-bike
# mode GO bans at peak and is here only to price what that rule costs.
ORACLE_EXTRA_COMBOS = [
    {"key": "oracle: drive both ends", "access": ["CAR_PARKING"],
     "egress": ["WALK", "CAR_PICKUP"]},
    {"key": "oracle: bike both ends", "access": ["BICYCLE_PARKING"],
     "egress": ["WALK", "BICYCLE_RENTAL"]},
    {"key": "oracle: bike share both ends", "access": ["BICYCLE_RENTAL", "WALK"],
     "egress": ["WALK", "BICYCLE_RENTAL"]},
    {"key": "oracle: drive to station, bike share to the door",
     "access": ["CAR_PARKING"], "egress": ["WALK", "BICYCLE_RENTAL"]},
    # OTP refuses BICYCLE on one end only: "if BICYCLE is used for access,
    # egress or transfer, then it should be used for all".
    {"key": "oracle: carry the bike aboard", "access": ["BICYCLE"],
     "egress": ["BICYCLE"], "transfer": ["BICYCLE"],
     "policy": "carrying a bike aboard, which GO bans at peak"},
]

QUERY = """
query Audit($origin: PlanLabeledLocationInput!,
            $destination: PlanLabeledLocationInput!,
            $dateTime: PlanDateTimeInput!, $modes: PlanModesInput!,
            $first: Int, $prefs: PlanPreferencesInput,
            $filter: PlanItineraryFilterInput, $window: Duration) {
  planConnection(origin: $origin, destination: $destination,
                 dateTime: $dateTime, modes: $modes, first: $first,
                 preferences: $prefs, itineraryFilter: $filter,
                 searchWindow: $window) {
    edges { node {
      duration start end
      systemNotices { tag text }
      legs { mode distance duration rentedBike
             start { scheduledTime } end { scheduledTime }
             agency { name } route { shortName }
             from { name } to { name } }
    } }
  }
}
"""


def next_service_date(day_kind):
    """Same rule as benchmark.py: feeds go stale, so trips store the KIND of
    day and resolve to the next real one."""
    target = {"weekday": 1, "saturday": 5, "sunday": 6}[day_kind]
    today = date.today()
    delta = (target - today.weekday()) % 7 or 7
    return (today + timedelta(days=delta)).isoformat()


def to_datetime(day_kind, hhmm):
    return (datetime.fromisoformat(next_service_date(day_kind) + "T" + hhmm)
            .astimezone().isoformat())


def ask(trip, modes, first, prefs=None, debug=False, window=None):
    variables = {
        "origin": {"location": {"coordinate": {
            "latitude": trip["from"]["latitude"],
            "longitude": trip["from"]["longitude"]}}},
        "destination": {"location": {"coordinate": {
            "latitude": trip["to"]["latitude"],
            "longitude": trip["to"]["longitude"]}}},
        "dateTime": {"earliestDeparture": to_datetime(trip["day"], trip["time"])},
        "modes": modes,
        "first": first,
        "prefs": prefs,
        # LIST_ALL hands back the itineraries OTP's own filters deleted,
        # which is most of the point of the oracle pass.
        "filter": {"itineraryFilterDebugProfile": "LIST_ALL"} if debug else None,
        "window": window,
    }
    payload = json.dumps({"query": QUERY, "variables": variables}).encode()
    req = urllib.request.Request(
        OTP_URL, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.load(resp)
    if "errors" in data:
        raise RuntimeError(data["errors"][0].get("message", data["errors"]))
    return [e["node"] for e in data["data"]["planConnection"]["edges"]]


def modes_for(combo):
    if combo.get("pure"):
        return {"directOnly": True, "direct": [combo["pure"]]}
    transit = {"access": combo["access"], "egress": combo["egress"]}
    if combo.get("transfer"):
        transit["transfer"] = combo["transfer"]
    return {"transit": transit}


def prefs_for(combo, car_reluctance=None):
    """Mirror of the per-request preferences fetchCombo() builds."""
    street = {}
    if car_reluctance is not None:
        street["car"] = {"reluctance": car_reluctance}
    if combo.get("walkReluctance"):
        street["walk"] = {"reluctance": combo["walkReluctance"]}
    return {"street": street} if street else None


def keep(combo, itins):
    """The same result filters fetchCombo() applies. Without these the app
    would appear to find routes it actually discards."""
    out = []
    for it in itins:
        legs = it["legs"]
        if not legs:
            continue
        if combo.get("pure"):
            if all(l["mode"] == combo["pure"] for l in legs) \
                    and it["duration"] <= combo["maxMin"] * 60:
                out.append(it)
            continue
        if not any(l["mode"] in TRANSIT for l in legs):
            continue
        if combo.get("needsLeg") and not any(
                l["mode"] == combo["needsLeg"] and not l.get("rentedBike")
                for l in legs):
            continue
        if combo.get("carAfter") and not end_leg_only(it, lambda l: l["mode"] == "CAR"):
            continue
        if combo.get("rentEnd") and not end_leg_only(it, lambda l: l.get("rentedBike")):
            continue
        if combo.get("rentStart") and not start_leg_only(it, lambda l: l.get("rentedBike")):
            continue
        out.append(it)
    if combo.get("pure"):
        out = sorted(out, key=lambda i: i["duration"])[:1]
    return out


def end_leg_only(it, match):
    """Mirror of endLegOnly() in index.html."""
    last_transit = -1
    for i, l in enumerate(it["legs"]):
        if l["mode"] in TRANSIT:
            last_transit = i
    if last_transit < 0:
        return False
    hits = [i for i, l in enumerate(it["legs"]) if match(l)]
    return bool(hits) and all(i > last_transit for i in hits)


def start_leg_only(it, match):
    first_transit = -1
    for i, l in enumerate(it["legs"]):
        if l["mode"] in TRANSIT:
            first_transit = i
            break
    if first_transit < 0:
        return False
    hits = [i for i, l in enumerate(it["legs"]) if match(l)]
    return bool(hits) and all(i < first_transit for i in hits)


def arrival(it):
    """When this option actually gets you there, as a timestamp."""
    return datetime.fromisoformat(it["end"]).timestamp()


def departure(it):
    return datetime.fromisoformat(it["start"]).timestamp()


def car_distance(it):
    """Mirror of carDistance() in index.html."""
    return sum(l.get("distance") or 0 for l in it["legs"] if l["mode"] == "CAR")


def deleted_by(it):
    """OTP tags an itinerary its own filters threw away. With the debug
    profile on, those come back in the results, so an untagged itinerary is
    one the engine kept and a tagged one is one it chose to drop."""
    return [n["tag"] for n in (it.get("systemNotices") or [])]


def signature(it):
    """Two itineraries are the same trip pattern if they use the same modes
    and routes in the same order between the same places."""
    parts = []
    for l in it["legs"]:
        route = (l.get("route") or {}).get("shortName") or ""
        parts.append(f"{l['mode']}:{route}:{l['from']['name']}>{l['to']['name']}")
    return "|".join(parts)


def describe(it):
    steps = []
    for l in it["legs"]:
        mode, dist = l["mode"], l.get("distance") or 0
        route = (l.get("route") or {}).get("shortName") or ""
        agency = (l.get("agency") or {}).get("name") or ""
        if mode == "WALK":
            steps.append(f"walk {round(dist)}m")
        elif mode in ("BICYCLE", "SCOOTER"):
            verb = "bike share" if l.get("rentedBike") else "bike"
            steps.append(f"{verb} {dist / 1000:.1f}km")
        elif mode == "CAR":
            steps.append(f"drive {dist / 1000:.1f}km to {l['to']['name']}")
        else:
            steps.append(f"{agency} {route}".strip() or mode)
    return (f"{round(it['duration'] / 60):>3} min, {it['start'][11:16]} to "
            f"{it['end'][11:16]} | " + " -> ".join(steps))


def app_pass(trip, pool):
    """Everything web/index.html would collect for this trip."""
    jobs = []
    for combo in APP_COMBOS:
        if combo.get("drive"):
            for r in DRIVE_RELUCTANCE + combo.get("extraReluctance", []):
                jobs.append((combo, r))
        else:
            jobs.append((combo, None))

    def run(job):
        combo, reluctance = job
        try:
            raw = ask(trip, modes_for(combo), APP_FIRST,
                      prefs_for(combo, reluctance))
            return combo, keep(combo, raw), None
        except Exception as e:
            return combo, [], e

    found, errors = {}, []
    for combo, itins, err in pool.map(run, jobs):
        if err:
            errors.append(f"{combo['key']}: {err}")
        for it in itins:
            # visibleIts(): the drive cap hides long drives on drive combos
            if combo.get("drive") and car_distance(it) > MAX_DRIVE_M:
                continue
            found.setdefault(signature(it), it)
    return list(found.values()), errors


def oracle_pass(trip, pool):
    """The same trip, asked as expensively as we like."""
    jobs = []
    for combo in APP_COMBOS + ORACLE_EXTRA_COMBOS:
        if combo.get("pure"):
            # no effort cap here: a long ride the app hides on purpose is a
            # POLICY finding, and it cannot be one if it is never fetched
            jobs.append((dict(combo, maxMin=10 ** 6), None))
        elif "CAR_PARKING" in combo.get("access", []) \
                or "CAR_PICKUP" in combo.get("egress", []):
            for r in ORACLE_CAR_RELUCTANCE:
                jobs.append((combo, r))
        else:
            jobs.append((combo, None))

    def run(job):
        combo, reluctance = job
        try:
            raw = ask(trip, modes_for(combo), ORACLE_FIRST,
                      prefs_for(combo, reluctance), debug=True,
                      window=ORACLE_WINDOW)
            # only the shape filters, not the app's policy caps: the oracle
            # is allowed to see options the app chooses to hide
            out = []
            for it in raw:
                if not it["legs"]:
                    continue
                if combo.get("pure"):
                    if all(l["mode"] == combo["pure"] for l in it["legs"]):
                        out.append((combo, it))
                elif any(l["mode"] in TRANSIT for l in it["legs"]):
                    out.append((combo, it))
            return out, None
        except Exception as e:
            return [], f"{combo['key']}: {e}"

    found, errors = {}, []
    for out, err in pool.map(run, jobs):
        if err:
            errors.append(err)
        for combo, it in out:
            found.setdefault(signature(it), (combo, it))
    return list(found.values()), errors


def classify(combo, it):
    """Why the app would not have shown this one. None means it should have."""
    if combo.get("policy"):
        return combo["policy"]
    if combo.get("pure"):
        cap = next((c["maxMin"] for c in APP_COMBOS
                    if c.get("pure") == combo["pure"]), None)
        if cap and it["duration"] > cap * 60:
            return (f"a {round(it['duration'] / 60)} min pure "
                    f"{combo['pure'].lower()} ride, past the {cap} min effort cap")
    km = car_distance(it)
    if km > MAX_DRIVE_M:
        return (f"a {km / 1000:.0f} km drive, past the "
                f"{MAX_DRIVE_M // 1000} km drive cap (the slider hint offers it)")
    return None


def audit(trip, pool, verbose):
    app_its, app_errs = app_pass(trip, pool)
    oracle_its, oracle_errs = oracle_pass(trip, pool)

    print(f"--- {trip['id']}")
    print(f"    {trip['description']}")
    for e in app_errs + oracle_errs:
        print(f"    ! {e}")

    if not app_its:
        print("    [NO ROUTE] the app's own fan-out found nothing at all")
        print()
        return "NO ROUTE"

    app_best = min(app_its, key=arrival)
    print(f"    app best:    {describe(app_best)}")

    # Anything the engine offers that leaves before the time that was asked
    # for is not an option a rider has. The debug profile hands these back.
    asked = datetime.fromisoformat(to_datetime(trip["day"], trip["time"])).timestamp()
    app_sigs = {signature(it) for it in app_its}
    better = [(c, it) for c, it in oracle_its
              if departure(it) >= asked
              and arrival(it) < arrival(app_best) - SIGNIFICANT_SEC]
    better.sort(key=lambda x: arrival(x[1]))

    if verbose:
        for c, it in better[:5]:
            print(f"    oracle:      {describe(it)}   [{c['key']}]")

    missed = [(c, it) for c, it in better
              if signature(it) not in app_sigs and classify(c, it) is None]
    policy = [(c, it) for c, it in better
              if signature(it) not in app_sigs and classify(c, it) is not None]

    verdict = "OK"
    if missed:
        verdict = "MISSED"
        c, it = missed[0]
        gap = round((arrival(app_best) - arrival(it)) / 60)
        tags = deleted_by(it)
        print(f"    [MISSED] gets you there {gap} min earlier, and the app "
              f"never found it:")
        print(f"             {describe(it)}")
        print(f"             found by: {c['key']}")
        if tags:
            print(f"             OTP's own filters deleted this one: "
                  f"{', '.join(sorted(set(tags)))}")
        if len(missed) > 1:
            print(f"             ({len(missed) - 1} more like it)")
    if policy:
        c, it = policy[0]
        gap = round((arrival(app_best) - arrival(it)) / 60)
        print(f"    [POLICY] gets you there {gap} min earlier but is hidden "
              f"on purpose: {classify(c, it)}")
        print(f"             {describe(it)}")
        if verdict == "OK":
            verdict = "POLICY"
    if verdict == "OK":
        print("    [OK] nothing the oracle found beats the app's best")
    print()
    return verdict


def main():
    verbose = "-v" in sys.argv
    words = [a for a in sys.argv[1:] if not a.startswith("-")]

    here = os.path.dirname(os.path.abspath(__file__))
    trips = []
    for name in ("benchmarks.json", "audit-trips.json"):
        path = os.path.join(here, name)
        if os.path.exists(path):
            with open(path) as fh:
                trips += json.load(fh)["trips"]
    seen, unique = set(), []
    for t in trips:
        if t["id"] not in seen:
            seen.add(t["id"])
            unique.append(t)
    trips = unique
    if words:
        trips = [t for t in trips if any(w in t["id"] for w in words)]

    print(f"Auditing {len(trips)} trips against {OTP_URL}")
    print(f"A gap under {SIGNIFICANT_SEC // 60} min is treated as jitter.\n")

    tally = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        for trip in trips:
            verdict = audit(trip, pool, verbose)
            tally[verdict] = tally.get(verdict, 0) + 1

    print("=" * 62)
    print("  ".join(f"{k} {v}" for k, v in sorted(tally.items())))
    if tally.get("MISSED"):
        print(f"\n{tally['MISSED']} trip(s) where a better route existed and "
              f"the app's fan-out did not find it.")


if __name__ == "__main__":
    main()
