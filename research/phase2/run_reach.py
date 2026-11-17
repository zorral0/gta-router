"""Phase 2, version 2: ask the research reach engine for travel-time surfaces from every starting point.

Version 2 (2026-09-15) differs from version 1 (kept as run_reach_v1.py):
  - engine: the research graph with a 40 km buffer (engine/research-buffer), served on :8091
  - time limits: transit at 30 and 60 minutes (45 minutes on a fixed 10% sample)
  - starting points: research/data/census/origin_points_v2.csv (one point per DA up to 2 km2,
    one per populated dissemination block in larger DAs); build it with build_origin_points.py
  - roads for snapping come from the buffer map; the far-north DAs are included
  - outputs go to surfaces_v2/ so they never mix with version 1

    research/.venv/bin/python research/phase2/run_reach.py --dry-run   # plan and time estimate, no engine
    research/.venv/bin/python research/phase2/run_reach.py --pilot
    research/.venv/bin/python research/phase2/run_reach.py --limit 30
    research/.venv/bin/python research/phase2/run_reach.py             # all starting points
    research/.venv/bin/python research/phase2/run_reach.py --summary   # areas table, no engine

Per starting point, weekday morning only by default (--periods am):
  13 transit  WALK,TRANSIT cutoff 30M, every 5 min 07:30-08:30  (am_30_HHMM.tif)
  13 transit  WALK,TRANSIT cutoff 60M, same departures           (am_60_HHMM.tif)
   1 car      CAR cutoff 30M at 08:00                            (car_30.tif)
  13 extra    WALK,TRANSIT cutoff 45M, same departures, 10% sample (am_45_HHMM.tif)
   1 extra    CAR cutoff 30M from the backup start point, for input-flagged
              points and a 5% sample (car_30_alt.tif). Logged, never swapped in.
Each threshold is read only from requests made at that same cutoff.
Safe to stop and re-run at any time: finished files are skipped.
"""
import argparse
import csv
import hashlib
import json
import os
import shutil
import signal
import statistics
import sys
import threading
import time
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(RESEARCH / "pilot"))
from surface import TIFF_MAGIC, area_km2, is_valid_tiff  # noqa: E402

ORIGIN_POINTS = RESEARCH / "data" / "census" / "origin_points_v2.csv"  # built by build_origin_points.py
ROADS = RESEARCH / "data" / "osm" / "drive-roads-buffer.geojsonseq"   # drivable roads from the 40 km buffer map
UTM = "EPSG:32617"
DESIGN = "v2"

RETRIES = 3            # extra tries per request after the first
BACKOFF_S = 2          # 2, 4, 8 s
DOWN_AFTER = 12        # this many connection failures in a row = engine down
POLL_S = 30            # while down, check the engine this often
SLOWED_CAR_S = round(30 * 60 / 1.24)  # 24:12. Factor vs car surfaces, corrected trip points (pretest.py calib, 2026-09-14)

NORTH_LAT = 44.35      # only with --exclude-north: the v1 map ended here; the v2 buffer map covers these DAs
QA_SNAP_M = 300        # input flag: origin moved more than this to reach a drivable road
WIDE_ALT_M = 3000      # wider search radius for a backup start point
DIAG_RATIO = 3.0       # diagnostic only: car 30-min area below 3x median transit 30-min area

# Measured 2026-09-15 on the buffer graph with the v2 request mix, after a restart (swap 0):
# 8 workers 0.078 s per request (~8.3 h full job); 12 workers 0.104 s (slower on 10 cores).
# Pace collapses if the Mac swaps: restart first and run nothing else heavy.
SEC_PER_REQUEST = 0.078

# ---------------------------------------------------------------- request design

N_DEPARTURES = 13
STEP_MIN = 5
PERIODS = {  # name: (date, first departure minute of day). All -04:00 (EDT).
    "am": ("2026-09-22", 7 * 60 + 30),
    "pm": ("2026-09-22", 20 * 60 + 30),
    "sun": ("2026-09-20", 10 * 60 + 30),
}
TRANSIT_CUTOFFS = (30, 60)
SENSITIVITY_CUTOFF = 45
SENSITIVITY_PERIODS = ("am",)
TRANSIT = "WALK,TRANSIT"
CAR_WHEN = "2026-09-22T08:00:00-04:00"

Req = namedtuple("Req", "name when modes cutoff start")  # start: "main" or "alt"


def departures(period):
    """[(HHMM, ISO time)] for one period: 13 departures, 5 minutes apart."""
    day, first = PERIODS[period]
    out = []
    for i in range(N_DEPARTURES):
        m = first + STEP_MIN * i
        out.append((f"{m // 60:02d}{m % 60:02d}", f"{day}T{m // 60:02d}:{m % 60:02d}:00-04:00"))
    return out


def _hash_mod(origin_id, n, salt=""):
    return int(hashlib.sha256(f"{salt}{origin_id}".encode()).hexdigest()[:8], 16) % n


def in_sensitivity_sample(origin_id):
    """Stable 10% sample (unchanged from the old design): same answer on every run and machine."""
    return _hash_mod(origin_id, 10) == 0


def in_qa_sample(origin_id):
    """Stable 5% sample for the backup-point car check, independent of the 10% sample."""
    return _hash_mod(origin_id, 20, salt="qa-alt:") == 0


def input_flags(o):
    """Reasons from inputs only (never from results) to distrust the main start point."""
    reasons = []
    if float(o["snap_m"]) > QA_SNAP_M:
        reasons.append(f"snap_gt_{QA_SNAP_M}m")
    if not o.get("alt_lat"):
        reasons.append("no_backup_point")
    return reasons


def wants_alt_car(o):
    return bool(input_flags(o)) or in_qa_sample(o["origin_id"])


def parse_periods(text):
    names = [p.strip() for p in text.split(",") if p.strip()]
    bad = [p for p in names if p not in PERIODS]
    if bad or not names:
        raise argparse.ArgumentTypeError(f"periods must be from {','.join(PERIODS)}; got {text!r}")
    return [p for p in PERIODS if p in names]  # canonical order


def request_plan(o, periods=("am",)):
    """Requests for one origin, in fetch order. File name = f'{req.name}.tif'."""
    oid = o["origin_id"]
    plan = []
    for period in periods:
        deps = departures(period)
        for cut in TRANSIT_CUTOFFS:
            plan += [Req(f"{period}_{cut}_{hhmm}", when, TRANSIT, f"{cut}M", "main") for hhmm, when in deps]
            if period == "am" and cut == 30:
                plan.append(Req("car_30", CAR_WHEN, "CAR", "30M", "main"))
    if "am" not in periods:
        plan.append(Req("car_30", CAR_WHEN, "CAR", "30M", "main"))
    if in_sensitivity_sample(oid):
        for period in periods:
            if period in SENSITIVITY_PERIODS:
                plan += [Req(f"{period}_{SENSITIVITY_CUTOFF}_{hhmm}", when, TRANSIT, f"{SENSITIVITY_CUTOFF}M", "main")
                         for hhmm, when in departures(period)]
    if wants_alt_car(o) and o.get("alt_lat"):
        plan.append(Req("car_30_alt", CAR_WHEN, "CAR", "30M", "alt"))
    return plan


def done_marker(d, periods):
    return d / f"_done_{DESIGN}_{'-'.join(periods)}"


# ---------------------------------------------------------------- origins

SNAP_COLS = ["origin_id", "DAUID", "kind", "weight", "lat", "lon", "snap_lat", "snap_lon", "snap_m", "alt_lat", "alt_lon", "alt_m", "alt_how",
             "snap_highway", "alt_highway"]


def load_roads():
    """(road geometries in UTM, highway tag per road, name tag per road)."""
    import geopandas as gpd
    from shapely.geometry import shape

    print("  loading drivable roads ...", flush=True)
    geoms, hw, names = [], [], []
    with open(ROADS) as f:
        for line in f:
            if not line.strip():
                continue
            feat = json.loads(line.lstrip("\x1e"))
            props = feat.get("properties") or {}
            geoms.append(shape(feat["geometry"]))
            hw.append(props.get("highway", ""))
            names.append(props.get("name", ""))
    return gpd.GeoSeries(geoms, crs="EPSG:4326").to_crs(UTM).values, hw, names


def alternative_points(rows, roads):
    """For each origin, a second drivable-road start point for the QA check.

    First choice: the nearest point on another road whose point is at least
    40 m from the main snapped point (the second-nearest road). Otherwise a
    50 to 150 m nudge along the same road. Roads within 500 m only; see
    wide_alternative_points for the rest.
    """
    import numpy as np
    import shapely
    from pyproj import Transformer

    tree = shapely.STRtree(roads)
    fwd = Transformer.from_crs("EPSG:4326", UTM, always_xy=True)
    back = Transformer.from_crs(UTM, "EPSG:4326", always_xy=True)
    rx, ry = fwd.transform([float(r["lon"]) for r in rows], [float(r["lat"]) for r in rows])
    sx, sy = fwd.transform([float(r["snap_lon"]) for r in rows], [float(r["snap_lat"]) for r in rows])
    raw_pts = shapely.points(rx, ry)
    snap_pts = shapely.points(sx, sy)
    pairs = tree.query(raw_pts, predicate="dwithin", distance=500)
    cands = {}
    for oi, ri in zip(*pairs):
        cands.setdefault(int(oi), []).append(int(ri))
    for i, r in enumerate(rows):
        p, s = raw_pts[i], snap_pts[i]
        idx = cands.get(i, [])
        idx = sorted(idx, key=lambda k: roads[k].distance(p))
        pick, how = None, ""
        for k in idx:
            q = roads[k].interpolate(roads[k].project(p))
            if q.distance(s) >= 40:
                pick, how = q, "second_road"
                break
        if pick is None and idx:
            line = roads[idx[0]]
            d = line.project(s)
            for delta in (100, -100, 150, -150, 50, -50):
                if 0 <= d + delta <= line.length:
                    q = line.interpolate(d + delta)
                    if q.distance(s) >= 30:
                        pick, how = q, f"nudge_{delta:+d}m"
                        break
        if pick is None:
            r.update(alt_lat="", alt_lon="", alt_m="", alt_how="none")
            continue
        lon, lat = back.transform(pick.x, pick.y)
        r.update(alt_lat=round(lat, 6), alt_lon=round(lon, 6), alt_m=round(float(np.hypot(pick.x - p.x, pick.y - p.y)), 1),
                 alt_how=how)


def add_road_info(rows, roads, hw, names):
    """Adds snap_highway and alt_highway, and a wider backup search for origins without one.

    The snapped road is found the same way pilot.snap_to_roads found it (nearest
    road to the raw point) and checked against the saved snap point. Origins with
    alt_how == none get the nearest point on a different road way within
    WIDE_ALT_M of the raw point, at least 40 m from the snapped point; a road with
    a different name is preferred over another piece of the same street.
    """
    import numpy as np
    import shapely
    from pyproj import Transformer

    tree = shapely.STRtree(roads)
    fwd = Transformer.from_crs("EPSG:4326", UTM, always_xy=True)
    back = Transformer.from_crs(UTM, "EPSG:4326", always_xy=True)
    rx, ry = fwd.transform([float(r["lon"]) for r in rows], [float(r["lat"]) for r in rows])
    sx, sy = fwd.transform([float(r["snap_lon"]) for r in rows], [float(r["snap_lat"]) for r in rows])
    raw_pts, snap_pts = shapely.points(rx, ry), shapely.points(sx, sy)
    near = tree.nearest(raw_pts)
    mismatch = 0
    for i, r in enumerate(rows):
        k = int(near[i])
        if roads[k].distance(snap_pts[i]) > 2:  # should be ~0: fall back to the road under the snap point
            mismatch += 1
            k = int(tree.nearest(snap_pts[i]))
            near[i] = k
        r["snap_highway"] = hw[k]
    if mismatch:
        print(f"  note: {mismatch} snap points were not on the nearest road; used the road under the point", flush=True)

    wide = 0
    for i, r in enumerate(rows):
        if r.get("alt_lat"):
            continue
        p, s, own = raw_pts[i], snap_pts[i], int(near[i])
        idx = [int(k) for k in tree.query(p, predicate="dwithin", distance=WIDE_ALT_M) if int(k) != own]
        idx.sort(key=lambda k: roads[k].distance(p))
        pick = None
        for need_new_name in (True, False):
            for k in idx:
                if need_new_name and names[k] and names[k] == names[own]:
                    continue
                q = roads[k].interpolate(roads[k].project(p))
                if q.distance(s) >= 40:
                    pick = q
                    how = "second_road_wide" if need_new_name else "same_name_way_wide"
                    break
            if pick is not None:
                break
        if pick is None:
            r.update(alt_lat="", alt_lon="", alt_m="", alt_how="none")
            continue
        lon, lat = back.transform(pick.x, pick.y)
        r.update(alt_lat=round(lat, 6), alt_lon=round(lon, 6), alt_m=round(float(np.hypot(pick.x - p.x, pick.y - p.y)), 1),
                 alt_how=how)
        wide += 1
    have = [i for i, r in enumerate(rows) if r.get("alt_lat")]
    ax, ay = fwd.transform([float(rows[i]["alt_lon"]) for i in have], [float(rows[i]["alt_lat"]) for i in have])
    alt_near = tree.nearest(shapely.points(ax, ay)) if have else []
    for i, k in zip(have, alt_near):
        rows[i]["alt_highway"] = hw[int(k)]
    for r in rows:
        r.setdefault("alt_highway", "")
    print(f"  road classes added; wider search found a backup point for {wide} more origins, "
          f"{sum(not r.get('alt_lat') for r in rows)} still have none", flush=True)


def write_rows(path, rows, cols):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)


def snap_origins(raw, cache):
    """raw: list of dicts with origin_id, DAUID, kind, weight, lat, lon. Snapped once, cached to `cache`."""
    if cache.exists():
        with open(cache, newline="") as f:
            reader = csv.DictReader(f)
            rows, cols = list(reader), reader.fieldnames
        if [r["origin_id"] for r in rows] != [str(o["origin_id"]) for o in raw]:
            sys.exit(f"{cache} does not match the starting-point list. Delete it to rebuild the snap.")
        if all(c in cols for c in SNAP_COLS):
            return rows
        sys.exit(f"{cache} is missing columns {sorted(set(SNAP_COLS) - set(cols))}. Delete it to rebuild the snap.")
    import pilot  # heavy imports only when needed

    pilot.ROADS = ROADS  # snap onto roads from the buffer map, not the old GTA-only extract
    t0 = time.time()
    print(f"Snapping {len(raw)} starting points onto drivable roads (one time, cached in {cache.name}) ...", flush=True)
    snapped = pilot.snap_to_roads([(str(o["origin_id"]), float(o["lat"]), float(o["lon"]), o["kind"]) for o in raw])
    rows = [dict(origin_id=str(o["origin_id"]), DAUID=str(o["DAUID"]), kind=o["kind"], weight=o["weight"],
                 lat=o["lat"], lon=o["lon"], snap_lat=sn[1], snap_lon=sn[2], snap_m=sn[4])
            for o, sn in zip(raw, snapped)]
    roads, hw, names = load_roads()
    alternative_points(rows, roads)
    add_road_info(rows, roads, hw, names)
    write_rows(cache, rows, SNAP_COLS)
    print(f"  done in {time.time() - t0:.0f} s", flush=True)
    return rows


def load_origins(pilot):
    if pilot:
        from pilot import ORIGINS

        raw = [dict(origin_id=name, DAUID=name, kind="pilot", weight="", lat=lat, lon=lon)
               for name, lat, lon, kind in ORIGINS]
        return snap_origins(raw, HERE / f"pilot_origins_snapped_{DESIGN}.csv")
    if not ORIGIN_POINTS.exists():
        sys.exit(f"{ORIGIN_POINTS} not found. Build it first: "
                 f"research/.venv/bin/python research/data/census/build_origin_points.py")
    with open(ORIGIN_POINTS, newline="") as f:
        raw = list(csv.DictReader(f))
    return snap_origins(raw, HERE / f"origins_snapped_{DESIGN}.csv")


def split_excluded(origins):
    keep, out = [], []
    for o in origins:
        if float(o["lat"]) > NORTH_LAT:
            out.append(dict(origin_id=o["origin_id"], DAUID=o.get("DAUID", ""), lat=o["lat"], lon=o["lon"], snap_m=o["snap_m"],
                            reason=f"north of latitude {NORTH_LAT}, outside the map extract (study decision)"))
        else:
            keep.append(o)
    return keep, out


# ---------------------------------------------------------------- engine

class FetchError(Exception):
    pass


def atomic_write(path, blob):
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    with open(tmp, "wb") as f:
        f.write(blob)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


QA_COLS = ["origin_id", "snap_m", "snap_highway", "input_flag", "flag_reasons", "in_qa_sample", "alt_how", "alt_m",
           "alt_highway", "car30_km2", "car30_alt_km2", "alt_over_main", "transit30_am_median_km2",
           "diag_car_over_transit30", "diag_below_3x"]


class Runner:
    def __init__(self, args, out_surfaces, errors_csv, qa_csv):
        self.api = args.api.rstrip("/")
        self.timeout = args.timeout
        self.periods = args.periods
        self.surfaces = out_surfaces
        self.errors_csv = errors_csv
        self.qa_csv = qa_csv
        self.lock = threading.Lock()
        self.local = threading.local()
        self.engine_ok = threading.Event()
        self.engine_ok.set()
        self.fails_in_row = 0
        self.requests_made = 0
        self.qa_logged = set()
        if qa_csv.exists():
            with open(qa_csv, newline="") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames != QA_COLS:
                    sys.exit(f"{qa_csv} has columns from another design. Move it away and run again.")
                self.qa_logged = {r["origin_id"] for r in reader}

    # -- engine health
    def engine_alive(self):
        try:
            return requests.get(self.api + "/otp", timeout=10).status_code < 500
        except requests.RequestException:
            return False

    def wait_for_engine(self, reason):
        """Called with engine_ok cleared. Polls until the engine answers."""
        print(f"\n[{now()}] ENGINE NOT ANSWERING at {self.api} ({reason}).\n"
              f"  Pausing. Checking again every {POLL_S} s. Finished files are safe.\n"
              f"  Start the research buffer engine again (see README.md) and this run will carry on.", flush=True)
        t0 = time.time()
        polls = 0
        while not self.engine_alive():
            time.sleep(POLL_S)
            polls += 1
            if polls % 20 == 0:  # every 10 minutes
                print(f"[{now()}] still waiting for the engine ({(time.time() - t0) / 60:.0f} min so far)", flush=True)
        with self.lock:
            self.fails_in_row = 0
        print(f"[{now()}] Engine is back after {(time.time() - t0) / 60:.1f} min. Carrying on.", flush=True)
        self.engine_ok.set()

    def _connection_failure(self):
        """Returns True if this failure put the run into (or it already is in) pause."""
        with self.lock:
            self.fails_in_row += 1
            if self.fails_in_row >= DOWN_AFTER and self.engine_ok.is_set():
                self.engine_ok.clear()
                threading.Thread(target=self.wait_for_engine, args=(f"{self.fails_in_row} failures in a row",),
                                 daemon=True).start()
            return not self.engine_ok.is_set()

    def fetch(self, lat, lon, when, modes, cutoff):
        if not hasattr(self.local, "session"):
            self.local.session = requests.Session()
        params = {"location": f"{lat},{lon}", "time": when, "modes": modes, "cutoff": cutoff}
        attempt, last = 0, ""
        while True:
            self.engine_ok.wait()
            engine_trouble = False
            try:
                r = self.local.session.get(self.api + "/otp/traveltime/surface", params=params,
                                           timeout=(10, self.timeout))
                with self.lock:
                    self.fails_in_row = 0
                    self.requests_made += 1
                if r.status_code == 200 and r.content[:4] in TIFF_MAGIC and len(r.content) >= 200:
                    return r.content
                last = f"http {r.status_code} ({len(r.content)} bytes): {r.content[:150]!r}"
            except (requests.ConnectionError, requests.Timeout) as ex:
                last = f"{type(ex).__name__}: {str(ex)[:150]}"
                engine_trouble = True
            except requests.RequestException as ex:
                last = f"{type(ex).__name__}: {str(ex)[:150]}"
            if engine_trouble and self._connection_failure():
                continue  # engine is down: do not use up this request's retries
            attempt += 1
            if attempt > RETRIES:
                raise FetchError(last)
            time.sleep(BACKOFF_S * 2 ** (attempt - 1))

    # -- logs
    def log_error(self, oid, kind, err):
        with self.lock:
            new = not self.errors_csv.exists()
            with open(self.errors_csv, "a", newline="") as f:
                w = csv.writer(f)
                if new:
                    w.writerow(["origin_id", "kind", "error", "when"])
                w.writerow([oid, kind, err, now()])

    def log_qa(self, row):
        with self.lock:
            if row["origin_id"] in self.qa_logged:
                return
            new = not self.qa_csv.exists()
            with open(self.qa_csv, "a", newline="") as f:
                w = csv.DictWriter(f, fieldnames=QA_COLS)
                if new:
                    w.writeheader()
                w.writerow(row)
            self.qa_logged.add(row["origin_id"])

    # -- per origin
    def do_origin(self, o):
        oid = o["origin_id"]
        d = self.surfaces / oid
        d.mkdir(parents=True, exist_ok=True)
        for stale in d.glob(".*.tmp"):
            stale.unlink(missing_ok=True)
        ok, fetched = True, 0
        for req in request_plan(o, self.periods):
            path = d / f"{req.name}.tif"
            if is_valid_tiff(path):
                continue
            lat, lon = (o["snap_lat"], o["snap_lon"]) if req.start == "main" else (o["alt_lat"], o["alt_lon"])
            try:
                atomic_write(path, self.fetch(lat, lon, req.when, req.modes, req.cutoff))
                fetched += 1
            except FetchError as ex:
                ok = False
                self.log_error(oid, req.name, str(ex))
        if ok:
            self.log_qa(qa_row(o, d))
            atomic_write(done_marker(d, self.periods), now().encode())
        return ok, fetched


def qa_row(o, d):
    """Input-based flags plus logged (never acted on) car checks for one finished origin."""
    oid = o["origin_id"]
    reasons = input_flags(o)
    car = area_km2(d / "car_30.tif", 1800)
    alt_p = d / "car_30_alt.tif"
    alt = area_km2(alt_p, 1800) if is_valid_tiff(alt_p) else None
    am30 = [d / f"am_30_{hhmm}.tif" for hhmm, _ in departures("am")]
    t30 = statistics.median(area_km2(p, 1800) for p in am30) if all(is_valid_tiff(p) for p in am30) else None
    return dict(
        origin_id=oid, snap_m=o["snap_m"], snap_highway=o.get("snap_highway", ""),
        input_flag=int(bool(reasons)), flag_reasons=";".join(reasons), in_qa_sample=int(in_qa_sample(oid)),
        alt_how=o.get("alt_how", ""), alt_m=o.get("alt_m", ""), alt_highway=o.get("alt_highway", ""),
        car30_km2=round(car, 2),
        car30_alt_km2=round(alt, 2) if alt is not None else "",
        alt_over_main=round(alt / car, 3) if alt is not None and car else "",
        transit30_am_median_km2=round(t30, 2) if t30 is not None else "",
        diag_car_over_transit30=round(car / t30, 2) if t30 else "",
        diag_below_3x=int(car < DIAG_RATIO * t30) if t30 is not None else "",
    )


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def fmt_dur(s):
    s = int(s)
    return f"{s // 3600}h{s % 3600 // 60:02d}m" if s >= 3600 else f"{s // 60}m{s % 60:02d}s"


# ---------------------------------------------------------------- dry run

def dry_run(origins, excluded, periods, pick, workers):
    by_id = {o["origin_id"]: o for o in origins}
    if pick and pick not in by_id:
        sys.exit(f"--origin {pick} is not in the study origins (excluded or unknown)")
    o = by_id[pick] if pick else origins[0]
    plan = request_plan(o, periods)
    flags = input_flags(o)
    print(f"DRY RUN (no engine calls). Design {DESIGN}, periods {','.join(periods)}.\n")
    print(f"Origin {o['origin_id']}: snap {o['snap_m']} m on '{o.get('snap_highway', '')}', backup {o.get('alt_how', '')}; "
          f"10% sample {'yes' if in_sensitivity_sample(o['origin_id']) else 'no'}, "
          f"5% QA sample {'yes' if in_qa_sample(o['origin_id']) else 'no'}, input flags {';'.join(flags) or 'none'}")
    for i, r in enumerate(plan, 1):
        lat, lon = (o["snap_lat"], o["snap_lon"]) if r.start == "main" else (o["alt_lat"], o["alt_lon"])
        print(f"  {i:3d}  {r.name + '.tif':20} {r.modes:13} cutoff {r.cutoff:4} {r.when}  from {r.start} {lat},{lon}")
    print(f"  = {len(plan)} requests for this origin\n")

    counts = [len(request_plan(x, periods)) for x in origins]
    sens = sum(in_sensitivity_sample(x["origin_id"]) for x in origins)
    flagged = sum(bool(input_flags(x)) for x in origins)
    qa_sample = sum(in_qa_sample(x["origin_id"]) for x in origins)
    alt_req = sum(wants_alt_car(x) and bool(x.get("alt_lat")) for x in origins)
    no_backup = sum(not x.get("alt_lat") for x in origins)
    base = N_DEPARTURES * len(TRANSIT_CUTOFFS) * len(periods) + 1
    total = sum(counts)
    hours = total * SEC_PER_REQUEST / 3600
    print(f"Full job: {len(origins)} origins ({len(excluded)} north of {NORTH_LAT} skipped)")
    print(f"  base          {base} per origin x {len(origins)} = {base * len(origins)}")
    print(f"  {SENSITIVITY_CUTOFF}-min sample {sens} origins x {N_DEPARTURES * sum(p in SENSITIVITY_PERIODS for p in periods)} "
          f"= {sens * N_DEPARTURES * sum(p in SENSITIVITY_PERIODS for p in periods)}")
    print(f"  backup car    {alt_req} origins x 1 = {alt_req}  ({flagged} input-flagged, {qa_sample} in the 5% sample, "
          f"{no_backup} with no backup point at all)")
    print(f"  total         {total} requests, {total / len(origins):.2f} per origin")
    print(f"  estimate      {hours:.1f} h at {SEC_PER_REQUEST:.3f} s per request "
          f"(measured pace with 8 workers after a restart; this run would use {workers})")


# ---------------------------------------------------------------- summary

def summary(origins, surfaces, qa_csv):
    flags = {}
    if qa_csv.exists():
        with open(qa_csv, newline="") as f:
            flags = {r["origin_id"]: r for r in csv.DictReader(f)}
    print(f"{'origin':22} {'snap_m':>6} {'road':12} {'am30 med':>8} {'am60 med':>8} {'car30':>7} {'car24:12':>8} "
          f"{'car/am30':>8} {'car alt':>7}  flags")
    rows = []
    for o in origins:
        d = surfaces / o["origin_id"]
        am30 = [d / f"am_30_{h}.tif" for h, _ in departures("am")]
        am60 = [d / f"am_60_{h}.tif" for h, _ in departures("am")]
        if not (is_valid_tiff(d / "car_30.tif") and all(map(is_valid_tiff, am30 + am60))):
            continue
        t30 = statistics.median(area_km2(p, 1800) for p in am30)
        t60 = statistics.median(area_km2(p, 3600) for p in am60)
        c30, cs = area_km2(d / "car_30.tif", 1800), area_km2(d / "car_30.tif", SLOWED_CAR_S)
        q = flags.get(o["origin_id"], {})
        alt = q.get("car30_alt_km2", "")
        ftxt = ";".join(x for x in (q.get("flag_reasons", ""), "qa_sample" if q.get("in_qa_sample") == "1" else "",
                                    "diag_below_3x" if q.get("diag_below_3x") == "1" else "") if x)
        print(f"{o['origin_id']:22} {float(o['snap_m']):6.0f} {o.get('snap_highway', ''):12} {t30:8.1f} {t60:8.1f} "
              f"{c30:7.0f} {cs:8.0f} {c30 / t30 if t30 else float('nan'):8.1f} {alt:>7}  {ftxt}")
        rows.append((t30, t60, c30))
    if rows:
        print(f"\n{len(rows)} origins. medians: am30 {statistics.median(r[0] for r in rows):.1f} km2, "
              f"am60 {statistics.median(r[1] for r in rows):.1f} km2, car30 {statistics.median(r[2] for r in rows):.0f} km2")


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pilot", action="store_true", help=f"only the 20 named pilot origins (pilot_surfaces_{DESIGN}/)")
    ap.add_argument("--limit", type=int, help="only the first N origins")
    ap.add_argument("--periods", type=parse_periods, default=["am"], help="comma list from am,pm,sun (default am)")
    ap.add_argument("--exclude-north", action="store_true", help=f"skip DAs north of latitude {NORTH_LAT} (v1 behaviour)")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--timeout", type=float, default=120, help="seconds to wait for one surface")
    ap.add_argument("--api", default="http://localhost:8091")
    ap.add_argument("--out", type=Path, default=HERE, help="folder for surfaces and logs (testing)")
    ap.add_argument("--summary", action="store_true", help="print areas for finished origins, no requests")
    ap.add_argument("--dry-run", action="store_true", help="print the request plan and time estimate, no requests")
    ap.add_argument("--origin", help="with --dry-run: which origin's request list to print (default the first)")
    args = ap.parse_args()

    prefix = "pilot_" if args.pilot else ""
    surfaces = args.out / f"{prefix}surfaces_{DESIGN}"
    errors_csv = args.out / f"{prefix}errors_{DESIGN}.csv"
    qa_csv = args.out / f"{prefix}qa_flags_{DESIGN}.csv"
    excluded_csv = args.out / f"{prefix}excluded_origins_{DESIGN}.csv"

    origins = load_origins(args.pilot)
    excluded = []
    if args.exclude_north:
        origins, excluded = split_excluded(origins)
    if args.dry_run:
        dry_run(origins[:args.limit] if args.limit else origins, excluded, args.periods, args.origin, args.workers)
        return
    if args.limit:
        origins = origins[:args.limit]
    if args.summary:
        summary(origins, surfaces, qa_csv)
        return
    if excluded or not args.pilot:
        write_rows(excluded_csv, excluded, ["origin_id", "DAUID", "lat", "lon", "snap_m", "reason"])

    surfaces.mkdir(parents=True, exist_ok=True)
    total = len(origins)
    todo = [o for o in origins if not done_marker(surfaces / o["origin_id"], args.periods).exists()]
    already = total - len(todo)
    n_req = sum(len(request_plan(o, args.periods)) for o in todo)
    print(f"[{now()}] {total} origins, periods {','.join(args.periods)} ({len(excluded)} north of {NORTH_LAT} skipped), "
          f"{already} already finished, {len(todo)} to do: up to {n_req} requests, "
          f"roughly {fmt_dur(n_req * SEC_PER_REQUEST)}. Workers {args.workers}. Output {surfaces}", flush=True)
    if not todo:
        print("Nothing to do.")
        return

    need = n_req * 20_000 * 2
    free = shutil.disk_usage(surfaces).free
    if free < need + 1e9:
        sys.exit(f"Not enough disk: {free / 1e9:.1f} GB free, want about {(need + 1e9) / 1e9:.1f} GB.")
    print(f"  disk: {free / 1e9:.0f} GB free, run needs roughly {n_req * 16_000 / 1e9:.2f} GB", flush=True)

    runner = Runner(args, surfaces, errors_csv, qa_csv)
    if not runner.engine_alive():
        runner.engine_ok.clear()
        runner.wait_for_engine("not answering at start")

    def stop(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    every = 50 if total > 200 else 5
    t0 = time.time()
    done_now = failed = 0
    ex = ThreadPoolExecutor(max_workers=args.workers)
    try:
        futures = [ex.submit(runner.do_origin, o) for o in todo]
        for fut in as_completed(futures):
            ok, fetched = fut.result()
            done_now += 1
            failed += not ok
            if done_now % every == 0 or done_now == len(todo):
                el = time.time() - t0
                rate = done_now / el if el else 0
                eta = (len(todo) - done_now) / rate if rate else 0
                print(f"[{now()}] {already + done_now}/{total} origins  {el / done_now:.2f} s/origin "
                      f"({rate * 3600:.0f}/h)  elapsed {fmt_dur(el)}  ETA {fmt_dur(eta)}  "
                      f"requests {runner.requests_made}  incomplete {failed}", flush=True)
    except KeyboardInterrupt:
        print(f"\n[{now()}] Stopped. {already + done_now}/{total} origins finished; finished files are kept. "
              f"Run the same command again to carry on.", flush=True)
        os._exit(130)
    ex.shutdown()
    el = time.time() - t0
    print(f"[{now()}] Finished this pass in {fmt_dur(el)}: {done_now - failed} origins complete, {failed} incomplete "
          f"(see {errors_csv.name}; run again to retry them). {runner.requests_made} requests, "
          f"{el / max(done_now, 1):.2f} s per origin.", flush=True)
    if qa_csv.exists():
        with open(qa_csv, newline="") as f:
            st = list(csv.DictReader(f))
        print(f"  {qa_csv.name}: {len(st)} origins logged, {sum(r['input_flag'] == '1' for r in st)} input-flagged, "
              f"{sum(r['car30_alt_km2'] != '' for r in st)} with a backup-point car surface, "
              f"{sum(r['diag_below_3x'] == '1' for r in st)} below the 3x diagnostic", flush=True)


if __name__ == "__main__":
    main()
