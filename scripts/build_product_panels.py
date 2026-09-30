"""XSP / SPY day panels for the $25k tests.

    python scripts/build_product_panels.py XSP 2021-01-01 2026-09-29 [workers]

Per day: the 8 delta-resolved short strikes on the product's own 10:00 chain, put quotes
(all strikes of the shortest expiry) at 10:00/10:01/10:03/10:05/15:45/15:55, and settlement.
XSP spot = SPX/10 (exact index relation). SPY spot = put-call-parity median at 10:00.
Output: data/processed/<ROOT>/dp/<day>.pkl
"""
from __future__ import annotations

import concurrent.futures as cf
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from vrp_ltr.calendar import fomc_excluded_days, sessions, trading_time_years  # noqa: E402
from vrp_ltr.data import spx_minute  # noqa: E402
from vrp_ltr.panel import effr_asof, load_chain, settlement  # noqa: E402
from vrp_ltr.surface import parity_spot  # noqa: E402
from vrp_ltr.universe import build_universe  # noqa: E402

TIMES = ("10:00", "10:01", "10:03", "10:05", "15:45", "15:55")


def one(args):
    root, day = args
    out = ROOT / "data" / "processed" / root / "dp" / f"{day}.pkl"
    if out.exists():
        return day, "cached"
    if day in fomc_excluded_days():
        return day, "FOMC"
    q = load_chain(root, day)
    if q is None or q.empty:
        return day, "no-chain"
    t10 = pd.Timestamp(f"{day} 10:00", tz="America/New_York")
    r = effr_asof(day)
    e0 = q["expiration"].min()
    snap = q[q["ts"] == t10]
    spx = spx_minute.level_asof(t10)
    if root == "XSP":
        S = spx / 10 if spx else None
    else:
        S = parity_spot(snap, e0, r, trading_time_years(t10, e0), (spx or 0) / 10 * 1.0, n=5)
    if not S or not np.isfinite(S):
        return day, "no-spot"
    u = build_universe(snap.drop(columns=["ts", "root"], errors="ignore"), S, r, t10)
    if u is None or u.candidates.empty:
        return day, "no-universe"
    puts = q[(q["right"] == "P") & (q["expiration"] == u.expiry)]
    rows = []
    for t in TIMES:
        tt = pd.Timestamp(f"{u.expiry if t >= '15:00' else day} {t}", tz="America/New_York")
        x = puts[puts["ts"] == tt][["strike", "bid", "ask"]].assign(t=t)
        rows.append(x)
    quotes = pd.concat(rows, ignore_index=True)
    if root == "XSP":
        settle = settlement(u.expiry, "XSP")
    else:  # SPY: close level via parity at 15:59 (only used if an exit quote is missing)
        t59 = pd.Timestamp(f"{u.expiry} 15:59", tz="America/New_York")
        settle = parity_spot(q[q["ts"] == t59], u.expiry, r, 1e-6, S, n=5)
    dp = {"cands": dict(zip(u.candidates["strategy"], u.candidates["strike"])),
          "cand_table": u.candidates[["strategy", "strike", "bid", "ask", "mid", "iv", "delta"]],
          "quotes": quotes, "settle": settle, "spot": S, "expiry": u.expiry, "r": r}
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "wb") as f:
        pickle.dump(dp, f)
    return day, "ok"


def main():
    root, start, end = sys.argv[1], sys.argv[2], sys.argv[3]
    workers = int(sys.argv[4]) if len(sys.argv) > 4 else 4
    days = [d.date() for d in sessions(start, end)]
    with cf.ProcessPoolExecutor(workers) as ex:
        res = list(ex.map(one, [(root, d) for d in days]))
    from collections import Counter
    print(Counter(s if not s.startswith("error") else "error" for _, s in res))


if __name__ == "__main__":
    main()
