"""P&L engines: one-contract (selection test) and the paper's sized NAV loop (alg:walk_forward)."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .config import PRODUCTS, SIZING_GRIDS, SKIP, VOL_ANCHOR
from .execution import fees, regt_short_put_margin
from .sizing import size

SINGLE_EXEC = {
    # name: (quote time, price rule, fee level)
    "L1": ("10:00", "mid", "paper"),
    "P75": ("10:00", "p75", "paper"),
    "L2": ("10:00", "bid", "paper"),
    "L3": ("10:00", "bid-1", "full"),
    "L2_1001": ("10:01", "bid", "paper"), "L3_1001": ("10:01", "bid-1", "full"),
    "L2_1003": ("10:03", "bid", "paper"), "L3_1003": ("10:03", "bid-1", "full"),
    "L2_1005": ("10:05", "bid", "paper"), "L3_1005": ("10:05", "bid-1", "full"),
    "DOUBLE": ("10:00", "double", "double"),
}


def single_credit(row: pd.Series, rule: str, t: str, product) -> float:
    bid, ask = row.get(f"bid_{t}", np.nan), row.get(f"ask_{t}", np.nan)
    if not (np.isfinite(bid) and np.isfinite(ask)) or bid <= 0 or ask <= bid:
        return np.nan
    mid = 0.5 * (bid + ask)
    if rule == "mid":
        px = mid
    elif rule == "p75":
        px = 0.75 * bid + 0.25 * ask
    elif rule == "bid":
        px = bid
    elif rule == "bid-1":
        px = bid - product.tick(bid)
    elif rule == "double":
        px = mid - 2 * (mid - (bid - product.tick(bid)))
    else:
        raise ValueError(rule)
    return px if px > 0 else np.nan


def candidate_pnls(c: pd.DataFrame, root: str = "SPXW") -> pd.DataFrame:
    """Adds net_<level> ($ per 1 contract, fees included) for every execution level."""
    prod = PRODUCTS[root]
    out = c.copy()
    for name, (t, rule, fee_level) in SINGLE_EXEC.items():
        vals = []
        for _, r in c.iterrows():
            cr = single_credit(r, rule, t, prod)
            if not np.isfinite(cr) or not np.isfinite(r.get("outcome_intrinsic", np.nan)):
                vals.append(np.nan)
                continue
            if fee_level == "double":
                f = 2 * fees(prod, [(cr, 1)], "full")
            else:
                f = fees(prod, [(cr, 1)], fee_level)
            vals.append(prod.multiplier * (cr - r["outcome_intrinsic"]) - f)
        out[f"net_{name}"] = vals
    return out


def one_contract_series(picks: pd.Series, table: pd.DataFrame, level: str) -> pd.Series:
    """picks: date -> strategy (or SKIP / None). table: rows (date, strategy, net_<level>).
    No fill (NaN) on a picked contract → 0 (no trade), logged by caller."""
    t = table.set_index(["date", "strategy"])[f"net_{level}"]
    vals = []
    for d, s in picks.items():
        if s is None or s == SKIP:
            vals.append(0.0)
            continue
        v = t.get((d, s), np.nan)
        vals.append(0.0 if not np.isfinite(v) else float(v))
    return pd.Series(vals, index=picks.index, name=level)


def sized_nav(picks: pd.Series, table: pd.DataFrame, daily_x: dict, method: str, theta: float,
              nav0: float, level: str = "L1", root: str = "SPXW") -> pd.DataFrame:
    """Paper Algorithm 2, Phase B: Q from sizing method, margin cap, fees at `level`."""
    prod = PRODUCTS[root]
    t = table.set_index(["date", "strategy"])
    nav = nav0
    rows = []
    for d, s in picks.items():
        q, pnl = 0, 0.0
        if s is not None and s != SKIP and (d, s) in t.index:
            r = t.loc[(d, s)]
            credit = single_credit(r, SINGLE_EXEC[level][1], SINGLE_EXEC[level][0], prod)
            if np.isfinite(credit) and np.isfinite(r["outcome_intrinsic"]):
                M = regt_short_put_margin(credit, r["spot"], r["strike"], prod.multiplier)
                x = dict(daily_x.get(d, {}), M=M, delta=r["delta"], gamma=r["gamma"], S=r["spot"])
                try:
                    q = size(method, theta, nav, x)
                except (KeyError, ZeroDivisionError, ValueError):
                    q = 0
                if q > 0:
                    gross = q * prod.multiplier * (credit - r["outcome_intrinsic"])
                    pnl = gross - fees(prod, [(credit, q)], SINGLE_EXEC[level][2] if SINGLE_EXEC[level][2] != "double" else "full")
        rows.append({"date": d, "q": q, "pnl": pnl, "nav_prev": nav})
        nav += pnl
    df = pd.DataFrame(rows).set_index("date")
    df["ret"] = df["pnl"] / df["nav_prev"]
    return df


def calibrate_theta(picks_train, table, daily_x, method, nav0) -> tuple[float, float]:
    """Equal-vol calibration (eq:equal_vol_calibration) on training-window predictions."""
    best = None
    for th in SIZING_GRIDS[method]:
        r = sized_nav(picks_train, table, daily_x, method, th, nav0)["ret"]
        vol = float(r.std(ddof=1) * math.sqrt(252))
        dev = abs(vol - VOL_ANCHOR)
        if best is None or dev < best[1] - 1e-12:
            best = (th, dev, vol)
    return best[0], best[2]
