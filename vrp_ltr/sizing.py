"""Position sizing (PAPER_SPEC §10) plus the $25k one-lot rules (PREREGISTRATION §4).

All methods return a non-negative integer contract count before the margin cap.
Inputs per day (dict `x`): M (Reg-T margin per contract $), delta, gamma, S, sigma_intra5d
(daily sd of 1-min returns ×√390), atm_iv_0dte, vix9d, edge_pct (F̂_train of the edge),
richness_scale, kelly_f (rolling), k_move.
"""
from __future__ import annotations

import math

import numpy as np

from .config import VOL_ANCHOR


def q_fmu(theta, nav, x):
    return math.floor(theta * nav / x["M"])


def q_vt(theta, nav, x):
    sig_c = abs(x["delta"]) * x["S"] * x["sigma_intra5d"] * 100
    tgt = theta * VOL_ANCHOR / math.sqrt(252) * nav
    return math.floor(tgt / sig_c) if sig_c > 0 else 0


def q_srs(theta, nav, x):
    return math.floor(theta * x["richness_scale"] * nav / x["M"])


def q_ea(theta, nav, x):
    return math.floor(theta * x["edge_pct"] * nav / x["M"])


def q_gb(theta, nav, x):
    ks = x["k_move"] * x["S"]
    L = (abs(x["delta"]) * ks + 0.5 * abs(x["gamma"]) * ks * ks) * 100
    return math.floor(theta * nav / L) if L > 0 else 0


def q_kelly(theta, nav, x, alpha):
    f = min(theta, max(0.0, alpha * x["kelly_f"]))
    return math.floor(f * nav / x["M"])


METHODS = {
    "FMU": q_fmu, "VT": q_vt, "SRS": q_srs, "EA": q_ea, "GB": q_gb,
    "HK": lambda t, n, x: q_kelly(t, n, x, 0.5), "QK": lambda t, n, x: q_kelly(t, n, x, 0.25),
}


def size(method: str, theta: float, nav: float, x: dict) -> int:
    q = METHODS[method](theta, nav, x)
    q = max(int(q), 0)
    cap = math.floor(nav / x["M"]) if x["M"] > 0 else 0
    return min(q, cap)


def edge_value(atm_iv_0dte: float, sigma_intra5d_daily: float) -> float:
    rv = sigma_intra5d_daily * math.sqrt(252)
    return (atm_iv_0dte - rv) / rv if rv > 0 else np.nan


def ecdf(train_values: np.ndarray):
    v = np.sort(np.asarray(train_values, float)[np.isfinite(train_values)])

    def F(x):
        return float(np.searchsorted(v, x, side="right") / len(v)) if len(v) else np.nan
    return F


def one_lot(trade: bool) -> int:
    """$25k rule: 0 or 1 contract."""
    return 1 if trade else 0
