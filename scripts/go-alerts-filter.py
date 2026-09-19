"""Filter the GO/Metrolinx GTFS-Realtime service alerts feed for OTP.

Metrolinx emits EntitySelectors that carry explicitly-present but EMPTY
agency_id and route_id fields next to a perfectly good stop_id (and, on
route alerts, an empty stop_id next to a good route_id). OTP 2.9 builds a
FeedScopedId from whatever fields are present, an empty one fails
StringUtils.assertHasValue, and the exception aborts the WHOLE alerts batch
for that feed on every polling cycle:

    ERROR Error while running graph writer GtfsRealtimeAlertsUpdater
    java.lang.IllegalArgumentException: Missing mandatory id on FeedScopeId

Measured on 2026-09-19: the feed carried 55 alerts with 128 empty ids across
85 informed_entity selectors, and the engine held ZERO GO alerts while TTC
(12) and MiWay (39) arrived normally. Elevator outages, accessibility ramp
failures and stop relocations at GO stations were all silently missing.

Every selector in that sample was usable once the empty fields were removed,
so this strips ONLY the zero-length id strings. No alert and no selector is
dropped, and nothing else in the message is touched or re-ordered.

With no arguments, loops forever, rewriting the output every 50 seconds;
point an alerts updater at it with a file: URL. With --once, runs a single
fetch and exits. --probe reports what it would strip and changes nothing.

Standard library only: the protobuf wire format is walked by hand, the same
way ttc-rt-filter.py does, because this project has no pip packages.
"""
import os
import sys
import tempfile
import time
import urllib.request

FEED_URL = ("https://api.openmetrolinx.com/OpenDataAPI/api/V1/Gtfs.proto"
            "/Feed/Alerts")
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "go-alerts-filtered.pb")
REFRESH_SECONDS = 50

# Wire-format field numbers, from gtfs-realtime.proto.
F_ENTITY = 2          # FeedMessage.entity
F_ALERT = 5           # FeedEntity.alert
F_INFORMED = 5        # Alert.informed_entity
SELECTOR_IDS = {1, 2, 5}      # EntitySelector agency_id, route_id, stop_id
F_TRIP = 4                    # EntitySelector.trip
TRIP_IDS = {1, 5}             # TripDescriptor trip_id, route_id

stripped = 0


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
    """Yield (field_no, wire_type, raw_value) for one message."""
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


def clean_trip(buf):
    global stripped
    out = bytearray()
    for fn, wt, val in walk(buf):
        if fn in TRIP_IDS and wt == 2 and len(val) == 0:
            stripped += 1
            continue
        out += emit(fn, wt, val)
    return bytes(out)


def clean_selector(buf):
    global stripped
    out = bytearray()
    for fn, wt, val in walk(buf):
        if fn in SELECTOR_IDS and wt == 2 and len(val) == 0:
            stripped += 1
            continue
        if fn == F_TRIP and wt == 2:
            out += emit(fn, wt, clean_trip(val))
            continue
        out += emit(fn, wt, val)
    return bytes(out)


def clean_alert(buf):
    out = bytearray()
    for fn, wt, val in walk(buf):
        if fn == F_INFORMED and wt == 2:
            out += emit(fn, wt, clean_selector(val))
            continue
        out += emit(fn, wt, val)
    return bytes(out)


def clean_entity(buf):
    out = bytearray()
    for fn, wt, val in walk(buf):
        if fn == F_ALERT and wt == 2:
            out += emit(fn, wt, clean_alert(val))
            continue
        out += emit(fn, wt, val)
    return bytes(out)


def clean_feed(raw):
    out = bytearray()
    for fn, wt, val in walk(raw):
        if fn == F_ENTITY and wt == 2:
            out += emit(fn, wt, clean_entity(val))
            continue
        out += emit(fn, wt, val)
    return bytes(out)


def key():
    """The Metrolinx key lives in metrolinx.env, which is not committed."""
    env = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "metrolinx.env")
    if os.path.exists(env):
        with open(env) as fh:
            for line in fh:
                if "=" in line and "KEY" in line.split("=")[0].upper():
                    return line.split("=", 1)[1].strip().strip('"\'')
    return os.environ.get("METROLINX_KEY", "")


def once(probe=False):
    global stripped
    stripped = 0
    url = FEED_URL + "?key=" + key()
    raw = urllib.request.urlopen(url, timeout=30).read()
    cleaned = clean_feed(raw)
    alerts = sum(1 for fn, wt, _ in walk(raw) if fn == F_ENTITY and wt == 2)
    if probe:
        print(f"{alerts} alerts, {stripped} empty ids would be stripped, "
              f"{len(raw)} bytes in, {len(cleaned)} out")
        return
    # atomic: OTP may be reading the old file at any moment
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(OUT), suffix=".tmp")
    with os.fdopen(fd, "wb") as fh:
        fh.write(cleaned)
    os.replace(tmp, OUT)
    print(f"{alerts} alerts, stripped {stripped} empty ids -> {OUT}")


def main():
    if "--probe" in sys.argv:
        once(probe=True)
        return
    if "--once" in sys.argv:
        once()
        return
    while True:
        try:
            once()
        except Exception as e:
            print(f"go-alerts-filter: {e}", file=sys.stderr)
        time.sleep(REFRESH_SECONDS)


if __name__ == "__main__":
    main()
