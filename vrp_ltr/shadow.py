"""Forward shadow protocol (PREREGISTRATION §9): append-only, hash-chained daily log.

    python -m vrp_ltr.shadow capture   # run ~10:16 ET: snapshot Cboe delayed chains, write decision
    python -m vrp_ltr.shadow outcome   # run ~16:30 ET: append realised outcome for today's record
    python -m vrp_ltr.shadow verify    # recompute the hash chain

Each JSONL record contains `prev_sha256` = SHA-256 of the previous line's bytes.
Editing or deleting any past line breaks `verify`. Corrections are new records.
Without a frozen model file (models/frozen_oot.json), the decision field records
"NO-MODEL" together with the 8 resolved candidates. That still builds a real forward dataset
of 10:00 chains, spreads and outcomes.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "shadow" / "log.jsonl"
SNAPDIR = ROOT / "data" / "raw" / "cboe_delayed"
URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/{sym}.json"
SYMS = {"SPXW": "_SPX", "XSP": "_XSP", "SPY": "SPY"}


def _last_hash() -> str:
    if not LOG.exists() or LOG.stat().st_size == 0:
        return "GENESIS"
    last = LOG.read_bytes().rstrip(b"\n").split(b"\n")[-1]
    return hashlib.sha256(last).hexdigest()


def append(rec: dict) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    rec = {"prev_sha256": _last_hash(), "written_at_utc": dt.datetime.utcnow().isoformat(timespec="seconds"), **rec}
    line = json.dumps(rec, sort_keys=True, default=str)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def verify() -> bool:
    if not LOG.exists():
        print("no log")
        return True
    prev = "GENESIS"
    for i, line in enumerate(LOG.read_bytes().rstrip(b"\n").split(b"\n")):
        rec = json.loads(line)
        if rec["prev_sha256"] != prev:
            print(f"BROKEN at line {i + 1}")
            return False
        prev = hashlib.sha256(line).hexdigest()
    print("chain OK")
    return True


def fetch(sym: str, day: dt.date) -> Path:
    d = SNAPDIR / str(day)
    d.mkdir(parents=True, exist_ok=True)
    t = dt.datetime.now().strftime("%H%M%S")
    p = d / f"{sym}_{t}.json"
    req = urllib.request.Request(URL.format(sym=sym), headers={"User-Agent": "Mozilla/5.0 research"})
    p.write_bytes(urllib.request.urlopen(req, timeout=90).read())
    return p


def capture() -> None:
    from .config import PRODUCTS
    from .data import cboe_snapshot
    from .universe import build_universe
    day = pd.Timestamp.now(tz="America/New_York").date()
    cands = {}
    for root, sym in SYMS.items():
        chain, meta = cboe_snapshot.parse(fetch(sym, day))
        c = chain[chain["root"] == root]
        exps = sorted(e for e in c["expiration"].unique() if e >= day)
        if not exps:
            continue
        r = 0.0388  # replaced by EFFR lookup in the frozen pipeline
        u = build_universe(c[c["expiration"] == exps[0]].drop(columns="root"), meta["spot"], r,
                           meta["quotes_as_of_et"])
        if u is None:
            continue
        cands[root] = {"quotes_as_of": str(meta["quotes_as_of_et"]), "spot": meta["spot"], "expiry": str(u.expiry),
                       "candidates": u.candidates[["strategy", "strike", "bid", "ask", "mid", "iv", "delta"]]
                       .round(5).to_dict("records")}
    model = ROOT / "models" / "frozen_oot.json"
    decision = json.loads(model.read_text()).get("decide_live", "NO-MODEL") if model.exists() else "NO-MODEL"
    append({"type": "capture", "session": str(day), "decision": decision, "universe": cands})


def outcome() -> None:
    day = pd.Timestamp.now(tz="America/New_York").date()
    spx = fetch("_SPX", day)
    from .data import cboe_snapshot
    _, meta = cboe_snapshot.parse(spx)
    append({"type": "outcome", "session": str(day), "spx_last": meta["spot"],
            "note": "official settlement to be confirmed from FRED SP500 next session"})


if __name__ == "__main__":
    {"capture": capture, "outcome": outcome, "verify": verify}[sys.argv[1]]()
