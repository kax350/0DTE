"""V3 forward shadow (RETAIL_V3_PREREGISTRATION.md): zero-capital, hash-chained, no orders.

    python scripts/shadow_v3.py strikes S0     # run at ~10:15 ET (Cboe delayed => quotes as of 10:00)
    python scripts/shadow_v3.py fill S0        # run at ~10:18 ET (quotes as of 10:03)
    python scripts/shadow_v3.py strikes S1     # ~15:15 ET
    python scripts/shadow_v3.py fill S1        # ~15:18 ET
    python scripts/shadow_v3.py settle [YYYY-MM-DD]   # after the close (SPX close from Cboe prev_close next day)
    python scripts/shadow_v3.py verify
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from vrp_ltr import bs  # noqa: E402
from vrp_ltr.calendar import fomc_excluded_days, trading_time_years  # noqa: E402
from vrp_ltr.data import cboe_snapshot  # noqa: E402
from vrp_ltr.retail import fees  # noqa: E402
from vrp_ltr.shadow import fetch  # noqa: E402

LOG = ROOT / "shadow" / "v3_log.jsonl"
HYP = {"S0": {"t0": "10:00", "delta": 0.05}, "S1": {"t0": "15:00", "delta": 0.05}}
B, MINCREDIT, TOL, R = 500.0, 0.05, 0.025, 0.04


def _last() -> str:
    if not LOG.exists() or LOG.stat().st_size == 0:
        return "GENESIS"
    return hashlib.sha256(LOG.read_bytes().rstrip(b"\n").split(b"\n")[-1]).hexdigest()


def append(rec: dict) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    rec = {"prev_sha256": _last(), "written_at_utc": dt.datetime.utcnow().isoformat(timespec="seconds"), **rec}
    with open(LOG, "a") as f:
        f.write(json.dumps(rec, sort_keys=True, default=str) + "\n")


def records() -> list[dict]:
    return [json.loads(x) for x in LOG.read_text().splitlines()] if LOG.exists() else []


def snap(sym: str, day):
    df, meta = cboe_snapshot.parse(fetch(sym, day))
    df = df[df["expiration"] == day]
    return df, meta


def strikes(h: str) -> None:
    day = pd.Timestamp.now(tz="America/New_York").date()
    base = {"kind": "strikes", "hyp": h, "day": str(day), "note": "spot = Cboe delayed SPX level (backtest: 1-min bar)"}
    if day in fomc_excluded_days():
        return append({**base, "decision": "NO TRADE", "reason": "fomc"})
    spx, meta = snap("_SPX", day)
    spx = spx[(spx["root"] == "SPXW") & (spx["right"] == "P") & (spx["bid"] > 0) & (spx["ask"] > spx["bid"])]
    if spx.empty:
        return append({**base, "decision": "NO TRADE", "reason": "no-same-day-expiry"})
    S, asof = meta["spot"], meta["quotes_as_of_et"]
    T = trading_time_years(asof, day)
    mid = 0.5 * (spx["bid"] + spx["ask"]).values
    k = spx["strike"].values
    iv = bs.implied_vol(mid, S, k, T, R, "P")
    ok = np.isfinite(iv)
    d = np.abs(bs.greeks(S, k[ok], T, R, iv[ok], "P")["delta"])
    dist = np.abs(d - HYP[h]["delta"])
    if not len(dist) or dist.min() > TOL:
        return append({**base, "decision": "NO TRADE", "reason": "delta-unavailable", "quotes_as_of": asof})
    j = np.flatnonzero(dist == dist.min())
    kspx = float(k[ok][j].min())
    append({**base, "decision": "PENDING-FILL", "k_spxw": kspx, "delta": float(d[j[0]]), "spx": S,
            "quotes_as_of": asof})


def fill(h: str) -> None:
    day = pd.Timestamp.now(tz="America/New_York").date()
    prev = [r for r in records() if r.get("hyp") == h and r.get("day") == str(day) and r["kind"] == "strikes"]
    if not prev or prev[-1]["decision"] != "PENDING-FILL":
        return
    kspx = prev[-1]["k_spxw"]
    out = {"kind": "fill", "hyp": h, "day": str(day)}
    for root, sym, scale in (("XSP", "_XSP", 0.1), ("SPXW", "_SPX", 1.0)):
        q, meta = snap(sym, day)
        q = q[(q["root"] == root) & (q["right"] == "P") & (q["ask"] > 0)].set_index("strike").sort_index()
        if q.empty:
            out[root] = {"decision": "NO TRADE", "reason": "no-quotes"}
            continue
        ks = float(q.index[np.argmin(np.abs(q.index.values - kspx * scale))])
        bs_ = float(q.loc[ks, "bid"])
        best = None
        for kl in q.index[q.index < ks][::-1]:
            al = float(q.loc[kl, "ask"])
            nat = round(bs_ - al, 2)
            if nat <= 0:
                continue
            ml = (ks - kl - nat) * 100 + fees(root, [bs_, al], 1)
            if ml <= B:
                best = (float(kl), nat, ml, al)
            else:
                break
        if best is None:
            out[root] = {"decision": "NO TRADE", "reason": "no-wing", "short_k": ks}
        elif best[1] < MINCREDIT:
            out[root] = {"decision": "NO TRADE", "reason": "below-min-credit", "short_k": ks, "credit": best[1]}
        else:
            out[root] = {"decision": "TRADE (hypothetical)", "short_k": ks, "long_k": best[0], "credit": best[1],
                         "max_loss": best[2], "fees_entry": fees(root, [bs_, best[3]], 1),
                         "quotes_as_of": str(meta["quotes_as_of_et"])}
    append(out)


def settle(day: str | None = None) -> None:
    today = pd.Timestamp.now(tz="America/New_York").date()
    _, meta = snap("_SPX", today)
    close = meta["prev_close"]  # previous session's SPX close
    target = day or str(today - dt.timedelta(days=1))
    for r in [r for r in records() if r["kind"] == "fill" and r["day"] == target]:
        res = {"kind": "settle", "hyp": r["hyp"], "day": target, "spx_close": close}
        for root, scale in (("XSP", 0.1), ("SPXW", 1.0)):
            x = r.get(root, {})
            if str(x.get("decision", "")).startswith("TRADE"):
                S = close * scale
                pay = max(x["short_k"] - S, 0) - max(x["long_k"] - S, 0)
                res[root] = {"pnl": 100 * (x["credit"] - pay) - x["fees_entry"]}
        append(res)


def verify() -> None:
    prev = "GENESIS"
    for i, line in enumerate(LOG.read_bytes().rstrip(b"\n").split(b"\n") if LOG.exists() else []):
        if json.loads(line)["prev_sha256"] != prev:
            print("BROKEN at", i + 1)
            return
        prev = hashlib.sha256(line).hexdigest()
    print("chain OK")


if __name__ == "__main__":
    cmd = sys.argv[1]
    {"strikes": lambda: strikes(sys.argv[2]), "fill": lambda: fill(sys.argv[2]),
     "settle": lambda: settle(sys.argv[2] if len(sys.argv) > 2 else None), "verify": verify}[cmd]()
