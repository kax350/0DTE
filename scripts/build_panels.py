"""Build per-day SPXW panels (candidates + labels + execution P&L + same-day/close features).

    python scripts/build_panels.py 2019-06-01 2019-06-30 [workers]

Output: data/processed/SPXW/panel/<day>.parquet (8 candidate rows) and
        data/processed/SPXW/dayfeat/<day>.json (same-day CS features and close features).
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from vrp_ltr.backtest import candidate_pnls  # noqa: E402
from vrp_ltr.calendar import sessions  # noqa: E402
from vrp_ltr.features import entry_ps  # noqa: E402
from vrp_ltr.panel import build_day, morning_features, spx_close, surface_day_features  # noqa: E402

from vrp_ltr.config import PANEL_TAG  # noqa: E402

OUT = ROOT / "data" / "processed" / "SPXW"


def prev_close(day):
    s = spx_close()
    s = s[s.index < day]
    return float(s.iloc[-1]) if len(s) else None


def one(day):
    fp, fj = OUT / f"panel{PANEL_TAG}" / f"{day}.parquet", OUT / "dayfeat" / f"{day}.json"
    if fp.exists() and fj.exists():  # dayfeat is target-independent and shared
        return day, "cached"
    if not (OUT / "chain" / f"{day}.parquet").exists() or not (OUT / "surface" / f"{day}.parquet").exists():
        return day, "pending-download"
    try:
        res = build_day(day, "SPXW")
        feats = {}
        feats.update(morning_features(day, prev_close(day)))
        sf = surface_day_features(day)
        feats.update(sf)
        if "atmf_iv_1dte_0935" in sf and "atmf_iv_1dte_1000" in sf:
            feats["morning_atmf_iv_change"] = sf["atmf_iv_1dte_1000"] - sf["atmf_iv_1dte_0935"]
            feats["morning_atmf_iv_pct_change"] = sf["atmf_iv_1dte_1000"] / sf["atmf_iv_1dte_0935"] - 1
        if "risk_reversal_delta25_1dte_0935" in sf and "risk_reversal_delta25_1dte_1000" in sf:
            feats["morning_skew_change"] = sf["risk_reversal_delta25_1dte_1000"] - sf["risk_reversal_delta25_1dte_0935"]
        fj.parent.mkdir(parents=True, exist_ok=True)
        if res is None:
            fj.write_text(json.dumps({"status": "no-data", **feats}, default=float))
            return day, "no-data"
        if "excluded" in res:
            fj.write_text(json.dumps({"status": "FOMC", **feats}, default=float))
            return day, "FOMC"
        c = res["candidates"]
        # ATMF IV of the traded expiry at 10:00 (put nearest the forward) for intra-strategy features
        puts = res["puts_10"]
        F = res["spot"] * np.exp(res["r"] * puts["T"].iloc[0])
        atmf = float(puts.iloc[np.argmin(np.abs(puts["strike"].values - F))]["iv"])
        c = entry_ps(c, atmf)
        c = candidate_pnls(c, "SPXW")
        c["atmf_iv_entry"] = atmf
        c = c.rename(columns={"day": "date"})
        fp.parent.mkdir(parents=True, exist_ok=True)
        c.to_parquet(fp, index=False)
        fj.write_text(json.dumps({"status": "ok", **feats}, default=float))
        return day, "ok"
    except Exception as e:  # noqa: BLE001
        return day, f"error: {e}"[:300]


def main():
    start, end = sys.argv[1], sys.argv[2]
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else 4
    days = [d.date() for d in sessions(start, end)]
    with cf.ProcessPoolExecutor(workers) as ex:
        for day, st in ex.map(one, days):
            if st not in ("ok", "cached"):
                print(day, st)
    print("done", len(days))


if __name__ == "__main__":
    main()
