"""Filter the Durham Region Transit GTFS-Realtime trip updates feed for OTP.

DRT sends stop_time_updates for stops that are not on the trip. Measured
2026-09-19 on trip 3003__461032_Timetable_-_2026-09, which has 49 stops:

    [42] seq=50..53   stops 719-722, not on this trip at all
    [46] seq=43       back to the real stops, so the sequence goes BACKWARDS

OTP sees a stop_sequence that both references unknown stops and stops
increasing, reports INVALID_STOP_SEQUENCE and drops the WHOLE trip. About 30
trips a cycle failed that way, roughly 22% of the feed, so those buses stayed
on scheduled times with no sign anything was wrong.

Removing the phantom updates leaves 1..42 followed by 43..49: strictly
increasing and valid. Nothing real is lost, because the dropped updates refer
to stops the trip does not serve.

Which sequences are real is read from the static feed itself
(engine/drt-gtfs.zip), so this stays correct across schedule changes. Re-run
it after refresh.sh replaces that zip.

Note the User-Agent: DRT's endpoint answers a bare urllib request with
403 Forbidden.

With no arguments, loops forever, rewriting the output every 50 seconds;
point a stop-time-updater at it with a file: URL. With --once, a single pass.
--probe reports what it would drop and changes nothing.

Standard library only. The protobuf wire format is walked by hand, the same
way go-alerts-filter.py and ttc-rt-filter.py do it.
"""
import collections
import csv
import io
import os
import sys
import tempfile
import time
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEED_URL = "https://drtonline.durhamregiontransit.com/gtfsrealtime/TripUpdates"
STATIC_ZIP = os.path.join(ROOT, "engine", "drt-gtfs.zip")
OUT = os.path.join(ROOT, "drt-rt-filtered.pb")
REFRESH_SECONDS = 50
UA = {"User-Agent": "OpenTripPlanner/2.9.0"}

F_ENTITY = 2          # FeedMessage.entity
F_TRIP_UPDATE = 3     # FeedEntity.trip_update
F_TRIP = 1            # TripUpdate.trip
F_STOP_TIME_UPDATE = 2  # TripUpdate.stop_time_update
F_TRIP_ID = 1         # TripDescriptor.trip_id
F_STOP_SEQUENCE = 1   # StopTimeUpdate.stop_sequence

dropped = 0


def read_varint(buf, i):
    v = shift = 0
    while True:
        b = buf[i]
        i += 1
        v |= (b & 0x7F) << shift
        if not b & 0x80:
            return v, i
        shift += 7


def write_varint(v):
    out = bytearray()
    while True:
        b = v & 0x7F
        v >>= 7
        out.append(b | (0x80 if v else 0))
        if not v:
            return bytes(out)


def walk(buf):
    i, n = 0, len(buf)
    while i < n:
        tag, i = read_varint(buf, i)
        fn, wt = tag >> 3, tag & 7
        if wt == 0:
            v, i = read_varint(buf, i)
            yield fn, wt, v
        elif wt == 2:
            ln, i = read_varint(buf, i)
            yield fn, wt, buf[i:i + ln]
            i += ln
        elif wt == 5:
            yield fn, wt, buf[i:i + 4]
            i += 4
        elif wt == 1:
            yield fn, wt, buf[i:i + 8]
            i += 8
        else:
            raise ValueError(f"unsupported wire type {wt}")


def emit(fn, wt, val):
    tag = write_varint((fn << 3) | wt)
    if wt == 0:
        return tag + write_varint(val)
    if wt == 2:
        return tag + write_varint(len(val)) + val
    return tag + val


def load_valid_sequences():
    """trip_id -> the set of stop_sequence values that trip really has."""
    valid = collections.defaultdict(set)
    with zipfile.ZipFile(STATIC_ZIP) as zf:
        with zf.open("stop_times.txt") as fh:
            for row in csv.DictReader(io.TextIOWrapper(fh, "utf-8-sig")):
                valid[row["trip_id"]].add(int(row["stop_sequence"]))
    return valid


def trip_id_of(trip_update):
    for fn, wt, val in walk(trip_update):
        if fn == F_TRIP and wt == 2:
            for a, w, v in walk(val):
                if a == F_TRIP_ID and w == 2:
                    return v.decode("utf-8", "replace")
    return None


def sequence_of(stop_time_update):
    for fn, wt, val in walk(stop_time_update):
        if fn == F_STOP_SEQUENCE and wt == 0:
            return val
    return None


def clean_trip_update(buf, valid):
    """Drop stop_time_updates whose stop_sequence is not on this trip."""
    global dropped
    tid = trip_id_of(buf)
    allowed = valid.get(tid)
    if not allowed:
        # unknown trip: leave it exactly as it came, OTP will judge it
        return buf
    out = bytearray()
    for fn, wt, val in walk(buf):
        if fn == F_STOP_TIME_UPDATE and wt == 2:
            seq = sequence_of(val)
            # no stop_sequence at all means the update is keyed by stop_id,
            # which this feed does not do, but do not silently eat it
            if seq is not None and seq not in allowed:
                dropped += 1
                continue
        out += emit(fn, wt, val)
    return bytes(out)


def clean_entity(buf, valid):
    out = bytearray()
    for fn, wt, val in walk(buf):
        if fn == F_TRIP_UPDATE and wt == 2:
            out += emit(fn, wt, clean_trip_update(val, valid))
            continue
        out += emit(fn, wt, val)
    return bytes(out)


def clean_feed(raw, valid):
    out = bytearray()
    for fn, wt, val in walk(raw):
        if fn == F_ENTITY and wt == 2:
            out += emit(fn, wt, clean_entity(val, valid))
            continue
        out += emit(fn, wt, val)
    return bytes(out)


def once(valid, probe=False):
    global dropped
    dropped = 0
    req = urllib.request.Request(FEED_URL, headers=UA)
    raw = urllib.request.urlopen(req, timeout=30).read()
    cleaned = clean_feed(raw, valid)
    trips = sum(1 for fn, wt, _ in walk(raw) if fn == F_ENTITY and wt == 2)
    if probe:
        print(f"{trips} trips, {dropped} phantom stop updates would be dropped, "
              f"{len(raw)} bytes in, {len(cleaned)} out")
        return
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(OUT), suffix=".tmp")
    with os.fdopen(fd, "wb") as fh:
        fh.write(cleaned)
    os.replace(tmp, OUT)
    print(f"{trips} trips, dropped {dropped} phantom stop updates -> {OUT}")


def main():
    valid = load_valid_sequences()
    if "--probe" in sys.argv:
        once(valid, probe=True)
        return
    if "--once" in sys.argv:
        once(valid)
        return
    while True:
        try:
            once(valid)
        except Exception as e:
            print(f"drt-rt-filter: {e}", file=sys.stderr)
        time.sleep(REFRESH_SECONDS)


if __name__ == "__main__":
    main()
