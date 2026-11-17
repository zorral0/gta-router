import pandas as pd, numpy as np, json
da = pd.read_csv("phase3/da_scores.csv", dtype={"DAUID": str})
w = da.pop2021
def wmed(v, w):
    m = v.notna() & w.notna()
    v, w = v[m].to_numpy(), w[m].to_numpy()
    o = np.argsort(v); v, w = v[o], w[o]; c = np.cumsum(w)
    return v[np.searchsorted(c, c[-1] / 2)]
print("DAs", len(da), "people", int(w.sum()))
for col in ["tr30_pop", "car_main_pop", "mag_pop", "tr60_jobs"]:
    print("GTA wmed", col, wmed(da[col], w))
# near times: over60 treated how?
for col in ["tr_near_groc_min", "tr_near_ed_min"]:
    v = da[col]
    print(col, "NaN:", v.isna().sum(), "max", v.max(), "wmed dropna", wmed(v, w), "wmed fill61", wmed(v.fillna(61), w),
          "over60 people", int(w[da[col + "_over60"] == 1].sum()), "nan people", int(w[v.isna()].sum()))
print("\nby region")
for reg, g in da.groupby("CDNAME"):
    print(reg, int(g.pop2021.sum()), wmed(g.tr30_pop, g.pop2021), wmed(g.car_main_pop, g.pop2021), wmed(g.tr60_jobs, g.pop2021),
          round(wmed(g.tr_near_groc_min.fillna(61), g.pop2021), 2), round(wmed(g.tr_near_ed_min.fillna(61), g.pop2021), 2),
          int(g.pop2021[g.tr_near_ed_min_over60 == 1].sum()), "mag", round(wmed(g.mag_pop, g.pop2021), 3),
          "max jobs", int(g.tr60_jobs.max()), "DAs>=200k jobs", int((g.tr60_jobs >= 200000).sum()), "of", len(g))
print("\nno groc in 30:", int(w[da.tr30_groc == 0].sum()), "| <0.5:", int(w[da.tr30_groc < 0.5].sum()),
      "| by region", da[da.tr30_groc == 0].groupby("CDNAME").pop2021.sum().to_dict())
print("near groc >30min people:", int(w[(da.tr_near_groc_min > 30) | (da.tr_near_groc_min_over60 == 1)].sum()),
      da[(da.tr_near_groc_min > 30) | (da.tr_near_groc_min_over60 == 1)].groupby("CDNAME").pop2021.sum().to_dict())
print("groc >60:", int(w[da.tr_near_groc_min_over60 == 1].sum()))
# headline class
hi = da[da.need_class == 3]
print("\nhigh low-income third people", int(hi.pop2021.sum()))
print(hi.groupby("acc_transit_pop30").pop2021.sum().to_dict())
cell = da[(da.need_class == 3) & (da.acc_transit_pop30 == 1)]
print("cell people", int(cell.pop2021.sum()), "stable", int(cell.pop2021[cell.stable_transit_pop30 == 1].sum()))
print("by muni (all):"); print(cell.groupby("CSDNAME").pop2021.sum().sort_values(ascending=False).head(10))
print("by muni (stable):"); print(cell[cell.stable_transit_pop30 == 1].groupby("CSDNAME").pop2021.sum().sort_values(ascending=False).head(10))
print("by region (all):", cell.groupby("CDNAME").pop2021.sum().to_dict())
print("by region (stable):", cell[cell.stable_transit_pop30 == 1].groupby("CDNAME").pop2021.sum().to_dict())
print("\nno income DAs", int(da.lim_at_pct.isna().sum()), int(w[da.lim_at_pct.isna()].sum()), "need_class NaN", int(da.need_class.isna().sum()))
print("big DAs n_points>1:", int((da.n_points > 1).sum()), int(w[da.n_points > 1].sum()), "points", int(da.n_points[da.n_points > 1].sum()), "total pts", int(da.n_points.sum()))
print(">2km2:", int((da.landarea_km2 > 2).sum()), int(w[da.landarea_km2 > 2].sum()))
b = da[da.CSDNAME == "Brampton"]
print("\nBrampton", int(b.pop2021.sum()), int(b.pop2021[b.tr_near_ed_min_over60 == 1].sum()), b.pop2021[b.tr_near_ed_min_over60 == 1].sum() / b.pop2021.sum())
ns = pd.read_csv("phase5/da_no_stop.csv", dtype={"DAUID": str})
print("no stop DAs", int(ns.no_stop.sum()), int(ns["pop"][ns.no_stop == 1].sum()), "rows", len(ns))
m = da.merge(ns, on="DAUID")
print("no stop merged w/ scored", int(m.no_stop.sum()), int(m.pop2021[m.no_stop == 1].sum()))
print("faded (<150/km2) DAs", int((da.density_per_km2 < 150).sum()))
print("terciles check: need classes people", da.groupby("need_class").pop2021.sum().to_dict())
print("acc_transit classes people", da.groupby("acc_transit_pop30").pop2021.sum().to_dict())
# ratio stats
print("ratio median car/transit:", wmed(da.car_main_pop, w) / wmed(da.tr30_pop, w), " wmed of ratios", wmed(da.car_over_transit_pop.replace(np.inf, np.nan), w))
# stories
st = json.load(open("phase5/report/data/stories.json"))
for k in ("oshawa", "kerr"):
    s = da[da.DAUID.isin(st[k]["dauids"])]
    print(k, int(s.pop2021.sum()), round(np.average(s.lim_at_pct, weights=s.pop2021), 1), round(np.average(s.tr60_jobs, weights=s.pop2021)), "wmed jobs", wmed(s.tr60_jobs, s.pop2021),
          "ED med", np.nanmedian(s.tr_near_ed_min), "ED wmed", wmed(s.tr_near_ed_min, s.pop2021), "classes", s.need_class.tolist(), s.acc_jobs60.tolist(), s.acc_transit_pop30.tolist())
