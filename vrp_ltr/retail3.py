"""Retail V3 structure engine — RETAIL_V3_LAYER_A_PROTOCOL.md.

One day = one pass over the product's and SPXW's raw minute chains. Every variant
(T0 × |Δ| × structure × exit) is evaluated with V2 mechanics: SPXW-resolved short strikes,
CAP risk wing at the order minute, natural fills, full fees, $0.05 minimum credit per spread.
"""
from __future__ import annotations

import itertools
import math

import numpy as np
import pandas as pd

from . import bs
from .calendar import fomc_excluded_days, session_bounds, trading_time_years
from .data import spx_minute
from .panel import effr_asof, load_chain, settlement
from .retail import fees

TIMES = ("10:00", "12:00", "14:00", "15:00")
DELTAS = (0.05, 0.10, 0.15)
STRUCTS = ("PS", "CS", "IC")
EXITS = ("HOLD", "STOP2")
VARIANTS = [f"{t}|{d:.2f}|{s}|{x}" for t, d, s, x in itertools.product(TIMES, DELTAS, STRUCTS, EXITS)]
MINCREDIT = 0.05
TOL = 0.025
STOP_MULT = 3.0  # exit when position mid >= 3 x entry credit (loss of 2 x credit at mid)


def _plus(hhmm: str, k: int) -> str:
    h, m = map(int, hhmm.split(":"))
    m += k
    return f"{h + m // 60:02d}:{m % 60:02d}"


class Chain:
    """Minute NBBO of the 0DTE expiry as arrays [minute, strike] per right."""

    def __init__(self, root: str, day):
        self.ok = False
        q = load_chain(root, day)
        if q is None or q.empty:
            return
        q = q[q["expiration"] == day]
        if q.empty:
            return
        q = q.assign(m=q["ts"].dt.tz_convert("America/New_York").dt.strftime("%H:%M"))
        self.mins = sorted(q["m"].unique())
        self.mi = {m: i for i, m in enumerate(self.mins)}
        self.side = {}
        for right in ("P", "C"):
            x = q[q["right"] == right]
            if x.empty:
                continue
            b = x.pivot_table(index="m", columns="strike", values="bid", aggfunc="last").reindex(self.mins)
            a = x.pivot_table(index="m", columns="strike", values="ask", aggfunc="last").reindex(self.mins)
            K = b.columns.values.astype(float)
            B, A = b.values.astype(float), a.values.astype(float)
            bad = ~((A > 0) & (B >= 0) & (A > B))
            B[bad], A[bad] = np.nan, np.nan
            self.side[right] = (K, B, A)
        self.ok = "P" in self.side

    def quote(self, t, right, k):
        if right not in self.side or t not in self.mi:
            return np.nan, np.nan
        K, B, A = self.side[right]
        j = np.searchsorted(K, k)
        if j >= len(K) or not np.isclose(K[j], k):
            return np.nan, np.nan
        i = self.mi[t]
        return B[i, j], A[i, j]

    def listed(self, t, right):
        if right not in self.side or t not in self.mi:
            return np.array([])
        K, B, A = self.side[right]
        return K[np.isfinite(A[self.mi[t]])]


def deltas_at(ch: Chain, t, right, S, T, r):
    """(strikes, |delta|) on two-sided quotes at minute t (IV from mid)."""
    if right not in ch.side or t not in ch.mi:
        return np.array([]), np.array([])
    K, B, A = ch.side[right]
    i = ch.mi[t]
    b, a = B[i], A[i]
    ok = np.isfinite(a) & (b > 0)
    if not ok.any():
        return np.array([]), np.array([])
    k, mid = K[ok], 0.5 * (b[ok] + a[ok])
    iv = bs.implied_vol(mid, S, k, T, r, right)
    good = np.isfinite(iv)
    if not good.any():
        return np.array([]), np.array([])
    d = bs.greeks(S, k[good], T, r, iv[good], right)["delta"]
    return k[good], np.abs(d)


def pick(k, absd, target, right):
    if len(k) == 0:
        return None
    dist = np.abs(absd - target)
    best = np.flatnonzero(dist == dist.min())
    j = best[np.argmin(k[best])] if right == "P" else best[np.argmax(k[best])]  # tie -> further OTM
    return float(k[j]) if dist[j] <= TOL + 1e-12 else None


def nearest(listed, x):
    if len(listed) == 0:
        return None
    d = np.abs(listed - x)
    best = np.flatnonzero(np.isclose(d, d.min()))
    return float(listed[best].min())


def wing(ch: Chain, t, right, ks, bs_, root, B):
    """CAP wing for one vertical: widest listed long strike with natural credit > 0 and max loss <= B."""
    lst = ch.listed(t, right)
    cand = lst[lst < ks][::-1] if right == "P" else lst[lst > ks]
    best = None
    for kl in cand:
        _, al = ch.quote(t, right, kl)
        if not np.isfinite(al):
            continue
        nat = bs_ - al
        if nat <= 0:
            continue
        ml = (abs(ks - kl) - nat) * 100 + fees(root, [bs_, al], 1)
        if ml <= B + 1e-9:
            best = (float(kl), float(al))
        else:
            break
    return best


def ic_width(ch: Chain, t, kp, kc, bp, bc, root, B):
    lp, lc = ch.listed(t, "P"), ch.listed(t, "C")
    widths = sorted({round(kp - x, 6) for x in lp if x < kp} & {round(x - kc, 6) for x in lc if x > kc})
    best = None
    for w in widths:
        _, ap = ch.quote(t, "P", kp - w)
        _, ac = ch.quote(t, "C", kc + w)
        if not (np.isfinite(ap) and np.isfinite(ac)):
            continue
        np_, nc = bp - ap, bc - ac
        if np_ <= 0 or nc <= 0:
            continue
        ml = (w - np_ - nc) * 100 + fees(root, [bp, ap, bc, ac], 1)
        if ml <= B + 1e-9:
            best = (w, ap, ac)
        else:
            break
    return best


def _mid(b, a):
    return 0.5 * (b + a) if np.isfinite(a) and np.isfinite(b) else np.nan


def _close_debit(ch, t, legs, root):
    """Natural debit to close all legs at minute t. legs = [(right, ks, kl, W)]."""
    debit, prem = 0.0, []
    for right, ks, kl, w in legs:
        _, as_ = ch.quote(t, right, ks)
        bl, _ = ch.quote(t, right, kl)
        if not np.isfinite(as_):
            return np.nan, None
        sell = bl if np.isfinite(bl) and bl > 0 else 0.0
        debit += min(max(as_ - sell, 0.0), w)
        prem += [as_] + ([sell] if sell > 0 else [])
    return debit, fees(root, prem, 1)


def payoff_at(legs, S):
    v = 0.0
    for right, ks, kl, _ in legs:
        if right == "P":
            v += max(ks - S, 0.0) - max(kl - S, 0.0)
        else:
            v += max(S - ks, 0.0) - max(S - kl, 0.0)
    return v


def eval_day(args) -> list[dict]:
    root, day, B = args
    out = []
    if day in fomc_excluded_days():
        return [{"date": day, "variant": v, "traded": 0, "pnl": 0.0, "reason": "fomc", "eligible": 0} for v in VARIANTS]
    ch = Chain(root, day)
    sx = ch if root == "SPXW" else Chain("SPXW", day)
    open_, close = session_bounds(day)
    last = (close - pd.Timedelta(minutes=1)).strftime("%H:%M")
    if not (ch.ok and sx.ok):
        return [{"date": day, "variant": v, "traded": 0, "pnl": 0.0, "reason": "no-0dte-chain", "eligible": 0}
                for v in VARIANTS]
    ST = settlement(day, "XSP" if root == "XSP" else "SPXW")
    r = effr_asof(day)
    scale = 0.1 if root == "XSP" else 1.0
    res_cache = {}
    for v in VARIANTS:
        t0, dlt, st, ex = v.split("|")
        dlt = float(dlt)
        rec = {"date": day, "variant": v, "traded": 0, "pnl": 0.0, "reason": "", "eligible": 1}
        t1 = _plus(t0, 3)
        ts0 = pd.Timestamp(f"{day} {t0}", tz="America/New_York")
        if ts0 >= close - pd.Timedelta(minutes=5) or t1 not in ch.mi:
            rec.update(reason="session-closed", eligible=0 if ts0 >= close else 1)
            out.append(rec)
            continue
        S = spx_minute.level_asof(ts0)
        if S is None or ST is None:
            rec["reason"] = "no-spot-or-settle"
            rec["eligible"] = 0
            out.append(rec)
            continue
        T = trading_time_years(ts0, day)
        sides = ["P"] if st == "PS" else ["C"] if st == "CS" else ["P", "C"]
        shorts = {}
        for right in sides:
            key = (t0, right)
            if key not in res_cache:
                res_cache[key] = deltas_at(sx, t0, right, S, T, r)
            k_spx = pick(*res_cache[key], dlt, right)
            if k_spx is None:
                break
            ks = nearest(ch.listed(t1, right), k_spx * scale)
            if ks is None:
                break
            shorts[right] = ks
        if len(shorts) != len(sides):
            rec["reason"] = "delta-unavailable"
            out.append(rec)
            continue
        bid = {rt: ch.quote(t1, rt, k)[0] for rt, k in shorts.items()}
        if any(not np.isfinite(b) or b <= 0 for b in bid.values()):
            rec["reason"] = "no-bid"
            out.append(rec)
            continue
        if st == "IC":
            w = ic_width(ch, t1, shorts["P"], shorts["C"], bid["P"], bid["C"], root, B)
            if w is None:
                rec["reason"] = "no-wing"
                out.append(rec)
                continue
            W, ap, ac = w
            legs = [("P", shorts["P"], shorts["P"] - W, W), ("C", shorts["C"], shorts["C"] + W, W)]
            cr = {"P": bid["P"] - ap, "C": bid["C"] - ac}
            prem = [bid["P"], ap, bid["C"], ac]
            maxw = W
        else:
            rt = sides[0]
            w = wing(ch, t1, rt, shorts[rt], bid[rt], root, B)
            if w is None:
                rec["reason"] = "no-wing"
                out.append(rec)
                continue
            kl, al = w
            W = abs(shorts[rt] - kl)
            legs = [(rt, shorts[rt], kl, W)]
            cr = {rt: bid[rt] - al}
            prem = [bid[rt], al]
            maxw = W
        if min(cr.values()) < MINCREDIT - 1e-9:
            rec["reason"] = "below-min-credit"
            out.append(rec)
            continue
        credit = sum(cr.values())
        f_in = fees(root, prem, 1)
        ml = (maxw - credit) * 100 + f_in
        if ml > B + 1e-6:
            rec["reason"] = "fill-breaches-cap"
            out.append(rec)
            continue
        pnl, stopped, xt = None, 0, ""
        if ex == "STOP2":
            i1 = ch.mi[t1]
            for m in ch.mins[i1 + 1:]:
                if m > last:
                    break
                mid = 0.0
                for right, ks, kl, _ in legs:
                    ms = _mid(*ch.quote(m, right, ks))
                    bl, al_ = ch.quote(m, right, kl)
                    ml_ = _mid(bl, al_) if np.isfinite(al_) else 0.0
                    mid += ms - ml_
                if np.isfinite(mid) and mid >= STOP_MULT * credit:
                    debit, f_out = _close_debit(ch, m, legs, root)
                    if np.isfinite(debit):
                        pnl = 100 * (credit - debit) - f_in - f_out
                        stopped, xt = 1, m
                        break
        if pnl is None:
            pnl = 100 * (credit - payoff_at(legs, ST)) - f_in  # settlement() already returns SPX/10 for XSP
        rec.update(traded=1, pnl=float(pnl), credit=credit, width=maxw, max_loss=ml, stopped=stopped, exit_t=xt,
                   short_p=shorts.get("P"), short_c=shorts.get("C"))
        out.append(rec)
    return out
