"""Secondary need indicators by DA: share aged 65+, share of recent immigrants.

Reads the same 2021 Census Profile as build_census.py (whose parser it reuses)
and writes da_need_extra.csv. Kept separate so da_profile.csv is untouched.

  pct_65plus        65 years and over / total age groups (100% data)
  pct_recent_imm    immigrated 2016 to 2021 / total immigrant status
                    (population in private households, 25% sample)

Run: research/.venv/bin/python research/data/census/build_need_extra.py
"""
import csv
import os

import build_census as bc

EXTRA_IDS = {8: "age_total", 24: "age_65plus", 1527: "imm_total", 1536: "imm_2016_2021"}


def main():
    bc.CHAR_IDS = EXTRA_IDS
    data = bc.load_profile_gta(bc.ensure_extracted())
    out = os.path.join(bc.HERE, "da_need_extra.csv")
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["DAUID", "pct_65plus", "pct_recent_imm"])
        for dauid in sorted(data):
            d = data[dauid]
            p65 = (100 * d["age_65plus"] / d["age_total"]) if d.get("age_total") and d.get("age_65plus") is not None else None
            pim = (100 * d["imm_2016_2021"] / d["imm_total"]) if d.get("imm_total") and d.get("imm_2016_2021") is not None else None
            w.writerow([dauid, None if p65 is None else round(p65, 2), None if pim is None else round(pim, 2)])
    print("wrote", out, len(data))


if __name__ == "__main__":
    main()
