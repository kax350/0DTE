"""Retail V2 statistics: loss structure, tail, capital, paired tests vs always-5Δ (prereg §7, §10)."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy.stats import norm

from . import metrics as M


def dm_hac(d) -> tuple[float, float]:
    """Diebold–Mariano on a loss differential with Newey–West HAC, lag floor(4(T/100)^(2/9)).
    Returns (t, one-sided p for H1: mean d > 0)."""
    d = np.asarray(d, float)
    n = len(d)
    if n < 10:
        return float("nan"), float("nan")
    L = int(math.floor(4 * (n / 100.0) ** (2.0 / 9.0)))
    x = d - d.mean()
    lrv = x @ x / n
    for k in range(1, L + 1):
        lrv += 2 * (1 - k / (L + 1)) * (x[k:] @ x[:-k]) / n
    if lrv <= 0:
        return float("nan"), float("nan")
    t = d.mean() / math.sqrt(lrv / n)
    return float(t), float(1 - norm.cdf(t))


def _maxdd(pnl: pd.Series, nav0: float):
    """(MaxDD $, first day of the drawdown episode, trough day)."""
    full = np.r_[nav0, nav0 + pnl.cumsum().values]       # full[k] = NAV after k days
    peak = np.maximum.accumulate(full)
    dd = full - peak
    i = int(np.argmin(dd))
    if dd[i] >= 0:
        return 0.0, None, None
    j = int(np.flatnonzero(full[: i + 1] == peak[i])[-1])  # last peak before the trough
    return float(-dd[i]), pnl.index[j], pnl.index[i - 1]


def summarize(df: pd.DataFrame, nav0: float, n_trials: int | None = None) -> dict:
    pnl = df["pnl"].astype(float)
    tr = df[df["traded"] == 1]
    tp = tr["pnl"].astype(float)
    n = len(pnl)
    r = pnl / nav0
    sd = r.std(ddof=1)
    out = {"n_days": n, "n_trades": int(len(tr)), "trade_rate": len(tr) / n if n else np.nan,
           "trades_per_month": len(tr) / (n / 21.0) if n else np.nan,
           "total_pnl": float(pnl.sum()), "mean_daily_pnl": float(pnl.mean()) if n else np.nan,
           "sharpe_ann": float(r.mean() / sd * math.sqrt(252)) if n > 2 and sd > 0 else np.nan,
           "sortino_ann": float(M.sortino(r.values) * math.sqrt(252)) if n > 2 else np.nan,
           "win_rate": float((tp > 0).mean()) if len(tp) else np.nan,
           "avg_win": float(tp[tp > 0].mean()) if (tp > 0).any() else np.nan,
           "avg_loss": float(tp[tp <= 0].mean()) if (tp <= 0).any() else np.nan,
           "avg_credit": float(tr["credit"].mean()) if len(tr) else np.nan}
    dd, p0, p1 = _maxdd(pnl, nav0)
    out.update(max_dd=dd, max_dd_pct=dd / nav0, dd_start=str(p0), dd_end=str(p1))
    if dd > 0 and p0 is not None:
        epi = pnl.loc[p0:p1]
        out["single_trade_share_of_maxdd"] = float(-epi.min() / dd) if epi.min() < 0 else 0.0
    idx = pd.to_datetime(pd.Index(pnl.index))
    s = pd.Series(pnl.values, idx)
    out.update(worst_trade=float(tp.min()) if len(tp) else 0.0, best_trade=float(tp.max()) if len(tp) else 0.0,
               worst_week=float(s.resample("W").sum().min()), worst_month=float(s.resample("ME").sum().min()))
    for q, nm in ((0.95, "cvar95"), (0.99, "cvar99")):
        if len(tp) >= 20:
            k = max(int(math.floor((1 - q) * len(tp))), 1)
            out[nm] = float(np.sort(tp.values)[:k].mean())
        else:
            out[nm] = np.nan
    yearly = s.groupby(s.index.year).sum()
    out["yearly"] = {int(y): float(v) for y, v in yearly.items()}
    lt = {}
    for y, g in tp.groupby(pd.to_datetime(pd.Index(tp.index)).year):
        a = yearly.get(y, np.nan)
        losses = np.sort(g.values[g.values < 0])
        lt[int(y)] = {"annual": float(a), "largest_loss": float(losses[0]) if len(losses) else 0.0,
                      "largest_loss_over_annual": float(-losses[0] / a) if len(losses) and a > 0 else np.nan,
                      "largest3_over_annual": float(-losses[:3].sum() / a) if len(losses) and a > 0 else np.nan}
    out["loss_vs_annual"] = lt
    losses = np.sort(tp.values[tp.values < 0])
    out["largest5_losses_over_total"] = float(-losses[:5].sum() / pnl.sum()) if pnl.sum() > 0 else np.nan
    out["largest5_losses"] = float(losses[:5].sum()) if len(losses) else 0.0
    if n > 20:
        out["boot_p_stationary"] = float((M.stationary_bootstrap_means(pnl.values) > 0).mean())
        out["boot_p_block"] = float((M.block_bootstrap_means(pnl.values) > 0).mean())
        out["psr0"] = float(M.psr(r.values))
        out["dsr"] = float(M.dsr(r.values, n_trials)) if n_trials else np.nan
    if len(tr):
        out.update(util_median=float(tr["util"].median()), util_p95=float(tr["util"].quantile(0.95)),
                   util_max=float(tr["util"].max()), margin_median=float(tr["margin"].median()),
                   margin_p95=float(tr["margin"].quantile(0.95)), margin_max=float(tr["margin"].max()),
                   contracts_mean=float(tr["n"].mean()))
    out["reasons"] = df["reason"].replace("", "traded").value_counts().to_dict()
    return out


def paired(x: pd.DataFrame, base: pd.DataFrame) -> dict:
    d = (x["pnl"] - base["pnl"].reindex(x.index)).astype(float)
    t, p = dm_hac(d.values)
    yrs = d.groupby(pd.to_datetime(pd.Index(d.index)).year).mean()
    return {"mean_diff": float(d.mean()), "total_diff": float(d.sum()),
            "p_stationary": float((M.stationary_bootstrap_means(d.values) > 0).mean()) if len(d) > 20 else np.nan,
            "p_block": float((M.block_bootstrap_means(d.values) > 0).mean()) if len(d) > 20 else np.nan,
            "dm_t": t, "dm_p": p, "mean_diff_by_year": {int(k): float(v) for k, v in yrs.items()},
            "years_positive": int((yrs > 0).sum()), "n_years": int(len(yrs))}


def incremental_alpha(pr: dict, min_years: int = 3) -> bool:
    return bool(pr["p_stationary"] >= 0.95 and pr["dm_p"] < 0.05 and pr["years_positive"] >= min_years)


def remove_top(pnl: pd.Series, k: int, worst: bool = False) -> float:
    v = np.sort(pnl.values)
    return float(v[k:].sum() if worst else v[:-k].sum()) if len(v) > k else float("nan")


def remove_period(pnl: pd.Series, freq: str, which: str = "best") -> float:
    s = pd.Series(pnl.values, pd.to_datetime(pd.Index(pnl.index)))
    g = s.groupby(s.index.year if freq == "Y" else s.index.to_period("M")).sum()
    drop = g.idxmax() if which == "best" else g.idxmin()
    return float(g.drop(drop).sum())
