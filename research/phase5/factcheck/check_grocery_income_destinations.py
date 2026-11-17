import pandas as pd, numpy as np, glob, os
da = pd.read_csv("phase3/da_scores.csv", dtype={"DAUID": str}); w = da.pop2021
pt = pd.read_csv("phase3/points_scores.csv", dtype={"DAUID": str, "origin_id": str})
print("points", len(pt), pt.kind.value_counts().to_dict(), "weight sum", pt.weight.sum(), "in45", int(pt.in_45_sample.sum()))
print("point-level: people at points with tr30_groc==0:", int(pt.weight[pt.tr30_groc == 0].sum()), " <0.5:", int(pt.weight[pt.tr30_groc < 0.5].sum()))
reg = da.set_index("DAUID").CDNAME
z = pt[pt.tr30_groc == 0]; print("  by region", z.groupby(z.DAUID.map(reg)).weight.sum().to_dict())
print("DA <0.5 by region", da[da.tr30_groc < 0.5].groupby("CDNAME").pop2021.sum().to_dict())
print("point-level ED >60 (NaN near_ed):", int(pt.weight[pt.tr_near_ed_s.isna()].sum()), " groc >60:", int(pt.weight[pt.tr_near_groc_s.isna()].sum()))
# low-income persons estimate
li = da.lim_at_pct / 100 * w
ok = da.lim_at_pct.notna()
print("\nest. low-income persons", int(li.sum()), "by transit class", (li.groupby(da.acc_transit_pop30).sum() / li.sum()).round(3).to_dict())
print("low-income persons by region share", (li.groupby(da.CDNAME).sum() / li.sum()).round(3).to_dict(), " pop share", (w.groupby(da.CDNAME).sum() / w.sum()).round(3).to_dict())
hi = da[da.need_class == 3]
print("high-LI-third residents by region share", (hi.groupby("CDNAME").pop2021.sum() / hi.pop2021.sum()).round(3).to_dict())
print("best transit third by region", (da[da.acc_transit_pop30 == 3].groupby("CDNAME").pop2021.sum() / w[da.acc_transit_pop30 == 3].sum()).round(3).to_dict())
print("low-income persons in the high-LI/worst-transit cell:", int(li[(da.need_class == 3) & (da.acc_transit_pop30 == 1)].sum()))
# destinations
for f in ["data/healthcare/healthcare_gta.csv", "data/buffer/ed_buffer.csv"]:
    d = pd.read_csv(f); print(f, len(d), d["type"].value_counts().to_dict() if "type" in d else "")
for f in glob.glob("data/grocery/grocery_gta_v1*") + glob.glob("data/buffer/groc*"):
    try: print(f, len(pd.read_csv(f)))
    except Exception as e: print(f, "ERR", e)
# stable classes for jobs cell
c = da[(da.need_class == 3) & (da.acc_jobs60 == 1)]; print("jobs cell", int(c.pop2021.sum()), int(c.pop2021[c.stable_jobs60 == 1].sum()))
print("downtown points", int(pt.downtown.sum()))
