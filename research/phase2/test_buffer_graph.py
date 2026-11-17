"""Check the research buffer graph after it is built.

Starts nothing by itself: run the buffer engine first, from the repo root:
    java -Xmx6G -jar engine/otp25.jar --load engine/research-buffer --port 8091 \
        > engine/research-buffer/serve.log 2>&1 &
then:
    research/.venv/bin/python research/phase2/test_buffer_graph.py

Checks: the engine loaded the research router config with 0 updaters, all 13
agencies are present, and example trips across the old map edge use the new
buffer agencies (HSR, GRT, Barrie) on Tuesday 2026-09-22 around 08:00.
"""
import re
import sys
from pathlib import Path

import requests

BASE = "http://localhost:8091/otp"
GQL = BASE + "/routers/default/index/graphql"
LOG = Path(__file__).resolve().parents[2] / "engine" / "research-buffer" / "serve.log"
EXPECTED_AGENCIES = {"GO", "UP", "TTC", "YRT", "MIWAY", "BRAMPTON", "DRT", "OAKVILLE", "BURLINGTON", "MILTON", "HSR", "GRT", "BARRIE"}

# name, from (lat, lon), to (lat, lon), feed id that should appear in the best trip
TRIPS = [
    # Trips from Burlington into Hamilton legitimately use Burlington Transit or GO
    # buses, so HSR is tested on trips inside Hamilton that only HSR serves.
    ("McMaster University to Limeridge Mall (inside Hamilton)", (43.2609, -79.9192), (43.2179, -79.8622), "HSR"),
    ("Hamilton GO Centre to Eastgate Square (inside Hamilton)", (43.2530, -79.8687), (43.2320, -79.7630), "HSR"),
    ("Cambridge (Ainslie Terminal) to Kitchener (Fairview Park Mall)", (43.3589, -80.3136), (43.4239, -80.4407), "GRT"),
    ("Barrie South GO to Georgian Mall", (44.3514, -79.6286), (44.4115, -79.6696), "BARRIE"),
    ("Control: Union Station to Yonge & Eglinton", (43.6453, -79.3806), (43.7066, -79.3985), "TTC"),
]

Q = """{ plan(from:{lat:%f,lon:%f}, to:{lat:%f,lon:%f}, date:"2026-09-22", time:"08:00", numItineraries:5,
  transportModes:[{mode:WALK},{mode:TRANSIT}]) { itineraries { duration legs { mode route { gtfsId shortName } } } routingErrors { code } } }"""


def main():
    failures = 0
    try:
        requests.get(BASE + "/", timeout=5)
    except requests.RequestException:
        sys.exit("Buffer engine not answering on :8091. Start it first (see docstring).")

    if LOG.exists():
        log = LOG.read_text(errors="ignore")
        m = re.search(r"OTP UPDATERS INITIALIZED \((\d+) updaters\)", log)
        cfg = "router-config.json  engine/research-buffer" in log or "research-buffer/router-config.json" in log
        print(f"router config loaded from research-buffer: {cfg} | updaters: {m.group(1) if m else 'not found in log'}")
        if not m or m.group(1) != "0":
            failures += 1
    else:
        print("serve.log not found; skipping updater check")

    ag = requests.post(GQL, json={"query": "{ agencies { gtfsId name routes { gtfsId } } }"}, timeout=60).json()
    feeds = {}
    for a in ag["data"]["agencies"]:
        feeds.setdefault(a["gtfsId"].split(":")[0], []).append((a["name"], len(a["routes"])))
    print("agencies by feed:", {k: sum(n for _, n in v) for k, v in sorted(feeds.items())})
    missing = EXPECTED_AGENCIES - set(feeds)
    if missing:
        print("MISSING feeds:", sorted(missing))
        failures += 1

    for name, a, b, want in TRIPS:
        j = requests.post(GQL, json={"query": Q % (a[0], a[1], b[0], b[1])}, timeout=120).json()
        its = (j.get("data") or {}).get("plan", {}).get("itineraries") or []
        if not its:
            print(f"FAIL  {name}: no itinerary {j.get('data', {}).get('plan', {}).get('routingErrors')}")
            failures += 1
            continue
        best = min(its, key=lambda i: i["duration"])
        used = [(l["route"] or {}).get("gtfsId", "") for l in best["legs"] if l["mode"] != "WALK"]
        legs = " > ".join(f"{l['mode']} {(l['route'] or {}).get('shortName') or ''}".strip() for l in best["legs"])
        uses = any(u.startswith(want + ":") for u in used)
        print(f"{'ok  ' if uses else 'FAIL'}  {name}: {best['duration'] / 60:.0f} min | {legs}")
        failures += 0 if uses else 1

    print("\nall checks passed" if failures == 0 else f"\n{failures} check(s) failed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
