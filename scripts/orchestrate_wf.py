"""Run each walk-forward window as soon as its data is complete (deterministic, so identical to a
single end-of-download run). Order: WF2, WF3, WF4, then OOT + EXT_B once 2026 is complete.

    python scripts/orchestrate_wf.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from vrp_ltr.calendar import fomc_excluded_days, sessions  # noqa: E402

P = ROOT / "data" / "processed" / "SPXW"
LAST = "2026-09-29"


def complete(through: str) -> bool:
    for d in sessions("2017-01-01", through):
        day = d.date()
        if not (P / "chain" / f"{day}.parquet").exists() or not (P / "surface" / f"{day}.parquet").exists():
            return False
    return True


def build(through: str) -> None:
    subprocess.run([sys.executable, "-W", "ignore", "scripts/build_panels.py", "2017-01-01", through, "4"],
                   cwd=ROOT, check=False)


def run(windows: str, end: str) -> None:
    for pol in ("P-LAG", "A-LAG"):
        log = ROOT / "logs" / f"wf_{pol}_{windows.replace(',', '_')}.log"
        with open(log, "w") as f:
            subprocess.run([sys.executable, "-W", "ignore", "scripts/run_walkforward.py", "--policy", pol,
                            "--windows", windows, "--end", end], cwd=ROOT, stdout=f, stderr=subprocess.STDOUT)
        print(time.strftime("%H:%M"), "done", pol, windows, flush=True)


def main() -> None:
    plan = [("WF2", "2022-12-31"), ("WF3", "2023-12-31"), ("WF4", "2024-12-31"), ("OOT,EXT_B", LAST)]
    for windows, through in plan:
        while not complete(through):
            time.sleep(60)
        print(time.strftime("%H:%M"), "data complete through", through, flush=True)
        build(through)
        run(windows, "2026-12-31" if "OOT" in windows else through)
    print("ALL WINDOWS DONE", flush=True)


if __name__ == "__main__":
    main()
