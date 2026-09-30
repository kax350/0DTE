"""Per-window feature selection S1–S5 (alg:feature_selection, PAPER_SPEC §5)."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from .config import (CORR_CLUSTER, GROUP_CAP_DEFAULT, GROUP_CAPS, MODE_FREQ_MAX, NULL_RATE_MAX,
                     RELEVANCE_MIN, STABILITY_FOLDS, STABILITY_MIN, SKIP, VAR_MIN)
from .features import GROUP_PRIORITY, group_of


def _real(panel: pd.DataFrame) -> pd.DataFrame:
    return panel[panel["strategy"] != SKIP]


def s1_null(panel, feats):
    r = _real(panel)
    return [f for f in feats if r[f].isna().mean() <= NULL_RATE_MAX]


def s2_variance(panel, feats):
    r = _real(panel)
    keep = []
    for f in feats:
        x = r[f].dropna()
        if len(x) == 0:
            continue
        if x.var() < VAR_MIN:
            continue
        if x.value_counts(normalize=True).iloc[0] > MODE_FREQ_MAX:
            continue
        keep.append(f)
    return keep


def s3_relevance(panel, feats, target: str = "label_score") -> dict[str, float]:
    r = _real(panel)
    # clip the degenerate TDD=0 scores (1e8-scale) for Spearman — ranks are unaffected
    out = {}
    day_mean = r.groupby("date")[target].mean()
    for f in feats:
        scope, _ = group_of(f)
        if scope == "CS":
            x = r.groupby("date")[f].first().reindex(day_mean.index)
            ok = x.notna()
            rho = stats.spearmanr(x[ok], day_mean[ok]).statistic if ok.sum() > 10 else np.nan
        else:
            vals = []
            for _, g in r[[f, target, "date"]].dropna().groupby("date"):
                if g[f].nunique() > 1 and g[target].nunique() > 1:
                    vals.append(stats.spearmanr(g[f], g[target]).statistic)
            rho = float(np.nanmedian(vals)) if vals else np.nan
        if np.isfinite(rho) and abs(rho) >= RELEVANCE_MIN:
            out[f] = float(rho)
    return out


def s4_cluster(panel, rel: dict[str, float]) -> list[str]:
    r = _real(panel)
    keep = []
    for scope in ("CS", "PS"):
        fs = [f for f in rel if group_of(f)[0] == scope]
        if not fs:
            continue
        X = (r.groupby("date")[fs].first() if scope == "CS" else r[fs])
        C = X.rank().corr(method="pearson").abs().fillna(0).values  # Spearman via ranks
        n = len(fs)
        seen = [False] * n
        for i in range(n):
            if seen[i]:
                continue
            comp, stack = [], [i]
            seen[i] = True
            while stack:  # connected components at |rho| >= threshold
                a = stack.pop()
                comp.append(a)
                for b in range(n):
                    if not seen[b] and C[a, b] >= CORR_CLUSTER:
                        seen[b] = True
                        stack.append(b)

            def key(j):
                f = fs[j]
                g = group_of(f)[1]
                prio = GROUP_PRIORITY.index(g) if g in GROUP_PRIORITY else 99
                return (-abs(rel[f]), prio, r[f].isna().mean(), f)
            keep.append(fs[min(comp, key=key)])
    # per-group caps
    by_group: dict[str, list[str]] = {}
    for f in keep:
        by_group.setdefault(group_of(f)[1], []).append(f)
    final = []
    for g, fs in by_group.items():
        cap = GROUP_CAPS.get(g, GROUP_CAP_DEFAULT)
        final += sorted(fs, key=lambda f: -abs(rel[f]))[:cap]
    return sorted(final)


def s1_to_s4(panel, feats) -> tuple[list[str], dict]:
    f1 = s1_null(panel, feats)
    f2 = s2_variance(panel, f1)
    rel = s3_relevance(panel, f2)
    f4 = s4_cluster(panel, rel)
    return f4, {"S1": len(f1), "S2": len(f2), "S3": len(rel), "S4": len(f4)}


def select_features(panel: pd.DataFrame, feats: list[str]) -> tuple[list[str], dict]:
    full, info = s1_to_s4(panel, feats)
    days = np.array(sorted(panel["date"].unique()))
    surv = {f: 0 for f in full}
    for k in range(1, STABILITY_FOLDS + 1):
        cut = days[: int(len(days) * k / STABILITY_FOLDS)]
        fk, _ = s1_to_s4(panel[panel["date"].isin(cut)], feats)
        for f in fk:
            if f in surv:
                surv[f] += 1
    final = [f for f in full if surv[f] >= STABILITY_MIN]
    info["S5"] = len(final)
    return final, info
