"""PAPER_AUDIT R4: does the paper-literal per-strategy lag ('trade outcome, day t, lag >= 1') leak
same-day information on days where yesterday's 1-DTE trade settles at today's close?

Compares P-LAG vs A-LAG features against today's realised P&L on 'leaky' vs normal days.
Data: 2017-2021 (training + WF1). Output: docs/leak_test.json
"""
import json
import sys
from pathlib import Path

import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from vrp_ltr.assemble import build  # noqa: E402

out = {}
res = {}
for pol in ("P-LAG", "A-LAG"):
    p, _ = build("2017-01-01", "2021-12-31", pol)
    res[pol] = p[p.strategy != "SKIP"][["date", "strategy", "returns_on_margin", "label_gross", "expiry"]]
c = res["P-LAG"]
days = sorted(c.date.unique())
exp_by_day = c.groupby("date").expiry.first().to_dict()
leaky = {d for i, d in enumerate(days) if i > 0 and exp_by_day[days[i - 1]] == d}
out["n_days"], out["n_leaky_days"] = len(days), len(leaky)
for pol in ("P-LAG", "A-LAG"):
    g = res[pol].groupby("date").agg(rom=("returns_on_margin", "mean"), y=("label_gross", "mean")).dropna()
    for name, sel in (("leaky", [d in leaky for d in g.index]), ("normal", [d not in leaky for d in g.index])):
        x = g[sel]
        r = stats.spearmanr(x.rom, x.y)
        out[f"{pol}_{name}"] = {"spearman": float(r.statistic), "p": float(r.pvalue), "n": int(len(x))}
(ROOT / "docs" / "leak_test.json").write_text(json.dumps(out, indent=1))
print(json.dumps(out, indent=1))
