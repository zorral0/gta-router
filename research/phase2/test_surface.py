"""Tiny test for surface.py. Run:

    research/.venv/bin/python research/phase2/test_surface.py

Decodes one surface saved by run_reach.py if any exist, plus the two sample
surfaces in test_data/ (downtown Union, 2026-09-22 08:00) whose numbers are
pinned so a decoder change that alters results is caught.
"""
import glob
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from surface import NODATA, area_km2, is_valid_tiff, read_surface  # noqa: E402


def check_shape(path):
    t0 = time.perf_counter()
    w, h, v, t = read_surface(path)
    ms = (time.perf_counter() - t0) * 1000
    assert len(v) == w * h, (path, len(v), w * h)
    assert 0.001 < t.cell_x < 0.01 and -0.01 < t.cell_y < -0.001, t  # ~200 m cells in degrees
    assert -81 < t.origin_x < -78 and 42.5 < t.origin_y < 45, t  # GTA-ish
    good = [x for x in v if x != NODATA]
    assert good and min(good) >= 0, path
    return w, h, t, ms


def main():
    car = HERE / "test_data" / "sample_car_30M.tif"
    tr = HERE / "test_data" / "sample_transit_45M.tif"
    for p in (car, tr):
        assert is_valid_tiff(p), p
        w, h, t, ms = check_shape(p)
        print(f"ok  {p.name}: {w}x{h}, {ms:.1f} ms")
    assert read_surface(car)[:2] == (113, 69)
    assert read_surface(tr)[:2] == (231, 115)
    # The car sample came from the raw (footway) downtown point before road
    # snapping, so it is walk-sized: the case the snap and backup-point checks guard against.
    assert abs(area_km2(car, 1800) - 26.20) < 0.05, area_km2(car, 1800)
    assert abs(area_km2(tr, 2700) - 133.03) < 0.05, area_km2(tr, 2700)
    print(f"ok  areas: car<=30min {area_km2(car, 1800):.1f} km2, transit<=45min {area_km2(tr, 2700):.1f} km2")

    saved = sorted(glob.glob(str(HERE / "*surfaces*" / "*" / "*.tif")))
    if saved:
        w, h, t, ms = check_shape(saved[0])
        print(f"ok  saved surface {saved[0]}: {w}x{h}, {ms:.1f} ms")
    else:
        print("note: no saved surfaces yet, only the samples were decoded")
    print("all surface tests passed")


if __name__ == "__main__":
    main()
