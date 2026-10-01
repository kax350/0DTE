"""V3 Layer A evaluation + pre-specified candidate selection (RETAIL_V3_LAYER_A_PROTOCOL.md).

    python scripts/v3_layer_a_eval.py
Writes results/retail_v3/layerA/{summary_XSP.csv, summary_SPXW.csv, selection.json}.
"""
from __future__ import annotations

import itertools
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import beta

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from vrp_ltr import metrics as M  # noqa: E402
from vrp_ltr import registry  # noqa: E402
from vrp_ltr.retail3 import VARIANTS  # noqa: E402

D = ROOT / "results" / "retail_v3" / "layerA"
NOT_SESSION = {"fomc", "no-0dte-chain", "no-spot-or-settle"}
SPLIT = pd.Timestamp("2024-01-01").date()


def stationary_idx(n, reps, mean_block=10.0, seed=7):
    rng = np.random.default_rng(seed)
    idx = np.empty((reps, n), dtype=np.int64)
    idx[:, 0] = rng.integers(0, n, reps)
    new = rng.random((reps, n)) < 1.0 / mean_block
    starts = rng.integers(0, n, (reps, n))
    for t in range(1, n):
        idx[:, t] = np.where(new[:, t], starts[:, t], (idx[:, t - 1] + 1) % n)
    return idx


def pbo_cscv(Mx: np.ndarray, S: int = 16) -> dict:
    T, N = Mx.shape
    edges = np.linspace(0, T, S + 1).astype(int)
    s1 = np.array([Mx[edges[b]:edges[b + 1]].sum(0) for b in range(S)])
    s2 = np.array([(Mx[edges[b]:edges[b + 1]] ** 2).sum(0) for b in range(S)])
    cnt = np.diff(edges)
    lam = []
    for comb in itertools.combinations(range(S), S // 2):
        isb = np.zeros(S, bool)
        isb[list(comb)] = True

        def sharpe(mask):
            n = cnt[mask].sum()
            m = s1[mask].sum(0) / n
            v = s2[mask].sum(0) / n - m ** 2
            return np.where(v > 1e-12, m / np.sqrt(np.maximum(v, 1e-12)), 0.0)
        si, so = sharpe(isb), sharpe(~isb)
        k = int(np.argmax(si))
        rank = (so < so[k]).sum() + 1 + 0.5 * ((so == so[k]).sum() - 1)
        w = rank / (N + 1)
        lam.append(math.log(w / (1 - w)))
    lam = np.array(lam)
    return {"pbo": float((lam <= 0).mean()), "n_splits": len(lam), "median_logit": float(np.median(lam))}


def white_rc(Mx: np.ndarray, reps: int = 2000) -> dict:
    T, N = Mx.shape
    mu = Mx.mean(0)
    V = math.sqrt(T) * mu.max()
    idx = stationary_idx(T, reps)
    vb = np.empty(reps)
    for i in range(0, reps, 100):
        mb = Mx[idx[i:i + 100]].mean(1)          # (100, N)
        vb[i:i + 100] = (math.sqrt(T) * (mb - mu)).max(1)
    return {"p_value": float((vb >= V).mean()), "best": VARIANTS[int(mu.argmax())], "best_mean": float(mu.max())}


def stats(df: pd.DataFrame, days: list) -> pd.DataFrame:
    rows = []
    for v, g in df.groupby("variant"):
        g = g.set_index("date").reindex(days)
        pnl = g["pnl"].fillna(0.0)
        tr = g[g["traded"] == 1]
        tp = tr["pnl"]
        nl = int((tp < 0).sum())
        aw = float(tp[tp > 0].mean()) if (tp > 0).any() else 0.0
        al = float(-tp[tp < 0].mean()) if nl >= 5 else float(tr["max_loss"].mean()) if len(tr) else np.nan
        be = aw / (aw + al) if aw > 0 and al and al > 0 else 0.0
        up = float(beta.ppf(0.95, nl + 1, len(tp) - nl)) if len(tp) > nl else 1.0
        bm = M.stationary_bootstrap_means(pnl.values, reps=10_000) if len(pnl) > 20 else np.array([np.nan])
        h1 = float(pnl[[d < SPLIT for d in pnl.index]].sum())
        h2 = float(pnl[[d >= SPLIT for d in pnl.index]].sum())
        nav = 25_000 + pnl.cumsum()
        dd = float((np.maximum.accumulate(np.r_[25_000, nav.values])[1:] - nav.values).max())
        yrs = pnl.groupby([d.year for d in pnl.index]).sum()
        rows.append({"variant": v, "n_days": len(pnl), "trades": len(tr), "total": float(pnl.sum()),
                     "per_year": float(pnl.sum()) / (len(pnl) / 252.0), "mean_daily": float(pnl.mean()),
                     "H1": h1, "H2": h2, "win_rate": float((tp > 0).mean()) if len(tp) else np.nan,
                     "avg_win": aw, "avg_loss_used": al, "n_losses": nl, "loss_rate": nl / len(tp) if len(tp) else np.nan,
                     "cp95_loss_upper": up, "breakeven_loss_rate": be, "tail_ok": bool(len(tp) and up < be),
                     "boot_p": float((bm > 0).mean()), "boot_p05_mean": float(np.quantile(bm, 0.05)),
                     "worst": float(tp.min()) if len(tp) else 0.0, "max_dd": dd,
                     "avg_credit": float(tr["credit"].mean()) if len(tr) else np.nan,
                     "stop_rate": float(tr["stopped"].mean()) if len(tr) and "stopped" in tr else np.nan,
                     "sharpe_ann": float(pnl.mean() / pnl.std() * math.sqrt(252)) if pnl.std() > 0 else np.nan,
                     "dsr": float(M.dsr((pnl / 25_000).values, registry.n_trials())) if pnl.std() > 0 else np.nan,
                     "yearly": {int(y): round(float(x), 2) for y, x in yrs.items()},
                     "reasons": g["reason"].fillna("").replace("", "traded").value_counts().to_dict()})
    return pd.DataFrame(rows).set_index("variant").reindex(VARIANTS)


def main():
    res = {}
    S = {}
    mats = {}
    for root in ("XSP", "SPXW"):
        df = pd.read_pickle(D / f"rows_{root}.pkl")
        sess = df.groupby("date")["reason"].apply(lambda r: not set(r).issubset(NOT_SESSION))
        days = sorted(sess[sess].index)
        S[root] = stats(df, days)
        S[root].drop(columns=["yearly", "reasons"]).to_csv(D / f"summary_{root}.csv")
        S[root][["yearly", "reasons"]].to_json(D / f"detail_{root}.json", orient="index", indent=1)
        mats[root] = df.pivot_table(index="date", columns="variant", values="pnl", aggfunc="sum").reindex(
            index=days, columns=VARIANTS).fillna(0.0).values
        res[root] = {"n_days": len(days), "pbo": pbo_cscv(mats[root]), "white_rc": white_rc(mats[root])}
    x, s = S["XSP"], S["SPXW"]
    elig = x[(x["H1"] > 0) & (x["H2"] > 0) & (x["boot_p"] >= 0.95) & (x["tail_ok"])]
    elig = elig.assign(spxw_twin_total=s.loc[elig.index, "total"])
    shadow_only = elig[elig["spxw_twin_total"] <= 0].index.tolist()
    elig_b = elig[elig["spxw_twin_total"] > 0].sort_values("boot_p05_mean", ascending=False)
    res["eligible_xsp"] = elig.index.tolist()
    res["candidates"] = elig_b.index[:3].tolist()
    res["shadow_only"] = shadow_only
    res["n_trials_total"] = registry.n_trials()
    (D / "selection.json").write_text(json.dumps(res, indent=1, default=str))
    cols = ["trades", "total", "per_year", "H1", "H2", "boot_p", "loss_rate", "cp95_loss_upper", "breakeven_loss_rate",
            "avg_credit", "worst", "max_dd", "stop_rate"]
    pd.set_option("display.width", 250)
    print(x[cols].round(3).to_string())
    print(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()
