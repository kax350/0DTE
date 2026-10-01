"""Layer B holdout download: SPXW 0DTE chains 2013-04 → 2016-12 (RETAIL_V3_PREREGISTRATION.md §Layer B).

    DATABENTO_KEY_FILE=... python scripts/download_holdout.py [workers]

Run ONLY after RETAIL_V3_PREREGISTRATION.md is committed. Budget is guarded by databento_dl.priced_get
(DATABENTO_CAP_USD, default $300 cumulative). Chains only (no surface): all puts of the same-day
expiry + calls within ±3% of the 10:00 SPX level, minute cbbo 09:30–16:15.
"""
from __future__ import annotations

import concurrent.futures as cf
import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from vrp_ltr.calendar import sessions  # noqa: E402
from vrp_ltr.data import databento_dl as D  # noqa: E402
from vrp_ltr.data import spx_minute  # noqa: E402

START, END = "2013-04-01", "2016-12-30"
OUT = ROOT / "data" / "processed" / "SPXW" / "chain"
LOG = ROOT / "data" / "reference" / "download_log_holdout.jsonl"


def expiry_days(c) -> list[dt.date]:
    sess = [d.date() for d in sessions(START, END)]
    firsts = sorted({min(d for d in sess if (d.year, d.month) == ym) for ym in {(d.year, d.month) for d in sess}})
    exps = set()
    for d in firsts:
        df = D.definitions(c, "SPXW", d)
        if len(df):
            exps |= {e for e in df["expiration"].unique()}
    return sorted(d for d in sess if d in exps)


def fetch(args):
    c, day = args
    f = OUT / f"{day}.parquet"
    if f.exists():
        return {"day": str(day), "status": "cached"}
    defs = D.definitions(c, "SPXW", day)
    ch = defs[defs["expiration"] == day]
    if ch.empty:
        return {"day": str(day), "status": "no-same-day-expiry"}
    S = spx_minute.level_asof(pd.Timestamp(f"{day} 10:00", tz="America/New_York"))
    puts = ch[ch["right"] == "P"]
    calls = ch[ch["right"] == "C"]
    if S:
        calls = calls[(calls["strike"] / S - 1).abs() <= 0.03]
    syms = puts["raw_symbol"].tolist() + calls["raw_symbol"].tolist()
    q = D.quotes(c, "SPXW", day, syms, "09:30", "16:15", "holdout-chain")
    if len(q):
        q = q[q["expiration"] == day]
    OUT.mkdir(parents=True, exist_ok=True)
    q.to_parquet(f, index=False)
    return {"day": str(day), "status": "ok", "n_rows": len(q)}


def main():
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    c = D.client()
    days = expiry_days(c)
    print("expiry days", len(days), days[:3], days[-3:], "spend so far", round(D.spent(), 2), flush=True)
    with cf.ThreadPoolExecutor(workers) as ex:
        for r in ex.map(fetch, [(c, d) for d in days]):
            with open(LOG, "a") as fh:
                fh.write(json.dumps(r) + "\n")
    print("done; spend", round(D.spent(), 2), flush=True)


if __name__ == "__main__":
    main()
