"""Implied-volatility surface utilities on real quotes (App. B "Implied-volatility surface").

ATMF IV: IV of the put closest to F = S·e^{rT}. Per-delta IV: linear interpolation of IV in
|delta| between the two listed strikes that bracket the target (no extrapolation → NaN).
DTE target τ: expiry with calendar DTE closest to τ (ties → shorter).
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from . import bs
from .calendar import trading_time_years


def iv_table(q: pd.DataFrame, S: float, r: float, now: pd.Timestamp) -> pd.DataFrame:
    """q: quotes of one timestamp (canonical columns). Adds mid, T, iv, delta."""
    q = q[(q["bid"] > 0) & (q["ask"] > q["bid"])].copy()
    if q.empty:
        return q
    q["mid"] = 0.5 * (q["bid"] + q["ask"])
    Tmap = {e: trading_time_years(now, e) for e in q["expiration"].unique()}
    q["T"] = q["expiration"].map(Tmap)
    q = q[q["T"] > 0]
    out = []
    for right, g in q.groupby("right"):
        iv = bs.implied_vol(g["mid"].values, S, g["strike"].values, g["T"].values, r, right)
        g = g.assign(iv=iv)
        g = g[np.isfinite(g["iv"])]
        g["delta"] = bs.greeks(S, g["strike"].values, g["T"].values, r, g["iv"].values, right)["delta"]
        out.append(g)
    return pd.concat(out, ignore_index=True) if out else q.iloc[0:0]


def pick_expiry(expiries, day: dt.date, tau: int):
    exps = sorted(e for e in expiries if e >= day)
    if not exps:
        return None
    return min(exps, key=lambda e: (abs((e - day).days - tau), (e - day).days))


def atmf_iv(tbl: pd.DataFrame, expiry, S: float, r: float) -> float:
    p = tbl[(tbl["expiration"] == expiry) & (tbl["right"] == "P")]
    if p.empty:
        return np.nan
    F = S * np.exp(r * p["T"].iloc[0])
    return float(p.iloc[np.argmin(np.abs(p["strike"].values - F))]["iv"])


def iv_at_delta(tbl: pd.DataFrame, expiry, right: str, target: float) -> float:
    g = tbl[(tbl["expiration"] == expiry) & (tbl["right"] == right)].copy()
    if len(g) < 2:
        return np.nan
    g["ad"] = g["delta"].abs()
    g = g.sort_values("ad")
    x, y = g["ad"].values, g["iv"].values
    if target < x.min() or target > x.max():
        return np.nan
    return float(np.interp(target, x, y))


def parity_spot(tbl_or_quotes: pd.DataFrame, expiry, r: float, T: float, S_ref: float, n: int = 5) -> float:
    """Spot implied by put-call parity from the n strikes nearest S_ref (median)."""
    q = tbl_or_quotes[tbl_or_quotes["expiration"] == expiry]
    q = q[(q["bid"] > 0) & (q["ask"] > q["bid"])]
    q = q.assign(mid=0.5 * (q["bid"] + q["ask"]))
    c = q[q["right"] == "C"].set_index("strike")["mid"]
    p = q[q["right"] == "P"].set_index("strike")["mid"]
    ks = c.index.intersection(p.index)
    if len(ks) == 0:
        return np.nan
    ks = sorted(ks, key=lambda k: abs(k - S_ref))[:n]
    disc = np.exp(-r * T)
    est = [c[k] - p[k] + k * disc for k in ks]  # S = C - P + K e^{-rT} (no dividends)
    return float(np.median(est))


def snapshot_features(tbl: pd.DataFrame, day: dt.date, S: float, r: float, suffix: str) -> dict:
    """ATMF IV at DTE targets, 25/10-delta wings, risk reversals, skews for one snapshot."""
    out = {}
    exps = tbl["expiration"].unique() if len(tbl) else []
    for tau in (0, 1, 5, 10, 20, 30, 60, 90):
        e = pick_expiry(exps, day, tau)
        if e is None:
            continue
        if tau == 0 and e != day:
            continue  # no same-session expiry: 0-DTE quantities undefined
        a = atmf_iv(tbl, e, S, r)
        c25, p25 = iv_at_delta(tbl, e, "C", 0.25), iv_at_delta(tbl, e, "P", 0.25)
        c10, p10 = iv_at_delta(tbl, e, "C", 0.10), iv_at_delta(tbl, e, "P", 0.10)
        out[f"atmf_iv_{tau}dte_{suffix}"] = a
        out[f"call_25d_iv_{tau}dte_{suffix}"] = c25
        out[f"put_25d_iv_{tau}dte_{suffix}"] = p25
        out[f"risk_reversal_delta25_{tau}dte_{suffix}"] = c25 - p25
        out[f"risk_reversal_delta10_{tau}dte_{suffix}"] = c10 - p10
        out[f"put_skew_delta25_{tau}dte_{suffix}"] = (a - p25) / a if a and np.isfinite(a) else np.nan
        out[f"call_skew_delta25_{tau}dte_{suffix}"] = (a - c25) / a if a and np.isfinite(a) else np.nan
    return out
