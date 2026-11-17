"""Phase 3, step 1: score every starting point from the saved travel-time maps.

Reads research/phase2/surfaces_v2/<origin_id>/ (13 transit departures at
30 and 60 minutes, one car map, and 45 minutes for the 10% sample) and
counts what each map reaches. Follows the measures in the plan v2
(research/plan/build_plan_docx.js, sections 5 to 8):

  Transit, 30 min   people (by block), grocery stores, EDs, km2
  Transit, 60 min   jobs (TTS zones, area-weighted), time to nearest grocery
                    store and ED (censored above 60 min)
  Transit, 45 min   same counts, 10% sample only (threshold sensitivity)
  Car, 30 min       people, grocery stores, EDs, km2, for the main case and
                    four sensitivity cases (traffic factor, terminal time)

Each transit number is computed for every one of the 13 departures, then
summarised as the median (the study value) and as a "reliable" value: the
25th percentile for counts and the 75th percentile for times, i.e. what
you get at 3 departures in 4 or more.

Rules used:
- A threshold is read only from maps requested at that same cut-off.
- A place counts as reached if the map cell containing it is within the
  time. If that cell has no value at all (never reached, e.g. inside a large
  parking lot or hospital grounds), the nearest reached neighbouring cell
  whose centre is within FALLBACK_M is used (review #33). This applies to
  destinations and to population blocks alike; the use is counted.
- Car budget = (30 min - terminal time) / traffic factor of driving time.
  Terminal time 5 min in downtown Toronto (TTS 2022 Planning District 1),
  3 min elsewhere. Factor 1.24 (weekday 8 AM, calibrated on the car grid).
- The car map is car_30.tif except for the 84 points listed in
  research/phase2/car_source_v2.csv.
- Edge test: a point is flagged if any cell it reaches (car within 30 min
  of driving, or transit within 60 min at any departure) lies within
  EDGE_M of the routing map's outer edge.

Output: research/phase3/points_scores.csv (one row per starting point) and
research/phase3/fallback_destinations.json.

Run: research/.venv/bin/python research/phase3/score_points.py [--limit N] [--workers N]
"""
import argparse
import csv
import json
import math
import os
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
sys.path.insert(0, str(RESEARCH / "phase2"))
from surface import NODATA, read_surface  # noqa: E402

SURF = Path(os.environ.get("REACH_SURF", RESEARCH / "phase2" / "surfaces_v2"))
DATA = RESEARCH / "data"
OUT = HERE / "points_scores.csv"

DEPARTURES = ["0730", "0735", "0740", "0745", "0750", "0755", "0800",
              "0805", "0810", "0815", "0820", "0825", "0830"]
FACTOR = 1.24
TERMINAL_DOWNTOWN, TERMINAL_ELSEWHERE = 5, 3
# name: (traffic factor, terminal minutes or None for the 3/5 default)
CAR_CASES = {"main": (FACTOR, None), "f100": (1.00, None), "f170": (1.70, None),
             "t0": (FACTOR, 0), "t8": (FACTOR, 8)}
FALLBACK_M = 210.0   # "about 200 m": one ~200 m cell over
EDGE_M = 2000.0
EDGE_CELL_DEG = 0.004
M_PER_DEG_LAT = 110574.0
M_PER_DEG_LON = 111320.0

G = {}  # per-worker globals


# --------------------------------------------------------------- point sets
class PointSet:
    """Points with weights, bucketed on a coarse lat/lon grid for bbox queries."""

    def __init__(self, lat, lon, w, ids=None, cell=0.05):
        self.lat = np.asarray(lat, float)
        self.lon = np.asarray(lon, float)
        self.w = np.asarray(w, float)
        self.ids = None if ids is None else np.asarray(ids)
        self.cell = cell
        self.lat0, self.lon0 = self.lat.min(), self.lon.min()
        bi = ((self.lat - self.lat0) // cell).astype(int)
        bj = ((self.lon - self.lon0) // cell).astype(int)
        self.ni, self.nj = bi.max() + 1, bj.max() + 1
        key = bi * self.nj + bj
        self.order = np.argsort(key, kind="stable")
        self.keys = key[self.order]

    def query(self, lat_min, lat_max, lon_min, lon_max):
        i0 = max(int((lat_min - self.lat0) // self.cell), 0)
        i1 = min(int((lat_max - self.lat0) // self.cell), self.ni - 1)
        j0 = max(int((lon_min - self.lon0) // self.cell), 0)
        j1 = min(int((lon_max - self.lon0) // self.cell), self.nj - 1)
        if i0 > i1 or j0 > j1:
            return np.empty(0, int)
        parts = []
        for i in range(i0, i1 + 1):
            lo = np.searchsorted(self.keys, i * self.nj + j0, "left")
            hi = np.searchsorted(self.keys, i * self.nj + j1, "right")
            parts.append(self.order[lo:hi])
        idx = np.concatenate(parts)
        m = ((self.lat[idx] >= lat_min) & (self.lat[idx] <= lat_max) &
             (self.lon[idx] >= lon_min) & (self.lon[idx] <= lon_max))
        return idx[m]


# ---------------------------------------------------------------- surfaces
class Grid:
    def __init__(self, path):
        w, h, values, t = read_surface(path)
        self.w, self.h, self.t = w, h, t
        self.a = np.frombuffer(values, dtype=np.int32).reshape(h, w)
        self.lon_min = t.origin_x
        self.lon_max = t.origin_x + w * t.cell_x
        self.lat_max = t.origin_y
        self.lat_min = t.origin_y + h * t.cell_y

    def bbox(self):
        return self.lat_min, self.lat_max, self.lon_min, self.lon_max

    def times(self, lat, lon):
        """Travel seconds at each point (inf if unreached); bool array of fallback use."""
        t = self.t
        c = np.floor((lon - t.origin_x) / t.cell_x).astype(int)
        r = np.floor((lat - t.origin_y) / t.cell_y).astype(int)
        inb = (r >= 0) & (r < self.h) & (c >= 0) & (c < self.w)
        out = np.full(len(lat), np.inf)
        v = np.full(len(lat), NODATA, dtype=np.int64)
        v[inb] = self.a[r[inb], c[inb]]
        ok = v != NODATA
        out[ok] = v[ok]
        fb = np.zeros(len(lat), bool)
        need = np.nonzero(inb & ~ok)[0]
        if len(need):
            best_d = np.full(len(need), FALLBACK_M)
            best_v = np.full(len(need), np.inf)
            coslat = np.cos(np.radians(lat[need]))
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if dr == 0 and dc == 0:
                        continue
                    rr, cc = r[need] + dr, c[need] + dc
                    good = (rr >= 0) & (rr < self.h) & (cc >= 0) & (cc < self.w)
                    nv = np.full(len(need), NODATA, dtype=np.int64)
                    nv[good] = self.a[rr[good], cc[good]]
                    clon = t.origin_x + (cc + 0.5) * t.cell_x
                    clat = t.origin_y + (rr + 0.5) * t.cell_y
                    d = np.hypot((lon[need] - clon) * M_PER_DEG_LON * coslat,
                                 (lat[need] - clat) * M_PER_DEG_LAT)
                    better = (nv != NODATA) & (d <= best_d)
                    best_d[better] = d[better]
                    best_v[better] = nv[better]
            hit = np.isfinite(best_v)
            out[need[hit]] = best_v[hit]
            fb[need[hit]] = True
        return out, fb

    def reached_cells(self, max_s):
        rows, cols = np.nonzero((self.a != NODATA) & (self.a <= max_s))
        t = self.t
        return t.origin_y + (rows + 0.5) * t.cell_y, t.origin_x + (cols + 0.5) * t.cell_x

    def area_km2(self, max_s):
        lat, _ = self.reached_cells(max_s)
        if not len(lat):
            return 0.0
        cell = abs(self.t.cell_x) * M_PER_DEG_LON * abs(self.t.cell_y) * M_PER_DEG_LAT
        return float((cell * np.cos(np.radians(lat))).sum() / 1e6)


def near_edge(grid, max_s):
    lat, lon = grid.reached_cells(max_s)
    if not len(lat):
        return False
    e = G["edge"]
    i = ((lat - e["lat0"]) / EDGE_CELL_DEG).astype(int)
    j = ((lon - e["lon0"]) / EDGE_CELL_DEG).astype(int)
    m = e["mask"]
    out = (i < 0) | (i >= m.shape[0]) | (j < 0) | (j >= m.shape[1])
    if out.any():
        return True
    return bool(m[i, j].any())


# ------------------------------------------------------------------ loading
def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_globals():
    import geopandas as gpd
    import shapely

    blocks = read_csv(DATA / "buffer" / "blocks_buffer.csv")
    G["blocks"] = PointSet([float(b["lat"]) for b in blocks], [float(b["lon"]) for b in blocks],
                           [int(b["pop"]) for b in blocks])
    groc = [(r["osm_id"], float(r["lat"]), float(r["lon"])) for r in read_csv(DATA / "grocery" / "grocery_gta_v1.csv")]
    groc += [(r["osm_id"], float(r["lat"]), float(r["lon"])) for r in read_csv(DATA / "buffer" / "grocery_buffer.csv")]
    G["groc"] = PointSet([g[1] for g in groc], [g[2] for g in groc], np.ones(len(groc)), ids=[g[0] for g in groc])
    ed = [(r["id"], float(r["lat"]), float(r["lon"])) for r in read_csv(DATA / "healthcare" / "healthcare_gta.csv")
          if r["type"] == "hospital_emergency"]
    ed += [("buf:" + r["name"], float(r["lat"]), float(r["lon"])) for r in read_csv(DATA / "buffer" / "ed_buffer.csv")]
    G["ed"] = PointSet([e[1] for e in ed], [e[2] for e in ed], np.ones(len(ed)), ids=[e[0] for e in ed])
    j = np.load(DATA / "buffer" / "jobs_points.npz")
    G["jobs"] = PointSet(j["lat"], j["lon"], j["weight"], cell=0.02)

    buf = gpd.read_file(DATA / "buffer" / "gta_buffer_40km.geojson").to_crs(3161).geometry.iloc[0]
    inner = gpd.GeoSeries([buf.buffer(-EDGE_M)], crs=3161).to_crs(4326).iloc[0]
    b4326 = gpd.GeoSeries([buf], crs=3161).to_crs(4326).iloc[0]
    lon0, lat0, lon1, lat1 = b4326.bounds
    lats = lat0 + (np.arange(int((lat1 - lat0) / EDGE_CELL_DEG) + 1) + 0.5) * EDGE_CELL_DEG
    lons = lon0 + (np.arange(int((lon1 - lon0) / EDGE_CELL_DEG) + 1) + 0.5) * EDGE_CELL_DEG
    LON, LAT = np.meshgrid(lons, lats)
    G["edge"] = {"lat0": lat0, "lon0": lon0,
                 "mask": ~shapely.contains_xy(inner, LON.ravel(), LAT.ravel()).reshape(LAT.shape)}

    z = gpd.read_file(DATA / "tts" / "raw" / "zones2022" / "tts2022_v1_1_shapefile.shp").to_crs(4326)
    G["downtown"] = z[(z.Reg_no == 1) & (z.PD_no == 1)].geometry.buffer(0).union_all()

    G["car_source"] = {r["origin_id"]: r["car_source"] for r in read_csv(RESEARCH / "phase2" / "car_source_v2.csv")}
    oct_fix = RESEARCH / "phase4" / "car_fix_oct.csv"  # second car-start fix (Phase 4, October)
    if oct_fix.exists():
        G["car_source"].update({r["origin_id"]: r["car_source"] for r in read_csv(oct_fix)
                                if r["verdict"] in ("use_alt", "use_oct")})


def init_worker():
    load_globals()


# ------------------------------------------------------------------ scoring
def counts(grid, pset, idx, max_s, track_ids=False):
    if not len(idx):
        return 0.0, 0, set()
    t, fb = grid.times(pset.lat[idx], pset.lon[idx])
    hit = t <= max_s
    ids = set(pset.ids[idx[hit & fb]]) if track_ids and pset.ids is not None else set()
    return float(pset.w[idx][hit].sum()), int((hit & fb).sum()), ids


def nearest(grid, pset, idx, max_s):
    if not len(idx):
        return math.inf
    t, _ = grid.times(pset.lat[idx], pset.lon[idx])
    m = t.min() if len(t) else math.inf
    return float(m) if m <= max_s else math.inf


def union_bbox(grids):
    return (min(g.lat_min for g in grids), max(g.lat_max for g in grids),
            min(g.lon_min for g in grids), max(g.lon_max for g in grids))


def summarise(row, name, values, kind):
    a = np.array(values, float)
    if kind == "count":
        row[name] = round(float(np.median(a)), 2)
        row[name + "_p25"] = round(float(np.percentile(a, 25)), 2)
    else:  # time in seconds; inf = more than the cut-off
        med, p75 = np.median(a), np.percentile(a, 75)
        row[name] = "" if not np.isfinite(med) else round(float(med), 1)
        row[name + "_p75"] = "" if not np.isfinite(p75) else round(float(p75), 1)
        row[name + "_n_reached"] = int(np.isfinite(a).sum())


def score(o):
    import shapely
    oid = o["origin_id"]
    d = SURF / oid
    row = {"origin_id": oid, "DAUID": o["DAUID"], "kind": o["kind"], "weight": o["weight"]}
    downtown = bool(shapely.contains_xy(G["downtown"], float(o["lon"]), float(o["lat"])))
    term_default = TERMINAL_DOWNTOWN if downtown else TERMINAL_ELSEWHERE
    row["downtown"] = int(downtown)
    fb_ids = {"groc": set(), "ed": set()}
    fb_n = {"pop": 0, "groc": 0, "ed": 0, "jobs": 0}

    # transit at 30 min
    g30 = [Grid(d / f"am_30_{t}.tif") for t in DEPARTURES]
    bb = union_bbox(g30)
    ib, ig, ie = (G[k].query(*bb) for k in ("blocks", "groc", "ed"))
    pop, groc, ed, area = [], [], [], []
    for g in g30:
        p, n, _ = counts(g, G["blocks"], ib, 1800); pop.append(p); fb_n["pop"] += n
        c, n, s = counts(g, G["groc"], ig, 1800, True); groc.append(c); fb_n["groc"] += n; fb_ids["groc"] |= s
        c, n, s = counts(g, G["ed"], ie, 1800, True); ed.append(c); fb_n["ed"] += n; fb_ids["ed"] |= s
        area.append(g.area_km2(1800))
    summarise(row, "tr30_pop", pop, "count")
    summarise(row, "tr30_groc", groc, "count")
    summarise(row, "tr30_ed", ed, "count")
    summarise(row, "tr30_km2", area, "count")
    edge30 = any(near_edge(g, 1800) for g in g30)
    del g30

    # transit at 60 min
    g60 = [Grid(d / f"am_60_{t}.tif") for t in DEPARTURES]
    bb = union_bbox(g60)
    ij, ig, ie = (G[k].query(*bb) for k in ("jobs", "groc", "ed"))
    jobs, ng, ne = [], [], []
    for g in g60:
        c, n, _ = counts(g, G["jobs"], ij, 3600); jobs.append(c); fb_n["jobs"] += n
        ng.append(nearest(g, G["groc"], ig, 3600))
        ne.append(nearest(g, G["ed"], ie, 3600))
    summarise(row, "tr60_jobs", jobs, "count")
    summarise(row, "tr_near_groc_s", ng, "time")
    summarise(row, "tr_near_ed_s", ne, "time")
    edge60 = any(near_edge(g, 3600) for g in g60)
    del g60

    # transit at 45 min (10% sample)
    if (d / "am_45_0800.tif").exists():
        g45 = [Grid(d / f"am_45_{t}.tif") for t in DEPARTURES]
        bb = union_bbox(g45)
        ib, ig, ie, ij = (G[k].query(*bb) for k in ("blocks", "groc", "ed", "jobs"))
        vals = {k: [] for k in ("pop", "groc", "ed", "jobs", "km2")}
        for g in g45:
            vals["pop"].append(counts(g, G["blocks"], ib, 2700)[0])
            vals["groc"].append(counts(g, G["groc"], ig, 2700)[0])
            vals["ed"].append(counts(g, G["ed"], ie, 2700)[0])
            vals["jobs"].append(counts(g, G["jobs"], ij, 2700)[0])
            vals["km2"].append(g.area_km2(2700))
        for k, v in vals.items():
            summarise(row, f"tr45_{k}", v, "count")
        row["in_45_sample"] = 1
        del g45
    else:
        row["in_45_sample"] = 0

    # car
    car_file = G["car_source"].get(oid, "car_30.tif")
    if not (d / car_file).exists():  # re-run folders only hold car_30 / car_30_alt
        car_file = "car_30.tif"
    row["car_file"] = car_file
    gc = Grid(d / car_file)
    bb = gc.bbox()
    ib, ig, ie = (G[k].query(*bb) for k in ("blocks", "groc", "ed"))
    for case, (f, term) in CAR_CASES.items():
        term = term_default if term is None else term
        budget = (30 - term) * 60 / f
        p, n, _ = counts(gc, G["blocks"], ib, budget)
        c, n2, s2 = counts(gc, G["groc"], ig, budget, case == "main")
        e, n3, s3 = counts(gc, G["ed"], ie, budget, case == "main")
        row[f"car_{case}_pop"] = round(p)
        row[f"car_{case}_groc"] = int(c)
        row[f"car_{case}_ed"] = int(e)
        row[f"car_{case}_km2"] = round(gc.area_km2(budget), 2)
        if case == "main":
            row["car_budget_s"] = round(budget, 1)
            fb_ids["groc"] |= s2
            fb_ids["ed"] |= s3
    edge_car = near_edge(gc, 1800)

    row["edge_car"] = int(edge_car)
    row["edge_tr30"] = int(edge30)
    row["edge_tr60"] = int(edge60)
    for k, v in fb_n.items():
        row[f"fallback_{k}"] = v
    return row, {k: sorted(v) for k, v in fb_ids.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--ids", help="comma-separated origin_ids")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--surf", help="read maps from this folder instead (Phase 4 re-run check)")
    a = ap.parse_args()
    global SURF
    if a.surf:
        SURF = Path(a.surf)
        os.environ["REACH_SURF"] = str(SURF)  # worker processes re-import this module
    origins = read_csv(RESEARCH / "phase2" / "origins_snapped_v2.csv")
    if a.surf:
        origins = [o for o in origins if (SURF / o["origin_id"]).is_dir()]
    missing = [] if a.surf else [o["origin_id"] for o in origins if not (SURF / o["origin_id"] / "_done_v2_am").exists()]
    if missing:
        raise SystemExit(f"{len(missing)} points have no finished maps, e.g. {missing[:3]}")
    if a.ids:
        want = set(a.ids.split(","))
        origins = [o for o in origins if o["origin_id"] in want]
    if a.limit:
        origins = origins[::max(1, len(origins) // a.limit)][:a.limit]
    t0 = time.time()
    rows, fb = [], {"groc": set(), "ed": set()}
    with Pool(a.workers, initializer=init_worker) as pool:
        for i, (row, ids) in enumerate(pool.imap_unordered(score, origins, chunksize=8), 1):
            rows.append(row)
            for k in fb:
                fb[k] |= set(ids[k])
            if i % 500 == 0 or i == len(origins):
                el = time.time() - t0
                print(f"{i}/{len(origins)} points, {el / 60:.1f} min, ~{el / i * (len(origins) - i) / 60:.0f} min left", flush=True)
    rows.sort(key=lambda r: r["origin_id"])
    fields = []
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)
    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    fb_path = Path(a.out).with_name(Path(a.out).stem + "_fallback_destinations.json")
    fb_path.write_text(json.dumps({k: sorted(v) for k, v in fb.items()}, indent=1))
    print(f"wrote {a.out} ({len(rows)} rows) and {fb_path.name}; "
          f"destinations that needed the 200 m rule: grocery {len(fb['groc'])}, ED {len(fb['ed'])}")


if __name__ == "__main__":
    main()
