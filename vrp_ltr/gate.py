"""Confidence gate (PAPER_SPEC §7): tau from an 8-point trade-rate grid, Sortino objective."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import GATE_TRADE_RATES


def sortino_daily(x: np.ndarray) -> float:
    x = np.asarray(x, float)
    dd = np.sqrt(np.mean(np.minimum(x, 0) ** 2))
    return float(np.mean(x) / dd) if dd > 0 else (np.inf if np.mean(x) > 0 else -np.inf)


def calibrate(gaps: pd.Series, net_pnl_top1: pd.Series, rates=GATE_TRADE_RATES) -> dict:
    """gaps / net_pnl_top1 indexed by date on the calibration slice (SKIP picks carry 0 P&L).

    For each target trade rate q, tau = (1-q) quantile of gaps; days with gap < tau abstain.
    Returns the tau maximizing the Sortino of the gated daily net P&L. Ties → higher rate.
    """
    g = gaps.reindex(net_pnl_top1.index)
    best = None
    table = []
    for q in sorted(rates, reverse=True):
        tau = 0.0 if q >= 1.0 else float(np.quantile(g.values, 1 - q))
        pnl = np.where(g.values >= tau, net_pnl_top1.values, 0.0)
        s = sortino_daily(pnl)
        table.append({"rate": q, "tau": tau, "sortino": s, "realized_rate": float(np.mean(g.values >= tau))})
        if best is None or s > best["sortino"]:
            best = table[-1]
    return {"tau": best["tau"], "rate": best["rate"], "table": table}


def apply(gaps: pd.Series, tau: float) -> pd.Series:
    return gaps >= tau
