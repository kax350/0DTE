"""Retail V2 day panels (RETAIL_V2_PREREGISTRATION §2–§4) for XSP / SPY / SPXW.

    python scripts/build_retail_panels.py XSP 2021-01-01 2026-09-29 [workers]

Per day: the 0DTE put chain at 10:00 with IV/delta (short-leg resolution), raw put NBBO (bid ≥ 0,
ask > 0; long legs may have a zero bid) at every minute 10:00–10:11 and at 15:45/15:55/15:59,
spot at 10:00, settlement (XSP/SPXW: SPX close; SPY: 15:59 put-call-parity spot).
Days whose shortest listed expiry is not the same session are stored with is_0dte=False.
Output: data/processed/<ROOT>/rp/<day>.pkl
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
from vrp_ltr.universe import enrich_puts  # noqa: E402

TIMES = tuple(f"10:{m:02d}" for m in range(0, 12)) + ("15:45", "15:55", "15:59")


def one(args):
    root, day = args
    out = ROOT / "data" / "processed" / root / "rp" / f"{day}.pkl"
    if out.exists():
        return day, "cached"
    if day in fomc_excluded_days():
        return day, "FOMC"
    q = load_chain(root, day)
    if q is None or q.empty:
        return day, "no-chain"
    t10 = pd.Timestamp(f"{day} 10:00", tz="America/New_York")
    e0 = q["expiration"].min()
    r = effr_asof(day)
    snap = q[q["ts"] == t10]
    spx = spx_minute.level_asof(t10)
    if root == "XSP":
        S = spx / 10 if spx else None
    elif root == "SPXW":
        S = spx
    else:
        S = parity_spot(snap, e0, r, trading_time_years(t10, e0), (spx or 0) / 10, n=5)
    if not S or not np.isfinite(S):
        return day, "no-spot"
    puts10 = enrich_puts(snap.drop(columns=["ts", "root"], errors="ignore"), S, r, t10, e0)
    if puts10.empty:
        return day, "no-puts"
    puts10 = puts10[["strike", "bid", "ask", "mid", "iv", "delta"]].reset_index(drop=True)
    p = q[(q["right"] == "P") & (q["expiration"] == e0)]
    rows = []
    for t in TIMES:
        x = p[p["ts"] == pd.Timestamp(f"{e0 if t >= '15:00' else day} {t}", tz="America/New_York")]
        rows.append(x[["strike", "bid", "ask"]].assign(t=t))
    quotes = pd.concat(rows, ignore_index=True)
    quotes = quotes[(quotes["ask"] > 0) & (quotes["bid"] >= 0) & (quotes["ask"] > quotes["bid"])]
    spot_1559 = None
    if root == "SPY":
        t59 = pd.Timestamp(f"{e0} 15:59", tz="America/New_York")
        spot_1559 = parity_spot(q[q["ts"] == t59], e0, r, 1e-6, S, n=5)
        settle = spot_1559
    else:
        settle = settlement(e0, "XSP" if root == "XSP" else "SPXW")
    rp = {"day": day, "expiry": e0, "is_0dte": e0 == day, "spot10": float(S), "r": r, "puts10": puts10,
          "quotes": quotes.reset_index(drop=True), "settle": settle, "spot_1559": spot_1559}
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "wb") as f:
        pickle.dump(rp, f)
    return day, "ok"


def main():
    root, start, end = sys.argv[1], sys.argv[2], sys.argv[3]
    workers = int(sys.argv[4]) if len(sys.argv) > 4 else 3
    days = [d.date() for d in sessions(start, end)]
    with cf.ProcessPoolExecutor(workers) as ex:
        res = list(ex.map(one, [(root, d) for d in days]))
    from collections import Counter
    print(root, Counter(s if not s.startswith("error") else "error" for _, s in res), flush=True)


if __name__ == "__main__":
    main()
