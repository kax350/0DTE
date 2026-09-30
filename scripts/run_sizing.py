"""Paper sizing replication (7 methods, NAV0 $5M, equal-vol θ per window) + $25k discretisation.

    python scripts/run_sizing.py --policy P-LAG --gate G-UNION

Inputs per day (all known by 10:00): sigma_intra5d (prior 5 sessions of 1-min SPX returns),
0DTE ATMF IV at 10:00, VIX9D prior close, training-window ECDF/medians/p95, rolling Kelly on
settled picks. θ* is fitted on in-sample training picks (the paper's procedure, whose optimism
the paper itself acknowledges).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from vrp_ltr import metrics as M  # noqa: E402
from vrp_ltr import registry  # noqa: E402
from vrp_ltr.assemble import load_candidates  # noqa: E402
from vrp_ltr.backtest import calibrate_theta, sized_nav  # noqa: E402
from vrp_ltr.calendar import sessions  # noqa: E402
from vrp_ltr.config import PAPER_NAV0, SKIP, WINDOWS  # noqa: E402
from vrp_ltr.data import spx_minute  # noqa: E402
from vrp_ltr.features import daily_sources  # noqa: E402
from vrp_ltr.sizing import ecdf, edge_value  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
from run_experiments import load_picks  # noqa: E402


def intraday_inputs(days):
    df = spx_minute.load()
    rth = df[(df["bar_start"].dt.strftime("%H:%M") >= "09:30") & (df["bar_start"].dt.strftime("%H:%M") < "16:00")]
    by = {d: g["close"].values for d, g in rth.groupby("date")}
    sess = [d.date() for d in sessions("2016-06-01", "2026-12-31")]
    pos = {d: i for i, d in enumerate(sess)}
    rv1 = {d: float(np.sqrt(np.mean(np.diff(np.log(v)) ** 2))) for d, v in by.items() if len(v) > 50}
    out = {}
    for d in days:
        i = pos.get(d)
        prev = [sess[j] for j in range(max(i - 5, 0), i)] if i else []
        vals = [rv1[p] for p in prev if p in rv1]
        s5 = float(np.sqrt(np.mean(np.square(vals))) * math.sqrt(390)) if len(vals) >= 3 else np.nan
        v = by.get(d)
        adv = np.nan
        if v is not None and len(v) > 60:
            s10 = v[29]  # close of 09:59 bar = level at 10:00
            adv = float((s10 - v[30:].min()) / s10)
        out[d] = {"sigma_intra5d": s5, "adverse_after_10": adv}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", default="P-LAG")
    ap.add_argument("--gate", default="G-UNION")
    a = ap.parse_args()
    base = ROOT / "results" / a.policy
    picks = load_picks(a.policy, a.gate)["M-HEAD"]
    alldays = [d.date() for d in sessions("2018-01-01", "2026-12-31")]
    cands = load_candidates(alldays)
    atm = cands.groupby("date")["atmf_iv_entry"].first().to_dict()
    ii = intraday_inputs(alldays)
    vix9 = daily_sources()["VIX9D"].shift(1).to_dict()
    res, navs = {}, {}
    for method in ("EA", "FMU", "SRS", "VT", "GB", "HK", "QK"):
        nav = PAPER_NAV0
        pieces = []
        for w in ("WF1", "WF2", "WF3", "WF4", "OOT"):
            wd = base / w
            if not (wd / "picks_train.parquet").exists():
                continue
            y0, y1, yt = WINDOWS[w]
            tr_days = [d for d in alldays if y0 <= d.year <= y1]
            edges = np.array([edge_value(atm.get(d, np.nan), ii[d]["sigma_intra5d"]) for d in tr_days])
            F = ecdf(edges)
            rich = np.array([atm.get(d, np.nan) / (vix9.get(d, np.nan) / 100) for d in tr_days])
            rich = rich[np.isfinite(rich)]
            med, c95 = float(np.median(rich)), float(np.quantile(rich / np.median(rich), 0.95))
            kmove = float(np.nanquantile([ii[d]["adverse_after_10"] for d in tr_days], 0.95))

            def dx(days):
                out = {}
                for d in days:
                    e = edge_value(atm.get(d, np.nan), ii.get(d, {}).get("sigma_intra5d", np.nan))
                    R = atm.get(d, np.nan) / (vix9.get(d, np.nan) / 100)
                    out[d] = {"sigma_intra5d": ii.get(d, {}).get("sigma_intra5d", np.nan),
                              "edge_pct": F(e) if np.isfinite(e) else 0.0,
                              "richness_scale": min(c95, max(1.0, R / med)) if np.isfinite(R) else 1.0,
                              "k_move": kmove, "kelly_f": 0.0}
                return out
            ptr = pd.read_parquet(wd / "picks_train.parquet")["pick"]
            ptr = ptr[[d in set(tr_days) for d in ptr.index]]
            xtr = dx(list(ptr.index))
            theta, vol = calibrate_theta(ptr, cands, xtr, method, PAPER_NAV0)
            pt = picks[[d.year == yt for d in picks.index]]
            nav_df = sized_nav(pt, cands, dx(list(pt.index)), method, theta, nav)
            nav = nav + nav_df["pnl"].sum()
            nav_df["window"], nav_df["theta"], nav_df["train_vol"] = w, theta, vol
            pieces.append(nav_df)
        if not pieces:
            continue
        df = pd.concat(pieces)
        navs[method] = df
        registry.record(f"SPXW|paper-sizing|{a.policy}|{a.gate}|{method}", "2021-2025")
        r = df["ret"]
        res[method] = {}
        for sl, (y0, y1) in {"WF": (2021, 2024), "OOT_2025": (2025, 2025), "2021": (2021, 2021), "2022": (2022, 2022),
                             "2023": (2023, 2023), "2024": (2024, 2024)}.items():
            x = r[[y0 <= d.year <= y1 for d in r.index]]
            if len(x) > 5:
                s = M.summary_returns(x, registry.n_trials())
                res[method][sl] = {k: s[k] for k in ("sharpe_geom", "sharpe_arith", "cagr_per_obs", "ann_vol", "max_dd", "sortino", "psr0", "dsr")}
                res[method][sl]["trades"] = int((df.loc[x.index, "q"] > 0).sum())
        res[method]["theta_by_window"] = df.groupby("window")["theta"].first().to_dict()
    (base / f"paper_sizing_{a.gate}.json").write_text(json.dumps(res, indent=1, default=float))
    pd.to_pickle(navs, base / f"paper_sizing_nav_{a.gate}.pkl")
    print(json.dumps({m: {k: v for k, v in d.items() if k in ("WF", "OOT_2025")} for m, d in res.items()}, indent=1, default=float)[:3000])


if __name__ == "__main__":
    main()
