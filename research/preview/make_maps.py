"""Draw the preview maps as one self-contained HTML file (inline SVG, no internet)."""
import csv
from pathlib import Path

import geopandas as gpd

HERE = Path(__file__).resolve().parent
OUT = HERE / "preview_maps.html"
W, H = 720, 560

TRANSIT_COLORS = ["#f7f4d8", "#d9e8a8", "#9fd07f", "#5fb373", "#2c8a6d", "#14615c"]
RATIO_COLORS = ["#fde8d4", "#fbc6a4", "#f79b74", "#e86d4d", "#c94434", "#8f2320"]


def nice(v):
    """Round a break to something a reader can hold in their head."""
    if v >= 100:
        return int(round(v / 10) * 10)
    if v >= 20:
        return int(round(v / 5) * 5)
    return round(v, 1) if v < 10 else int(round(v))


def quantile_breaks(values, n=6):
    """Breaks at equal counts, so each colour holds a sixth of the neighbourhoods."""
    vs = sorted(values)
    out = []
    for i in range(1, n):
        b = nice(vs[int(len(vs) * i / n)])
        if not out or b > out[-1]:
            out.append(b)
    return out
MISSING = "#e6e6e6"
LABELS = [("Toronto", 43.653, -79.383), ("Mississauga", 43.589, -79.644), ("Brampton", 43.685, -79.760),
          ("Markham", 43.856, -79.337), ("Oshawa", 43.897, -78.865), ("Oakville", 43.447, -79.667),
          ("Newmarket", 44.050, -79.461)]


def klass(v, breaks):
    if v == "" or v is None:
        return None
    v = float(v)
    for i, b in enumerate(breaks):
        if v < b:
            return i
    return len(breaks)


def main():
    da = gpd.read_file(HERE.parent / "data" / "census" / "da_gta.gpkg")[["DAUID", "geometry"]]
    vals = {r["DAUID"]: r for r in csv.DictReader(open(HERE / "da_preview.csv"))}
    da = da.to_crs(3857)
    da["geometry"] = da.geometry.simplify(120)
    minx, miny, maxx, maxy = da.total_bounds
    sx = (W - 20) / (maxx - minx); sy = (H - 60) / (maxy - miny)
    s = min(sx, sy)
    ox, oy = 10 + ((W - 20) - (maxx - minx) * s) / 2, 40 + ((H - 60) - (maxy - miny) * s) / 2

    def pt(x, y):
        return f"{(x - minx) * s + ox:.1f},{(maxy - y) * s + oy:.1f}"

    def path(geom):
        parts = geom.geoms if geom.geom_type == "MultiPolygon" else [geom]
        d = []
        for p in parts:
            for ring in [p.exterior] + list(p.interiors):
                c = list(ring.coords)
                if len(c) < 3:
                    continue
                d.append("M" + " L".join(pt(x, y) for x, y in c) + " Z")
        return "".join(d)

    paths = [(r.DAUID, path(r.geometry)) for r in da.itertuples() if not r.geometry.is_empty]

    def svg(column, breaks, colors, title, unit):
        body = [f'<svg viewBox="0 0 {W} {H}" width="100%" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{title}">',
                f'<rect width="{W}" height="{H}" fill="#fbfbfa"/>',
                f'<text x="14" y="24" font-size="15" font-weight="600" fill="#1d1d1f">{title}</text>']
        for dauid, d in paths:
            v = vals.get(dauid, {}).get(column, "")
            k = klass(v, breaks)
            fill = MISSING if k is None else colors[k]
            body.append(f'<path d="{d}" fill="{fill}" stroke="{fill}" stroke-width="0.3"/>')
        for name, lat, lon in LABELS:
            p = gpd.GeoSeries.from_xy([lon], [lat], crs=4326).to_crs(3857).iloc[0]
            body.append(f'<text x="{(p.x - minx) * s + ox:.0f}" y="{(maxy - p.y) * s + oy:.0f}" font-size="10" '
                        f'fill="#1d1d1f" stroke="#ffffff" stroke-width="2.5" paint-order="stroke" '
                        f'text-anchor="middle">{name}</text>')
        # legend
        lx, ly = 14, H - 26
        edges = ["0"] + [str(b) for b in breaks] + [""]
        for i, c in enumerate(colors):
            body.append(f'<rect x="{lx + i * 74}" y="{ly}" width="70" height="11" fill="{c}"/>')
            lo, hi = edges[i], edges[i + 1]
            label = f"{lo} to {hi}" if hi else f"{lo}+"
            body.append(f'<text x="{lx + i * 74}" y="{ly + 23}" font-size="10" fill="#4a4a4a">{label}</text>')
        body.append(f'<text x="{lx + len(colors) * 74 + 6}" y="{ly + 9}" font-size="10" fill="#4a4a4a">{unit}</text>')
        body.append("</svg>")
        return "".join(body)

    t_breaks = quantile_breaks([float(v["transit30_km2"]) for v in vals.values()])
    r_breaks = quantile_breaks([float(v["car_over_transit"]) for v in vals.values() if v["car_over_transit"] != ""])
    print("transit breaks:", t_breaks, "| ratio breaks:", r_breaks)
    m1 = svg("transit30_km2", t_breaks, TRANSIT_COLORS,
             "How much area you can reach in 30 minutes by transit, weekday 8:00 AM", "km2")
    m2 = svg("car_over_transit", r_breaks, RATIO_COLORS,
             "How many times more area a car reaches in the same 30 minutes", "times")

    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>GTA transit reach preview</title>
<style>
body{{margin:0;background:#f2f2ef;color:#1d1d1f;font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
main{{max-width:1500px;margin:0 auto;padding:24px}}
h1{{font-size:24px;margin:0 0 4px}}
p.sub{{color:#6e6e73;margin:0 0 20px;font-size:14px}}
.maps{{display:grid;grid-template-columns:repeat(auto-fit,minmax(460px,1fr));gap:18px}}
.card{{background:#fff;border:1px solid #e3e3e0;border-radius:12px;padding:10px}}
.note{{background:#fff;border:1px solid #e3e3e0;border-radius:12px;padding:14px 18px;margin-top:18px;font-size:14px}}
table{{border-collapse:collapse;margin-top:8px}}td,th{{text-align:left;padding:3px 18px 3px 0;font-size:14px}}
</style></head><body><main>
<h1>What the overnight run produced</h1>
<p class="sub">13,460 starting points, 382,252 travel-time maps, weekday Tuesday 22 September 2026.
Preview only: these maps use a single 8:00 AM departure, while the study uses the middle of 13 departures,
and the car side here has no traffic factor or parking time yet.</p>
<div class="maps">
<div class="card">{m1}</div>
<div class="card">{m2}</div>
</div>
<div class="note">
<b>How to read these.</b> Left: darker green means more of the region is within 30 minutes by transit.
Right: darker red means driving covers far more ground than transit does in the same 30 minutes.
Grey means no result for that neighbourhood.
<table>
<tr><th>Typical neighbourhood</th><th>Value</th></tr>
<tr><td>Area reachable in 30 minutes by transit</td><td>16.8 km2</td></tr>
<tr><td>Area reachable in 60 minutes by transit</td><td>172 km2</td></tr>
<tr><td>Area reachable in 30 minutes by car</td><td>964 km2</td></tr>
<tr><td>Car area divided by transit area</td><td>58 times</td></tr>
<tr><td>Best tenth of neighbourhoods</td><td>under 27 times</td></tr>
<tr><td>Worst tenth of neighbourhoods</td><td>over 120 times</td></tr>
</table>
</div>
</main></body></html>"""
    OUT.write_text(html)
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
