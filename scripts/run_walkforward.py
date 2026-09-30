"""Walk-forward replication R0 (PREREGISTRATION §1) — SPXW, one-contract and paper sizing.

    python scripts/run_walkforward.py --policy P-LAG [--windows WF1,WF2,WF3,WF4,OOT] [--trials 50]

Per window: grades from the ranker slice, S1–S5 selection, Optuna, refit, gate, test-year picks.
Artifacts: results/<policy>/<window>/{model.txt, features.json, meta.json, picks.parquet}
The OOT/EXT models are hashed into models/*.sha256 before any 2025/2026 P&L is computed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from vrp_ltr import gate as G  # noqa: E402
from vrp_ltr.assemble import build, feature_coverage  # noqa: E402
from vrp_ltr.backtest import one_contract_series  # noqa: E402
from vrp_ltr.config import SKIP, WINDOWS  # noqa: E402
from vrp_ltr.label import fit_thresholds, grade, skip_grade_check  # noqa: E402
from vrp_ltr.model import predict, split_window, top_picks, tune_and_fit  # noqa: E402
from vrp_ltr.selection import select_features  # noqa: E402


def gate_pnl(panel, picks):
    t = panel[panel["strategy"] != SKIP].set_index(["date", "strategy"])["net_L1"]
    return pd.Series([0.0 if s == SKIP else float(t.get((d, s), 0.0) or 0.0) for d, s in picks["pick"].items()],
                     index=picks.index)


def run_window(panel, feats_all, name, policy, n_trials, outdir, opts=None):
    opts = opts or {}
    y0, y1, ytest = WINDOWS[name]
    if opts.get("rolling3y"):
        y0 = y1 - 2
    days = sorted(d for d in panel["date"].unique() if y0 <= d.year <= y1)
    sl = split_window(days, y1)
    ranker = panel[panel["date"].isin(set(sl["ranker"]))]
    thr = fit_thresholds(ranker.loc[ranker["strategy"] != SKIP, "label_score"].values)
    p = panel.copy()
    p["grade"] = grade(p["label_score"].values, thr)
    feats, info = select_features(p[p["date"].isin(set(sl["ranker"]))], feats_all)
    seed = 20260825 + list(WINDOWS).index(name) + int(opts.get("seed_offset", 0))
    model, tinfo = tune_and_fit(p, feats, sl, seed, n_trials)
    # gate on the held-out 6 months
    pg = p[p["date"].isin(set(sl["gate"]))]
    picks_g = top_picks(pg, predict(model, pg, feats))
    cal = G.calibrate(picks_g["gap"], gate_pnl(p, picks_g))
    # test-year predictions (window's own year only)
    pt = p[p["date"].map(lambda d: d.year == ytest)]
    out = {}
    if len(pt):
        sc = predict(model, pt, feats)
        out["head"] = top_picks(pt, sc)
        out["forced"] = top_picks(pt, sc, forced=True)
    if name == "OOT":  # TEST A: the frozen OOT model applied unchanged to 2026 (no retraining)
        p26 = p[p["date"].map(lambda d: d.year == 2026)]
        if len(p26):
            sc26 = predict(model, p26, feats)
            out["ext_a"] = top_picks(p26, sc26)
            out["ext_a_forced"] = top_picks(p26, sc26, forced=True)
    # in-sample picks on training days (for sizing calibration only)
    ptr = p[p["date"].isin(set(days))]
    out["train"] = top_picks(ptr, predict(model, ptr, feats))
    wdir = outdir / name
    wdir.mkdir(parents=True, exist_ok=True)
    model.save_model(str(wdir / "model.txt"))
    (wdir / "features.json").write_text(json.dumps(feats, indent=1))
    meta = {"window": name, "policy": policy, "thresholds": thr.tolist(), "skip_in_grade1": skip_grade_check(thr),
            "selection": info, "tuning": tinfo, "gate": {k: v for k, v in cal.items()},
            "n_train_days": len(days), "slices": {k: [str(v[0]), str(v[-1]), len(v)] if v else [] for k, v in sl.items()}}
    (wdir / "meta.json").write_text(json.dumps(meta, indent=1, default=str))
    for k, v in out.items():
        v.to_parquet(wdir / f"picks_{k}.parquet")
    h = hashlib.sha256((wdir / "model.txt").read_bytes()).hexdigest()
    (ROOT / "models").mkdir(exist_ok=True)
    (ROOT / "models" / f"{outdir.name}_{name}.sha256").write_text(h + "\n")
    return meta, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", default="P-LAG")
    ap.add_argument("--windows", default="WF1,WF2,WF3,WF4,OOT")
    ap.add_argument("--trials", type=int, default=50)
    ap.add_argument("--end", default="2026-12-31")
    ap.add_argument("--tag", default="")
    ap.add_argument("--seed-offset", type=int, default=0)
    ap.add_argument("--corr", type=float, default=None)
    ap.add_argument("--rolling3y", action="store_true")
    a = ap.parse_args()
    from vrp_ltr.config import PANEL_TAG
    outdir = ROOT / "results" / (a.policy + PANEL_TAG + a.tag)
    outdir.mkdir(parents=True, exist_ok=True)
    if a.corr is not None:
        import vrp_ltr.selection as S
        S.CORR_CLUSTER = a.corr
    opts = {"seed_offset": a.seed_offset, "rolling3y": a.rolling3y}
    panel, feats = build("2017-01-01", a.end, a.policy)
    feature_coverage(panel, feats).to_csv(outdir / "feature_coverage.csv", index=False)
    print("panel", panel.shape, "features", len(feats), flush=True)
    for w in a.windows.split(","):
        meta, _ = run_window(panel, feats, w, a.policy, a.trials, outdir, opts)
        print(w, json.dumps({k: meta[k] for k in ("thresholds", "skip_in_grade1", "selection", "gate")}, default=str)[:600],
              flush=True)


if __name__ == "__main__":
    main()
