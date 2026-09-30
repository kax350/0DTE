"""Single coordinated downloader for every missing (root, day), in priority order.

    DATABENTO_KEY_FILE=... python scripts/download_missing.py [workers]

Priority: SPXW 2018-2021 (first walk-forward window) → SPXW 2022-2025 → XSP/SPY 2021-2025
→ all 2026. One shared thread pool keeps the account under Databento's rate limit.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from vrp_ltr.calendar import sessions  # noqa: E402
from vrp_ltr.data import databento_dl as D  # noqa: E402

SPOT_SCALE = {"SPXW": 1.0, "XSP": 0.1, "SPY": 0.1}


def missing(root: str, start: str, end: str) -> list:
    out = []
    for d in sessions(start, end):
        day = d.date()
        ch = ROOT / "data" / "processed" / root / "chain" / f"{day}.parquet"
        sf = ROOT / "data" / "processed" / root / "surface" / f"{day}.parquet"
        if not ch.exists() or (root == "SPXW" and not sf.exists()):
            out.append((root, day))
    return out


def main() -> None:
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 24
    queue = (missing("SPXW", "2017-01-01", "2021-12-31") + missing("SPXW", "2022-01-01", "2025-12-31")
             + missing("XSP", "2021-01-01", "2025-12-31") + missing("SPY", "2021-01-01", "2025-12-31")
             + missing("SPXW", "2026-01-01", "2026-09-29") + missing("XSP", "2026-01-01", "2026-09-29")
             + missing("SPY", "2026-01-01", "2026-09-29"))
    print("missing", len(queue), flush=True)
    lvl = pd.read_csv(ROOT / "data" / "reference" / "spx_1000.csv")
    lvl = dict(zip(pd.to_datetime(lvl["date"]).dt.date, lvl["spx_1000"]))
    c = D.client()

    def one(item):
        root, day = item
        spx = lvl.get(day)
        hint = float(spx) * SPOT_SCALE[root] if spx is not None and pd.notna(spx) else None
        try:
            r = D.fetch_day(c, root, day, hint)
        except Exception as e:  # noqa: BLE001
            r = {"day": str(day), "root": root, "status": f"error: {e}"[:300]}
        with open(ROOT / "data" / "reference" / f"download_log_{root}.jsonl", "a") as f:
            f.write(json.dumps(r) + "\n")
        return r

    n_ok = n_err = 0
    with cf.ThreadPoolExecutor(workers) as ex:
        for r in ex.map(one, queue):
            if r["status"] == "ok":
                n_ok += 1
            elif r["status"].startswith("error"):
                n_err += 1
                print(r["root"], r["day"], r["status"][:80], flush=True)
    print(f"done ok={n_ok} err={n_err} spend=${D.spent():.2f}", flush=True)


if __name__ == "__main__":
    main()
