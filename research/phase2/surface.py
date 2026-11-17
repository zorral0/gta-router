"""Read OTP /otp/traveltime/surface GeoTIFFs without rasterio.

The reach engine returns a small GeoTIFF: int32 travel seconds, LZW
compressed, EPSG:4326, a ~200 m grid, nodata = -2147483648 (cells the
search never reached). This module decodes it in pure Python (~4 ms each).

    from surface import read_surface, area_km2
    w, h, values, t = read_surface("surfaces/35180017/car.tif")
    area_km2("surfaces/35180017/car.tif", 1800)
"""
import array
import math
import struct
import sys
from collections import namedtuple

NODATA = -2147483648
TIFF_MAGIC = (b"II*\x00", b"MM\x00*")

# origin_x/origin_y: lon/lat of the top-left corner of the top-left cell.
# cell_x is positive degrees of longitude, cell_y is negative degrees of latitude.
Transform = namedtuple("Transform", "origin_x origin_y cell_x cell_y")

_TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 16: 8}
_TYPE_FMT = {1: "B", 3: "H", 4: "I", 6: "b", 8: "h", 9: "i", 11: "f", 12: "d", 16: "Q"}


def is_valid_tiff(path, min_bytes=200):
    """Cheap check used for resume: TIFF magic bytes and a non-trivial size."""
    try:
        with open(path, "rb") as f:
            head = f.read(4)
            f.seek(0, 2)
            size = f.tell()
    except OSError:
        return False
    return head in TIFF_MAGIC and size >= min_bytes


def _read_tags(b):
    e = "<" if b[:2] == b"II" else ">"
    off = struct.unpack(e + "I", b[4:8])[0]
    n = struct.unpack(e + "H", b[off:off + 2])[0]
    tags = {}
    for i in range(n):
        base = off + 2 + 12 * i
        tag, typ, cnt = struct.unpack(e + "HHI", b[base:base + 8])
        size = _TYPE_SIZE.get(typ, 1) * cnt
        raw = b[base + 8:base + 12]
        if size > 4:
            ptr = struct.unpack(e + "I", raw)[0]
            raw = b[ptr:ptr + size]
        if typ in (2, 7):
            tags[tag] = raw[:cnt].rstrip(b"\x00").decode("latin-1") if typ == 2 else raw[:cnt]
        elif typ in (5, 10):
            v = struct.unpack(e + "%d%s" % (2 * cnt, "I" if typ == 5 else "i"), raw[:size])
            tags[tag] = [v[j] / v[j + 1] if v[j + 1] else 0.0 for j in range(0, len(v), 2)]
        else:
            v = struct.unpack(e + "%d%s" % (cnt, _TYPE_FMT[typ]), raw[:size])
            tags[tag] = v[0] if cnt == 1 else list(v)
    return tags, e


def _as_list(v):
    return v if isinstance(v, list) else [v]


def lzw_decode(data):
    """TIFF-flavour LZW (MSB-first codes, early change)."""
    out = bytearray()
    table = [bytes([i]) for i in range(256)] + [b"", b""]
    prev = b""
    bitpos, nbits, total = 0, 9, len(data) * 8

    def read(nb):
        byte = bitpos // 8
        v = int.from_bytes(data[byte:byte + 4].ljust(4, b"\0"), "big")
        return (v >> (32 - (bitpos % 8) - nb)) & ((1 << nb) - 1)

    while bitpos + nbits <= total:
        code = read(nbits)
        bitpos += nbits
        if code == 257:  # end of information
            break
        if code == 256:  # clear table
            table = table[:258]
            nbits = 9
            if bitpos + nbits > total:
                break
            code = read(nbits)
            bitpos += nbits
            if code == 257:
                break
            prev = table[code]
            out += prev
        else:
            if code < len(table):
                entry = table[code]
                table.append(prev + entry[:1])
            else:
                entry = prev + prev[:1]
                table.append(entry)
            out += entry
            prev = entry
        n = len(table)
        if n == 511:
            nbits = 10
        elif n == 1023:
            nbits = 11
        elif n == 2047:
            nbits = 12
    return bytes(out)


def read_surface(path):
    """Return (width, height, values, transform).

    values is an array.array('i') of width*height travel seconds, row by row
    from the top (north) edge; unreached cells hold NODATA.
    """
    with open(path, "rb") as f:
        b = f.read()
    if b[:4] not in TIFF_MAGIC:
        raise ValueError(f"{path}: not a TIFF")
    tags, e = _read_tags(b)
    w, h = tags[256], tags[257]
    bits, fmt_code = _as_list(tags.get(258, 32))[0], tags.get(339, 1)
    if (bits, fmt_code) != (32, 2):
        raise ValueError(f"{path}: expected int32 samples, got bits={bits} format={fmt_code}")
    if tags.get(317, 1) != 1:
        raise ValueError(f"{path}: TIFF predictor {tags.get(317)} not supported")
    comp = tags.get(259, 1)
    parts = []
    for o, c in zip(_as_list(tags[273]), _as_list(tags[279])):
        chunk = b[o:o + c]
        if comp == 5:
            parts.append(lzw_decode(chunk))
        elif comp == 1:
            parts.append(chunk)
        else:
            raise ValueError(f"{path}: compression {comp} not supported")
    raw = b"".join(parts)
    if len(raw) < w * h * 4:
        raise ValueError(f"{path}: decoded {len(raw)} bytes, need {w * h * 4}")
    values = array.array("i", raw[:w * h * 4])
    if (e == ">") != (sys.byteorder == "big"):
        values.byteswap()

    if 34264 in tags:  # ModelTransformationTag, 4x4 matrix
        m = tags[34264]
        t = Transform(origin_x=m[3], origin_y=m[7], cell_x=m[0], cell_y=m[5])
    else:  # ModelPixelScale + ModelTiepoint
        sx, sy = tags[33550][0], tags[33550][1]
        tp = tags[33922]
        t = Transform(origin_x=tp[3] - tp[0] * sx, origin_y=tp[4] + tp[1] * sy, cell_x=sx, cell_y=-sy)
    return w, h, values, t


def area_km2(surface, max_seconds):
    """Area (km2) of cells reached within max_seconds.

    surface is a path or a (w, h, values, transform) tuple. Cell size is
    computed per row from its latitude, so north and south rows are fair.
    """
    w, h, values, t = read_surface(surface) if isinstance(surface, (str, bytes)) or hasattr(surface, "__fspath__") else surface
    cell_h_m = abs(t.cell_y) * 110574.0
    total = 0.0
    for r in range(h):
        row = values[r * w:(r + 1) * w]
        n = sum(1 for x in row if 0 <= x <= max_seconds)
        if n:
            lat = t.origin_y + (r + 0.5) * t.cell_y
            total += n * abs(t.cell_x) * 111320.0 * math.cos(math.radians(lat)) * cell_h_m
    return total / 1e6
