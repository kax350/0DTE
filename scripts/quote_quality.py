"""Data audit (no outcomes): NBBO quality of 0DTE puts 0.5-3% OTM at 09:58-10:05 by product/year.

    python scripts/quote_quality.py  -> docs/quote_quality_1000.csv
"""
from __future__ import annotations

import concurrent.futures as cf
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from vrp_ltr.calendar import sessions  # noqa: E402
from vrp_ltr.data import spx_minute  # noqa: E402

TIMES = ["09:58", "09:59", "10:00", "10:01", "10:02", "10:03", "10:05"]
SCALE = {"XSP": 0.1, "SPY": 0.1, "SPXW": 1.0}


def one(args):
    root, day = args
    f = ROOT / "data" / "processed" / root / "chain" / f"{day}.parquet"
    if not f.exists():
        return []
    c = pd.read_parquet(f, columns=["ts", "expiration", "right", "strike", "bid", "ask", "bid_size"])
    c = c[(c["right"] == "P")]
    c = c[pd.to_datetime(c["expiration"]).dt.date == min(pd.to_datetime(c["expiration"]).dt.date)]
    spx = spx_minute.level_asof(pd.Timestamp(f"{day} 10:00", tz="America/New_York"))
    if not spx:
        return []
    S = spx * SCALE[root]
    c = c[c["strike"].between(S * 0.97, S * 0.995)]
    hm = c["ts"].dt.strftime("%H:%M")
    out = []
    for t in TIMES:
        x = c[hm == t]
        if x.empty:
            continue
        ok = (x["bid"] > 0) & (x["ask"] > x["bid"])
        w = (x["ask"] - x["bid"])[ok]
        out.append({"root": root, "day": str(day), "year": day.year, "t": t, "n": len(x), "two_sided": int(ok.sum()),
                    "med_width": float(w.median()) if len(w) else np.nan,
                    "med_bid_size": float(x.loc[ok, "bid_size"].median()) if ok.any() else np.nan})
    return out


def main():
    jobs = [(r, d.date()) for r in ("XSP", "SPY", "SPXW") for d in sessions("2021-01-01", "2026-09-29")]
    rows = []
    with cf.ProcessPoolExecutor(3) as ex:
        for r in ex.map(one, jobs, chunksize=20):
            rows.extend(r)
    df = pd.DataFrame(rows)
    df.to_csv(ROOT / "docs" / "quote_quality_1000.csv", index=False)
    df["bad"] = (df["two_sided"] < 0.7 * df["n"]) | (df["med_width"] > 0.25 * SCALE_W(df))
    g = df.groupby(["root", "year", "t"]).agg(days=("day", "nunique"), med_width=("med_width", "median"),
                                             frac_bad=("bad", "mean")).reset_index()
    print(g.pivot_table(index=["root", "year"], columns="t", values="frac_bad").round(2).to_string())
    print(g.pivot_table(index=["root", "year"], columns="t", values="med_width").round(3).to_string())


def SCALE_W(df):
    return df["root"].map({"XSP": 1.0, "SPY": 1.0, "SPXW": 10.0})


if __name__ == "__main__":
    main()
