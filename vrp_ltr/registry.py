"""Trial registry: every variant that produces a P&L series is recorded, so the Deflated
Sharpe Ratio uses the true number of configurations tried (PREREGISTRATION §7).

Append-only JSONL at results/trials.jsonl. n_trials() counts distinct variant ids.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "results" / "trials.jsonl"


def record(variant_id: str, period: str, prereg: bool = True, note: str = "") -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a") as f:
        f.write(json.dumps({"t": dt.datetime.now().isoformat(timespec="seconds"), "variant": variant_id,
                            "period": period, "preregistered": prereg, "note": note}) + "\n")


def n_trials() -> int:
    if not LOG.exists():
        return 1
    ids = {json.loads(line)["variant"] for line in LOG.read_text().splitlines() if line.strip()}
    return max(len(ids), 1)
