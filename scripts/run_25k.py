"""$25k adaptations + kill tests + PASS evaluation (PREREGISTRATION §4, §5, §8).

    python scripts/run_25k.py --policy P-LAG --gate G-UNION --root XSP

Short leg = SPXW M-HEAD pick (strategy name), resolved on the product's own chain.
Primary candidate (named in advance): X-CAP2, NAT, fill 10:03, 1 lot.
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from vrp_ltr import metrics as M  # noqa: E402
from vrp_ltr import registry  # noqa: E402
from vrp_ltr.defined_risk import run  # noqa: E402
from run_experiments import load_picks  # noqa: E402

VARIANTS_X = ["NAKED", "W5", "W10", "CAP1", "CAP2", "CAP4"]
LEVELS = ["MID", "NAT", "NAT1"]
FILLS = ["10:00", "10:01", "10:03", "10:05"]
PRIMARY = ("CAP2", "NAT", "10:03")
YEARS = [2021, 2022, 2023, 2024, 2025, 2026]


def load_dp(root):
    d = {}
    for f in sorted((ROOT / "data" / "processed" / root / "dp").glob("*.pkl")):
        with open(f, "rb") as fh:
            d[pd.Timestamp(f.stem).date()] = pickle.load(fh)
    return d


def stats(df: pd.DataFrame) -> dict:
    out = {}
    pnl = df["pnl"]
    for name, sel in {"ALL_2021_2026": lambda y: 2021 <= y <= 2026, "WF_2021_2024": lambda y: 2021 <= y <= 2024,
                      **{str(y): (lambda yy: (lambda y: y == yy))(y) for y in YEARS}}.items():
        x = pnl[[sel(d.year) for d in pnl.index]]
        if len(x) < 5:
            continue
        r = df.loc[x.index, "ret"]
        s = M.summary_pnl(x)
        out[name] = {"n_days": len(x), "trades": int(df.loc[x.index, "traded"].sum()), "net_pnl": float(x.sum()),
                     "mean_daily": float(x.mean()), "sharpe_arith": M.sharpe_arithmetic(r.values),
                     "sharpe_geom": M.sharpe_geometric(r.values), "cagr_obs": M.arc(r.values), "max_dd": M.max_drawdown(r.values),
                     "worst_day": float(x.min()), "top5_share": s["top5_share_of_total"],
                     "minus_best5": s["total_minus_best5"], "minus_best10": s["total_minus_best10"],
                     "boot_p_gt0": s["boot_p_mean_gt0"], "cvar95": M.var_cvar(r.values)[1],
                     "max_theoretical_loss": float(df.loc[x.index, "max_loss"].max()),
                     "max_loss_pct_nav": float((df.loc[x.index, "max_loss"] / df.loc[x.index, "nav_prev"]).max())}
    return out


def pass_eval(res: dict, key_primary: str, cap_pct: float) -> dict:
    p = res[key_primary]
    g = lambda k: p.get(k, {})  # noqa: E731
    yrs_pos = sum(1 for y in ("2021", "2022", "2023", "2024", "2025") if g(y).get("net_pnl", -1) > 0)
    crit = {
        "1_net_positive": g("ALL_2021_2026").get("mean_daily", -1) > 0,
        "2_wf_sharpe_gt1": g("WF_2021_2024").get("sharpe_arith", -9) > 1.0,
        "3_2025_sharpe_gt1": g("2025").get("sharpe_arith", -9) > 1.0,
        "4_2026_sharpe_gt0": g("2026").get("sharpe_arith", -9) > 0.0,
        "5_4of5_years_positive": yrs_pos >= 4,
        "6_maxdd_lt10pct": g("ALL_2021_2026").get("max_dd", 1) < 0.10,
        "7_maxloss_within_budget": (g("ALL_2021_2026").get("max_loss_pct_nav") or 0) <= cap_pct + 1e-9,
        "8_nat_positive": res.get(key_primary.replace("|NAT1|", "|NAT|"), p).get("ALL_2021_2026", {}).get("mean_daily", -1) > 0,
        "9_delay_1001_1003_positive": all(res.get(key_primary.replace("10:03", t), {}).get("ALL_2021_2026", {}).get("mean_daily", -1) > 0
                                          for t in ("10:01", "10:03")),
        "10_minus_best5_positive": g("ALL_2021_2026").get("minus_best5", -1) > 0,
        "11_bootstrap_p95": g("ALL_2021_2026").get("boot_p_gt0", 0) >= 0.95,
    }
    fails = [k for k, v in crit.items() if not v]
    weak = set(fails) <= {"2_wf_sharpe_gt1", "3_2025_sharpe_gt1"} and all(
        g(k).get("sharpe_arith", -9) > 0.5 for k in (("WF_2021_2024",) if "2_wf_sharpe_gt1" in fails else ()) +
        (("2025",) if "3_2025_sharpe_gt1" in fails else ()))
    verdict = "PASS" if not fails else ("WEAK PASS" if weak else "FAIL")
    return {"criteria": crit, "failed": fails, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", default="P-LAG")
    ap.add_argument("--gate", default="G-UNION")
    ap.add_argument("--root", default="XSP")
    a = ap.parse_args()
    picks = load_picks(a.policy, a.gate)["M-HEAD"]
    dp = load_dp(a.root)
    res, series = {}, {}
    exits = [None] if a.root == "XSP" else ["15:45", "15:55"]
    variants = VARIANTS_X if a.root == "XSP" else [v for v in VARIANTS_X if v != "NAKED"]
    for v in variants:
        for lvl in LEVELS:
            for ft in FILLS:
                for ex in exits:
                    key = f"{a.root}|{v}|{lvl}|{ft}|{ex}"
                    df = run(picks, dp, a.root, v, lvl, ft, ex)
                    registry.record(f"25k|{a.policy}|{a.gate}|{key}", "2021-2026")
                    series[key] = df
                    res[key] = stats(df)
    out = ROOT / "results" / a.policy / f"25k_{a.root}_{a.gate}.json"
    evals = {}
    for ex in exits:
        pk = f"{a.root}|{PRIMARY[0]}|{PRIMARY[1]}|{PRIMARY[2]}|{ex}"
        if pk in res:
            evals[pk] = pass_eval(res, pk, 0.02)
    out.write_text(json.dumps({"results": res, "primary_eval": evals, "n_trials": registry.n_trials()}, indent=1, default=float))
    pd.to_pickle(series, out.with_suffix(".pkl"))
    print(json.dumps(evals, indent=1, default=str))


if __name__ == "__main__":
    main()
