"""$25k product tests (PREREGISTRATION §4): XSP / SPY verticals and naked benchmark, 0/1 lot.

Per day inputs (product panel): candidate short strikes by strategy (resolved on the product's
own 10:00 chain), put quotes for all strikes of the shortest expiry at EXEC times, settlement.
The short leg comes from the SPXW model's pick (strategy name) — never re-chosen here.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .config import PRODUCTS, SKIP, USER_NAV0, fee_per_contract
from .execution import regt_short_put_margin


def _q(quotes: pd.DataFrame, t: str, k: float):
    r = quotes[(quotes["t"] == t) & np.isclose(quotes["strike"], k)]
    if r.empty:
        return np.nan, np.nan
    return float(r["bid"].iloc[0]), float(r["ask"].iloc[0])


def spread_credit(bs, as_, bl, al, level, prod) -> float:
    if not all(np.isfinite([bs, as_, bl, al])) or bs <= 0 or as_ <= bs or al <= bl:
        return np.nan
    if level == "MID":
        c = 0.5 * (bs + as_) - 0.5 * (bl + al)
    elif level == "NAT":
        c = bs - al
    elif level == "NAT1":
        c = bs - al - prod.tick(max(bs - al, 0.0))
    else:
        raise ValueError(level)
    return c if c > 0 else np.nan


def leg_fees(prod, prem_s, prem_l, level) -> float:
    lvl = "full" if level == "NAT1" else "paper"
    f = fee_per_contract(prod, abs(prem_s), lvl) + fee_per_contract(prod, abs(prem_l), lvl)
    return max(f, 1.0)


def choose_long(quotes, ks, variant, nav, prod, t0="10:00"):
    """Long strike for the variant using decision-time (10:00) natural credit."""
    strikes = np.sort(quotes.loc[(quotes["t"] == t0) & (quotes["strike"] < ks), "strike"].unique())[::-1]
    if variant in ("W5", "W10", "W4", "W6"):
        w = float(variant[1:])
        kl = ks - w
        return kl if np.any(np.isclose(strikes, kl)) else None
    if variant.startswith("CAP"):
        cap = float(variant[3:]) / 100.0 * nav
        bs, _ = _q(quotes, t0, ks)
        best = None
        for kl in strikes:
            bl, al = _q(quotes, t0, kl)
            if not np.isfinite(al) or not np.isfinite(bs):
                continue
            cr = bs - al
            if cr <= 0:
                continue
            ml = (ks - kl - cr) * prod.multiplier + leg_fees(prod, bs, al, "NAT1")
            if ml <= cap:
                best = float(kl)
            else:
                break
        return best
    raise ValueError(variant)


def run(picks: pd.Series, day_panels: dict, root: str, variant: str, level: str, fill_time: str,
        exit_time: str | None = None, nav0: float = USER_NAV0, cap_pct: float | None = None) -> pd.DataFrame:
    """Daily NAV path. day_panels[d] = {"cands": {strategy: short_strike}, "quotes": df(t,strike,bid,ask),
    "settle": float}. variant ∈ NAKED | W5 | W10 | CAP1 | CAP2 | CAP4 (| W4 | W6 | CAP1.5 | CAP2.5)."""
    prod = PRODUCTS[root]
    nav = nav0
    rows = []
    for d, s in picks.items():
        rec = {"date": d, "pick": s, "traded": 0, "pnl": 0.0, "credit": np.nan, "max_loss": np.nan,
               "margin": np.nan, "long_k": np.nan, "short_k": np.nan, "reason": ""}
        dp = day_panels.get(d)
        if s is None or s == SKIP or dp is None or s not in dp["cands"]:
            rec["reason"] = "skip" if s == SKIP else "no-data"
        else:
            q, ks, settle = dp["quotes"], dp["cands"][s], dp["settle"]
            rec["short_k"] = ks
            bs, as_ = _q(q, fill_time, ks)
            if variant == "NAKED":
                if level == "MID":
                    cr = 0.5 * (bs + as_)
                elif level == "NAT":
                    cr = bs
                else:
                    cr = bs - prod.tick(bs) if np.isfinite(bs) else np.nan
                if np.isfinite(cr) and cr > 0 and settle is not None:
                    M = regt_short_put_margin(cr, dp.get("spot", settle), ks, prod.multiplier)
                    if M <= nav:
                        f = max(fee_per_contract(prod, cr, "full" if level == "NAT1" else "paper"), 1.0)
                        pnl = prod.multiplier * (cr - max(ks - settle, 0.0)) - f
                        rec.update(traded=1, pnl=pnl, credit=cr, margin=M)
                    else:
                        rec["reason"] = "margin>nav"
                else:
                    rec["reason"] = "no-fill"
            else:
                kl = choose_long(q, ks, variant, nav, prod)
                if kl is None:
                    rec["reason"] = "no-long-strike"
                else:
                    bl, al = _q(q, fill_time, kl)
                    cr = spread_credit(bs, as_, bl, al, level, prod)
                    fee = leg_fees(prod, bs, al, level) if np.isfinite(cr) else np.nan
                    w = ks - kl
                    ml = (w - cr) * prod.multiplier + fee if np.isfinite(cr) else np.nan
                    cap = (float(variant[3:]) / 100.0 * nav) if variant.startswith("CAP") else np.inf
                    if not np.isfinite(cr):
                        rec["reason"] = "no-fill"
                    elif ml > cap + 1e-9:
                        rec["reason"] = "fill-breaches-cap"  # manual rule: do not enter below min credit
                    elif w * prod.multiplier > nav:
                        rec["reason"] = "margin>nav"
                    else:
                        if exit_time is None:
                            payoff = max(ks - settle, 0.0) - max(kl - settle, 0.0)
                            pnl = prod.multiplier * (cr - payoff) - fee
                        else:
                            xbs, xas = _q(q, exit_time, ks)
                            xbl, xal = _q(q, exit_time, kl)
                            if level == "MID":
                                debit = 0.5 * (xbs + xas) - 0.5 * (xbl + xal)
                            else:
                                debit = xas - xbl + (prod.tick(max(xas - xbl, 0.0)) if level == "NAT1" else 0.0)
                            if not np.isfinite(debit):
                                # no exit quote: conservative — settle at intrinsic of the spread
                                debit = max(ks - settle, 0.0) - max(kl - settle, 0.0)
                            debit = min(max(debit, 0.0), w)
                            pnl = prod.multiplier * (cr - debit) - fee - leg_fees(prod, xas, xbl, level)
                        rec.update(traded=1, pnl=pnl, credit=cr, max_loss=ml, margin=w * prod.multiplier, long_k=kl)
        rec["nav_prev"] = nav
        nav += rec["pnl"]
        rows.append(rec)
    df = pd.DataFrame(rows).set_index("date")
    df["ret"] = df["pnl"] / df["nav_prev"]
    return df
