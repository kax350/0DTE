"""SPX 1-minute bars (HF thillsss/SPX-MES-VIX-data, Central Time) → ET parquet cache.

Bar convention in the source: timestamp = bar start (08:30 CT = 09:30 ET bar).
We expose `close` of the bar starting at hh:mm as the level at hh:mm+1. Accessors return
the level "as of" a time using the close of the bar that *ended* at or before that time,
so no bar that finishes after the decision time is ever used.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "data" / "raw" / "hf_spx" / "SPX_full_1min_CT.txt"
CACHE = ROOT / "data" / "processed" / "SPX_1min_et.parquet"
URL = "https://huggingface.co/datasets/thillsss/SPX-MES-VIX-data/resolve/main/SPX_full_1min_CT.txt"


def build_cache() -> pd.DataFrame:
    m = pd.read_csv(SRC, parse_dates=["datetime"])
    start = m["datetime"].dt.tz_localize("America/Chicago", ambiguous="NaT", nonexistent="NaT")
    m = m.assign(bar_start=start.dt.tz_convert("America/New_York")).dropna(subset=["bar_start"])
    m["bar_end"] = m["bar_start"] + pd.Timedelta(minutes=1)
    m = m[["bar_start", "bar_end", "open", "high", "low", "close"]].sort_values("bar_end")
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    m.to_parquet(CACHE, index=False)
    return m


@lru_cache(maxsize=1)
def load() -> pd.DataFrame:
    df = pd.read_parquet(CACHE) if CACHE.exists() else build_cache()
    df["date"] = df["bar_start"].dt.date
    return df


def level_asof(ts: pd.Timestamp) -> float | None:
    """Close of the last bar that ended at or before ts (no look-ahead)."""
    df = load()
    i = df["bar_end"].searchsorted(ts, side="right") - 1
    if i < 0:
        return None
    row = df.iloc[i]
    return float(row["close"]) if row["date"] == ts.date() else None


def session_bars(day) -> pd.DataFrame:
    df = load()
    d = df[df["date"] == day]
    return d[(d["bar_start"].dt.strftime("%H:%M") >= "09:30") & (d["bar_start"].dt.strftime("%H:%M") < "16:00")]
