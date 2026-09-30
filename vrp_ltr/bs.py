"""Black-Scholes (no dividends, r = EFFR) price, greeks and implied volatility.

PAPER_SPEC §2: IV recovered from the 10:00 mid, EFFR as r, no dividend yield.
Vectorised with numpy; IV via bracketed Newton/bisection hybrid (robust near expiry).
"""
from __future__ import annotations

import numpy as np
from scipy.special import ndtr

SQRT2PI = np.sqrt(2.0 * np.pi)


def _d1d2(S, K, T, r, sig):
    S, K, T, r, sig = map(np.asarray, (S, K, T, r, sig))
    vt = sig * np.sqrt(T)
    d1 = (np.log(S / K) + (r + 0.5 * sig * sig) * T) / vt
    return d1, d1 - vt


def price(S, K, T, r, sig, right="P"):
    d1, d2 = _d1d2(S, K, T, r, sig)
    disc = np.exp(-np.asarray(r) * np.asarray(T))
    if right == "C":
        return S * ndtr(d1) - K * disc * ndtr(d2)
    return K * disc * ndtr(-d2) - S * ndtr(-d1)


def greeks(S, K, T, r, sig, right="P") -> dict:
    """Per-share greeks. theta per year (negative for long), vega per 1.00 vol."""
    d1, d2 = _d1d2(S, K, T, r, sig)
    S, K, T, r, sig = map(np.asarray, (S, K, T, r, sig))
    pdf = np.exp(-0.5 * d1 * d1) / SQRT2PI
    disc = np.exp(-r * T)
    gamma = pdf / (S * sig * np.sqrt(T))
    vega = S * pdf * np.sqrt(T)
    if right == "C":
        delta = ndtr(d1)
        theta = -S * pdf * sig / (2 * np.sqrt(T)) - r * K * disc * ndtr(d2)
    else:
        delta = ndtr(d1) - 1.0
        theta = -S * pdf * sig / (2 * np.sqrt(T)) + r * K * disc * ndtr(-d2)
    return {"delta": delta, "gamma": gamma, "vega": vega, "theta": theta}


def implied_vol(p, S, K, T, r, right="P", lo=1e-4, hi=8.0, tol=1e-8, it=100):
    """Vectorised IV. Returns NaN where p is outside no-arbitrage bounds."""
    p, S, K, T, r = np.broadcast_arrays(*map(lambda x: np.asarray(x, dtype=float), (p, S, K, T, r)))
    disc = np.exp(-r * T)
    intrinsic = np.maximum(K * disc - S, 0.0) if right == "P" else np.maximum(S - K * disc, 0.0)
    upper = K * disc if right == "P" else S
    ok = (p > intrinsic + 1e-12) & (p < upper) & (T > 0)
    a = np.full(p.shape, lo)
    b = np.full(p.shape, hi)
    x = np.full(p.shape, 0.2)
    for _ in range(it):
        f = price(S, K, T, r, x, right) - p
        a = np.where(f < 0, x, a)
        b = np.where(f >= 0, x, b)
        v = greeks(S, K, T, r, x, right)["vega"]
        step = np.where(v > 1e-12, f / np.where(v > 1e-12, v, 1.0), np.inf)
        xn = x - step
        bad = ~np.isfinite(xn) | (xn <= a) | (xn >= b)
        xn = np.where(bad, 0.5 * (a + b), xn)
        if np.nanmax(np.abs(np.where(ok, xn - x, 0.0))) < tol:
            x = xn
            break
        x = xn
    return np.where(ok, x, np.nan)
