"""Feature assembly with the paper's timing rules (App. B, tab:feature_timing).

Row (day d, strategy s) may use:
  * same-day values fixed by 10:00 ET (calendar, morning window, 09:35/10:00 surface, entry
    Greeks/liquidity/intra-strategy context);
  * anything observed at a close only via the previous session (lag 1);
  * per-strategy outcome statistics under a lag policy:
      P-LAG  (paper-literal): trades entered on or before d-1;
      A-LAG  (availability-correct): trades whose settlement session < d.
Group tags drive the S4 caps; scope tags drive S3.
"""
from __future__ import annotations

import datetime as dt
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from .calendar import fomc_table, sessions

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"
REF = ROOT / "data" / "reference"

GROUP_PRIORITY = ["position", "vol_surface", "intra", "liquidity", "regime", "strategy", "morning",
                  "vix", "rv_iv", "vix_curvature", "spx", "higher_moments", "calendar", "macro", "trend"]


# ------------------------------------------------------------------ daily source series
@lru_cache(maxsize=1)
def daily_sources() -> pd.DataFrame:
    idx = pd.Index([d.date() for d in sessions("2015-06-01")], name="date")
    df = pd.DataFrame(index=idx)
    f = pd.read_csv(RAW / "SP500_fred.csv")
    f.columns = ["date", "spx"]
    f["date"] = pd.to_datetime(f["date"]).dt.date
    df = df.join(f.set_index("date")["spx"].apply(pd.to_numeric, errors="coerce"))
    for s in ("VIX", "VIX9D", "VIX3M", "VIX6M", "VVIX", "VIX1D"):
        x = pd.read_csv(RAW / "cboe_idx" / f"{s}_History.csv")
        x.columns = [c.strip().upper() for c in x.columns]
        x["DATE"] = pd.to_datetime(x["DATE"], format="mixed").dt.date
        col = "CLOSE" if "CLOSE" in x.columns else x.columns[-1]
        df = df.join(x.set_index("DATE")[col].rename(s))
    vx = pd.read_parquet(PROC / "vx_curve.parquet").set_index("date")
    df = df.join(vx)
    e = pd.read_csv(RAW / "EFFR.csv")
    e.columns = ["date", "effr"]
    e["date"] = pd.to_datetime(e["date"]).dt.date
    df = df.join(e.set_index("date")["effr"].apply(pd.to_numeric, errors="coerce") / 100)
    c = pd.read_csv(RAW / "ICNSA.csv")
    c.columns = ["date", "claims"]
    c["date"] = pd.to_datetime(c["date"]).dt.date + dt.timedelta(days=5)  # week ending Sat -> released Thu
    df = df.join(c.set_index("date")["claims"].apply(pd.to_numeric, errors="coerce"), how="left")
    pcr = pd.read_csv(RAW / "cboe_pcr.csv")
    pcr["date"] = pd.to_datetime(pcr["date"]).dt.date
    df = df.join(pcr.set_index("date")[["spx_put_call_ratio", "vix_put_call_ratio"]], how="left")
    return df.sort_index().ffill()


def _pct_rank(s: pd.Series, w: int = 252) -> pd.Series:
    return s.rolling(w + 1, min_periods=w // 2).apply(lambda x: np.mean(x[:-1] < x[-1]), raw=True)


def close_based_cs(surface_close: pd.DataFrame) -> pd.DataFrame:
    """CS features observed at the close of day d (to be lagged 1 session by the caller)."""
    d = daily_sources().copy()
    out = pd.DataFrame(index=d.index)
    p = d["spx"]
    lr = np.log(p).diff()
    for name, n in (("1d", 1), ("5d", 5), ("10d", 10), ("1m", 21), ("3m", 63), ("6m", 126), ("1y", 252)):
        out[f"spx_{name}_returns"] = p / p.shift(n) - 1
    out["spx_returns_roll_avg_30d"] = out["spx_1d_returns"].rolling(30).mean()
    out["spx_returns_roll_std_30d"] = out["spx_1d_returns"].rolling(30).std()
    for n in (5, 21, 63, 252):
        out[f"spx_{n}d_rv"] = np.sqrt(252) * np.sqrt((lr ** 2).rolling(n).mean())
    out["spx_1y_percentile"] = _pct_rank(p)
    lo, hi = p.rolling(252).min(), p.rolling(252).max()
    out["spx_position_52w"] = (p - lo) / (hi - lo)
    for n in (21, 63):
        out[f"spx_realized_skew_{n}d"] = lr.rolling(n).skew()
        out[f"spx_realized_kurtosis_{n}d"] = lr.rolling(n).kurt()
    ma50, ma200 = p.rolling(50).mean(), p.rolling(200).mean()
    out["spx_distance_from_50dma_pct"] = (p - ma50) / ma50
    out["spx_distance_from_200dma_pct"] = (p - ma200) / ma200
    out["spx_50_200_dma_signal"] = np.sign(ma50 - ma200)
    out["spx_200dma_slope_21d_pct"] = ma200 / ma200.shift(21) - 1
    for s in ("VIX", "VIX1D", "VIX9D", "VIX3M", "VIX6M", "VVIX"):
        out[s] = d[s]
    for s in ("VIX1D", "VIX9D", "VIX3M", "VIX6M"):
        out[f"VIX_{s}_ratio"] = d["VIX"] / d[s]
        out[f"VIX_{s}_spread"] = d["VIX"] - d[s]
    for s in ("VIX", "VIX1D", "VVIX"):
        out[f"{s}_5d_pct_change"] = d[s] / d[s].shift(5) - 1
        out[f"{s}_21d_pct_change"] = d[s] / d[s].shift(21) - 1
        out[f"{s}_1y_percentile"] = _pct_rank(d[s])
    out["vix_futures_front_price"] = d["M1"]
    out["vix_front_slope"] = d["M2"] - d["M1"]
    out["vix_front_curvature"] = 2 * d["M2"] - d["M1"] - d["M3"]
    out["front_roll_yield"] = (d["M2"] - d["M1"]) / d["D1"]
    out["vix_z_60d"] = (d["VIX"] - d["VIX"].rolling(60).mean()) / d["VIX"].rolling(60).std()
    out["vix_curvature_9d_30d_3m"] = d["VIX9D"] - 2 * d["VIX"] + d["VIX3M"]
    out["vix_curvature_1d_9d_30d"] = d["VIX1D"] - 2 * d["VIX9D"] + d["VIX"]
    out["vix_curvature_1d_30d_3m"] = d["VIX1D"] - 2 * d["VIX"] + d["VIX3M"]
    for k in ("spx", "vix"):
        x = d[f"{k}_put_call_ratio"]
        out[f"{k}_put_call_ratio"] = x
        out[f"{k}_pcr_21d_avg"] = x.rolling(21).mean()
        out[f"{k}_pcr_5d_pct_change"] = x / x.shift(5) - 1
        out[f"{k}_pcr_21d_pct_change"] = x / x.shift(21) - 1
    out["effr_rate"] = d["effr"]
    out["effr_rate_1y_pct_change"] = d["effr"] / d["effr"].shift(252) - 1
    out["effr_rate_1y_percentile"] = _pct_rank(d["effr"])
    out["jobless_claims"] = d["claims"]
    out["jobless_claims_1y_pct_change"] = d["claims"] / d["claims"].shift(252) - 1
    out["jobless_claims_1y_percentile"] = _pct_rank(d["claims"])
    # morning VIX block (App. B): VIX/VVIX closes, lagged by the caller like every close value
    out["morning_vix_level"] = d["VIX"]
    out["morning_vix_change"] = d["VIX"].diff()
    out["morning_vvix_change"] = d["VVIX"].diff()
    # closing-surface block
    if surface_close is not None and len(surface_close):
        sc = surface_close.reindex(out.index)
        out = out.join(sc)
        for tau in (1, 5, 30):
            col = f"atmf_iv_{tau}dte_close"
            if col in out:
                out[f"atmf_iv_{tau}dte_percentile_252d"] = _pct_rank(out[col])
        def fwd(a, b, pre):
            ca, cb = f"{pre}_{a}dte_close", f"{pre}_{b}dte_close"
            if ca in out and cb in out:
                ta, tb = a / 252, b / 252
                v = (out[cb] ** 2 * tb - out[ca] ** 2 * ta) / (tb - ta)
                return np.sqrt(v.where(v > 0))
            return np.nan
        for a, b in ((5, 10), (5, 30), (10, 20), (20, 30), (30, 60)):
            out[f"atmf_forward_vol_{a}d_{b}d_close"] = fwd(a, b, "atmf_iv")
        for a, b in ((5, 30), (10, 20)):
            out[f"put_25d_forward_vol_{a}d_{b}d_close"] = fwd(a, b, "put_25d_iv")
        if "atmf_iv_5dte_close" in out:
            m5 = out["atmf_iv_5dte_close"].rolling(5).mean()
            out["rv_surprise_5d"] = (out["spx_5d_rv"] - m5) / m5
            out["rv_iv_spread_5d"] = out["spx_5d_rv"] - out["atmf_iv_5dte_close"]
            out["rv_iv_ratio_5d"] = out["spx_5d_rv"] / out["atmf_iv_5dte_close"]
        if "atmf_iv_20dte_close" in out:
            out["rv_iv_spread_21d"] = out["spx_21d_rv"] - out["atmf_iv_20dte_close"]
            out["rv_iv_ratio_21d"] = out["spx_21d_rv"] / out["atmf_iv_20dte_close"]
        if {"atmf_iv_30dte_close", "atmf_iv_5dte_close"} <= set(out):
            out["iv_term_slope_5d_30d"] = out["atmf_iv_30dte_close"] - out["atmf_iv_5dte_close"]
            out["rv_term_slope_5d_21d"] = out["spx_21d_rv"] - out["spx_5d_rv"]
            out["iv_minus_rv_term_slope"] = out["iv_term_slope_5d_30d"] - out["rv_term_slope_5d_21d"]
        for tau in (0, 1, 5, 10, 20, 30):
            col = f"atmf_iv_{tau}dte_close"
            if col in out:
                out[f"iv_to_spot_change_ratio_{tau}dte_close"] = out[col].pct_change() / out["spx_1d_returns"].replace(0, np.nan)
    return out


def calendar_cs(days: list[dt.date]) -> pd.DataFrame:
    idx = pd.Index(days, name="date")
    out = pd.DataFrame(index=idx)
    s = pd.to_datetime(pd.Series(days, index=idx))
    out["day_of_week"] = s.dt.weekday + 1
    out["day_of_month"] = s.dt.day
    out["month_of_year"] = s.dt.month
    third_fri = (s.dt.weekday == 4) & (s.dt.day >= 15) & (s.dt.day <= 21)
    out["is_monthly_opex"] = third_fri.astype(float)
    out["is_quarterly_opex"] = (third_fri & s.dt.month.isin([3, 6, 9, 12])).astype(float)
    all_s = [d.date() for d in sessions("2015-01-01")]
    pos = {d: i for i, d in enumerate(all_s)}
    prev_gap = {d: (d - all_s[i - 1]).days if i > 0 else 1 for d, i in pos.items()}
    next_gap = {d: (all_s[i + 1] - d).days if i + 1 < len(all_s) else 1 for d, i in pos.items()}
    out["is_post_holiday_session"] = [float(prev_gap.get(d, 1) > (3 if d.weekday() == 0 else 1)) for d in days]
    out["is_pre_holiday_session"] = [float(next_gap.get(d, 1) > (3 if d.weekday() == 4 else 1)) for d in days]
    fomc = sorted(fomc_table().query("kind in ['scheduled','cancelled']")["date"])
    ev = {"fomc": fomc}
    mr = REF / "macro_release_dates.csv"
    if mr.exists():
        m = pd.read_csv(mr, parse_dates=["date"])
        for e, g in m.groupby("event"):
            ev[e] = sorted(g["date"].dt.date)

    def count_to(d, dates, forward=True):
        if forward:
            nxt = [x for x in dates if x >= d]
            return len([s for s in all_s if d <= s < nxt[0]]) if nxt else np.nan
        prv = [x for x in dates if x < d]
        return len([s for s in all_s if prv[-1] <= s < d]) if prv else np.nan

    for e, dates in ev.items():
        if e != "fomc":
            out[f"is_{e}_day"] = [float(d in set(dates)) for d in days]
        out[f"days_until_next_{e}"] = [count_to(d, dates, True) for d in days]
    out["days_since_last_fomc"] = [count_to(d, ev["fomc"], False) for d in days]
    return out


# ------------------------------------------------------------------ per-strategy features
PS_ENTRY = ["delta", "gamma", "theta", "vega", "dollar_delta", "gamma_exposure", "log_moneyness", "leverage",
            "entry_bid_ask_spread", "entry_bid_ask_spread_pct", "entry_log_premium",
            "delta_distance_from_target", "iv_at_strike_minus_atmf", "iv_at_strike_minus_atmf_pct",
            "dte_of_selected_option"]


def entry_ps(c: pd.DataFrame, atmf_iv_entry: float) -> pd.DataFrame:
    x = c.copy()
    S = x["spot"]
    x["dollar_delta"] = x["delta"].abs() * 100
    x["gamma_exposure"] = -x["gamma"].abs() * 100 * S
    x["log_moneyness"] = np.log(x["strike"] / S)
    x["leverage"] = (S * x["delta"] / x["mid"]).abs()
    x["entry_bid_ask_spread"] = x["ask"] - x["bid"]
    x["entry_bid_ask_spread_pct"] = (x["ask"] - x["bid"]) / x["mid"]
    x["entry_log_premium"] = np.log(x["mid"])
    x["iv_at_strike_minus_atmf"] = x["iv"] - atmf_iv_entry
    x["iv_at_strike_minus_atmf_pct"] = x["iv_at_strike_minus_atmf"] / atmf_iv_entry
    x["dte_of_selected_option"] = x["dte_sessions"]
    return x


def rolling_ps(hist: pd.DataFrame, day: dt.date, policy: str) -> pd.DataFrame:
    """Per-strategy statistics from outcome history, respecting the lag policy.

    hist columns: day, strategy, mid, label_gross, outcome_settle_day, spx_1d_return_on_day.
    """
    if policy == "P-LAG":
        h = hist[hist["day"] < day]
    elif policy == "A-LAG":
        h = hist[hist["outcome_settle_day"] < day]
    else:
        raise ValueError(policy)
    rows = []
    for s, g in h.groupby("strategy"):
        g = g.sort_values("day")
        rom = g["label_gross"] / g["mid"]
        C = (g["label_gross"] * 100).cumsum()
        rec = {"strategy": s, "returns_on_margin": rom.iloc[-1] if len(rom) else np.nan}
        rec["rom_diff_to_spx"] = rec["returns_on_margin"] - g["spx_1d_return_on_day"].iloc[-1] if len(g) else np.nan
        r30, r60 = rom.tail(30), rom.tail(60)
        rec["rom_roll_avg_30d"] = r30.mean()
        rec["rom_roll_std_30d"] = r30.std()
        rec["rom_roll_skew_30d"] = r30.skew()
        sr = rom.rolling(60, min_periods=20).mean() / rom.rolling(60, min_periods=20).std()
        rec["sharpe_ratio_rom_60d"] = sr.iloc[-1] if len(sr) else np.nan
        rec["sharpe_ratio_rom_std_60d"] = sr.tail(60).std()
        for n in (63, 126, 252):
            w = C.tail(n)
            mx = w.max() if len(w) else np.nan
            rec[f"drawdown_{n}d"] = (mx - C.iloc[-1]) / mx if len(w) and mx > 0 else np.nan
            rec[f"distance_from_max_{n}d"] = C.iloc[-1] - mx if len(w) else np.nan
        rec["win_rate_30d"] = (r30 > 0).mean() if len(r30) else np.nan
        if len(r60) >= 10:
            rec["stability_coef_60d"] = np.corrcoef(r60.values, np.arange(len(r60)))[0, 1] ** 2
        q05 = r30.quantile(0.05) if len(r30) else np.nan
        rec["tail_ratio_rom_30d"] = abs(r30.quantile(0.95)) / abs(q05) if q05 not in (0, np.nan) and len(r30) else np.nan
        w5 = C.tail(5)
        rec["prior_day_strategy_drawdown_max_5d"] = float((w5.cummax() - w5).max()) if len(w5) else np.nan
        rows.append(rec)
    return pd.DataFrame(rows)


INTERACTIONS = {
    "delta_x_VIX": ("delta", "VIX"),
    "gamma_x_morning_spx_rv_annualized": ("gamma", "morning_spx_rv_annualized"),
    "vega_x_VIX_5d_pct_change": ("vega", "VIX_5d_pct_change"),
    "iv_at_strike_minus_atmf_x_VIX_VIX9D_spread": ("iv_at_strike_minus_atmf", "VIX_VIX9D_spread"),
    "theta_x_atmf_iv_5dte_percentile_252d": ("theta", "atmf_iv_5dte_percentile_252d"),
    "delta_distance_from_target_x_VVIX_1y_percentile": ("delta_distance_from_target", "VVIX_1y_percentile"),
    "gamma_x_dte": ("gamma", "dte_of_selected_option"),
}
WD_RANK = ["iv_at_strike_minus_atmf", "returns_on_margin", "sharpe_ratio_rom_60d", "drawdown_63d",
           "entry_bid_ask_spread_pct", "entry_log_premium"]


def add_interactions_and_ranks(panel: pd.DataFrame) -> pd.DataFrame:
    p = panel.copy()
    for name, (a, b) in INTERACTIONS.items():
        if a in p and b in p:
            p[name] = p[a] * p[b]
    is_skip = p["strategy"] == "SKIP"
    for f in WD_RANK:
        if f in p:
            r = p[~is_skip].groupby("date")[f].rank(method="average")
            p[f + "_wd_rank"] = r
            p.loc[is_skip, f + "_wd_rank"] = 8.5
    return p


def group_of(f: str) -> tuple[str, str]:
    """(scope, group) for S3/S4. Tail-risk features are source-tagged (paper §6.3)."""
    ps_entry = set(PS_ENTRY)
    if f in INTERACTIONS:
        return "PS", "regime"
    if f.endswith("_wd_rank"):
        return "PS", group_of(f[:-8])[1]
    if f in {"delta", "gamma", "theta", "vega", "dollar_delta", "gamma_exposure", "log_moneyness", "leverage"}:
        return "PS", "position"
    if f.startswith("entry_"):
        return "PS", "liquidity"
    if f in ps_entry:
        return "PS", "intra"
    if f in {"returns_on_margin", "rom_diff_to_spx", "rom_roll_avg_30d", "rom_roll_std_30d", "rom_roll_skew_30d",
             "sharpe_ratio_rom_60d", "sharpe_ratio_rom_std_60d", "win_rate_30d", "stability_coef_60d",
             "tail_ratio_rom_30d", "prior_day_strategy_drawdown_max_5d"} or f.startswith(("drawdown_", "distance_from_max_")):
        return "PS", "strategy"
    if f.startswith("morning_"):
        return "CS", "morning"
    if f.startswith(("day_of", "month_of", "is_", "days_")):
        return "CS", "calendar"
    if f.startswith(("effr", "jobless")):
        return "CS", "macro"
    if f.startswith("vix_curvature"):
        return "CS", "vix_curvature"
    if f.startswith(("rv_iv", "iv_term", "rv_term", "iv_minus_rv")):
        return "CS", "rv_iv"
    if f.startswith("spx_realized"):
        return "CS", "higher_moments"
    if f.startswith(("spx_distance", "spx_50_200", "spx_200dma")):
        return "CS", "trend"
    if f.startswith(("spx_", "vix_put", "vix_pcr")):
        return "CS", "spx"
    if f.startswith(("VIX", "VVIX", "vix_", "front_roll")):
        return "CS", "vix"
    return "CS", "vol_surface"


# ------------------------------------------------------------------ the paper's catalog (App. B)
def paper_catalog() -> list[str]:
    """Exact feature names listed in App. B. Only these may reach the model (PAPER_SPEC §4).
    PCR (8) and CPI/NFP (4) are listed but not buildable (RESEARCH_LEDGER #15)."""
    cal = ["day_of_week", "day_of_month", "month_of_year", "is_monthly_opex", "is_quarterly_opex",
           "is_post_holiday_session", "is_pre_holiday_session", "days_until_next_fomc", "days_since_last_fomc",
           "is_cpi_day", "days_until_next_cpi", "is_nfp_day", "days_until_next_nfp", "is_pce_day", "days_until_next_pce"]
    morning = ["morning_spx_log_return", "morning_spx_range_pct", "morning_spx_rv_annualized",
               "morning_spx_directionality", "morning_gap_size", "morning_gap_filled", "morning_atmf_iv_change",
               "morning_atmf_iv_pct_change", "morning_skew_change", "morning_vix_level", "morning_vix_change",
               "morning_vvix_change"]
    spx = [f"spx_{n}_returns" for n in ("1d", "5d", "10d", "1m", "3m", "6m", "1y")] + \
          ["spx_returns_roll_avg_30d", "spx_returns_roll_std_30d"] + [f"spx_{n}d_rv" for n in (5, 21, 63, 252)] + \
          ["spx_1y_percentile", "spx_position_52w", "spx_put_call_ratio", "spx_pcr_21d_avg", "spx_pcr_5d_pct_change",
           "spx_pcr_21d_pct_change", "vix_put_call_ratio", "vix_pcr_21d_avg", "vix_pcr_5d_pct_change",
           "vix_pcr_21d_pct_change"]
    vix = ["VIX", "VIX1D", "VIX9D", "VIX3M", "VIX6M", "VVIX"] + \
          [f"VIX_{s}_{k}" for s in ("VIX1D", "VIX9D", "VIX3M", "VIX6M") for k in ("ratio", "spread")] + \
          [f"{s}_{n}_pct_change" for s in ("VIX", "VIX1D", "VVIX") for n in ("5d", "21d")] + \
          [f"{s}_1y_percentile" for s in ("VIX", "VIX1D", "VVIX")] + \
          ["vix_futures_front_price", "vix_front_slope", "vix_front_curvature", "front_roll_yield", "vix_z_60d"]
    macro = ["effr_rate", "effr_rate_1y_pct_change", "effr_rate_1y_percentile", "jobless_claims",
             "jobless_claims_1y_pct_change", "jobless_claims_1y_percentile"]
    surf = [f"atmf_iv_{t}dte_close" for t in (1, 5, 20, 30, 60, 90)] + ["atmf_iv_1dte_1000", "atmf_iv_5dte_1000"] + \
           [f"{r}_25d_iv_{t}dte_close" for r in ("call", "put") for t in (5, 30)] + \
           [f"atmf_iv_{t}dte_percentile_252d" for t in (1, 5, 30)] + \
           [f"risk_reversal_delta25_{t}dte_close" for t in (1, 5, 10, 20, 30)] + \
           [f"risk_reversal_delta10_{t}dte_close" for t in (0, 1, 5, 10, 20, 30)] + \
           [f"{s}_skew_delta25_{t}dte_close" for s in ("put", "call") for t in (1, 5, 20, 30)] + \
           [f"atmf_forward_vol_{a}d_{b}d_close" for a, b in ((5, 10), (5, 30), (10, 20), (20, 30), (30, 60))] + \
           [f"put_25d_forward_vol_{a}d_{b}d_close" for a, b in ((5, 30), (10, 20))] + ["rv_surprise_5d"] + \
           [f"iv_to_spot_change_ratio_{t}dte_close" for t in (0, 1, 5, 10, 20, 30)] + \
           [f"atmf_iv_{t}dte_intraday_{k}" for t in (0, 10, 30) for k in ("pct_change", "range")]
    rviv = ["rv_iv_spread_5d", "rv_iv_ratio_5d", "rv_iv_spread_21d", "rv_iv_ratio_21d", "iv_term_slope_5d_30d",
            "rv_term_slope_5d_21d", "iv_minus_rv_term_slope"]
    hm = [f"spx_realized_{k}_{n}d" for k in ("skew", "kurtosis") for n in (21, 63)]
    curv = ["vix_curvature_9d_30d_3m", "vix_curvature_1d_9d_30d", "vix_curvature_1d_30d_3m"]
    trend = ["spx_distance_from_50dma_pct", "spx_distance_from_200dma_pct", "spx_50_200_dma_signal",
             "spx_200dma_slope_21d_pct"]
    position = ["delta", "gamma", "theta", "vega", "dollar_delta", "gamma_exposure", "log_moneyness", "leverage"]
    strat = ["returns_on_margin", "rom_diff_to_spx", "rom_roll_avg_30d", "rom_roll_std_30d", "rom_roll_skew_30d",
             "sharpe_ratio_rom_60d", "sharpe_ratio_rom_std_60d"] + [f"drawdown_{n}d" for n in (63, 126, 252)] + \
            [f"distance_from_max_{n}d" for n in (63, 126, 252)] + \
            ["win_rate_30d", "stability_coef_60d", "tail_ratio_rom_30d", "prior_day_strategy_drawdown_max_5d",
             "iv_at_strike_minus_atmf_wd_rank", "returns_on_margin_wd_rank", "sharpe_ratio_rom_60d_wd_rank",
             "drawdown_63d_wd_rank"]
    liq = ["entry_bid_ask_spread", "entry_bid_ask_spread_pct", "entry_log_premium",
           "entry_bid_ask_spread_pct_wd_rank", "entry_log_premium_wd_rank"]
    intra = ["delta_distance_from_target", "iv_at_strike_minus_atmf", "iv_at_strike_minus_atmf_pct",
             "dte_of_selected_option"]
    return cal + morning + spx + vix + macro + surf + rviv + hm + curv + trend + position + strat + liq + intra + list(INTERACTIONS)
