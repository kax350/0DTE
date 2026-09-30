"""One-contract selection test + baselines (PREREGISTRATION §2, §3, §8 selection-alpha verdict).

    python scripts/run_experiments.py --policy P-LAG --gate G-UNION

Reads results/<policy>/<window>/picks_*.parquet and the SPXW day panels.
Writes results/<policy>/one_contract_*.csv/json. Every series is recorded in the trial registry.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from vrp_ltr import metrics as M  # noqa: E402
from vrp_ltr import registry  # noqa: E402
from vrp_ltr.assemble import load_candidates  # noqa: E402
from vrp_ltr.backtest import SINGLE_EXEC, one_contract_series  # noqa: E402
from vrp_ltr.calendar import sessions  # noqa: E402
from vrp_ltr.config import SKIP, STRATEGIES  # noqa: E402
from vrp_ltr.gate import calibrate  # noqa: E402

PUTS = [s for s in STRATEGIES if s != SKIP]
SLICES = {"WF_2021_2024": (2021, 2024), "Y2021": (2021, 2021), "Y2022": (2022, 2022), "Y2023": (2023, 2023),
          "Y2024": (2024, 2024), "OOT_2025": (2025, 2025), "EXT_2026": (2026, 2026)}


def load_picks(policy: str, gate_variant: str) -> dict[str, pd.Series]:
    base = ROOT / "results" / policy
    head, skipnog, forced, gaps = [], [], [], []
    for w in ("WF1", "WF2", "WF3", "WF4", "OOT"):
        d = base / w
        if not (d / "picks_head.parquet").exists():
            continue
        h = pd.read_parquet(d / "picks_head.parquet")
        f = pd.read_parquet(d / "picks_forced.parquet")
        meta = json.loads((d / "meta.json").read_text())
        tau = meta["gate"]["tau"]
        h["window"] = w
        h["tau"] = tau
        head.append(h)
        forced.append(f["pick"])
    H = pd.concat(head)
    if gate_variant == "G-UNION" and (H["window"] == "OOT").any():
        # tab:gate: OOT threshold calibrated on the union of the WF test-year predictions
        wf = H[H["window"] != "OOT"]
        cands = load_candidates(sorted(wf.index))
        t = cands.set_index(["date", "strategy"])["net_L1"]
        pnl = pd.Series([0.0 if s == SKIP else float(t.get((d, s), 0.0) or 0.0) for d, s in wf["pick"].items()], index=wf.index)
        H.loc[H["window"] == "OOT", "tau"] = calibrate(wf["gap"], pnl)["tau"]
    gated = H.apply(lambda r: r["pick"] if (r["pick"] != SKIP and r["gap"] >= r["tau"]) else SKIP, axis=1)
    return {"M-HEAD": gated, "M-SKIP": H["pick"], "M-FORCED": pd.concat(forced)}


def baselines(cands: pd.DataFrame, days: list, train_best: dict) -> dict[str, pd.Series]:
    out = {f"B-FIX-{s[1:]}": pd.Series(s, index=days) for s in PUTS}
    rng_out = {}
    for seed in range(100):
        rng = np.random.default_rng(seed)
        rng_out[seed] = pd.Series(rng.choice(PUTS, len(days)), index=days)
    out["B-RAND-0"] = rng_out[0]
    # rolling baselines use settled outcomes only (A-LAG timing)
    t = cands.pivot_table(index="date", columns="strategy", values="net_L1")
    settle = cands.pivot_table(index="date", columns="strategy", values="outcome_settle_day", aggfunc="first")
    rb, rs, mo = {}, {}, {}
    for d in days:
        known = t[settle.max(axis=1) < d] if len(t) else t
        tail = known.tail(30)
        rb[d] = tail.mean().idxmax() if len(tail) >= 10 else None
        sr = tail.mean() / tail.std()
        rs[d] = sr.idxmax() if len(tail) >= 10 else None
        mo[d] = known.iloc[-1].idxmax() if len(known) else None
    out["B-ROLLBEST"] = pd.Series(rb)
    out["B-ROLLSHARPE"] = pd.Series(rs)
    out["B-MOM"] = pd.Series(mo)
    out["B-FIX-BESTTRAIN"] = pd.Series({d: train_best.get(d.year) for d in days})
    return out, rng_out


def best_train_bucket(cands: pd.DataFrame) -> dict[int, str]:
    """For each test year Y, the fixed bucket with the best one-contract L1 Sharpe on 2018..Y-1."""
    t = cands.pivot_table(index="date", columns="strategy", values="net_L1").fillna(0.0)
    out = {}
    for y in range(2021, 2027):
        tr = t[(t.index >= pd.Timestamp("2018-01-01").date()) & (t.index < pd.Timestamp(f"{y}-01-01").date())]
        if len(tr):
            out[y] = (tr.mean() / tr.std()).idxmax()
    return out


def slice_stats(s: pd.Series) -> dict:
    res = {}
    for name, (a, b) in SLICES.items():
        x = s[[a <= d.year <= b for d in s.index]]
        if len(x) > 5:
            st = M.summary_pnl(x, nav0=25_000.0)
            res[name] = {k: st[k] for k in ("n_days", "n_trades", "total_pnl", "mean_daily_pnl", "sharpe_arith_daily_pnl",
                                            "win_rate", "worst_day", "max_dd_dollars", "top5_share_of_total",
                                            "total_minus_best5", "boot_p_mean_gt0")}
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", default="P-LAG")
    ap.add_argument("--gate", default="G-UNION")
    a = ap.parse_args()
    out = ROOT / "results" / a.policy
    picks = load_picks(a.policy, a.gate)
    days = sorted(picks["M-HEAD"].index)
    cands = load_candidates([d.date() for d in sessions("2018-01-01", "2026-12-31")])
    tb = best_train_bucket(cands)
    base, rnd = baselines(cands, days, tb)
    allp = {**picks, **base}
    table = {}
    for name, p in allp.items():
        p = p.reindex(days)
        for lvl in SINGLE_EXEC:
            s = one_contract_series(p, cands, lvl)
            registry.record(f"SPXW|1lot|{a.policy}|{a.gate}|{name}|{lvl}", "2021-2026")
            table[(name, lvl)] = s
    rows = []
    for (name, lvl), s in table.items():
        for sl, st in slice_stats(s).items():
            rows.append({"strategy": name, "level": lvl, "slice": sl, **st})
    R = pd.DataFrame(rows)
    R.to_csv(out / f"one_contract_{a.gate}.csv", index=False)
    # random baseline distribution (L1, WF and OOT)
    rd = []
    for seed, p in rnd.items():
        s = one_contract_series(p.reindex(days), cands, "L1")
        for sl in ("WF_2021_2024", "OOT_2025"):
            a0, b0 = SLICES[sl]
            x = s[[a0 <= d.year <= b0 for d in s.index]]
            rd.append({"seed": seed, "slice": sl, "total": x.sum(), "sharpe": M.sharpe_arithmetic(x.values)})
    pd.DataFrame(rd).to_csv(out / "random_baseline_distribution.csv", index=False)
    # selection-alpha verdict: M-HEAD vs B-FIX-BESTTRAIN, paired stationary bootstrap of the daily difference
    verdict = {}
    for lvl in ("L1", "L2", "L3", "L3_1003"):
        d = table[("M-HEAD", lvl)] - table[("B-FIX-BESTTRAIN", lvl)]
        wf = d[[2021 <= x.year <= 2024 for x in d.index]]
        o25 = d[[x.year == 2025 for x in d.index]]
        b = M.stationary_bootstrap_means(wf.values) if len(wf) > 20 else np.array([np.nan])
        verdict[lvl] = {"wf_mean_diff": float(wf.mean()), "wf_boot_p_gt0": float((b > 0).mean()),
                        "oot2025_mean_diff": float(o25.mean()) if len(o25) else None,
                        "pass": bool((b > 0).mean() >= 0.95 and len(o25) and o25.mean() > 0)}
    (out / f"selection_alpha_{a.gate}.json").write_text(json.dumps({"train_best_bucket": tb, "verdict": verdict}, indent=1, default=str))
    pd.to_pickle({k: v for k, v in table.items()}, out / f"one_contract_series_{a.gate}.pkl")
    print(json.dumps(verdict, indent=1))


if __name__ == "__main__":
    main()
