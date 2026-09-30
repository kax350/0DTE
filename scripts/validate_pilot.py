"""Data-quality validation of a downloaded window (PREREGISTRATION §0).

Checks per session (SPXW): (a) put-call-parity implied spot vs SPX 1-min level at 10:00,
(b) crossed/locked quote rate at 10:00, (c) |delta| coverage 0.05..0.45 on the shortest
expiry, (d) expiry pattern (0-DTE vs 1-DTE), (e) presence of the 10:00/10:01/10:03/10:05 records.
Inspects quotes only — no strategy P&L is computed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from vrp_ltr.calendar import sessions, trading_time_years  # noqa: E402
from vrp_ltr.data import spx_minute  # noqa: E402
from vrp_ltr.surface import iv_table, parity_spot  # noqa: E402

EFFR = pd.read_csv(ROOT / "data" / "raw" / "EFFR.csv")
EFFR.columns = ["date", "effr"]
EFFR["date"] = pd.to_datetime(EFFR["date"]).dt.date
EFFR["effr"] = pd.to_numeric(EFFR["effr"], errors="coerce") / 100
EFFR = EFFR.dropna().set_index("date")["effr"]


def effr_asof(day) -> float:
    s = EFFR[EFFR.index < day]  # prior published value (no look-ahead)
    return float(s.iloc[-1]) if len(s) else 0.0


def main(root: str, start: str, end: str) -> None:
    rows = []
    scale = {"SPXW": 1.0, "XSP": 0.1}.get(root, None)
    for d in sessions(start, end):
        day = d.date()
        f = ROOT / "data" / "processed" / root / "chain" / f"{day}.parquet"
        if not f.exists():
            rows.append({"day": day, "status": "missing"})
            continue
        q = pd.read_parquet(f)
        q["expiration"] = pd.to_datetime(q["expiration"]).dt.date
        t10 = pd.Timestamp(f"{day} 10:00", tz="America/New_York")
        snap = q[q["ts"] == t10]
        e0 = q["expiration"].min()
        r = effr_asof(day)
        spx = spx_minute.level_asof(t10)
        S_ref = spx * scale if (spx and scale) else np.nan
        T = trading_time_years(t10, e0)
        ps = parity_spot(snap, e0, r, T, S_ref) if len(snap) else np.nan
        tbl = iv_table(snap[snap["right"] == "P"], S_ref, r, t10) if len(snap) and np.isfinite(S_ref) else pd.DataFrame()
        ad = tbl["delta"].abs() if len(tbl) else pd.Series(dtype=float)
        crossed = float(((snap["ask"] <= snap["bid"]) & (snap["bid"] > 0)).mean()) if len(snap) else np.nan
        present = {m: bool((q["ts"] == pd.Timestamp(f"{day} {m}", tz="America/New_York")).any())
                   for m in ("10:00", "10:01", "10:03", "10:05")}
        rows.append({"day": day, "status": "ok", "expiry": e0, "dte_cal": (e0 - day).days,
                     "n_contracts_10": int(snap[["strike", "right"]].drop_duplicates().shape[0]),
                     "spx_10": spx, "parity_spot": ps,
                     "parity_err_bp": (ps / S_ref - 1) * 1e4 if np.isfinite(ps) and S_ref else np.nan,
                     "crossed_locked_rate": crossed, "min_abs_delta": ad.min() if len(ad) else np.nan,
                     "max_abs_delta": ad.max() if len(ad) else np.nan,
                     **{f"has_{k.replace(':', '')}": v for k, v in present.items()}})
    df = pd.DataFrame(rows)
    out = ROOT / "docs" / f"validation_{root}_{start}_{end}.csv"
    df.to_csv(out, index=False)
    pd.set_option("display.width", 220)
    print(df.to_string(index=False))
    ok = df[df["status"] == "ok"]
    print("\nmedian |parity err| bp:", round(ok["parity_err_bp"].abs().median(), 2),
          "| p95:", round(ok["parity_err_bp"].abs().quantile(0.95), 2),
          "| crossed/locked median:", round(ok["crossed_locked_rate"].median(), 4),
          "| days min|d|<=0.05:", int((ok["min_abs_delta"] <= 0.05).sum()), "/", len(ok))


if __name__ == "__main__":
    main(*sys.argv[1:4])
