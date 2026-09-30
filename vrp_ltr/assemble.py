"""Assemble the model panel (8 candidates + SKIP per session) with lagged features."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .calendar import sessions
from .config import PANEL_TAG
from .config import SKIP
from .features import (add_interactions_and_ranks, calendar_cs, close_based_cs, daily_sources,
                       group_of, paper_catalog, rolling_ps, PS_ENTRY)

ROOT = Path(__file__).resolve().parents[1]
P = ROOT / "data" / "processed" / "SPXW"
SAMEDAY_SUFFIX = ("_0935", "_1000")
CLOSE_KEYS = ("_close", "_intraday_pct_change", "_intraday_range")


def load_dayfeat(days) -> tuple[pd.DataFrame, pd.DataFrame]:
    same, close = {}, {}
    for d in days:
        f = P / "dayfeat" / f"{d}.json"
        if not f.exists():
            continue
        j = json.loads(f.read_text())
        j.pop("status", None)
        same[d] = {k: v for k, v in j.items() if k.startswith("morning_") or k.endswith(SAMEDAY_SUFFIX)}
        close[d] = {k: v for k, v in j.items() if k.endswith(CLOSE_KEYS)}
    return pd.DataFrame.from_dict(same, orient="index"), pd.DataFrame.from_dict(close, orient="index")


def load_candidates(days) -> pd.DataFrame:
    fr = [pd.read_parquet(P / f"panel{PANEL_TAG}" / f"{d}.parquet") for d in days if (P / f"panel{PANEL_TAG}" / f"{d}.parquet").exists()]
    c = pd.concat(fr, ignore_index=True)
    for col in ("date", "expiry", "outcome_settle_day"):
        c[col] = pd.to_datetime(c[col]).dt.date
    return c


def build(start: str, end: str, policy: str) -> tuple[pd.DataFrame, list[str]]:
    days = [d.date() for d in sessions(start, end)]
    cands = load_candidates(days)
    same, close = load_dayfeat(days)
    # --- close-based CS, lagged one session
    cs_close = close_based_cs(close)
    all_sess = list(cs_close.index)
    lagged = cs_close.shift(1)
    lagged.index.name = "date"
    # --- same-day CS
    cal = calendar_cs(days)
    same.index.name = "date"
    cs = cal.join(same, how="left").join(lagged.reindex(cal.index), how="left")
    # --- per-strategy rolling (policy) — history needs the SPX same-day return of each trade day
    spx = daily_sources()["spx"]
    spx_ret = (spx / spx.shift(1) - 1).to_dict()
    hist = cands[["date", "strategy", "mid", "label_gross", "outcome_settle_day"]].copy()
    hist["spx_1d_return_on_day"] = hist["date"].map(spx_ret)
    hist = hist.rename(columns={"date": "day"})
    roll = []
    for d in sorted(cands["date"].unique()):
        r = rolling_ps(hist, d, policy)
        if len(r):
            r["date"] = d
            roll.append(r)
    roll = pd.concat(roll, ignore_index=True) if roll else pd.DataFrame(columns=["date", "strategy"])
    # --- rows
    c = cands.merge(roll, on=["date", "strategy"], how="left")
    skip = pd.DataFrame({"date": sorted(cands["date"].unique()), "strategy": SKIP, "label_score": 0.0,
                         "label_gross": 0.0})
    panel = pd.concat([c, skip], ignore_index=True, sort=False)
    panel = panel.merge(cs.reset_index(), on="date", how="left")
    panel = add_interactions_and_ranks(panel)
    exclude = {"date", "strategy", "root", "expiry", "outcome_settle_day", "outcome_intrinsic", "outcome_settle",
               "label_score", "label_gross", "label_tdd", "label_nbars", "strike", "bid", "ask", "mid", "T", "iv",
               "spot", "r", "target_delta", "dte_sessions", "expiration", "right", "bid_size", "ask_size",
               "cboe_iv", "cboe_delta", "volume", "open_interest", "atmf_iv_entry", "grade"}
    catalog = set(paper_catalog())
    feats = [f for f in panel.columns
             if f in catalog and f not in exclude and pd.api.types.is_numeric_dtype(panel[f])]
    panel = panel.sort_values(["date", "strategy"]).reset_index(drop=True)
    return panel, sorted(feats)


def feature_coverage(panel: pd.DataFrame, feats: list[str]) -> pd.DataFrame:
    rows = []
    real = panel[panel["strategy"] != SKIP]
    for f in feats:
        scope, grp = group_of(f)
        rows.append({"feature": f, "scope": scope, "group": grp, "null_rate": float(real[f].isna().mean())})
    return pd.DataFrame(rows)
