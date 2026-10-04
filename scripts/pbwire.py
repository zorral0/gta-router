"""Just enough of the protobuf wire format to rewrite GTFS-Realtime feeds.

Shared by go-alerts-filter.py and drt-rt-filter.py. This project has no pip
packages, so instead of the protobuf library the filters walk the raw bytes:
split a message into (field number, wire type, value), keep or change what
they need, and write the rest back out untouched.
"""


def read_varint(buf, i):
    """Decode the varint starting at buf[i]; return (value, next index)."""
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
    """Encode one field back to bytes; the inverse of one walk() step."""
    tag = write_varint((fn << 3) | wt)
    if wt == 0:
        return tag + write_varint(val)
    if wt == 2:
        return tag + write_varint(len(val)) + val
    return tag + val
