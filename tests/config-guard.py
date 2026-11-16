"""Guards for settings the routing silently depends on. Offline, standard library only.

    python3 tests/config-guard.py              run every check against the real files
    python3 tests/config-guard.py --self-test  prove each check fails on a broken input

Why this exists: many settings in engine/ and in the shell scripts look like
harmless tuning but each one fixes a real routing bug. If a check here fails,
somebody changed one of them. The message says what breaks and what to restore.
Only files tracked in git are read, so this runs in CI without the big data files.
"""
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = "See docs/routing-notes.md."

# Today's counts in data/parking-patch.osc. They may grow, never shrink.
MIN_PATCH_WAYS = 43
MIN_PATCH_NODES = 1
MIN_PATCH_PARK_RIDE = 44


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def strip_json_comments(text):
    """OpenTripPlanner config files allow // and /* */ comments. Strings (URLs
    contain //) are left alone."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            out.append(text[i:j + 1])
            i = j + 1
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
        elif text.startswith("/*", i):
            i = text.index("*/", i) + 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def load_json(rel):
    return json.loads(strip_json_comments(read(rel)))


def code_lines(text):
    """Shell lines with full-line comments dropped."""
    return [l for l in text.splitlines() if not l.lstrip().startswith("#")]


def line_of(text, pattern):
    """Index of the first non-comment line matching the regex, or None."""
    for i, l in enumerate(code_lines(text)):
        if re.search(pattern, l):
            return i
    return None


def dig(d, path):
    for k in path:
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d


def need(cond, msg):
    if not cond:
        raise AssertionError(msg + " " + DOC)


def duration_minutes(s):
    m = re.fullmatch(r"\s*(\d+)\s*([mh])\s*", str(s))
    return None if not m else int(m.group(1)) * (60 if m.group(2) == "h" else 1)


# ---- 1. engine/router-config.json -----------------------------------------

def check_router_config(cfg=None):
    cfg = cfg if cfg is not None else load_json("engine/router-config.json")
    rd = cfg.get("routingDefaults", {})

    # Default 500 only reaches nearby park-and-ride lots, so far stations never show.
    n = dig(rd, ["accessEgress", "maxStopCount"])
    need(isinstance(n, int) and n >= 4000,
         f"routingDefaults.accessEgress.maxStopCount is {n!r}, must be at least 4000. "
         "With the default of 500 the router only finds park-and-ride lots near the "
         "start, so distant GO and subway stations never appear as options. "
         "Restore 4000.")

    # 30m hid the right lot for downtown to suburb trips.
    v = dig(rd, ["accessEgress", "maxDurationForMode", "CAR_TO_PARK"])
    need(v == "45m",
         f"CAR_TO_PARK max access duration is {v!r}, must be \"45m\". A shorter "
         "limit hides the right parking lot for long downtown-to-suburb drives and "
         "the router picks a closer wrong lot. Restore \"45m\".")

    # false crashes OTP at startup; the default drops faster park-and-ride trips.
    f = dig(rd, ["itineraryFilters", "removeTransitWithHigherCostThanBestOnStreetOnly"])
    need(isinstance(f, str) and f.strip() != "",
         f"removeTransitWithHigherCostThanBestOnStreetOnly is {f!r}, must be a "
         "string such as \"9h + 9.0 t\", never true/false. false crashes the engine "
         "at startup, and the default silently drops park-and-ride trips that are "
         "faster on the clock. Restore \"9h + 9.0 t\".")

    g = dig(rd, ["itineraryFilters", "groupSimilarityKeepOne"])
    need(g == 0.95,
         f"itineraryFilters.groupSimilarityKeepOne is {g!r}, must be 0.95. A lower "
         "value merges near-identical trips and keeps the slower one, so faster "
         "trips are hidden. Restore 0.95.")

    w = dig(cfg, ["transit", "dynamicSearchWindow", "minWindow"])
    mins = duration_minutes(w)
    need(mins is not None and mins >= 60,
         f"transit.dynamicSearchWindow.minWindow is {w!r}, must be at least \"1h\". "
         "A smaller window makes the router miss the right bus at peak hours "
         "(a Pioneer Village option vanished at exactly 8:00am). Restore \"1h\".")

    # Present-only checks; values are tuning, printed so a reviewer can see them.
    for path in (["walk", "speed"], ["transferPenalty"], ["car", "reluctance"]):
        val = dig(rd, path)
        need(val is not None,
             f"routingDefaults.{'.'.join(path)} is missing. Without it the engine "
             "falls back to its own default, which changes walking times, transfer "
             "behaviour or drive-versus-transit balance everywhere. Put it back "
             "(was walk.speed 1.4, transferPenalty 300, car.reluctance 3.0).")

    o = dig(rd, ["bicycle", "optimization"])
    need(isinstance(o, str) and o.isupper(),
         f"bicycle.optimization is {o!r}, must be an enum string such as "
         "\"SAFEST_STREETS\". OpenTripPlanner 2.9 silently ignores the older object "
         "form, so bike routes lose the safe-streets preference. Restore "
         "\"SAFEST_STREETS\".")

    need("accessEgress" in rd and "maxAccessEgressDuration" not in rd,
         "routingDefaults uses the old maxAccessEgressDuration block instead of "
         "accessEgress. The engine silently ignores the old spelling, so every "
         "access limit reverts to its default. Use accessEgress.")

    # No literal key in a URL: the key comes from ${METROLINX_KEY}.
    urls = [s for s in re.findall(r'"([^"]*)"', strip_json_comments(json.dumps(cfg)))]
    for u in urls:
        for m in re.finditer(r"key=(?!\$\{)(\S+)", u):
            need(False, "a real-looking API key is written into a URL in "
                 "engine/router-config.json (key=" + m.group(1)[:3] + "...). The "
                 "file is public on GitHub. Replace it with key=${METROLINX_KEY} "
                 "and revoke the leaked key.")
    need(any("key=${METROLINX_KEY}" in u for u in urls),
         "the GO feed URL no longer says key=${METROLINX_KEY}. The key must come "
         "from metrolinx.env through that variable, never be typed into the file. "
         "Restore key=${METROLINX_KEY}.")

    ups = cfg.get("updaters", [])

    def url_of(kind, feed):
        for u in ups:
            if u.get("type") == kind and u.get("feedId") == feed:
                return u.get("url", "")
        return ""

    need("go-alerts-filtered.pb" in url_of("real-time-alerts", "GO"),
         "GO service alerts no longer read go-alerts-filtered.pb. Metrolinx's raw "
         "feed has empty id fields that make the engine throw away every GO alert "
         "each cycle; the local filtered copy fixes that. Restore "
         "file:${GTA_ROUTER_DIR}/go-alerts-filtered.pb.")
    need("drt-rt-filtered.pb" in url_of("stop-time-updater", "DRT"),
         "Durham trip updates no longer read drt-rt-filtered.pb. Durham's raw feed "
         "lists stops that are not on the trip, so the engine drops about a fifth "
         "of its trips back to scheduled times; the local filtered copy fixes that. "
         "Restore file:${GTA_ROUTER_DIR}/drt-rt-filtered.pb.")
    return {"maxStopCount": n, "CAR_TO_PARK": v, "filter": f, "groupSimilarityKeepOne": g,
            "minWindow": w, "walk.speed": dig(rd, ["walk", "speed"]),
            "transferPenalty": rd.get("transferPenalty"),
            "car.reluctance": dig(rd, ["car", "reluctance"]), "bicycle.optimization": o}


# ---- 2. engine/build-config.json ------------------------------------------

EXPECTED_FEEDS = {"GO", "UP", "TTC", "YRT", "MIWAY", "BRAMPTON", "DRT",
                  "OAKVILLE", "BURLINGTON", "MILTON"}


def check_build_config(cfg=None):
    cfg = cfg if cfg is not None else load_json("engine/build-config.json")
    # Without this flag the graph has zero bike racks and bike-to-station fails.
    need(cfg.get("staticBikeParkAndRide") is True,
         "staticBikeParkAndRide is not true in engine/build-config.json. Without "
         "it the graph is built with zero bike racks and every bike-to-station "
         "trip fails, even though the map data has the racks. Restore true.")
    need(cfg.get("staticParkAndRide") is not False,
         "staticParkAndRide is turned off in engine/build-config.json. That removes "
         "every car park-and-ride lot from the graph, so drive-to-station trips "
         "disappear. Delete the line or set it to true.")
    # Brampton's feed declares America/New_York; mixing zones refuses to build.
    tz = cfg.get("transitModelTimeZone")
    need(tz == "America/Toronto",
         f"transitModelTimeZone is {tz!r}, must be \"America/Toronto\". Brampton's "
         "schedule declares New York and the graph build refuses to mix time "
         "zones without this line. Restore \"America/Toronto\".")
    srcs = [o.get("source") for o in cfg.get("osm", [])]
    need(srcs == ["gta.osm.pbf"],
         f"the OSM source is {srcs!r}, must be exactly [\"gta.osm.pbf\"]. That is "
         "the cropped, parking-patched map setup.sh produces; the raw Ontario file "
         "has no park-and-ride fixes and takes far more memory. Restore "
         "\"gta.osm.pbf\".")
    ids = {t.get("feedId") for t in cfg.get("transitFeeds", [])}
    need(ids == EXPECTED_FEEDS,
         f"the GTFS feed ids are {sorted(ids)}, expected {sorted(EXPECTED_FEEDS)}. "
         "The ids are used by real-time updaters, fares and the web app; renaming "
         "or dropping one silently breaks live delays and fare lookups for that "
         "agency. If a feed was added on purpose, update this list and the three "
         "places named in the feed test.")
    return {"timezone": tz, "osm": srcs, "feeds": sorted(ids)}


# ---- 3. feeds agree in three places ---------------------------------------

def feed_zips_from_feeds_sh(text=None):
    text = text if text is not None else read("scripts/feeds.sh")
    return set(re.findall(r'^\s*"([a-z0-9-]+-gtfs\.zip)\s', text, re.M))


def local_fare_ids(text=None):
    text = text if text is not None else read("web/core.js")
    m = re.search(r"const LOCAL_FARES\s*=\s*\[(.*?)\];", text, re.S)
    need(m is not None, "LOCAL_FARES is missing from web/core.js. Without it the app "
         "cannot price any local bus or streetcar ride. Restore the table.")
    body = re.sub(r"//[^\n]*", "", m.group(1))
    return set(re.findall(r'\[\s*"([A-Z]+)"\s*,', body))


def check_feeds_agree(feeds_sh=None, build=None, core_js=None):
    zips = feed_zips_from_feeds_sh(feeds_sh)
    cfg = build if build is not None else load_json("engine/build-config.json")
    in_build = {t.get("source") for t in cfg.get("transitFeeds", [])}
    fares = local_fare_ids(core_js)
    ids = {t.get("feedId") for t in cfg.get("transitFeeds", [])}
    need(zips == in_build,
         f"scripts/feeds.sh and engine/build-config.json list different schedule "
         f"files (only in feeds.sh: {sorted(zips - in_build)}, only in "
         f"build-config: {sorted(in_build - zips)}). A feed that is downloaded but "
         "not built is wasted, and one that is built but not downloaded makes the "
         "graph build fail. Make both lists name the same files.")
    missing = (ids - {"GO", "UP"}) - fares
    need(not missing,
         f"feed(s) {sorted(missing)} are in build-config.json but have no row in "
         "LOCAL_FARES in web/core.js. Rides on them would be priced as free. Add a "
         "fare row for each (only GO and UP are priced elsewhere).")
    return {"zips": len(zips), "fare_rows": sorted(fares)}


# ---- 4. engine/otp-config.json --------------------------------------------

def check_otp_config(cfg=None):
    cfg = cfg if cfg is not None else load_json("engine/otp-config.json")
    on = dig(cfg, ["otpFeatures", "MinimumTransferTimeIsDefinitive"])
    need(on is True,
         "otpFeatures.MinimumTransferTimeIsDefinitive is not true in "
         "engine/otp-config.json. The 3-minute TTC subway transfer times we inject "
         "are only trusted with it; without it the router walks you out to the "
         "street at Bloor-Yonge and the subway loses to streetcars. Restore true.")
    return {"MinimumTransferTimeIsDefinitive": on}


# ---- 5. data/parking-patch.osc --------------------------------------------

def patch_counts(text=None):
    text = text if text is not None else read("data/parking-patch.osc")
    try:
        root = ET.fromstring(text.encode("utf-8"))
    except ET.ParseError as e:
        need(False, f"data/parking-patch.osc is not valid XML ({e}). osmium will "
             "refuse it and setup.sh stops, or the lots go unpatched. Restore the "
             "file from git.")
    ways = root.findall(".//way")
    nodes = root.findall(".//node")
    pr = [e for e in ways + nodes
          if any(t.get("k") == "park_ride" and t.get("v") == "yes" for t in e.findall("tag"))]
    return len(ways), len(nodes), len(pr)


def check_parking_patch(text=None):
    w, n, p = patch_counts(text)
    need(w >= MIN_PATCH_WAYS and n >= MIN_PATCH_NODES and p >= MIN_PATCH_PARK_RIDE,
         f"data/parking-patch.osc has {w} ways, {n} nodes, {p} park_ride=yes "
         f"entries; it must keep at least {MIN_PATCH_WAYS}, {MIN_PATCH_NODES}, "
         f"{MIN_PATCH_PARK_RIDE}. OpenStreetMap lacks the park_ride tag on these "
         "real commuter lots, so deleting entries makes the router stop driving "
         "to them. Restore the deleted entries from git.")
    return {"ways": w, "nodes": n, "park_ride_yes": p}


# ---- 6. setup.sh / refresh.sh / run.sh ordering ---------------------------

def check_setup_order(text=None):
    t = text if text is not None else read("setup.sh")
    ex = line_of(t, r"osmium extract")
    ap = line_of(t, r"osmium apply-changes.*parking-patch\.osc")
    bd = line_of(t, r"--build")
    need(ap is not None,
         "setup.sh no longer runs osmium apply-changes with data/parking-patch.osc. "
         "Without it about 28 real commuter lots are not park-and-ride in the "
         "graph, so the router never drives to them. Restore the apply-changes step.")
    need(ex is not None and bd is not None and ex < ap < bd,
         "setup.sh must run osmium extract, THEN osmium apply-changes with the "
         "parking patch, THEN the graph build (--build). Patching before the crop "
         "is thrown away by the crop, and patching after the build changes nothing "
         "in the graph. Restore that order.")
    need(line_of(t, r"engine-env\.sh") is not None,
         "setup.sh does not source scripts/engine-env.sh. The engine reads "
         "router-config.json even to build and refuses to run without the "
         "variables that file sets. Restore '. scripts/engine-env.sh'.")


def check_refresh_order(text=None):
    t = text if text is not None else read("refresh.sh")
    bd = line_of(t, r"--build")
    pt = line_of(t, r"patch_ttc_transfers\.py")
    bk = line_of(t, r"graph\.obj\.prev")
    need(bd is not None and pt is not None and pt < bd,
         "refresh.sh must run patch_ttc_transfers.py before any --build. TTC ships "
         "no transfers.txt, so a graph built without the patch makes subway "
         "interchanges walk out to the street. Restore the patch step before the "
         "first build.")
    # the backup is a cp line, not the trap message that merely mentions the name
    bk = line_of(t, r"cp\s+-f\s+graph\.obj\s+graph\.obj\.prev")
    need(bk is not None and bk < bd,
         "refresh.sh must copy graph.obj to graph.obj.prev before building. The "
         "build overwrites graph.obj, and the rollback instructions depend on the "
         "backup. Restore the cp line before the first --build.")
    need(line_of(t, r"engine-env\.sh") is not None,
         "refresh.sh does not source scripts/engine-env.sh. The engine reads "
         "router-config.json even to build and refuses to run without the "
         "variables that file sets. Restore '. ../scripts/engine-env.sh'.")


def check_run_sources_env(text=None):
    t = text if text is not None else read("run.sh")
    need(line_of(t, r"engine-env\.sh") is not None,
         "run.sh does not source scripts/engine-env.sh. The engine refuses to "
         "start without METROLINX_KEY and GTA_ROUTER_DIR, which router-config.json "
         "names. Restore '. scripts/engine-env.sh'.")


# ---- 7. run.sh binding and port guard -------------------------------------

def check_run_binding(text=None):
    t = text if text is not None else read("run.sh")
    need(re.search(r"otp\.jar .*--bindAddress\s+127\.0\.0\.1", "\n".join(code_lines(t))),
         "run.sh starts the engine without --bindAddress 127.0.0.1. OpenTripPlanner "
         "defaults to every network interface, which exposes the routing engine to "
         "everyone on the same Wi-Fi. Restore --bindAddress 127.0.0.1.")
    code = "\n".join(code_lines(t))
    m = re.search(r"for port in ([\d ]+); do(.*?)done", code, re.S)
    need(m is not None and {"8080", "8081", "8090"} <= set(m.group(1).split())
         and "lsof" in m.group(2) and "exit 1" in m.group(2),
         "run.sh no longer refuses to start when ports 8080, 8081 or 8090 are in "
         "use (the lsof loop). A second copy loads a second 6 GB engine and makes "
         "every search slow. Restore the loop with lsof and exit 1.")


# ---- 8. reach engine has no live updaters ---------------------------------

def check_reach_no_updaters(cfg=None):
    cfg = cfg if cfg is not None else load_json("engine/reach-engine/router-config.json")
    need(not cfg.get("updaters"),
         "engine/reach-engine/router-config.json has real-time updaters. The Reach "
         "map is a research view that must depend only on published schedules; live "
         "delays make its results change with the time of day and need keys the "
         "reach engine does not have. Remove \"updaters\".")


# ---- runner ---------------------------------------------------------------

CHECKS = [check_router_config, check_build_config, check_feeds_agree,
          check_otp_config, check_parking_patch, check_setup_order,
          check_refresh_order, check_run_sources_env, check_run_binding,
          check_reach_no_updaters]


def mutate_json(rel, fn):
    d = load_json(rel)
    fn(d)
    return d


def rep(rel, old, new):
    t = read(rel)
    assert old in t, f"self-test setup: {old!r} not in {rel}"
    return t.replace(old, new, 1)


def self_tests():
    """(label, checker, kwargs) where kwargs is a deliberately broken input."""
    rc = "engine/router-config.json"
    rd = lambda d: d["routingDefaults"]
    bc = "engine/build-config.json"
    swap_lines = lambda t, a, b: t.replace(a, "@@").replace(b, a).replace("@@", b)

    def feeds_sh_without_milton():
        return "\n".join(l for l in read("scripts/feeds.sh").splitlines()
                         if "milton-gtfs.zip" not in l)

    def patch_with_one_way():
        t = read("data/parking-patch.osc")
        return t[:t.index("</way>") + 6] + "</modify></osmChange>"

    def setup_patch_after_build():
        t = read("setup.sh")
        line = [l for l in t.splitlines() if "osmium apply-changes" in l][0]
        return t.replace(line, "# moved").replace("--build --save .", "--build --save .\n" + line)

    return [
        ("maxStopCount 500", check_router_config,
         dict(cfg=mutate_json(rc, lambda d: rd(d)["accessEgress"].update(maxStopCount=500)))),
        ("CAR_TO_PARK 30m", check_router_config,
         dict(cfg=mutate_json(rc, lambda d: rd(d)["accessEgress"]["maxDurationForMode"].update(CAR_TO_PARK="30m")))),
        ("filter is boolean", check_router_config,
         dict(cfg=mutate_json(rc, lambda d: rd(d)["itineraryFilters"].update(
             removeTransitWithHigherCostThanBestOnStreetOnly=False)))),
        ("groupSimilarityKeepOne 0.85", check_router_config,
         dict(cfg=mutate_json(rc, lambda d: rd(d)["itineraryFilters"].update(groupSimilarityKeepOne=0.85)))),
        ("minWindow 30m", check_router_config,
         dict(cfg=mutate_json(rc, lambda d: d["transit"]["dynamicSearchWindow"].update(minWindow="30m")))),
        ("walk speed missing", check_router_config,
         dict(cfg=mutate_json(rc, lambda d: rd(d)["walk"].pop("speed")))),
        ("bicycle optimization object", check_router_config,
         dict(cfg=mutate_json(rc, lambda d: rd(d)["bicycle"].update(optimization={"type": "safest-streets"})))),
        ("literal key in URL", check_router_config,
         dict(cfg=json.loads(json.dumps(load_json(rc)).replace("key=${METROLINX_KEY}", "key=abc123def456")))),
        ("GO alerts raw URL", check_router_config,
         dict(cfg=json.loads(json.dumps(load_json(rc)).replace(
             "file:${GTA_ROUTER_DIR}/go-alerts-filtered.pb", "https://api.openmetrolinx.com/x")))),
        ("DRT raw URL", check_router_config,
         dict(cfg=json.loads(json.dumps(load_json(rc)).replace(
             "file:${GTA_ROUTER_DIR}/drt-rt-filtered.pb", "https://maps.durham.ca/x")))),
        ("bike park-and-ride off", check_build_config,
         dict(cfg=mutate_json(bc, lambda d: d.update(staticBikeParkAndRide=False)))),
        ("car park-and-ride disabled", check_build_config,
         dict(cfg=mutate_json(bc, lambda d: d.update(staticParkAndRide=False)))),
        ("timezone New York", check_build_config,
         dict(cfg=mutate_json(bc, lambda d: d.update(transitModelTimeZone="America/New_York")))),
        ("OSM file renamed", check_build_config,
         dict(cfg=mutate_json(bc, lambda d: d["osm"][0].update(source="ontario-latest.osm.pbf")))),
        ("feed id dropped", check_build_config,
         dict(cfg=mutate_json(bc, lambda d: d["transitFeeds"].pop()))),
        ("feeds.sh missing a feed", check_feeds_agree, dict(feeds_sh=feeds_sh_without_milton())),
        ("fare row missing", check_feeds_agree,
         dict(core_js=rep("web/core.js", '["MILTON"', '["MILTONX"'))),
        ("transfer feature off", check_otp_config,
         dict(cfg={"otpFeatures": {"MinimumTransferTimeIsDefinitive": False}})),
        ("patch gutted", check_parking_patch, dict(text=patch_with_one_way())),
        ("patch not XML", check_parking_patch, dict(text="<osmChange><modify>")),
        ("patch after build", check_setup_order, dict(text=setup_patch_after_build())),
        ("setup without env", check_setup_order,
         dict(text=rep("setup.sh", ". scripts/engine-env.sh", ""))),
        ("TTC patch after build", check_refresh_order,
         dict(text=swap_lines(read("refresh.sh"), "python3 ../scripts/patch_ttc_transfers.py",
                              "java -Xmx8G -jar otp.jar --build --save ."))),
        ("no graph backup", check_refresh_order,
         dict(text=rep("refresh.sh", "cp -f graph.obj graph.obj.prev", ":"))),
        ("refresh without env", check_refresh_order,
         dict(text=rep("refresh.sh", ". ../scripts/engine-env.sh", ""))),
        ("run without env", check_run_sources_env,
         dict(text=rep("run.sh", ". scripts/engine-env.sh || exit 1", ""))),
        ("engine on all interfaces", check_run_binding,
         dict(text=rep("run.sh", "--bindAddress 127.0.0.1", ""))),
        ("port guard removed", check_run_binding,
         dict(text=rep("run.sh", "for port in 8080 8081 8090", "for port in 8081"))),
        ("reach engine has updaters", check_reach_no_updaters,
         dict(cfg={"updaters": [{"type": "real-time-alerts"}]})),
    ]


def run_self_tests():
    covered = set()
    for label, fn, kw in self_tests():
        try:
            fn(**kw)
        except AssertionError as e:
            msg = str(e)
            assert "docs/routing-notes.md" in msg, f"{label}: message lacks the doc pointer"
            covered.add(fn.__name__)
            print(f"ok broken input is caught: {label}")
        else:
            print(f"FAIL {label}: the check passed on a deliberately broken input")
            sys.exit(1)
    missed = {c.__name__ for c in CHECKS} - covered
    if missed:
        print("FAIL no self-test for", sorted(missed))
        sys.exit(1)
    print(f"all {len(self_tests())} broken inputs were caught")


def main():
    if "--self-test" in sys.argv[1:]:
        return run_self_tests()
    for fn in CHECKS:
        try:
            info = fn()
        except AssertionError as e:
            print(f"FAIL {fn.__name__}: {e}")
            sys.exit(1)
        print(f"ok {fn.__name__}" + (f" {info}" if info else ""))
    print(f"{len(CHECKS)} checks passed")


if __name__ == "__main__":
    main()
