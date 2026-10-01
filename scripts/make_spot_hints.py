"""Regenerate data/reference/spx_1000.csv (SPX level at 10:00 ET per session; download strike-band hints).

    python scripts/make_spot_hints.py      # needs data/raw/hf_spx/SPX_full_1min_CT.txt (see vrp_ltr/data/spx_minute.py)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from vrp_ltr.calendar import sessions  # noqa: E402
from vrp_ltr.data import spx_minute  # noqa: E402


def main() -> None:
    rows = []
    for d in sessions("2016-06-01"):
        v = spx_minute.level_asof(pd.Timestamp(f"{d.date()} 10:00", tz="America/New_York"))
        if v is not None:
            rows.append({"date": d.date(), "spx_1000": round(float(v), 2)})
    out = ROOT / "data" / "reference" / "spx_1000.csv"
    pd.DataFrame(rows).to_csv(out, index=False)
    print(out, len(rows))


if __name__ == "__main__":
    main()
