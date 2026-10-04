"""
Fare model sync check.

scripts/costs.py and the fare model inside web/core.js are deliberately
duplicated, and both files carry a comment saying to keep them in sync. That
comment was the only thing enforcing it. This script enforces it for real.

It compares, without running a browser:
  - every row of LOCAL_FARES (match key, adult, youth, transfer programme)
  - the scalar constants both copies declare
  - that every transit agency in the loaded graph has a fare row at all

scripts/costs.py is a local-only file and is not in the public repository, so
the two-copy diff is skipped when it is missing. The checks that read
web/core.js always run.

The last check is the one that would have caught the Halton gap: Oakville,
Burlington and Milton were loaded as feeds on 2026-09-12 and had no fares in
either copy, so their legs priced as $0 with no warning anywhere.

Usage:
    python3 tests/fare-sync.py          # compare the two copies
    python3 tests/fare-sync.py --feeds  # also check every loaded feed is priced

Standard library only. The --feeds check needs the engine running.
"""

import json
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(ROOT, "web", "core.js")   # the app's fare model
OTP_URL = "http://localhost:8080/otp/gtfs/v1"

sys.path.insert(0, os.path.join(ROOT, "scripts"))
try:
    import costs  # noqa: E402  (local only: absent from the public repo)
except ImportError:
    costs = None

# name in costs.py -> name in core.js
SCALARS = {
    "GO_BASE_FARE": "GO_BASE",
    "GO_PER_KM": "GO_PER_KM",
    "GO_YOUTH_FACTOR": "GO_YOUTH_FACTOR",
    "UP_EXPRESS_UNION_PEARSON": "UP_FARE",
    "UP_EXPRESS_YOUTH": "UP_YOUTH",
    "UP_EXPRESS_PEARSON_YOUTH": "UP_PEARSON_YOUTH",
    "UP_EXPRESS_CITY": "UP_CITY",
    "GAS_PER_KM": "GAS_PER_KM",
    "WEAR_PER_KM": "WEAR_PER_KM",
    "GO_STATION_PARKING": "GO_PARKING",
    "BIKESHARE_UNLOCK": "BIKESHARE_UNLOCK",
    "BIKESHARE_PER_MIN": "BIKESHARE_PER_MIN",
}


def js_source():
    with open(INDEX) as fh:
        return fh.read()


def js_local_fares(src):
    """Pull the LOCAL_FARES literal out of core.js. It is a plain array of
    arrays, so once the comments are stripped it is valid JSON apart from the
    bare true/false, which json already understands."""
    start = src.index("const LOCAL_FARES = [")
    body = src[start + len("const LOCAL_FARES = "):]
    end = body.index("];") + 1
    body = body[:end]
    body = re.sub(r"//[^\n]*", "", body)          # drop the inline comments
    rows = json.loads(body)
    return [tuple(r) for r in rows]


def js_scalar(src, name):
    m = re.search(r"\b" + re.escape(name) + r"\s*=\s*(-?[\d.]+)", src)
    return float(m.group(1)) if m else None


def loaded_feeds():
    payload = json.dumps({"query": "{agencies{gtfsId}}"}).encode()
    req = urllib.request.Request(
        OTP_URL, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    return sorted({a["gtfsId"].split(":")[0] for a in data["data"]["agencies"]})


def check_feeds(js_rows, problems):
    """Every feed the RUNNING graph actually holds should have a fare row (a
    stale graph can differ from build-config.json)."""
    if "--feeds" not in sys.argv:
        return
    try:
        feeds = loaded_feeds()
    except Exception as e:
        print(f"feeds: could not reach the engine ({e}). Is it running?")
        return
    keys = {row[0] for row in js_rows}
    for feed in feeds:
        if feed not in OWN_RULES and feed not in keys:
            problems.append(f"{feed}: loaded in the graph but has no fare "
                            f"row, so its legs price as $0")
    print(f"feeds: {len(feeds)} feeds in the running graph checked")


PROGRAMMES = {"onefare", "gocofare"}
# priced by their own rules (the GO fare table, the UP fares), not LOCAL_FARES
OWN_RULES = {"GO", "UP"}


def built_feeds():
    """The feedIds engine/build-config.json builds the graph from. The file
    allows // comments, which json does not."""
    with open(os.path.join(ROOT, "engine", "build-config.json")) as fh:
        text = re.sub(r"(?m)^\s*//[^\n]*", "", fh.read())
    return {f["feedId"] for f in json.loads(text)["transitFeeds"]}


def check_rows(js_rows, problems):
    """Sanity checks on the fare table itself, against the feeds the graph is
    built from. Needs nothing local, so it runs everywhere, GitHub included.
    This is the check that would have caught the Halton gap at the moment
    the three feeds were added to build-config.json."""
    keys = [r[0] for r in js_rows]
    feeds = built_feeds()
    for r in js_rows:
        if len(r) != 5:
            problems.append(f"{r[0]}: expected 5 columns, found {len(r)}")
            continue
        key, adult, youth, verified, prog = r
        if not (isinstance(adult, (int, float)) and adult > 0):
            problems.append(f"{key}: adult fare {adult!r} is not a positive number")
        if youth is not None and not (0 <= youth <= adult):
            problems.append(f"{key}: youth fare {youth!r} is not between 0 and the adult fare")
        if not isinstance(verified, bool):
            problems.append(f"{key}: verified flag {verified!r} is not true/false")
        if prog not in PROGRAMMES:
            problems.append(f"{key}: transfer programme {prog!r} is not one of {sorted(PROGRAMMES)}")
        if keys.count(key) > 1:
            problems.append(f"{key}: appears more than once")
        if key not in feeds:
            problems.append(f"{key}: no such feedId in engine/build-config.json, "
                            f"so this fare row can never match")
    for feed in sorted(feeds - OWN_RULES - set(keys)):
        problems.append(f"{feed}: built into the graph but has no fare row, "
                        f"so its legs price as $0")
    print(f"LOCAL_FARES: {len(js_rows)} rows checked against "
          f"{len(feeds)} feeds in build-config.json")


def report(problems):
    print()
    if problems:
        for p in problems:
            print(f"  MISMATCH  {p}")
        print(f"\n{len(problems)} problem(s) found.")
        sys.exit(1)
    print("The fare model checks out.")


def main():
    src = js_source()
    problems = []
    js_rows = js_local_fares(src)
    check_rows(js_rows, problems)

    if costs is None:
        print("costs.py is not here (it is a local-only file), so the "
              "two-copy diff is skipped.")
        print(f"LOCAL_FARES: {len(js_rows)} rows in core.js")
        check_feeds(js_rows, problems)
        report(problems)
        return

    py_rows = [tuple(r) for r in costs.LOCAL_FARES]
    py_by_key = {r[0]: r for r in py_rows}
    js_by_key = {r[0]: r for r in js_rows}

    for key in sorted(set(py_by_key) | set(js_by_key)):
        p, j = py_by_key.get(key), js_by_key.get(key)
        if p is None:
            problems.append(f"{key}: in core.js but not in costs.py")
            continue
        if j is None:
            problems.append(f"{key}: in costs.py but not in core.js")
            continue
        # core.js rows are [key, adult, youth, verified, programme];
        # costs.py rows are (key, adult, youth, programme)
        if float(p[1]) != float(j[1]):
            problems.append(f"{key}: adult {p[1]} in costs.py, {j[1]} in core.js")
        if float(p[2] or 0) != float(j[2] or 0):
            problems.append(f"{key}: youth {p[2]} in costs.py, {j[2]} in core.js")
        if p[3] != j[4]:
            problems.append(f"{key}: transfer programme {p[3]} in costs.py, "
                            f"{j[4]} in core.js")
    print(f"LOCAL_FARES: {len(py_rows)} rows in costs.py, "
          f"{len(js_rows)} in core.js")

    for py_name, js_name in sorted(SCALARS.items()):
        p = getattr(costs, py_name, None)
        j = js_scalar(src, js_name)
        if p is None:
            problems.append(f"{py_name}: missing from costs.py")
        elif j is None:
            problems.append(f"{js_name}: could not be read out of core.js")
        elif float(p) != j:
            problems.append(f"{py_name}/{js_name}: {p} in costs.py, {j} in core.js")
    print(f"scalars: {len(SCALARS)} compared")

    check_feeds(js_rows, problems)
    report(problems)


if __name__ == "__main__":
    main()
