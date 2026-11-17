"""Step 5: one-file version of the interactive report.

Puts the page, its script, its data and the methods appendix into a single
HTML file that opens by double-click (no server). The map library and fonts
load from the web, like the map tiles do, so it needs an internet connection.

Run: python3 research/phase5/build_standalone.py
Writes research/phase5/GTA-Transit-Access-interactive.html
"""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE / "report"
MAPLIBRE = "https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl"

html = (R / "index.html").read_text()
data = {f"data/{n}": json.loads((R / "data" / n).read_text())
        for n in ["summary.json", "stories.json", "da.geojson", "story_outlines.geojson", "eds.geojson"]}
data["methods"] = (R / "methods.html").read_text()
blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")

html, n = re.subn(r"<!--MAPLIBRE-->.*?<!--/MAPLIBRE-->",
                  f'<link href="{MAPLIBRE}.css" rel="stylesheet">\n<script src="{MAPLIBRE}.js"></script>', html, flags=re.S)
assert n == 1
assert "<!--DATA-->" in html
html = html.replace("<!--DATA-->", "<script>window.REPORT_DATA = " + blob + ";</script>")
js = (R / "report.js").read_text()
html, n = re.subn(r'<script src="report\.js[^"]*"></script>', lambda m: "<script>\n" + js + "\n</script>", html)
assert n == 1
html = html.replace('href="methods.html"', 'href="#appendix"').replace("are on a separate page.", "are at the end of this page.")
html = html.replace(".appendix h1 { font-size: 40pt; margin: 0 0 8px; break-before: page; }",
                    ".appendix h1 { font-size: 40pt; margin: 70px 0 8px; break-before: page; }")
out = HERE / "GTA-Transit-Access-interactive.html"
out.write_text(html)
print(out, round(out.stat().st_size / 1e6, 1), "MB")
