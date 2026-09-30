"""Per-session panel builder: real quotes → candidates, labels, execution quotes, features.

Everything here uses only data stamped at or before the time it is used for, except
fields explicitly named `outcome_*` / `label_*` / `close_*`, which are realised later and are
consumed only (a) as training labels or (b) as features after the lag rules of
`features.py` are applied.
"""
from __future__ import annotations

import datetime as dt
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from .calendar import fomc_excluded_days, session_bounds, trading_time_years
from .config import PRODUCTS, STRATEGIES
from .data import spx_minute
from .label import label_contract
from .surface import atmf_iv, iv_table, pick_expiry, snapshot_features
from .universe import build_universe

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
EXEC_TIMES = ("10:00", "10:01", "10:03", "10:05", "15:45", "15:55")


@lru_cache(maxsize=1)
def effr_series() -> pd.Series:
    e = pd.read_csv(ROOT / "data" / "raw" / "EFFR.csv")
    e.columns = ["date", "effr"]
    e["date"] = pd.to_datetime(e["date"]).dt.date
    e["effr"] = pd.to_numeric(e["effr"], errors="coerce") / 100
    return e.dropna().set_index("date")["effr"]


def effr_asof(day: dt.date) -> float:
    s = effr_series()
    s = s[s.index < day]
    return float(s.iloc[-1]) if len(s) else 0.0


@lru_cache(maxsize=1)
def spx_close() -> pd.Series:
    f = pd.read_csv(ROOT / "data" / "raw" / "SP500_fred.csv")
    f.columns = ["date", "close"]
    f["date"] = pd.to_datetime(f["date"]).dt.date
    f["close"] = pd.to_numeric(f["close"], errors="coerce")
    s = f.dropna().set_index("date")["close"]
    # fallback: HF 16:00 level where FRED is missing
    return s


def settlement(day: dt.date, root: str) -> float | None:
    s = spx_close()
    v = s.get(day)
    if v is None:
        v = spx_minute.level_asof(session_bounds(day)[1])
    if v is None:
        return None
    return float(v) * (0.1 if root == "XSP" else 1.0)


def _et(day, hhmm) -> pd.Timestamp:
    return pd.Timestamp(f"{day} {hhmm}", tz="America/New_York")


def load_chain(root: str, day: dt.date) -> pd.DataFrame | None:
    f = PROC / root / "chain" / f"{day}.parquet"
    if not f.exists():
        return None
    q = pd.read_parquet(f)
    q["expiration"] = pd.to_datetime(q["expiration"]).dt.date
    return q


def spot_asof(root: str, ts: pd.Timestamp) -> float | None:
    spx = spx_minute.level_asof(ts)
    if spx is None:
        return None
    return spx * (0.1 if root == "XSP" else 1.0)


def build_day(day: dt.date, root: str = "SPXW") -> dict | None:
    """Candidates (8 puts) with entry features, labels and execution quotes for one session."""
    if day in fomc_excluded_days():
        return {"day": day, "excluded": "FOMC"}
    q = load_chain(root, day)
    if q is None or q.empty:
        return None
    t10 = _et(day, "10:00")
    S = spot_asof(root, t10)
    r = effr_asof(day)
    if S is None:
        return None
    snap = q[q["ts"] == t10]
    uni = build_universe(snap.drop(columns=["ts", "root"], errors="ignore"), S, r, t10)
    if uni is None or uni.candidates.empty:
        return None
    c = uni.candidates.copy()
    exp = uni.expiry
    settle = settlement(exp, root)
    close_ts = session_bounds(exp)[1]
    puts = q[(q["right"] == "P") & (q["expiration"] == exp)]
    by_k = {k: g.sort_values("ts") for k, g in puts.groupby("strike")}
    rows = []
    for _, cand in c.iterrows():
        K = cand["strike"]
        g = by_k.get(K)
        rec = cand.to_dict()
        rec.update(day=day, root=root, expiry=exp, dte_sessions=uni.dte_sessions, spot=S, r=r)
        # execution quotes at fixed times (same contract)
        for m in EXEC_TIMES:
            tq = _et(day, m) if m < "15:00" or exp == day else _et(exp, m)
            row = g[g["ts"] == tq] if g is not None else None
            ok = row is not None and len(row) > 0
            rec[f"bid_{m}"] = float(row["bid"].iloc[0]) if ok else np.nan
            rec[f"ask_{m}"] = float(row["ask"].iloc[0]) if ok else np.nan
        # label: ask path strictly after 10:00 and strictly before expiry close
        if g is not None and settle is not None:
            path = g[(g["ts"] > t10) & (g["ts"] < close_ts)]["ask"].where(lambda x: x > 0)
            intrinsic = max(K - settle, 0.0)
            lab = label_contract(float(cand["mid"]), path, intrinsic)
            rec.update(label_score=lab["score"], label_gross=lab["gross_pnl"], label_tdd=lab["tdd"],
                       label_nbars=lab["n_bars"], outcome_intrinsic=intrinsic, outcome_settle=settle,
                       outcome_settle_day=exp)
        rows.append(rec)
    cand_df = pd.DataFrame(rows)
    cand_df["strategy"] = [s for s in STRATEGIES[:len(cand_df)]]
    return {"day": day, "candidates": cand_df, "puts_10": uni.puts, "expiry": exp, "spot": S, "r": r}


# ---------------- same-day intraday CS features (no lag needed) and close features -----------

def load_surface(day: dt.date) -> pd.DataFrame | None:
    f = PROC / "SPXW" / "surface" / f"{day}.parquet"
    if not f.exists():
        return None
    s = pd.read_parquet(f)
    s["expiration"] = pd.to_datetime(s["expiration"]).dt.date
    return s


def morning_features(day: dt.date, prev_close: float | None) -> dict:
    """App. B morning block from SPX 1-minute bars 09:30..09:59 (bar-start labels)."""
    b = spx_minute.session_bars(day)
    b = b[b["bar_start"].dt.strftime("%H:%M") <= "09:59"]
    if len(b) < 20:
        return {}
    s = b["close"].values
    s0, s1 = s[0], s[-1]
    hi, lo = b["high"].max(), b["low"].min()
    lr = np.diff(np.log(s))
    out = {
        "morning_spx_log_return": float(np.log(s1 / s0)),
        "morning_spx_range_pct": float((hi - lo) / s0),
        # App. B literal: sqrt(252 * 390 * sum_j r_j^2) (a sum, as printed in the paper)
        "morning_spx_rv_annualized": float(np.sqrt(252 * 390 * np.sum(lr ** 2))),
        "morning_spx_directionality": float((s1 - s0) / (hi - lo)) if hi > lo else 0.0,
    }
    if prev_close:
        open_px = b["open"].iloc[0]
        out["morning_gap_size"] = float((open_px - prev_close) / prev_close)
        out["morning_gap_filled"] = float(lo <= prev_close <= hi)
    return out


def surface_day_features(day: dt.date) -> dict:
    """09:35 / 10:00 snapshot features (usable same day) and close/intraday (lag later)."""
    s = load_surface(day)
    q = load_chain("SPXW", day)
    if s is None:
        return {}
    r = effr_asof(day)
    out = {}
    for hhmm, suf in (("09:35", "0935"), ("10:00", "1000"), ("15:59", "close")):
        ts = _et(day, hhmm)
        snap = s[s["ts"] == ts]
        if q is not None:
            snap = pd.concat([snap, q[q["ts"] == ts]], ignore_index=True).drop_duplicates(
                ["expiration", "right", "strike"])
        S = spx_minute.level_asof(ts)
        if snap.empty or S is None:
            continue
        tbl = iv_table(snap, S, r, ts)
        out.update(snapshot_features(tbl, day, S, r, suf))
    # intraday ATMF-IV paths for DTE 0 / 10 / 30 (close-vs-09:35 change and high-low range)
    allq = pd.concat([x for x in (s, q) if x is not None], ignore_index=True)
    for tau in (0, 10, 30):
        e = pick_expiry(allq["expiration"].unique(), day, tau)
        if e is None or (tau == 0 and e != day):
            continue
        path = []
        g = allq[(allq["expiration"] == e) & (allq["right"] == "P")]
        for ts, snap in g.groupby("ts"):
            if not (_et(day, "09:35") <= ts <= _et(day, "15:59")):
                continue
            S = spx_minute.level_asof(ts)
            if S is None:
                continue
            T = trading_time_years(ts, e)
            F = S * np.exp(r * T)
            row = snap.iloc[[np.argmin(np.abs(snap["strike"].values - F))]]
            tbl = iv_table(row, S, r, ts)
            if len(tbl):
                path.append(float(tbl["iv"].iloc[0]))
        if len(path) > 10:
            out[f"atmf_iv_{tau}dte_intraday_pct_change"] = path[-1] / path[0] - 1
            out[f"atmf_iv_{tau}dte_intraday_range"] = max(path) - min(path)
    return out
