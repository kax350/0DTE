"""Retail V2 selection, PASS criteria, kill tests, tail/regime/capital tables (prereg §7–§12).

    python scripts/v2_verdict.py --period conf

Reads results/retail_v2/<period>/{summary.json, paired.json, daily/series.pkl, model_*/...}.
Writes results/retail_v2/<period>/verdict.json and tables_*.csv.
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
from vrp_ltr import retail_metrics as RM  # noqa: E402

CANDS = ["B2-EDGE", "B2-TS", "R1", "R2-A", "R2-B", "R3", "R4-1.0", "R4-1.5", "R4-2.0"]
ML = ("R1", "R2-A", "R2-B", "R3")
SIMPLICITY = {"R0": 0, "B2-TS": 1, "B2-EDGE": 1, "R4-1.0": 2, "R4-1.5": 2, "R4-2.0": 2, "R2-A": 3, "R2-B": 3,
              "R3": 4, "R1": 5}
NOT_EXEC = {"delta-unavailable", "no-quote", "no-long-strike", "below-min-credit", "fill-breaches-cap", "size-zero",
            "no-fill", "no-settlement", "no-strike-shift"}
CRITICAL = ["K1", "K2", "K4", "K5", "K7", "K9", "K10", "K12", "K25"]


def load(period: str, sub: str = ""):
    d = ROOT / "results" / "retail_v2" / period / sub
    if not (d / "summary.json").exists():
        return None, None, None
    S = pd.read_json(d / "summary.json")
    P = pd.read_json(d / "paired.json") if (d / "paired.json").exists() else pd.DataFrame()
    ser = pd.read_pickle(d / "daily" / "series.pkl")
    return S, P, ser


def row(S, product, tag, rule):
    x = S[(S["product"] == product) & (S["tag"] == tag) & (S["rule"] == rule)]
    return x.iloc[0].to_dict() if len(x) else None


def kill_tests(S, ser, rule, nav0, models: dict) -> dict:
    base = ser[("XSP", "PRIMARY", rule)]
    pnl = base["pnl"]
    tr = base.loc[base["traded"] == 1, "pnl"]
    K = {}
    for k in ("K1", "K2", "K3", "K4", "K5", "K6", "K7", "K8", "K16", "K17", "K18", "K18-S1"):
        r = row(S, "XSP", k, rule)
        K[k] = {"value": r["total_pnl"] if r else None, "survive": bool(r and r["total_pnl"] > 0)}
    k14 = [row(S, "XSP", t, rule) for t in ("K14+", "K14-")]
    K["K14"] = {"value": [r["total_pnl"] if r else None for r in k14], "survive": all(r and r["total_pnl"] > 0 for r in k14)}
    K["K9"] = {"value": RM.remove_period(pnl, "M", "best"), "survive": RM.remove_period(pnl, "M", "best") > 0}
    K["K10"] = {"value": RM.remove_period(pnl, "Y", "best"), "survive": RM.remove_period(pnl, "Y", "best") > 0}
    K["K11"] = {"value": RM.remove_period(pnl, "Y", "worst"), "survive": RM.remove_period(pnl, "Y", "worst") > 0,
                "reported_only": True}
    v12 = RM.remove_top(tr, 5)
    K["K12"] = {"value": v12, "survive": bool(np.isfinite(v12) and v12 > 0)}
    v13 = RM.remove_top(tr, 5, worst=True)
    K["K13"] = {"value": v13, "survive": bool(np.isfinite(v13) and v13 > 0), "reported_only": True,
                "worst5_share_of_gross_profit": float(-np.sort(tr.values)[:5].sum() / tr[tr > 0].sum())
                if (tr > 0).any() else None}
    bp = float((M.block_bootstrap_means(pnl.values) > 0).mean())
    K["K25"] = {"value": bp, "survive": bp >= 0.90}
    if rule in ML:
        for k, labs in (("K15", ["corr080", "corr090"]), ("K19", ["roll3y"]), ("K20", ["seed1"]),
                        ("K21", ["nomacro"]), ("K22", ["top20"])):
            vals = []
            for lab in labs:
                m = models.get(lab)
                r = row(m[0], "XSP", "PRIMARY", rule) if m and m[0] is not None else None
                vals.append(r["total_pnl"] if r else None)
            app = all(v is not None for v in vals)
            K[k] = {"value": vals, "survive": all(v > 0 for v in vals) if app else None, "applicable": app}
        r0 = ser[("XSP", "PRIMARY", "R0")]["pnl"]
        K["K23"] = {"value": float(pnl.sum() - r0.sum()), "survive": float(pnl.sum() - r0.sum()) > 0}
        if rule in ("R1", "R3"):
            r2 = ser[("XSP", "PRIMARY", "R2-A")]["pnl"]
            K["K24"] = {"value": float(pnl.sum() - r2.sum()), "survive": float(pnl.sum() - r2.sum()) > 0}
    for k in ("K15", "K19", "K20", "K21", "K22", "K23", "K24"):
        K.setdefault(k, {"value": None, "survive": None, "applicable": False})
    crit = all(K[k]["survive"] for k in CRITICAL)
    nonc = [k for k in K if k not in CRITICAL and not K[k].get("reported_only") and K[k].get("applicable", True)
            and K[k]["survive"] is not None]
    frac = float(np.mean([K[k]["survive"] for k in nonc])) if nonc else float("nan")
    return {"tests": K, "critical_all": crit, "noncritical_frac": frac, "noncritical_n": len(nonc)}


def p1_exec(df) -> float:
    want = df[~df["reason"].isin(["flat", "edge<hurdle"])]
    return float((want["traded"] == 1).mean()) if len(want) else float("nan")


def criteria(S, ser, rule, nav0, kt) -> dict:
    df = ser[("XSP", "PRIMARY", rule)]
    s = row(S, "XSP", "PRIMARY", rule)
    yrs = s["yearly"]
    pos = sum(1 for v in yrs.values() if v > 0)
    need = 3 if len(yrs) >= 4 else len(yrs)
    C = {"P1_exec_ratio": p1_exec(df), "P2_mean": s["mean_daily_pnl"], "P2_boot": s.get("boot_p_stationary"),
         "P3_years_pos": f"{pos}/{len(yrs)}", "P5_maxdd_pct": s["max_dd_pct"]}
    C["P1"] = C["P1_exec_ratio"] >= 0.80
    C["P2"] = bool(s["mean_daily_pnl"] > 0 and (s.get("boot_p_stationary") or 0) >= 0.95)
    C["P2_weak"] = bool(s["mean_daily_pnl"] > 0 and 0.90 <= (s.get("boot_p_stationary") or 0) < 0.95)
    C["P3"] = pos >= need
    C["P4"] = bool(kt["tests"]["K12"]["survive"] and kt["tests"]["K9"]["survive"])
    C["P5"] = s["max_dd_pct"] <= 0.15
    C["P6"] = bool(kt["critical_all"] and (kt["noncritical_frac"] >= 2 / 3))
    tr = df[df["traded"] == 1]
    C["hard_constraints"] = bool(len(tr) == 0 or ((tr["max_loss"] <= 0.02 * nav0 + 1e-6).all()
                                                 and (tr["n"] == tr["n"].round()).all()))
    return C


def tail_tables(ser, rules, period_days=None) -> dict:
    out = {}
    for rule in rules:
        df = ser.get(("XSP", "PRIMARY", rule))
        if df is None:
            continue
        tr = df[df["traded"] == 1]
        by = {}
        if "target" in tr:
            for t, g in tr.groupby("target"):
                by[f"{int(round(t * 100))}D"] = {"trades": int(len(g)), "pnl": float(g["pnl"].sum()),
                                                 "worst": float(g["pnl"].min()), "mean": float(g["pnl"].mean()),
                                                 "loss_rate": float((g["pnl"] < 0).mean())}
        out[rule] = by
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", default="conf")
    a = ap.parse_args()
    S, P, ser = load(a.period)
    nav0 = 25_000.0
    models = {}
    base_dir = ROOT / "results" / "retail_v2" / a.period
    for d in sorted(base_dir.glob("model_*")):
        models[d.name[6:]] = load(a.period, d.name)
    # ---- §7 incremental alpha vs R0 (primary, XSP)
    PP = P[(P["product"] == "XSP") & (P["tag"] == "PRIMARY")].set_index("rule")
    inc = {}
    for c in CANDS:
        pr = PP.loc[c].to_dict()
        ny = pr["n_years"]
        inc[c] = {"mean_diff": pr["mean_diff"], "p_stationary": pr["p_stationary"], "p_block": pr["p_block"],
                  "dm_p": pr["dm_p"], "years_positive": f"{pr['years_positive']}/{ny}",
                  "incremental": bool(pr["p_stationary"] >= 0.95 and pr["dm_p"] < 0.05
                                      and pr["years_positive"] >= (3 if ny >= 4 else ny))}
    qualified = [c for c in CANDS if inc[c]["incremental"]]
    # ---- §8 selection
    kts = {r: kill_tests(S, ser, r, nav0, models) for r in ["R0"] + CANDS}

    def rank_key(c):
        s = row(S, "XSP", "PRIMARY", c)
        k18 = sum(1 for k in ("K1", "K2", "K3", "K4", "K5", "K6", "K7", "K8") if kts[c]["tests"][k]["survive"])
        l5 = s.get("largest5_losses_over_total")
        return (-s["mean_daily_pnl"], -inc[c]["p_stationary"], s["max_dd"], l5 if l5 == l5 and l5 is not None else 9,
                -k18, SIMPLICITY[c])
    chosen = sorted(qualified, key=rank_key)[0] if qualified else "R0"
    crit = {r: criteria(S, ser, r, nav0, kts[r]) for r in ["R0"] + CANDS}
    C = crit[chosen]
    spy = row(S, "SPY", "PRIMARY", chosen)
    spy_ok = bool(spy and spy["mean_daily_pnl"] > 0)
    core = all(C[k] for k in ("P1", "P3", "P4", "P5", "P6", "hard_constraints"))
    if core and C["P2"] and chosen in ML:
        verdict = "PASS (historical) — live use gated on P8 forward shadow"
    elif core and (C["P2"] or C["P2_weak"]):
        verdict = "WEAK PASS (historical) — simple strategy; live use gated on P8"
    else:
        verdict = "FAIL / NO RETAIL EDGE"
    if verdict.startswith("PASS") and not spy_ok:
        verdict = "WEAK PASS (historical) — NOT CONFIRMED ON SPY"
    elif verdict.startswith("WEAK") and not spy_ok:
        verdict += " — NOT CONFIRMED ON SPY"
    # ---- tables
    prim = S[S["tag"] == "PRIMARY"].drop(columns=["reasons", "loss_vs_annual"], errors="ignore")
    prim.to_csv(base_dir / "tables_primary.csv", index=False)
    ex = S[(S["product"] == "XSP") & (S["tag"].isin(["PRIMARY", "MID@10:03", "STRESS@10:03", "DL@10:01", "DL@10:03",
                                                       "DL@10:05"]))]
    ex[["tag", "rule", "n_trades", "total_pnl", "mean_daily_pnl", "sharpe_ann", "max_dd", "boot_p_stationary"]] \
        .to_csv(base_dir / "tables_execution.csv", index=False)
    dl = {}
    for t in ("DL@10:01", "DL@10:03", "DL@10:05"):
        for rule in ("R0",) + ML:
            d = ser.get(("XSP", t, rule))
            n = ser.get(("XSP", "PRIMARY", rule))
            if d is None:
                continue
            sub = d[d["reason"].isin(["no-fill"]) | (d["traded"] == 1)]
            filled, missed = sub.index[sub["traded"] == 1], sub.index[sub["reason"] == "no-fill"]
            dl[f"{t}|{rule}"] = {"submitted": int(len(sub)), "fill_rate": float(len(filled) / len(sub)) if len(sub) else None,
                                 "nat_pnl_mean_filled_days": float(n.loc[filled, "pnl"].mean()) if len(filled) else None,
                                 "nat_pnl_mean_missed_days": float(n.loc[missed, "pnl"].mean()) if len(missed) else None}
    grid = S[(S["product"] == "XSP") & (S["tag"].str.startswith(("risk", "nav", "mincredit")))]
    grid[["tag", "rule", "n_trades", "total_pnl", "mean_daily_pnl", "sharpe_ann", "max_dd", "worst_trade",
          "contracts_mean"]].to_csv(base_dir / "tables_grid.csv", index=False)
    reg = []
    for rule in ["R0"] + CANDS:
        df = ser[("XSP", "PRIMARY", rule)]
        v = df["vix_prev"]
        b = pd.cut(v, [-np.inf, 15, 25, np.inf], labels=["<15", "15-25", ">25"])
        r0 = ser[("XSP", "PRIMARY", "R0")]["pnl"]
        for lab, g in df.groupby(b, observed=False):
            reg.append({"rule": rule, "vix_prev": str(lab), "days": int(len(g)), "trades": int(g["traded"].sum()),
                        "pnl": float(g["pnl"].sum()), "diff_vs_R0": float((g["pnl"] - r0.reindex(g.index)).sum())})
    pd.DataFrame(reg).to_csv(base_dir / "tables_regime.csv", index=False)
    mod = []
    for lab, (Sm, Pm, sm) in models.items():
        if Sm is None:
            continue
        for rule in ML:
            r = row(Sm, "XSP", "PRIMARY", rule)
            pr = Pm[(Pm["rule"] == rule) & (Pm["tag"] == "PRIMARY") & (Pm["product"] == "XSP")]
            if r:
                mod.append({"model": lab, "rule": rule, "total_pnl": r["total_pnl"], "sharpe_ann": r["sharpe_ann"],
                            "max_dd": r["max_dd"], "yearly": r["yearly"],
                            "diff_vs_R0": float(pr["total_diff"].iloc[0]) if len(pr) else None,
                            "p_stationary": float(pr["p_stationary"].iloc[0]) if len(pr) else None})
    pd.DataFrame(mod).to_json(base_dir / "tables_models.json", orient="records", indent=1)
    res = {"period": a.period, "incremental_alpha_vs_R0": inc, "qualified": qualified, "chosen": chosen,
           "criteria": crit, "spy_validation": {"rule": chosen, "mean_daily_pnl": spy["mean_daily_pnl"] if spy else None,
                                                "total_pnl": spy["total_pnl"] if spy else None, "ok": spy_ok},
           "verdict": verdict, "kill_tests": kts, "delayed_limit": dl,
           "tail_by_delta": tail_tables(ser, ["R0", "R1", "R3", "R2-A"])}
    (base_dir / "verdict.json").write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps({k: res[k] for k in ("qualified", "chosen", "verdict", "spy_validation")}, indent=1, default=str))
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk in ("P1", "P2", "P2_weak", "P3", "P4", "P5", "P6",
                                                                 "P1_exec_ratio", "P2_boot", "P3_years_pos",
                                                                 "P5_maxdd_pct")}
                      for k, v in crit.items()}, indent=0, default=str)[:4000])


if __name__ == "__main__":
    main()
