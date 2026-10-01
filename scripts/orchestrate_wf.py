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


def done(windows: str, pol: str, tag: str = "") -> bool:
    return all((ROOT / "results" / (pol + tag) / w / "meta.json").exists() for w in windows.split(","))


V2_VARIANTS = [  # RETAIL_V2_PREREGISTRATION §10 (K15, K19-K22) and §11 ablation; A-LAG only
    ("_corr080", ["--corr", "0.80"]), ("_corr090", ["--corr", "0.90"]), ("_roll3y", ["--rolling3y"]),
    ("_seed1", ["--seed-offset", "1"]), ("_nomacro", ["--drop-groups", "macro"]),
    ("_top5", ["--topk", "5", "--topk-src", "A-LAG"]), ("_top10", ["--topk", "10", "--topk-src", "A-LAG"]),
    ("_top20", ["--topk", "20", "--topk-src", "A-LAG"]),
]


def run_v2_variants(end: str) -> None:
    import concurrent.futures as cf
    allw = "WF1,WF2,WF3,WF4,OOT,EXT_B"

    def one(v):
        tag, extra = v
        if done(allw, "A-LAG", tag):
            return
        with open(ROOT / "logs" / f"wf_A-LAG{tag}.log", "w") as f:
            subprocess.run([sys.executable, "-W", "ignore", "scripts/run_walkforward.py", "--policy", "A-LAG",
                            "--windows", allw, "--end", end, "--tag", tag, *extra], cwd=ROOT, stdout=f,
                           stderr=subprocess.STDOUT)
        print(time.strftime("%H:%M"), "done v2 variant", tag, flush=True)

    with cf.ThreadPoolExecutor(2) as ex:
        list(ex.map(one, V2_VARIANTS))


def run(windows: str, end: str) -> None:
    for pol in ("P-LAG", "A-LAG"):
        if done(windows, pol):
            print("skip (exists)", pol, windows, flush=True)
            continue
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
    run_v2_variants("2026-12-31")
    print("V2 VARIANTS DONE", flush=True)


if __name__ == "__main__":
    main()
