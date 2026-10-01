"""Retail V2 engine — RETAIL_V2_PREREGISTRATION.md (+ amendment A1).

One decision per day (target |Δ| or FLAT), one bull put spread position, integer contracts,
quote-based fills on the product's own minute NBBO, max loss checked at the actual fill.
"""
from __future__ import annotations

import math
import pickle
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from .config import CLEARING_REG_PER_CONTRACT, ORDER_MIN_FEE, PRODUCTS, ibkr_commission

PROC = Path(__file__).resolve().parents[1] / "data" / "processed"
TICK = {"XSP": 0.01, "SPY": 0.01, "SPXW": 0.05}
DL_WINDOW = 5  # minutes a delayed limit works before it is cancelled


@dataclass(frozen=True)
class Cfg:
    root: str = "XSP"
    nav0: float = 25_000.0
    risk: float = 0.02
    sizing: str = "S0"            # S0 (CAP-r, 1 lot) | S1 (W5, floor(B/ML)) | S2 (W5, vol-scaled)
    level: str = "NAT"            # MID | NAT | STRESS | DL
    t_sub: str = "10:03"          # order submission minute
    slip_k: float | None = None   # credit = mid - k*(mid - nat); None -> from level
    fee_mult: float = 1.0
    credit_adj: float = 0.0       # K7/K8
    strike_shift: int = 0         # K6
    delta_shift: float = 0.0      # K14
    mincredit: float = 0.05
    edge_h: float | None = None   # R4 hurdle
    snap1000: bool = False        # R0-SNAP1000 (frozen original, product's own 10:00 snapshot)
    width: float = 5.0            # S1/S2 fixed width (product units)
    tol: float = 0.025
    fractional: bool = False      # discretisation diagnostic only (never a candidate)

    def k(self) -> float:
        if self.slip_k is not None:
            return self.slip_k
        return {"MID": 0.0, "NAT": 1.0, "DL": 1.0, "STRESS": 2.0}[self.level]


# ---------------------------------------------------------------------------------- panels
@lru_cache(maxsize=None)
def load_rp(root: str, day) -> dict | None:
    f = PROC / root / "rp" / f"{day}.pkl"
    if not f.exists():
        return None
    with open(f, "rb") as fh:
        rp = pickle.load(fh)
    q = rp["quotes"]
    rp["Q"] = {(t, float(k)): (float(b), float(a)) for t, k, b, a in zip(q["t"], q["strike"], q["bid"], q["ask"])}
    rp["K"] = {t: np.sort(g["strike"].astype(float).unique()) for t, g in q.groupby("t")}
    return rp


def _q(rp, t, k):
    return rp["Q"].get((t, float(k)), (np.nan, np.nan))


def resolve(puts10: pd.DataFrame, target: float, tol: float):
    if puts10 is None or puts10.empty or not np.isfinite(target) or target <= 0:
        return None
    absd = puts10["delta"].abs().values
    dist = np.abs(absd - target)
    best = np.flatnonzero(dist == dist.min())
    i = best[np.argmin(puts10["strike"].values[best])]
    if dist[i] > tol + 1e-12:
        return None
    return float(puts10["strike"].values[i]), float(absd[i])


def nearest_listed(strikes: np.ndarray, x: float):
    if strikes is None or len(strikes) == 0:
        return None
    d = np.abs(strikes - x)
    best = np.flatnonzero(np.isclose(d, d.min()))
    return float(strikes[best].min())


# ------------------------------------------------------------------------------------ fees
def fees(root: str, prem_legs: list[float], n: int, fee_mult: float = 1.0) -> float:
    """Full retail fees for one order: IBKR commission (with $1 order minimum) + exchange + clearing."""
    if n <= 0 or not prem_legs:
        return 0.0
    prod = PRODUCTS[root]
    comm = sum(ibkr_commission(abs(p)) for p in prem_legs) * n
    other = sum(prod.exchange_fee["ge1" if abs(p) >= 1.0 else "lt1"] + CLEARING_REG_PER_CONTRACT for p in prem_legs) * n
    return (max(comm, ORDER_MIN_FEE) + other) * fee_mult


# ------------------------------------------------------------------------------ inputs (t-1)
@dataclass
class Ctx:
    sigma5: dict          # date -> daily vol from prior 5 sessions of 1-min SPX returns
    fhs_z: pd.Series      # date -> standardised 10:00->close log return of that day
    m_close: dict         # date -> minutes from 10:00 to the close
    sigma_bar: dict       # year -> median sigma5 over 2018..year-1 (S2)
    vix_prev: dict
    sessions: list
    pos: dict


def fhs_expected_payoff(ctx: Ctx, day, S10: float, ks: float, kl: float, lookback: int = 1000, min_n: int = 500):
    i = ctx.pos.get(day)
    if i is None:
        return np.nan
    hist = ctx.fhs_z.reindex(ctx.sessions[max(0, i - lookback):i]).dropna()
    if len(hist) < min_n:
        return np.nan
    s = ctx.sigma5.get(day, np.nan)
    m = ctx.m_close.get(day, 360)
    if not np.isfinite(s):
        return np.nan
    ST = S10 * np.exp(hist.values * s * math.sqrt(m / 390.0))
    return float(np.mean(np.maximum(ks - ST, 0.0) - np.maximum(kl - ST, 0.0)))


# ---------------------------------------------------------------------------------- engine
def _minute(t: str, add: int) -> str:
    h, m = map(int, t.split(":"))
    m += add
    return f"{h + m // 60:02d}:{m % 60:02d}"


def _credit(bs, as_, bl, al, k):
    if not all(np.isfinite([bs, as_, bl, al])) or bs <= 0 or as_ <= bs or al <= 0 or al <= bl:
        return np.nan, np.nan, np.nan
    mid = 0.5 * (bs + as_) - 0.5 * (bl + al)
    nat = bs - al
    return mid - k * (mid - nat), mid, nat


def _long_leg(rp, cfg: Cfg, ks: float, t: str, B: float):
    strikes = rp["K"].get(t)
    if strikes is None:
        return None
    if cfg.sizing == "S0":  # CAP-r: widest listed strike with natural credit > 0 and max loss <= B
        bs, _ = _q(rp, t, ks)
        best = None
        for kl in strikes[strikes < ks][::-1]:
            _, al = _q(rp, t, kl)
            if not (np.isfinite(al) and np.isfinite(bs)) or al <= 0:
                continue
            nat = bs - al
            if nat <= 0:
                continue
            ml = (ks - kl - nat) * 100 + fees(cfg.root, [bs, al], 1)
            if ml <= B + 1e-9:
                best = float(kl)
            else:
                break
        return best
    kl = ks - cfg.width
    return float(kl) if np.any(np.isclose(strikes, kl)) else None


def run_day(day, target, cfg: Cfg, ctx: Ctx, rp_spxw=None, rp=None) -> dict:
    """One day's outcome. target = |Δ| (float) or None (FLAT)."""
    rec = {"date": day, "target": target, "traded": 0, "pnl": 0.0, "n": 0, "reason": ""}
    if target is None:
        rec["reason"] = "flat"
        return rec
    rp = rp or load_rp(cfg.root, day)
    rp_spxw = rp_spxw or load_rp("SPXW", day)
    tgt = target + cfg.delta_shift
    B = cfg.risk * cfg.nav0
    # ---- short strike (A1: SPXW 10:00 chain, mapped to the product)
    if cfg.snap1000:
        r = resolve(rp["puts10"], tgt, cfg.tol)
        if r is None:
            rec["reason"] = "delta-unavailable"
            return rec
        ks, dlt = r
        t_build = "10:00"
    else:
        r = resolve(rp_spxw["puts10"], tgt, cfg.tol)
        if r is None:
            rec["reason"] = "delta-unavailable"
            return rec
        k_spx, dlt = r
        x = {"XSP": k_spx / 10.0, "SPXW": k_spx,
             "SPY": k_spx * rp["spot10"] / rp_spxw["spot10"]}[cfg.root]
        t_build = cfg.t_sub
        ks = nearest_listed(rp["K"].get(t_build), x)
        if ks is None:
            rec["reason"] = "no-quote"
            return rec
        rec["k_spxw"] = k_spx
    rec["delta"] = dlt
    if cfg.strike_shift:
        lst = rp["K"].get(t_build, np.array([]))
        up = lst[lst > ks]
        if len(up) == 0:
            rec["reason"] = "no-strike-shift"
            return rec
        shift = float(up[0] - ks)
    else:
        shift = 0.0
    kl = _long_leg(rp, cfg, ks, t_build, B)
    if kl is None:
        rec["reason"] = "no-long-strike"
        return rec
    ks, kl = ks + shift, kl + shift
    W = ks - kl
    rec.update(short_k=ks, long_k=kl, width=W)
    # ---- fill
    k = cfg.k()
    t_fill = cfg.t_sub
    bs, as_ = _q(rp, t_fill, ks)
    bl, al = _q(rp, t_fill, kl)
    c, mid, nat = _credit(bs, as_, bl, al, k)
    if not np.isfinite(mid):
        rec["reason"] = "no-quote"
        return rec
    rec.update(mid0=mid, nat0=nat)
    if cfg.level == "DL":
        tick = TICK[cfg.root]
        L = nat + math.floor(((mid - nat) / 2.0) / tick + 1e-9) * tick
        filled = None
        if L <= nat + 1e-9:
            filled = t_fill
        else:
            for j in range(1, DL_WINDOW + 1):
                tj = _minute(t_fill, j)
                b1, _ = _q(rp, tj, ks)
                _, a2 = _q(rp, tj, kl)
                if np.isfinite(b1) and np.isfinite(a2) and (b1 - a2) >= L + tick - 1e-9:
                    filled = tj
                    break
        if filled is None:
            rec["reason"] = "no-fill"
            rec["dl_limit"] = L
            return rec
        c = L - tick
        rec["fill_t"] = filled
    else:
        rec["fill_t"] = t_fill
    c = c + cfg.credit_adj
    if not np.isfinite(c) or c < cfg.mincredit - 1e-9:
        rec["reason"] = "below-min-credit"
        rec["credit"] = c
        return rec
    # ---- R4 edge gate (per spread, at the submission minute)
    if cfg.edge_h is not None:
        S10 = rp["spot10"]
        ep = fhs_expected_payoff(ctx, day, S10, ks, kl)
        C_hat = (mid - nat) * 100 + fees(cfg.root, [bs, al], 1)
        E_hat = (mid - ep) * 100 if np.isfinite(ep) else np.nan
        rec.update(edge_hat=E_hat, cost_hat=C_hat)
        if not np.isfinite(E_hat) or E_hat < cfg.edge_h * C_hat:
            rec["reason"] = "edge<hurdle"
            return rec
    # ---- sizing and max loss at the actual fill
    f1 = fees(cfg.root, [bs, al], 1, cfg.fee_mult)
    ml1 = (W - c) * 100 + f1
    if cfg.sizing == "S0":
        n = 1
    else:
        scale = 1.0
        if cfg.sizing == "S2":
            s = ctx.sigma5.get(day, np.nan)
            sb = ctx.sigma_bar.get(day.year, np.nan)
            scale = min(1.0, sb / s) if np.isfinite(s) and np.isfinite(sb) and s > 0 else 0.0
        n = (B * scale / ml1) if cfg.fractional else int(math.floor(B * scale / ml1 + 1e-9))
    if n <= 0:
        rec["reason"] = "size-zero"
        return rec
    f_entry = fees(cfg.root, [bs, al], max(int(math.ceil(n)), 1), cfg.fee_mult) * (n / max(math.ceil(n), 1))
    ml = (W - c) * 100 * n + f_entry
    if ml > B + 1e-6:
        rec["reason"] = "fill-breaches-cap"
        rec["credit"], rec["max_loss"] = c, ml
        return rec
    # ---- outcome
    if cfg.root == "SPY":
        xbs, xas = _q(rp, "15:55", ks)
        xbl, xal = _q(rp, "15:55", kl)
        S59 = rp.get("spot_1559")
        if np.isfinite(xas):
            sell_l = xbl if np.isfinite(xbl) and xbl > 0 else 0.0
            debit = min(max(xas - sell_l, 0.0), W)
            legs = [xas] + ([sell_l] if sell_l > 0 else [])
            f_exit = fees("SPY", legs, max(int(math.ceil(n)), 1), cfg.fee_mult) * (n / max(math.ceil(n), 1))
        else:
            S = S59 if S59 is not None and np.isfinite(S59) else rp["settle"]
            debit = max(ks - S, 0.0) - max(kl - S, 0.0)
            f_exit = 0.0
        pnl = 100 * n * (c - debit) - f_entry - f_exit
        if not np.isfinite(pnl):  # no exit quote and no closing spot: book the maximum loss (conservative)
            pnl, rec["exit_note"] = -ml, "exit-data-missing-assumed-max-loss"
        rec.update(exit_debit=debit, fees_exit=f_exit,
                   assign_risk=int(S59 is not None and np.isfinite(S59) and kl < S59 < ks))
    else:
        ST = rp["settle"]
        if ST is None or not np.isfinite(ST):
            rec["reason"] = "no-settlement"
            return rec
        payoff = max(ks - ST, 0.0) - max(kl - ST, 0.0)
        pnl = 100 * n * (c - payoff) - f_entry
        rec.update(settle=ST, payoff=payoff)
    rec.update(traded=1, pnl=float(pnl), n=n, credit=c, fees_entry=f_entry, max_loss=ml,
               margin=W * 100 * n, util=ml / cfg.nav0)
    return rec


def run(decisions: dict, days: list, cfg: Cfg, ctx: Ctx) -> pd.DataFrame:
    rows = [run_day(d, decisions.get(d), cfg, ctx) for d in days]
    df = pd.DataFrame(rows).set_index("date")
    df["nav"] = cfg.nav0 + df["pnl"].cumsum()
    df["vix_prev"] = [ctx.vix_prev.get(d, np.nan) for d in df.index]
    return df


def variant(cfg: Cfg, **kw) -> Cfg:
    return replace(cfg, **kw)
