"""Download a date range for one root. Usage:
    DATABENTO_KEY_FILE=... python scripts/download_databento.py SPXW 2019-06-01 2019-06-30 [workers]
Budget cap enforced inside vrp_ltr.data.databento_dl (default $300).
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vrp_ltr.calendar import sessions  # noqa: E402
from vrp_ltr.data import databento_dl as D  # noqa: E402
from vrp_ltr.data import spx_minute  # noqa: E402

SPOT_SCALE = {"SPXW": 1.0, "XSP": 0.1, "SPY": 0.1, "QQQ": None}


def main() -> None:
    root, start, end = sys.argv[1], sys.argv[2], sys.argv[3]
    workers = int(sys.argv[4]) if len(sys.argv) > 4 else 4
    c = D.client()
    days = [d.date() for d in sessions(start, end)]
    log = Path(__file__).resolve().parents[1] / "data" / "reference" / f"download_log_{root}.jsonl"

    def one(day):
        spx = spx_minute.level_asof(pd.Timestamp(f"{day} 10:00", tz="America/New_York"))
        sc = SPOT_SCALE.get(root)
        hint = spx * sc if (spx and sc) else None
        try:
            r = D.fetch_day(c, root, day, hint)
        except Exception as e:  # noqa: BLE001
            r = {"day": str(day), "root": root, "status": f"error: {e}"[:300]}
        with open(log, "a") as f:
            f.write(json.dumps(r) + "\n")
        return r

    with cf.ThreadPoolExecutor(workers) as ex:
        for r in ex.map(one, days):
            if r["status"] not in ("ok", "cached"):
                print(r)
    print(f"{root} {start}..{end}: {len(days)} sessions; total spend ${D.spent():.2f}")


if __name__ == "__main__":
    main()
