"""Recompute per-candidate test-year scores from a saved window model (deterministic; verifies picks).

    python scripts/rescore.py --policy A-LAG --windows WF1,WF2

Writes results/<policy>/<window>/scores_test.parquet and asserts the argmax equals the saved picks.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import lightgbm as lgb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from vrp_ltr.assemble import build  # noqa: E402
from vrp_ltr.config import WINDOWS  # noqa: E402
from vrp_ltr.model import top_picks  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", default="A-LAG")
    ap.add_argument("--windows", default="WF1,WF2")
    ap.add_argument("--end", default="2022-12-31")
    a = ap.parse_args()
    panel, _ = build("2017-01-01", a.end, a.policy)
    for w in a.windows.split(","):
        wd = ROOT / "results" / a.policy / w
        feats = json.loads((wd / "features.json").read_text())
        m = lgb.Booster(model_file=str(wd / "model.txt"))
        pt = panel[panel["date"].map(lambda d: d.year == WINDOWS[w][2])]
        sc = pd.Series(m.predict(pt[feats]), index=pt.index)
        new = top_picks(pt, sc)
        old = pd.read_parquet(wd / "picks_forced.parquet")
        newf = top_picks(pt, sc, forced=True)
        agree = float((new["pick"] == pd.read_parquet(wd / "picks_head.parquet")["pick"].reindex(new.index)).mean())
        agree_f = float((newf["pick"] == old["pick"].reindex(newf.index)).mean())
        pt[["date", "strategy"]].assign(score=sc.values).reset_index(drop=True).to_parquet(wd / "scores_test.parquet")
        print(w, "argmax agreement head", agree, "forced", agree_f, flush=True)


if __name__ == "__main__":
    main()
