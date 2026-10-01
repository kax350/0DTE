"""V3 Layer A (RETAIL_V3_LAYER_A_PROTOCOL.md): 72-variant structure grid, XSP + SPXW, 2021-01-04..2026-09-23.

    python scripts/run_v3_layer_a.py [workers]
Per-day rows (quote-derived) -> results/retail_v3/layerA/rows_<ROOT>.pkl (git-ignored).
"""
from __future__ import annotations

import concurrent.futures as cf
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from vrp_ltr import registry  # noqa: E402
from vrp_ltr import retail3 as R  # noqa: E402
from vrp_ltr.calendar import sessions  # noqa: E402

START, END = "2021-01-04", "2026-09-23"


def main():
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    out = ROOT / "results" / "retail_v3" / "layerA"
    out.mkdir(parents=True, exist_ok=True)
    days = [d.date() for d in sessions(START, END)]
    for root in ("XSP", "SPXW"):
        rows = []
        with cf.ProcessPoolExecutor(workers) as ex:
            for r in ex.map(R.eval_day, [(root, d, 500.0) for d in days], chunksize=4):
                rows.extend(r)
        df = pd.DataFrame(rows)
        df.to_pickle(out / f"rows_{root}.pkl")
        for v in R.VARIANTS:
            registry.record(f"V3A|{root}|{v}", "2021-2026")
        print(root, len(df), df["reason"].replace("", "traded").value_counts().to_dict(), flush=True)


if __name__ == "__main__":
    main()
