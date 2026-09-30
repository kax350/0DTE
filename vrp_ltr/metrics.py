"""Performance, risk and inference metrics (PAPER_SPEC §11, PREREGISTRATION §7).

Two families of input:
  * return series r_t (fraction of NAV), used for Sharpe/CAGR/MaxDD as in the paper;
  * dollar P&L series (one-contract tests), used for mean P&L, bootstrap and DM.
Zero days (no trade) are included as zeros; they are real days of the strategy.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import stats

A = 252
EULER = 0.5772156649015329


def arc(r: np.ndarray, periods_per_year: int = A) -> float:
    r = np.asarray(r, float)
    if len(r) == 0:
        return float("nan")
    g = np.prod(1 + r)
    return g ** (periods_per_year / len(r)) - 1 if g > 0 else -1.0


def asd(r, periods_per_year: int = A) -> float:
    r = np.asarray(r, float)
    return float(np.std(r, ddof=1) * math.sqrt(periods_per_year)) if len(r) > 1 else float("nan")


def sharpe_geometric(r) -> float:
    """Paper's convention: aRC / aSD (App. A)."""
    s = asd(r)
    return arc(r) / s if s and s > 0 else float("nan")


def sharpe_arithmetic(r) -> float:
    r = np.asarray(r, float)
    s = np.std(r, ddof=1)
    return float(np.mean(r) / s * math.sqrt(A)) if s > 0 else float("nan")


def sortino(r) -> float:
    r = np.asarray(r, float)
    dd = math.sqrt(A) * math.sqrt(np.mean(np.minimum(r, 0) ** 2))
    return arc(r) / dd if dd > 0 else float("nan")


def max_drawdown(r=None, nav=None) -> float:
    if nav is None:
        nav = np.cumprod(1 + np.asarray(r, float))
    nav = np.asarray(nav, float)
    peak = np.maximum.accumulate(nav)
    return float(np.max((peak - nav) / peak)) if len(nav) else float("nan")


def max_drawdown_dollars(pnl) -> float:
    c = np.cumsum(np.asarray(pnl, float))
    peak = np.maximum.accumulate(np.concatenate([[0.0], c]))[1:]
    return float(np.max(peak - c)) if len(c) else float("nan")


def var_cvar(x, q: float = 0.95) -> tuple[float, float]:
    """Historical VaR / CVaR of the loss tail, returned as (negative) returns."""
    x = np.sort(np.asarray(x, float))
    if len(x) == 0:
        return float("nan"), float("nan")
    k = max(int(math.floor((1 - q) * len(x))), 1)
    return float(np.quantile(x, 1 - q)), float(x[:k].mean())


def moments(x) -> tuple[float, float]:
    """(skew, non-excess kurtosis) — population estimators as in Bailey & Lopez de Prado."""
    x = np.asarray(x, float)
    return float(stats.skew(x, bias=True)), float(stats.kurtosis(x, fisher=False, bias=True))


def psr(r, sr_star_daily: float = 0.0) -> float:
    """Probabilistic Sharpe Ratio with daily arithmetic SR (App. A)."""
    r = np.asarray(r, float)
    n = len(r)
    s = np.std(r, ddof=1)
    if n < 3 or s == 0:
        return float("nan")
    sr = np.mean(r) / s
    g3, g4 = moments(r)
    den = 1 - g3 * sr + (g4 - 1) / 4 * sr * sr
    if den <= 0:
        return float("nan")
    return float(stats.norm.cdf((sr - sr_star_daily) * math.sqrt(n - 1) / math.sqrt(den)))


def expected_max_sr(n_obs: int, n_trials: int) -> float:
    if n_trials <= 1:
        return 0.0
    v = 1.0 / (n_obs - 1)
    return math.sqrt(v) * ((1 - EULER) * stats.norm.ppf(1 - 1 / n_trials)
                           + EULER * stats.norm.ppf(1 - 1 / (n_trials * math.e)))


def dsr(r, n_trials: int, sr_star_daily: float = 0.0) -> float:
    n = len(r)
    return psr(r, max(sr_star_daily, expected_max_sr(n, n_trials)))


def stationary_bootstrap_means(x, mean_block: float = 10.0, reps: int = 10_000, seed: int = 7) -> np.ndarray:
    """Politis-Romano stationary bootstrap of the sample mean (vectorised)."""
    x = np.asarray(x, float)
    n = len(x)
    rng = np.random.default_rng(seed)
    p = 1.0 / mean_block
    idx = np.empty((reps, n), dtype=np.int64)
    idx[:, 0] = rng.integers(0, n, reps)
    new = rng.random((reps, n)) < p
    starts = rng.integers(0, n, (reps, n))
    for t in range(1, n):
        idx[:, t] = np.where(new[:, t], starts[:, t], (idx[:, t - 1] + 1) % n)
    return x[idx].mean(axis=1)


def block_bootstrap_means(x, block: int = 20, reps: int = 10_000, seed: int = 11) -> np.ndarray:
    x = np.asarray(x, float)
    n = len(x)
    rng = np.random.default_rng(seed)
    nb = int(math.ceil(n / block))
    st = rng.integers(0, n - block + 1, (reps, nb))
    idx = (st[:, :, None] + np.arange(block)[None, None, :]).reshape(reps, -1)[:, :n]
    return x[idx].mean(axis=1)


def diebold_mariano(a, b, h: int = 1) -> tuple[float, float]:
    d = np.asarray(a, float) - np.asarray(b, float)
    n = len(d)
    dbar = d.mean()
    g0 = np.var(d, ddof=0)
    lrv = g0 + 2 * sum((1 - k / h) * np.cov(d[k:], d[:-k], ddof=0)[0, 1] for k in range(1, h))
    stat = dbar / math.sqrt(lrv / n) if lrv > 0 else float("nan")
    return float(stat), float(2 * (1 - stats.norm.cdf(abs(stat))))


def remove_best_days(pnl, k: int) -> np.ndarray:
    x = np.asarray(pnl, float)
    if k <= 0:
        return x
    keep = np.argsort(x)[:-k]
    return x[np.sort(keep)]


def summary_returns(r: pd.Series, n_trials: int = 1) -> dict:
    """Full panel for a NAV-return series indexed by date."""
    x = r.values.astype(float)
    g3, g4 = moments(x) if len(x) > 2 else (float("nan"), float("nan"))
    v95, c95 = var_cvar(x, 0.95)
    v99, c99 = var_cvar(x, 0.99)
    years = (r.index[-1] - r.index[0]).days / 365.25 if len(r) > 1 else float("nan")
    growth = float(np.prod(1 + x))
    return {
        "n_days": len(x), "sharpe_arith": sharpe_arithmetic(x), "sharpe_geom": sharpe_geometric(x),
        "cagr_per_obs": arc(x), "cagr_calendar": growth ** (1 / years) - 1 if years and years > 0 else float("nan"),
        "ann_vol": asd(x), "sortino": sortino(x), "max_dd": max_drawdown(x),
        "worst_day": float(x.min()), "best_day": float(x.max()),
        "var95": v95, "cvar95": c95, "var99": v99, "cvar99": c99,
        "skew": g3, "kurtosis": g4, "psr0": psr(x), "dsr": dsr(x, n_trials),
    }


def summary_pnl(pnl: pd.Series, nav0: float | None = None) -> dict:
    """One-contract dollar P&L panel (zero on no-trade days)."""
    x = pnl.values.astype(float)
    traded = x != 0
    boot = stationary_bootstrap_means(x) if len(x) > 20 else np.array([np.nan])
    tot = x.sum()
    top5 = np.sort(x)[-5:].sum() if len(x) >= 5 else float("nan")
    out = {
        "n_days": len(x), "n_trades": int(traded.sum()), "trade_rate": float(traded.mean()),
        "total_pnl": float(tot), "mean_daily_pnl": float(x.mean()),
        "mean_trade_pnl": float(x[traded].mean()) if traded.any() else float("nan"),
        "win_rate": float((x[traded] > 0).mean()) if traded.any() else float("nan"),
        "sharpe_arith_daily_pnl": sharpe_arithmetic(x) if x.std() > 0 else float("nan"),
        "worst_day": float(x.min()), "best_day": float(x.max()),
        "max_dd_dollars": max_drawdown_dollars(x),
        "top5_share_of_total": float(top5 / tot) if tot > 0 else float("nan"),
        "total_minus_best5": float(remove_best_days(x, 5).sum()),
        "total_minus_best10": float(remove_best_days(x, 10).sum()),
        "boot_p_mean_gt0": float((boot > 0).mean()),
        "boot_mean_ci95": (float(np.quantile(boot, 0.025)), float(np.quantile(boot, 0.975))),
    }
    if nav0:
        nav = nav0 + np.cumsum(x)
        r = np.diff(np.concatenate([[nav0], nav])) / np.concatenate([[nav0], nav[:-1]])
        out.update({"nav_sharpe_arith": sharpe_arithmetic(r), "nav_sharpe_geom": sharpe_geometric(r),
                    "nav_cagr_per_obs": arc(r), "nav_max_dd": max_drawdown(nav=np.concatenate([[nav0], nav]))})
    return out
