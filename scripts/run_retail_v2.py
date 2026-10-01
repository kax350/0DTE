"""Retail V2 evaluation (RETAIL_V2_PREREGISTRATION.md + A1).

    python scripts/run_retail_v2.py --period dev      # 2021-2022 (DEVELOPMENT; engine debugging)
    python scripts/run_retail_v2.py --period conf     # 2023-01-03 .. 2026-09-29 (CONFIRMATORY)

Outputs: results/retail_v2/<period>/ (aggregates committed; per-day logs git-ignored).
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
sys.path.insert(0, str(ROOT / "scripts"))
from vrp_ltr import registry  # noqa: E402
from vrp_ltr import retail as RT  # noqa: E402
from vrp_ltr import retail_metrics as RM  # noqa: E402
from vrp_ltr.assemble import load_candidates  # noqa: E402
from vrp_ltr.calendar import sessions  # noqa: E402
from vrp_ltr.config import SKIP  # noqa: E402
from vrp_ltr.data import spx_minute  # noqa: E402
from vrp_ltr.features import daily_sources  # noqa: E402

PERIODS = {"dev": ("2021-01-01", "2022-12-31"), "conf": ("2023-01-01", "2026-09-29")}
TARGET = {f"P{int(x):02d}": x / 100 for x in (5, 10, 15, 20, 25, 30, 40, 45)}
OUT = ROOT / "results" / "retail_v2"
ML_RULES = ("R1", "R2-A", "R2-B", "R3")


# ------------------------------------------------------------------------------ inputs
def build_ctx() -> RT.Ctx:
    df = spx_minute.load()
    hm = df["bar_start"].dt.strftime("%H:%M")
    rth = df[(hm >= "09:30") & (hm < "16:00")]
    sess = [d.date() for d in sessions("2016-06-01", "2026-12-31")]
    pos = {d: i for i, d in enumerate(sess)}
    rv1, S10, SC, MC = {}, {}, {}, {}
    for d, g in rth.groupby("date"):
        v = g["close"].values
        if len(v) <= 60:
            continue
        rv1[d] = float(np.sqrt(np.mean(np.diff(np.log(v)) ** 2)))
        S10[d], SC[d], MC[d] = float(v[29]), float(v[-1]), len(v) - 30
    sigma5 = {}
    for d in sess:
        i = pos[d]
        vals = [rv1[p] for p in sess[max(i - 5, 0):i] if p in rv1]
        sigma5[d] = float(np.sqrt(np.mean(np.square(vals))) * math.sqrt(390)) if len(vals) >= 3 else np.nan
    z = {}
    for d in S10:
        s = sigma5.get(d, np.nan)
        if np.isfinite(s) and s > 0:
            z[d] = math.log(SC[d] / S10[d]) / (s * math.sqrt(MC[d] / 390.0))
    sb = {}
    for y in range(2019, 2027):
        x = [sigma5[d] for d in sess if 2018 <= d.year <= y - 1 and np.isfinite(sigma5.get(d, np.nan))]
        sb[y] = float(np.median(x)) if x else np.nan
    ds = daily_sources()
    vix_prev = ds["VIX"].shift(1).to_dict()
    return RT.Ctx(sigma5=sigma5, fhs_z=pd.Series(z).sort_index(), m_close=MC, sigma_bar=sb, vix_prev=vix_prev,
                  sessions=sess, pos=pos)


def load_scores(policy: str, ext: str = "B") -> pd.DataFrame:
    base = ROOT / "results" / policy
    parts = []
    for w in ("WF1", "WF2", "WF3", "WF4", "OOT"):
        f = base / w / "scores_test.parquet"
        if f.exists():
            parts.append(pd.read_parquet(f))
    f26 = base / "EXT_B" / "scores_test.parquet" if ext == "B" else base / "OOT" / "scores_ext_a.parquet"
    if f26.exists():
        parts.append(pd.read_parquet(f26))
    s = pd.concat(parts).pivot_table(index="date", columns="strategy", values="score")
    s.index = [pd.Timestamp(d).date() for d in s.index]
    return s


def decisions(ctx: RT.Ctx, days: list, policy: str = "A-LAG", ext: str = "B") -> dict[str, dict]:
    from run_experiments import load_picks
    D = {"B0": {d: None for d in days}, "R0": {d: 0.05 for d in days}}
    # B2-EDGE: F_hat_{2018..Y-1}(E_t) >= 0.50, E_t = (ATMF IV_0DTE,10:00 - sigma5*sqrt252)/(sigma5*sqrt252)
    cands = load_candidates([d.date() for d in sessions("2018-01-01", "2026-09-29")])
    atm = cands.groupby("date")["atmf_iv_entry"].first().to_dict()

    def E(d):
        s = ctx.sigma5.get(d, np.nan)
        a = atm.get(d, np.nan)
        rv = s * math.sqrt(252)
        return (a - rv) / rv if np.isfinite(a) and np.isfinite(rv) and rv > 0 else np.nan
    ecdf = {}
    for y in sorted({d.year for d in days}):
        v = np.sort([e for d in atm if 2018 <= d.year <= y - 1 and np.isfinite(e := E(d))])
        ecdf[y] = v
    D["B2-EDGE"] = {}
    for d in days:
        e, v = E(d), ecdf[d.year]
        D["B2-EDGE"][d] = 0.05 if np.isfinite(e) and len(v) and np.searchsorted(v, e, side="right") / len(v) >= 0.50 else None
    ds = daily_sources()
    v9, vx = ds["VIX9D"].shift(1).to_dict(), ds["VIX"].shift(1).to_dict()
    D["B2-TS"] = {d: 0.05 if np.isfinite(v9.get(d, np.nan)) and np.isfinite(vx.get(d, np.nan)) and v9[d] <= vx[d]
                  else None for d in days}
    # ML families
    picks = load_picks(policy, "G-UNION", ext)
    head = picks["M-HEAD"]
    sc = load_scores(policy, ext)
    D["R1"] = {d: (TARGET.get(head.get(d)) if head.get(d) not in (None, SKIP) else None) for d in days}
    D["R2-B"] = {d: (0.05 if head.get(d) not in (None, SKIP) else None) for d in days}
    D["R2-A"], D["R3"] = {}, {}
    for d in days:
        if d not in sc.index:
            D["R2-A"][d] = D["R3"][d] = None
            continue
        row = sc.loc[d]
        D["R2-A"][d] = 0.05 if row["P05"] > row[SKIP] else None
        best = row[["P05", "P10", "P15", SKIP]].astype(float).idxmax()
        D["R3"][d] = TARGET.get(best) if best != SKIP else None
    D["_has_scores"] = {d: d in sc.index for d in days}
    return D


def eval_days(root: str, start: str, end: str, has_scores: dict) -> tuple[list, dict]:
    keep, why = [], {}
    for d in (x.date() for x in sessions(start, end)):
        rp, rs = RT.load_rp(root, d), RT.load_rp("SPXW", d)
        if rp is None or rs is None:
            why[str(d)] = "no-panel"
        elif not (rp["is_0dte"] and rs["is_0dte"]):
            why[str(d)] = "no-0dte"
        elif not has_scores.get(d, False):
            why[str(d)] = "no-scores"
        else:
            keep.append(d)
    return keep, why


def rules_cfg(base: RT.Cfg) -> dict[str, tuple[str, RT.Cfg]]:
    """rule id -> (decision key, cfg)."""
    out = {r: (r, base) for r in ("B0", "R0", "B2-EDGE", "B2-TS", "R1", "R2-A", "R2-B", "R3")}
    for h in (1.0, 1.5, 2.0):
        out[f"R4-{h}"] = ("R0", RT.variant(base, edge_h=h))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", default="dev", choices=list(PERIODS))
    ap.add_argument("--products", default="XSP,SPY,SPXW")
    ap.add_argument("--quick", action="store_true", help="primary configuration only")
    a = ap.parse_args()
    start, end = PERIODS[a.period]
    out = OUT / a.period
    (out / "daily").mkdir(parents=True, exist_ok=True)
    ctx = build_ctx()
    alld = [x.date() for x in sessions(start, end)]
    D = decisions(ctx, alld)
    nt = registry.n_trials()
    summary, paired_rows, series = [], [], {}

    def go(tag, product, rule, dkey, cfg, days):
        df = RT.run(D[dkey], days, cfg, ctx)
        registry.record(f"V2|{a.period}|{product}|{tag}|{rule}", a.period)
        series[(product, tag, rule)] = df
        s = RM.summarize(df, cfg.nav0, max(nt, 1))
        summary.append({"product": product, "tag": tag, "rule": rule, **{k: v for k, v in s.items()}})
        return df

    base = RT.Cfg()
    for product in a.products.split(","):
        days, why = eval_days(product, start, end, D["_has_scores"])
        (out / f"excluded_days_{product}.json").write_text(json.dumps(why, indent=0))
        pb = RT.variant(base, root=product)
        R = rules_cfg(pb)
        prim = {}
        for rule, (dk, cfg) in R.items():
            prim[rule] = go("PRIMARY", product, rule, dk, cfg, days)
        go("PRIMARY", product, "R0-SNAP1000", "R0", RT.variant(pb, snap1000=True), days)
        for rule in R:
            if rule != "R0":
                paired_rows.append({"product": product, "tag": "PRIMARY", "rule": rule,
                                    **RM.paired(prim[rule], prim["R0"])})
        if a.quick or product != "XSP":
            continue
        # execution levels (XSP)
        for lvl, t in (("MID", "10:03"), ("STRESS", "10:03"), ("DL", "10:01"), ("DL", "10:03"), ("DL", "10:05")):
            tag = f"{lvl}@{t}"
            res = {}
            for rule, (dk, cfg) in R.items():
                res[rule] = go(tag, product, rule, dk, RT.variant(cfg, level=lvl, t_sub=t), days)
            for rule in R:
                if rule != "R0":
                    paired_rows.append({"product": product, "tag": tag, "rule": rule, **RM.paired(res[rule], res["R0"])})
        # risk x sizing
        for risk in (0.005, 0.01, 0.02):
            for sz in ("S0", "S1", "S2"):
                if risk == 0.02 and sz == "S0":
                    continue
                tag = f"risk{risk}_{sz}"
                res = {}
                for rule, (dk, cfg) in R.items():
                    res[rule] = go(tag, product, rule, dk, RT.variant(cfg, risk=risk, sizing=sz), days)
                for rule in R:
                    if rule != "R0":
                        paired_rows.append({"product": product, "tag": tag, "rule": rule,
                                            **RM.paired(res[rule], res["R0"])})
        # NAV grid and discretisation
        for nav in (10_000.0, 50_000.0):
            for sz in ("S0", "S1"):
                for rule, (dk, cfg) in R.items():
                    go(f"nav{int(nav)}_{sz}", product, rule, dk, RT.variant(cfg, nav0=nav, sizing=sz), days)
        for nav in (10_000.0, 25_000.0, 50_000.0):
            for rule, (dk, cfg) in R.items():
                go(f"nav{int(nav)}_S1_FRACTIONAL", product, rule, dk,
                   RT.variant(cfg, nav0=nav, sizing="S1", fractional=True), days)
                if nav == 25_000.0:
                    go("nav25000_S1", product, rule, dk, RT.variant(cfg, sizing="S1"), days)
        # minimum-credit sensitivity
        for mc in (0.02, 0.10):
            for rule, (dk, cfg) in R.items():
                go(f"mincredit{mc}", product, rule, dk, RT.variant(cfg, mincredit=mc), days)
        # kill tests K1-K8, K14, K16-K18 (engine variants); K9-K13, K25 from the primary series
        KV = {"K1": dict(fee_mult=2.0), "K2": dict(slip_k=1.5), "K3": dict(slip_k=2.0), "K4": dict(t_sub="10:01"),
              "K5": dict(t_sub="10:05"), "K6": dict(strike_shift=1), "K7": dict(credit_adj=-0.01),
              "K8": dict(credit_adj=-0.02), "K14+": dict(delta_shift=0.025), "K14-": dict(delta_shift=-0.025),
              "K16": dict(slip_k=2.0, fee_mult=2.0), "K17": dict(nav0=10_000.0), "K18": dict(nav0=50_000.0),
              "K18-S1": dict(nav0=50_000.0, sizing="S1")}
        for kt, kw in KV.items():
            for rule, (dk, cfg) in R.items():
                go(kt, product, rule, dk, RT.variant(cfg, **kw), days)
    # ---- write
    S = pd.DataFrame(summary)
    S.to_json(out / "summary.json", orient="records", indent=1, default_handler=str)
    flat = S.drop(columns=[c for c in ("yearly", "loss_vs_annual", "reasons") if c in S.columns])
    flat.to_csv(out / "summary.csv", index=False)
    P = pd.DataFrame(paired_rows)
    P.to_json(out / "paired.json", orient="records", indent=1)
    pd.to_pickle(series, out / "daily" / "series.pkl")
    print(flat[flat["tag"] == "PRIMARY"][["product", "rule", "n_days", "n_trades", "total_pnl", "sharpe_ann",
                                          "max_dd", "worst_trade", "boot_p_stationary"]].round(3).to_string(index=False))
    if len(P):
        print(P[P["tag"] == "PRIMARY"][["product", "rule", "mean_diff", "p_stationary", "dm_p", "years_positive"]]
              .round(3).to_string(index=False))


if __name__ == "__main__":
    main()
