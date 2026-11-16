"""Record the live GTFS-Realtime feeds to disk, for the reliability engine.

The feeds only ever show the present, so anything not saved is gone. This
polls each feed on its own timer and keeps the raw bytes exactly as they came,
so a later change to how arrivals are worked out can re-read old recordings.

Saved under recordings/ (not committed):

    feeds/<feed>/<YYYY-MM-DD>/<HH>-<run>.gz   UTC date and hour, one per run
    schedules/<feed>/<YYYY-MM-DD>-<hash>.zip  a copy whenever a schedule changes
    status.json                               the health of every feed

A .gz holds many gzip members, one per snapshot, each "<ms> <length>\\n<bytes>"
where ms is when it was fetched. read_records() reads them back. A hard crash
can cut off the last snapshot of a run, so each run gets its own file and a
later run never appends after a damaged tail.

A snapshot is skipped when everything but the header's timestamp matches the
last one saved; alerts barely change, so this saves a lot.

Metrolinx's key stays out of the saved data and the logs. A feed that fails
waits longer between tries, up to 5 minutes. Saving stops, without stopping the
recorder, when the disk has under 20 GB free.

    python3 scripts/record-feeds.py            record until stopped
    python3 scripts/record-feeds.py --status   show the health of every feed

In the status, PROBLEM means the feed cannot be fetched, and STALE means it
answers but has sent nothing new for hours (stuck on the agency's side).

Standard library only, like the rest of scripts/.
"""
import fcntl
import gzip
import hashlib
import json
import os
import re
import shutil
import signal
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
import zlib

from pbwire import walk  # shared wire-format helpers

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "recordings")
UA = {"User-Agent": "gta-router-recorder/1.0"}
TIMEOUT_SECONDS = 25
MAX_BACKOFF_SECONDS = 300
MIN_FREE_BYTES = 20 * 1024 ** 3
STATUS_SECONDS = 60
# A vehicles or predictions feed that answers but has had nothing new for this
# long is frozen at the source (2026-11-14: Metrolinx served the same 37 GO
# vehicles for two days). Long enough to cover a quiet night with no service.
STALE_SECONDS = 8 * 3600
SCHEDULE_SECONDS = 24 * 3600

# Vehicle locations change about every 30 seconds (measured 2026-11-03 on the
# TTC), so 15 seconds catches nearly every update. Predictions and alerts move
# more slowly and trip updates are the biggest feeds, so they run less often.
VEHICLES, PREDICTIONS, SLOW = 15, 60, 300

TTC = "https://gtfsrt.ttc.ca"
METROLINX = "https://api.openmetrolinx.com/OpenDataAPI/api/V1"
YRT = "https://rtu.york.ca/gtfsrealtime"
MIWAY = "https://www.miapp.ca/GTFS_RT"
DRT = "https://drtonline.durhamregiontransit.com/gtfsrealtime"

# (name, url, seconds between polls). {key} is the Metrolinx key.
FEEDS = [
    ("ttc-vehicles", TTC + "/vehicles/position?format=binary", VEHICLES),
    ("ttc-trips", TTC + "/trips/update?format=binary", PREDICTIONS),
    ("ttc-subway", TTC + "/trips/subway?format=binary", PREDICTIONS),
    ("ttc-detours", TTC + "/trips/detour?format=binary", SLOW),
    ("ttc-alerts", TTC + "/alerts/all?format=binary", SLOW),
    ("go-vehicles", METROLINX + "/Gtfs.proto/Feed/VehiclePosition?key={key}", VEHICLES),
    ("go-trips", METROLINX + "/Gtfs.proto/Feed/TripUpdates?key={key}", PREDICTIONS),
    ("go-alerts", METROLINX + "/Gtfs.proto/Feed/Alerts?key={key}", SLOW),
    ("up-vehicles", METROLINX + "/UP/Gtfs.proto/Feed/VehiclePosition?key={key}", VEHICLES),
    ("up-trips", METROLINX + "/UP/Gtfs.proto/Feed/TripUpdates?key={key}", PREDICTIONS),
    ("yrt-vehicles", YRT + "/VehiclePositions", VEHICLES),
    ("yrt-trips", YRT + "/TripUpdates", PREDICTIONS),
    ("yrt-alerts", YRT + "/ServiceAlerts", SLOW),
    ("miway-vehicles", MIWAY + "/Vehicle/VehiclePositions.pb", VEHICLES),
    ("miway-trips", MIWAY + "/TripUpdate/TripUpdates.pb", PREDICTIONS),
    ("miway-alerts", MIWAY + "/Alerts/Alerts.pb", SLOW),
    ("drt-vehicles", DRT + "/VehiclePositions", VEHICLES),
    ("drt-trips", DRT + "/TripUpdates", PREDICTIONS),
]

# Schedule copies for the agencies recorded above; the live data can only be
# matched against the schedule in effect at the time.
SCHEDULES = ("go", "up", "ttc", "yrt", "miway", "drt")

F_HEADER = 1  # FeedMessage.header
F_ENTITY = 2  # FeedMessage.entity


def metrolinx_key():
    """The Metrolinx key lives in metrolinx.env, which is not committed."""
    env = os.path.join(ROOT, "metrolinx.env")
    if os.path.exists(env):
        with open(env) as fh:
            for line in fh:
                if "=" in line and "KEY" in line.split("=")[0].upper():
                    return line.split("=", 1)[1].strip().strip("\"'")
    return os.environ.get("METROLINX_KEY", "")


def fingerprint(raw):
    """Hash a feed, leaving out its header. Raises if it is not a real feed,
    such as an error page sent with a 200."""
    h = hashlib.sha256()
    header = False
    for fn, wt, val in walk(raw):
        if fn == F_HEADER and wt == 2:
            header = True
        elif fn == F_ENTITY and wt == 2:
            h.update(len(val).to_bytes(4, "big"))
            h.update(val)
        else:
            raise ValueError(f"unexpected field {fn}")
    if not header:
        raise ValueError("no feed header")
    return h.hexdigest()


def record_path(out, name, fetched_at, run_id):
    t = time.gmtime(fetched_at)
    return os.path.join(out, "feeds", name, time.strftime("%Y-%m-%d", t),
                        f"{time.strftime('%H', t)}-{run_id}.gz")


def save_record(path, raw, fetched_at):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    head = f"{int(fetched_at * 1000)} {len(raw)}\n".encode()
    member = gzip.compress(head + raw, mtime=0)
    with open(path, "ab") as fh:
        fh.write(member)
    return len(member)


def read_records(path):
    """Yield (fetched_at_seconds, raw bytes), stopping at a damaged tail.

    Reads member by member: gzip.open reads ahead, so a damaged tail would
    also lose good snapshots just before it."""
    with open(path, "rb") as fh:
        data = fh.read()
    while data:
        member = zlib.decompressobj(wbits=31)
        try:
            body = member.decompress(data)
            if not member.eof:
                return
            head, raw = body.split(b"\n", 1)
            ms, length = head.split()
            if len(raw) != int(length):
                return
        except (zlib.error, ValueError):
            return
        yield int(ms) / 1000, raw
        data = member.unused_data


def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
        return resp.read()


def backoff(interval, fails):
    return min(MAX_BACKOFF_SECONDS, interval * 2 ** min(fails, 10))


def new_state(interval):
    return {"interval": interval, "last_ok": None, "last_saved": None, "ok": 0,
            "saved": 0, "unchanged": 0, "failed": 0, "bytes": 0,
            "fails_in_a_row": 0, "last_error": None, "fingerprint": None}


def poll_once(name, url, state, out, run_id, secret="", fetcher=fetch,
              free_bytes=lambda p: shutil.disk_usage(p).free):
    """One fetch and save. Records any failure in state; never raises."""
    now = time.time()
    try:
        raw = fetcher(url)
        fp = fingerprint(raw)
        state["ok"] += 1
        state["last_ok"] = now
        if fp == state["fingerprint"]:
            state["unchanged"] += 1
        elif free_bytes(out) < MIN_FREE_BYTES:
            raise OSError("disk nearly full, not saving")
        else:
            state["bytes"] += save_record(record_path(out, name, now, run_id), raw, now)
            state["saved"] += 1
            state["last_saved"] = now
            state["fingerprint"] = fp
        state["fails_in_a_row"] = 0
        state["last_error"] = None
    except Exception as e:
        state["failed"] += 1
        state["fails_in_a_row"] += 1
        msg = f"{type(e).__name__}: {e}"
        state["last_error"] = msg.replace(secret, "KEY") if secret else msg


def poll_forever(name, url, state, out, run_id, secret, stop):
    while not stop.is_set():
        started = time.time()
        poll_once(name, url, state, out, run_id, secret)
        wait = state["interval"]
        if state["fails_in_a_row"]:
            wait = backoff(wait, state["fails_in_a_row"])
        stop.wait(max(0, wait - (time.time() - started)))


def schedule_urls():
    """The schedule addresses, from the one list setup.sh and refresh.sh use."""
    with open(os.path.join(ROOT, "scripts", "feeds.sh")) as fh:
        found = re.findall(r'"([a-z]+)-gtfs\.zip (\S+)"', fh.read())
    return [(n, u) for n, u in found if n in SCHEDULES]


def save_schedule(folder, raw, now):
    """Keep this schedule if it differs from the newest copy; returns the path
    saved, or None when nothing changed. Raises if it is not a real GTFS zip."""
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(raw)
        with zipfile.ZipFile(tmp) as zf:
            if "stops.txt" not in zf.namelist():
                raise ValueError("no stops.txt in the zip")
        digest = hashlib.sha256(raw).hexdigest()[:12]
        kept = sorted(f for f in os.listdir(folder) if f.endswith(".zip"))
        if kept and kept[-1].endswith(f"-{digest}.zip"):
            return None
        day = time.strftime("%Y-%m-%d", time.gmtime(now))
        path = os.path.join(folder, f"{day}-{digest}.zip")
        os.replace(tmp, path)
        return path
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def schedules_forever(states, out, stop):
    while not stop.is_set():
        for name, url in schedule_urls():
            if stop.is_set():
                return
            folder = os.path.join(out, "schedules", name)
            marker = os.path.join(folder, "last-checked")
            # a restart must not download every schedule all over again
            if os.path.exists(marker) and time.time() - os.path.getmtime(marker) < SCHEDULE_SECONDS:
                continue
            state = states[f"schedule-{name}"]
            try:
                raw = fetch(url)
                saved = save_schedule(folder, raw, time.time())
                with open(marker, "w"):
                    pass
                state["ok"] += 1
                state["last_ok"] = time.time()
                state["fails_in_a_row"] = 0
                state["last_error"] = None
                if saved:
                    state["saved"] += 1
                    state["last_saved"] = time.time()
                    state["bytes"] += len(raw)
            except Exception as e:
                state["failed"] += 1
                state["fails_in_a_row"] += 1
                state["last_error"] = f"{type(e).__name__}: {e}"
        stop.wait(3600)


def write_status(path, states, started):
    public = {n: {k: v for k, v in s.items() if k != "fingerprint"}
              for n, s in states.items()}
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    with os.fdopen(fd, "w") as fh:
        json.dump({"started": started, "updated": time.time(), "pid": os.getpid(),
                   "feeds": public}, fh, indent=1)
    os.replace(tmp, path)


def feed_health(s, now):
    """A plain verdict on one feed. A feed may be quiet overnight, but a
    fetch should still succeed."""
    if s["last_error"] and (s["fails_in_a_row"] >= 3 or s["last_ok"] is None):
        return "PROBLEM"
    if s["last_ok"] is None:
        return "starting"
    if now - s["last_ok"] > max(600, s["interval"] * 3):
        return "PROBLEM"
    # answering, but the same data every time: the agency's side is stuck.
    # Alerts and schedules really can stay the same for days, so only the
    # fast feeds are judged this way.
    if (s["interval"] <= PREDICTIONS and s["last_saved"] is not None
            and now - s["last_saved"] > STALE_SECONDS):
        return "STALE"
    return "ok"


def show_status(out):
    path = os.path.join(out, "status.json")
    if not os.path.exists(path):
        print("Nothing recorded yet.")
        return 1
    with open(path) as fh:
        st = json.load(fh)
    now = time.time()
    age = now - st["updated"]
    running = age < STATUS_SECONDS * 3
    print(f"Recorder: {'running' if running else 'NOT RUNNING'} "
          f"(last report {age:.0f} sec ago, started "
          f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(st['started']))})")
    used = 0
    for name, s in st["feeds"].items():
        # schedule copies are one-off downloads, so they would skew the rate
        if not name.startswith("schedule-"):
            used += s["bytes"]
        verdict = feed_health(s, st["updated"])
        print(f"  {name:18} {verdict:8} saved {s['saved']:>6}  same {s['unchanged']:>6}  "
              f"failed {s['failed']:>4}  {s['bytes'] / 1024 ** 2:>8.1f} MB"
              + (f"  {s['last_error']}" if s["last_error"] else "")
              + (f"  nothing new since {time.strftime('%b %d %H:%M', time.localtime(s['last_saved']))}"
                 if verdict == "STALE" else ""))
    hours = max((st["updated"] - st["started"]) / 3600, 1 / 60)
    print(f"Live feeds this run: {used / 1024 ** 3:.2f} GB, about {used / hours * 24 / 1024 ** 3:.1f} GB a day. "
          f"Disk free: {shutil.disk_usage(out).free / 1024 ** 3:.0f} GB")
    return 0 if running else 1


def main():
    os.makedirs(OUT, exist_ok=True)
    if "--status" in sys.argv:
        sys.exit(show_status(OUT))

    # one recorder at a time; the lock lets go by itself if this one dies
    lock = open(os.path.join(OUT, "recorder.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("The recorder is already running.")
        return

    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())

    key = metrolinx_key()
    started = time.time()
    run_id = str(int(started))
    states = {}
    threads = []
    for i, (name, url, seconds) in enumerate(FEEDS):
        if "{key}" in url and not key:
            print(f"Skipping {name}: no Metrolinx key in metrolinx.env")
            continue
        states[name] = new_state(seconds)
        args = (name, url.format(key=key) if "{key}" in url else url,
                states[name], OUT, run_id, key, stop)
        threads.append(threading.Thread(target=poll_forever, args=args, daemon=True))
    for name, _ in schedule_urls():
        states[f"schedule-{name}"] = new_state(SCHEDULE_SECONDS)
    threads.append(threading.Thread(target=schedules_forever, args=(states, OUT, stop),
                                    daemon=True))
    for t in threads:
        t.start()
        time.sleep(0.2)  # spread the first requests out

    print(f"Recording {len(FEEDS)} feeds to {OUT}", flush=True)
    status = os.path.join(OUT, "status.json")
    while not stop.is_set():
        write_status(status, states, started)
        stop.wait(STATUS_SECONDS)
    write_status(status, states, started)
    print("Stopped.", flush=True)


if __name__ == "__main__":
    main()
