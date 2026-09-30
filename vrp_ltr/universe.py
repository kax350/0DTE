"""Daily candidate universe: shortest-DTE expiry, delta-targeted strikes (PAPER_SPEC §2).

Input chain schema (canonical, one row per contract at one timestamp):
    expiration (date), strike (float), right ('P'/'C'), bid, ask, [bid_size, ask_size]
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import bs
from .calendar import trading_time_years
from .config import DELTA_TARGETS, STRATEGIES


def shortest_expiry(expirations, today: dt.date) -> dt.date | None:
    """Shortest available DTE on/after today (same-session expiry counts as DTE 0)."""
    exps = sorted(e for e in set(expirations) if e >= today)
    return exps[0] if exps else None


def clean_quotes(chain: pd.DataFrame) -> pd.DataFrame:
    """Frozen quote filter (PAPER_SPEC §2 [AMBIG]): bid > 0 and ask > bid."""
    c = chain.copy()
    c = c[(c["bid"] > 0) & (c["ask"] > c["bid"])]
    c["mid"] = 0.5 * (c["bid"] + c["ask"])
    return c


def enrich_puts(chain: pd.DataFrame, S: float, r: float, now: pd.Timestamp, expiry: dt.date) -> pd.DataFrame:
    """Put rows of `expiry` with mid, IV (from mid), BS greeks. Invalid IVs dropped."""
    p = clean_quotes(chain[(chain["expiration"] == expiry) & (chain["right"] == "P")])
    if p.empty:
        return p
    T = trading_time_years(now, expiry)
    p = p.assign(T=T)
    p["iv"] = bs.implied_vol(p["mid"].values, S, p["strike"].values, T, r, "P")
    p = p[np.isfinite(p["iv"])]
    g = bs.greeks(S, p["strike"].values, T, r, p["iv"].values, "P")
    for k, v in g.items():
        p[k] = v
    return p.sort_values("strike").reset_index(drop=True)


def resolve_strikes(puts: pd.DataFrame, targets=DELTA_TARGETS) -> pd.DataFrame:
    """argmin_K | |delta(K)| - target |, tie -> lower strike (frozen)."""
    rows = []
    absd = puts["delta"].abs().values
    for tgt, name in zip(targets, STRATEGIES):
        if len(puts) == 0:
            break
        dist = np.abs(absd - tgt)
        best = np.flatnonzero(dist == dist.min())
        i = best[np.argmin(puts["strike"].values[best])]
        row = puts.iloc[i].to_dict()
        row.update(strategy=name, target_delta=tgt, delta_distance_from_target=abs(row["delta"]) - tgt)
        rows.append(row)
    return pd.DataFrame(rows)


@dataclass
class DayUniverse:
    date: dt.date
    expiry: dt.date | None
    dte_sessions: int | None
    spot: float
    r: float
    candidates: pd.DataFrame  # one row per delta candidate (SKIP handled downstream)
    puts: pd.DataFrame        # full enriched put chain (for spreads / surface features)


def build_universe(chain: pd.DataFrame, S: float, r: float, now: pd.Timestamp,
                   excluded_days: set[dt.date] | None = None) -> DayUniverse | None:
    today = now.date()
    if excluded_days and today in excluded_days:
        return None
    exp = shortest_expiry(chain["expiration"].unique(), today)
    if exp is None:
        return None
    puts = enrich_puts(chain, S, r, now, exp)
    cands = resolve_strikes(puts)
    from .calendar import sessions
    dte = len(sessions(str(today), str(exp))) - 1
    return DayUniverse(today, exp, dte, S, r, cands, puts)


# ---- Defined-risk construction (PREREGISTRATION §4) ------------------------------------------

def vertical_long_strike(puts: pd.DataFrame, short_k: float, width: float) -> float | None:
    """Exact-width long strike K_s - W; None if not listed with a valid quote (-> SKIP)."""
    target = round(short_k - width, 6)
    hit = puts.loc[np.isclose(puts["strike"].values, target)]
    return float(hit["strike"].iloc[0]) if len(hit) else None


def risk_capped_long_strike(puts: pd.DataFrame, short_k: float, cap_dollars: float,
                            multiplier: int, qty: int = 1) -> float | None:
    """Widest listed long strike below K_s with (W - natural credit)*mult*qty <= cap and credit > 0.

    Natural credit = bid(short) - ask(long). Returns None if no strike satisfies (-> SKIP).
    """
    s = puts.loc[np.isclose(puts["strike"].values, short_k)]
    if s.empty:
        return None
    sbid = float(s["bid"].iloc[0])
    best = None
    for _, row in puts[puts["strike"] < short_k].sort_values("strike", ascending=False).iterrows():
        width = short_k - row["strike"]
        credit = sbid - row["ask"]
        if credit <= 0:
            continue
        maxloss = (width - credit) * multiplier * qty
        if maxloss <= cap_dollars + 1e-9:
            best = float(row["strike"])  # keep going: widest satisfying
        else:
            break  # max loss increases monotonically with width once past the cap
    return best
