"""
Routing benchmark.

Runs every trip in benchmarks.json through the local OpenTripPlanner server
three ways (transit only, bike and ride, drive to station), compares the
results against the expected answer, and prints PASS or MISS per trip plus
an overall miss rate.

Usage (with the engine running):
    python3 tests/benchmark.py            # grade all trips
    python3 tests/benchmark.py -v         # also print every itinerary
    python3 tests/benchmark.py union      # only trips whose id contains a word

Standard library only.
"""

import json
import os
import sys
import urllib.request
from datetime import date, timedelta

OTP_URL = "http://localhost:8080/otp/gtfs/v1"

# OTP 2.9 planConnection: access/egress street modes are separate lists.
# _PARKING = ride there and leave the bike/car (plain BICYCLE would mean
# carrying the bike aboard, which GO bans on peak trains).
MODE_COMBOS = {
    "transit_only":     {"access": ["WALK"], "egress": ["WALK"]},
    "bike_and_ride":    {"access": ["BICYCLE_PARKING"], "egress": ["WALK"]},
    "drive_to_station": {"access": ["CAR_PARKING"], "egress": ["WALK"]},
}

QUERY = """
query Plan($origin: PlanLabeledLocationInput!,
           $destination: PlanLabeledLocationInput!,
           $dateTime: PlanDateTimeInput!, $modes: PlanModesInput!) {
  planConnection(origin: $origin, destination: $destination,
                 dateTime: $dateTime, modes: $modes, first: 3) {
    edges {
      node {
        duration
        legs {
          mode
          distance
          agency { name }
          route { shortName longName }
          from { name }
          to { name }
        }
      }
    }
  }
}
"""


def next_service_date(day_kind):
    """Turn 'weekday'/'saturday' into a real upcoming date (feeds go stale,
    so benchmarks.json stores the kind of day, not a fixed date)."""
    target = {"weekday": 1, "saturday": 5, "sunday": 6}[day_kind]  # Tue/Sat/Sun
    today = date.today()
    delta = (target - today.weekday()) % 7 or 7
    return (today + timedelta(days=delta)).isoformat()


def to_location(point):
    """benchmarks.json uses latitude/longitude names - exactly what the
    OTP 2.9 planConnection schema wants (2.5 wanted lat/lon instead)."""
    return {"location": {"coordinate": {
        "latitude": point["latitude"], "longitude": point["longitude"]}}}


def to_datetime(day_kind, hhmm):
    """Local Toronto date+time -> ISO OffsetDateTime for earliestDeparture."""
    from datetime import datetime
    return (datetime.fromisoformat(next_service_date(day_kind) + "T" + hhmm)
            .astimezone().isoformat())


TRANSIT_MODES = {"BUS", "RAIL", "SUBWAY", "TRAM", "FERRY"}


def has_transit(itin):
    return any(l["mode"] in TRANSIT_MODES for l in itin["legs"])


def fetch(trip, modes):
    payload = json.dumps({
        "query": QUERY,
        "variables": {
            "origin": to_location(trip["from"]),
            "destination": to_location(trip["to"]),
            "dateTime": {"earliestDeparture": to_datetime(trip["day"], trip["time"])},
            "modes": {"transit": modes},
        },
    }).encode()
    req = urllib.request.Request(
        OTP_URL, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.load(resp)
    if "errors" in data:
        raise RuntimeError(data["errors"])
    itineraries = [e["node"] for e in data["data"]["planConnection"]["edges"]]
    # Park-and-ride searches can pad with plain walk+transit trips that
    # belong to transit_only; a park-and-ride answer must contain transit.
    if modes["access"] != ["WALK"]:
        itineraries = [it for it in itineraries if has_transit(it)]
    return itineraries


def itinerary_text(itin):
    """Everything nameable in one string, for must_include_any matching."""
    parts = []
    for leg in itin["legs"]:
        for key in ("from", "to"):
            parts.append(leg[key]["name"] or "")
        route = leg.get("route") or {}
        agency = leg.get("agency") or {}
        parts += [route.get("shortName") or "", route.get("longName") or "",
                  agency.get("name") or ""]
    return " | ".join(p for p in parts if p)


def describe(itin):
    mins = round(itin["duration"] / 60)
    steps = []
    for leg in itin["legs"]:
        mode = leg["mode"]
        route = (leg.get("route") or {}).get("shortName") or ""
        agency = (leg.get("agency") or {}).get("name") or ""
        if mode == "WALK":
            steps.append(f"walk {round(leg['distance'])}m")
        elif mode == "BICYCLE":
            steps.append(f"bike {round(leg['distance'] / 1000, 1)}km")
        elif mode == "CAR":
            steps.append(f"drive {round(leg['distance'] / 1000, 1)}km to {leg['to']['name']}")
        else:
            steps.append(f"{agency} {route}".strip() or mode)
    return f"{mins:>3} min | " + " -> ".join(steps)


def grade(trip, results):
    """Return (verdict, reasons). Verdict: PASS / MISS / REPORT-ONLY / ERROR."""
    combo = trip["expected_combo"]
    if combo is None:
        return "REPORT-ONLY", ["no confident expectation yet"]

    itineraries = results.get(combo)
    if isinstance(itineraries, Exception):
        return "ERROR", [f"{combo} query failed: {itineraries}"]
    if not itineraries:
        return "MISS", [f"{combo} returned no route at all"]

    reasons = []
    names = trip["must_include_any"]
    matching = [it for it in itineraries
                if not names or any(n in itinerary_text(it) for n in names)]
    if not matching:
        reasons.append(f"no {combo} option touches any of: {', '.join(names)}")
        candidates = itineraries
    else:
        candidates = matching

    best = min(candidates, key=lambda it: it["duration"])
    mins = best["duration"] / 60
    if mins > trip["max_minutes"]:
        reasons.append(f"best sane-shaped option takes {round(mins)} min "
                       f"(limit {trip['max_minutes']})")

    return ("PASS" if not reasons else "MISS"), reasons


def main():
    verbose = "-v" in sys.argv
    words = [a for a in sys.argv[1:] if a != "-v"]

    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "benchmarks.json")) as fh:
        trips = json.load(fh)["trips"]
    if words:
        trips = [t for t in trips if any(w in t["id"] for w in words)]

    tally = {"PASS": 0, "MISS": 0, "REPORT-ONLY": 0, "ERROR": 0}
    unfair_misses = 0

    for trip in trips:
        results = {}
        for combo, modes in MODE_COMBOS.items():
            try:
                results[combo] = fetch(trip, modes)
            except Exception as e:
                results[combo] = e

        verdict, reasons = grade(trip, results)
        tally[verdict] += 1
        if verdict == "MISS" and trip["known_unfair"]:
            unfair_misses += 1

        tag = " (known unfair - missing feeds)" if trip["known_unfair"] else ""
        print(f"[{verdict}] {trip['id']}{tag}")
        print(f"        {trip['description']}")
        print(f"        expected: {trip['expected_plain']}")
        for reason in reasons:
            print(f"        -> {reason}")
        for combo in MODE_COMBOS:
            res = results[combo]
            marker = "*" if combo == trip["expected_combo"] else " "
            if isinstance(res, Exception):
                print(f"      {marker} {combo}: ERROR {res}")
            elif not res:
                print(f"      {marker} {combo}: no route found")
            else:
                shown = res if verbose else [min(res, key=lambda i: i["duration"])]
                for it in shown:
                    print(f"      {marker} {combo}: {describe(it)}")
        print()

    graded = tally["PASS"] + tally["MISS"]
    print("=" * 60)
    print(f"PASS {tally['PASS']}  MISS {tally['MISS']}  "
          f"report-only {tally['REPORT-ONLY']}  errors {tally['ERROR']}")
    if graded:
        print(f"Miss rate: {tally['MISS']}/{graded}"
              f" ({tally['MISS'] / graded:.0%})"
              + (f", of which {unfair_misses} known-unfair" if unfair_misses else ""))


if __name__ == "__main__":
    main()
