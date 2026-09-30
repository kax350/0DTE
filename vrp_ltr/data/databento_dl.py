"""Budget-capped Databento OPRA downloader → canonical parquet.

Every request is priced with metadata.get_cost first; the spend is appended to
data/reference/databento_spend.csv and a hard cap (default $300, user-approved) is enforced.
The API key is read from $DATABENTO_API_KEY or a file path in $DATABENTO_KEY_FILE; it is
never written anywhere.

Per (root, session date) we store:
  chain/   shortest-expiry contracts, 1-minute CBBO 09:30-16:15 ET (both rights for SPXW/SPY
           near the money; puts only elsewhere); for a 1-DTE expiry the next session is
           appended so the label path reaches settlement.
  surface/ SPXW only: all strikes of the expiries nearest calendar-DTE {1,5,10,20,30,60,90}
           at 09:35, 10:00, 15:59; plus near-ATM (+/-1.5%) full-day 1-minute paths for the
           10- and 30-DTE expiries (intraday ATMF-IV range features).
Canonical columns: ts (ET, minute close), root, expiration, right, strike, bid, ask,
bid_size, ask_size.
"""
from __future__ import annotations

import csv
import datetime as dt
import os
import re
import threading
from pathlib import Path

import numpy as np
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[2]
RAW = ROOT_DIR / "data" / "raw" / "databento"
SPEND = ROOT_DIR / "data" / "reference" / "databento_spend.csv"
DATASET = "OPRA.PILLAR"
CAP_USD = float(os.environ.get("DATABENTO_CAP_USD", "300"))
OCC = re.compile(r"^([A-Z]+)\s*(\d{6})([CP])(\d{8})$")
_lock = threading.Lock()


def client():
    import databento as db
    key = os.environ.get("DATABENTO_API_KEY")
    if not key and os.environ.get("DATABENTO_KEY_FILE"):
        key = Path(os.environ["DATABENTO_KEY_FILE"]).read_text().strip()
    if not key:
        raise RuntimeError("set DATABENTO_API_KEY or DATABENTO_KEY_FILE")
    return db.Historical(key)


def spent() -> float:
    if not SPEND.exists():
        return 0.0
    df = pd.read_csv(SPEND)
    return float(df["usd"].sum()) if len(df) else 0.0


def _log(kind: str, root: str, day: str, detail: str, usd: float, mb: float) -> None:
    with _lock:
        new = not SPEND.exists()
        with open(SPEND, "a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["logged_at", "kind", "root", "day", "detail", "usd", "mb"])
            w.writerow([dt.datetime.now().isoformat(timespec="seconds"), kind, root, day, detail,
                        round(usd, 6), round(mb, 3)])


def _retry(fn, tries: int = 15):
    """Retry network resets (egress relay) and HTTP 429 rate limits with capped exponential backoff."""
    import random
    import time
    for k in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            fatal = "budget cap" in msg or " 400 " in f" {msg} " or "422" in msg
            if fatal or k == tries - 1 or (k >= 6 and "429" not in msg):
                raise
            time.sleep(min(2 ** (k + 1), 90) * (1 + random.random() * 0.5))


# Per-row prices calibrated against metadata.get_cost on 2019-06-25 (cbbo-1m) and 2019-06-17
# (definition): $0.0181 / 121,200 rows and $0.0174 / 10,380 rows. A 10% safety margin is added.
ROW_USD = {"cbbo-1m": 0.0181 / 121_200 * 1.10, "definition": 0.0174 / 10_380 * 1.10}
RESERVE_USD = 5.0


def priced_get(c, kind: str, root: str, day: str, detail: str, **kw):
    """Fetch (with retries) under the budget cap; cost estimated from returned rows and logged."""
    import databento as db
    kw.setdefault("dataset", DATASET)
    with _lock:
        if spent() > CAP_USD - RESERVE_USD:
            raise RuntimeError(f"budget cap ${CAP_USD} reached (spent {spent():.2f})")
    store = _retry(lambda: c.timeseries.get_range(**kw))
    df = store.to_df() if isinstance(store, db.DBNStore) else pd.DataFrame()
    usd = len(df) * ROW_USD.get(kw.get("schema"), 0.0)
    _log(kind, root, day, detail + " est", usd, float("nan"))
    return df


def parse_symbols(raw: pd.Series) -> pd.DataFrame:
    m = raw.str.extract(OCC)
    m.columns = ["root", "ymd", "right", "k"]
    out = pd.DataFrame({"raw_symbol": raw.values,
                        "root": m["root"].values,
                        "expiration": pd.to_datetime(m["ymd"], format="%y%m%d").dt.date.values,
                        "right": m["right"].values,
                        "strike": m["k"].astype(float).values / 1000.0})
    return out.dropna()


def definitions(c, root: str, day: dt.date) -> pd.DataFrame:
    cache = RAW / "definitions" / root / f"{day}.parquet"
    if cache.exists():
        return pd.read_parquet(cache)
    nxt = day + dt.timedelta(days=1)
    df = priced_get(c, "definition", root, str(day), "parent",
                    symbols=[f"{root}.OPT"], stype_in="parent", schema="definition",
                    start=str(day), end=str(nxt))
    if df.empty:
        out = pd.DataFrame(columns=["raw_symbol", "root", "expiration", "right", "strike"])
    else:
        out = parse_symbols(df["raw_symbol"].drop_duplicates())
        out = out[out["root"] == root]
    cache.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(cache, index=False)
    return out


def _et(day: dt.date, hhmm: str) -> pd.Timestamp:
    return pd.Timestamp(f"{day} {hhmm}", tz="America/New_York")


def quotes(c, root: str, day: dt.date, syms: list[str], t0: str, t1: str, kind: str) -> pd.DataFrame:
    """cbbo-1m for raw symbols between t0 and t1 ET (end exclusive)."""
    if not syms:
        return pd.DataFrame()
    frames = []

    def get(chunk, a, b, depth=0):
        try:
            return [priced_get(c, kind, root, str(day), f"{a}-{b} n={len(chunk)}",
                               symbols=chunk, stype_in="raw_symbol", schema="cbbo-1m",
                               start=_et(day, a).tz_convert("UTC"), end=_et(day, b).tz_convert("UTC"))]
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            if depth >= 3 or not ("504" in msg or "timed out" in msg.lower() or "prematurely" in msg):
                raise
            # gateway timeout on a heavy request: split symbols in half and the window in half
            ta, tb = _et(day, a), _et(day, b)
            mid = (ta + (tb - ta) / 2).floor("min").strftime("%H:%M")
            halves = [chunk[: len(chunk) // 2], chunk[len(chunk) // 2:]] if len(chunk) > 1 else [chunk]
            out = []
            for h in halves:
                for x, y in ((a, mid), (mid, b)) if mid not in (a, b) else ((a, b),):
                    out += get(h, x, y, depth + 1)
            return out

    for i in range(0, len(syms), 2000):  # API symbol-list limit
        for df in get(syms[i:i + 2000], t0, t1):
            if not df.empty:
                frames.append(df)
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames)
    return canonical(df)


def canonical(df: pd.DataFrame) -> pd.DataFrame:
    df = df.reset_index()
    tcol = "ts_recv" if "ts_recv" in df.columns else df.columns[0]
    ts = pd.to_datetime(df[tcol], utc=True).dt.tz_convert("America/New_York")
    out = pd.DataFrame({
        "ts": ts.reset_index(drop=True),
        "raw_symbol": df["symbol"].astype(str).reset_index(drop=True),
        "bid": df["bid_px_00"].astype(float).reset_index(drop=True),
        "ask": df["ask_px_00"].astype(float).reset_index(drop=True),
        "bid_size": df["bid_sz_00"].astype(float).reset_index(drop=True),
        "ask_size": df["ask_sz_00"].astype(float).reset_index(drop=True),
    })
    sym = parse_symbols(pd.Series(out["raw_symbol"].unique()))
    n = len(out)
    out = out.merge(sym, on="raw_symbol", how="left", validate="many_to_one").drop(columns="raw_symbol")
    assert len(out) == n
    return out[["ts", "root", "expiration", "right", "strike", "bid", "ask", "bid_size", "ask_size"]]


_VIX = None


def vix_prev_close(day: dt.date) -> float:
    """Prior-session VIX close (only used to size the downloaded strike band)."""
    global _VIX
    if _VIX is None:
        x = pd.read_csv(ROOT_DIR / "data" / "raw" / "cboe_idx" / "VIX_History.csv")
        x.columns = [c.strip().upper() for c in x.columns]
        x["DATE"] = pd.to_datetime(x["DATE"], format="mixed").dt.date
        _VIX = x.set_index("DATE")["CLOSE"]
    s = _VIX[_VIX.index < day]
    return float(s.iloc[-1]) if len(s) else 20.0


def next_session(day: dt.date) -> dt.date:
    from ..calendar import next_sessions
    return next_sessions(day + dt.timedelta(days=1), 1)[0]


def fetch_day(c, root: str, day: dt.date, spot_hint: float | None, rights_both_band: float = 0.03) -> dict:
    """Download one session for one root. spot_hint (underlying level at 10:00) limits calls."""
    out_dir = RAW.parent.parent / "processed" / root
    fchain = out_dir / "chain" / f"{day}.parquet"
    fsurf = out_dir / "surface" / f"{day}.parquet"
    if fchain.exists() and (root != "SPXW" or fsurf.exists()):
        return {"day": str(day), "root": root, "status": "cached"}
    lock = out_dir / "lock" / f"{day}.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    import time as _t
    try:
        os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except FileExistsError:
        if _t.time() - lock.stat().st_mtime < 45 * 60:
            return {"day": str(day), "root": root, "status": "locked-by-other-process"}
        lock.touch()  # stale lock: take over
    try:
        return _fetch_day_body(c, root, day, spot_hint, rights_both_band, out_dir, fchain, fsurf)
    finally:
        lock.unlink(missing_ok=True)


def _fetch_day_body(c, root, day, spot_hint, rights_both_band, out_dir, fchain, fsurf) -> dict:
    d = definitions(c, root, day)
    if d.empty:
        return {"day": str(day), "root": root, "status": "no-definitions"}
    exps = sorted(e for e in d["expiration"].unique() if e >= day)
    if not exps:
        return {"day": str(day), "root": root, "status": "no-expiry"}
    e0 = exps[0]
    ch = d[d["expiration"] == e0]
    puts = ch[ch["right"] == "P"]
    calls = ch[ch["right"] == "C"]
    if spot_hint:
        calls = calls[np.abs(calls["strike"] / spot_hint - 1) <= rights_both_band]
    syms = puts["raw_symbol"].tolist() + calls["raw_symbol"].tolist()
    cal_dte = {e: (e - day).days for e in exps}
    band = []
    if root == "SPXW" and spot_hint:
        for tgt in (10, 30):
            e = min(exps, key=lambda x: (abs(cal_dte[x] - tgt), cal_dte[x]))
            x = d[(d["expiration"] == e) & (np.abs(d["strike"] / spot_hint - 1) <= 0.015)]
            band += x["raw_symbol"].tolist()
    full = quotes(c, root, day, sorted(set(syms + band)), "09:30", "16:15", "chain+path")
    q = full[full["expiration"] == e0] if len(full) else full
    path = full[full["expiration"] != e0] if len(full) else full
    if e0 > day:  # 1-DTE: extend the path through the expiry session
        q2 = quotes(c, root, e0, syms, "09:30", "16:15", "chain-next")
        q = pd.concat([q, q2], ignore_index=True)
    fchain.parent.mkdir(parents=True, exist_ok=True)
    q.to_parquet(fchain, index=False)
    res = {"day": str(day), "root": root, "status": "ok", "expiry": str(e0), "n_chain_rows": len(q)}
    if root == "SPXW":
        snaps = [path]
        chosen = set()
        for tgt in (1, 5, 10, 20, 30, 60, 90):
            chosen.add(min(exps, key=lambda e: (abs(cal_dte[e] - tgt), cal_dte[e])))
        sd = d[d["expiration"].isin(chosen)].copy()
        if spot_hint:
            vol = 1.3 * vix_prev_close(day) / 100.0
            T = sd["expiration"].map(lambda e: max((e - day).days, 1) / 365.0)
            lo = np.exp(-np.maximum(0.03, 2.2 * vol * np.sqrt(T)))
            hi = np.exp(np.maximum(0.02, 1.6 * vol * np.sqrt(T)))
            m = sd["strike"] / spot_hint
            keep = ((sd["right"] == "P") & (m >= lo) & (m <= 1.02)) | ((sd["right"] == "C") & (m >= 0.98) & (m <= hi))
            sd = sd[keep]
        ssyms = sd["raw_symbol"].tolist()
        for t0, t1 in (("09:35", "09:36"), ("10:00", "10:01"), ("15:59", "16:00")):
            snaps.append(quotes(c, root, day, ssyms, t0, t1, f"surface-{t0}"))
        s = pd.concat([x for x in snaps if len(x)], ignore_index=True) if any(len(x) for x in snaps) else pd.DataFrame()
        fsurf.parent.mkdir(parents=True, exist_ok=True)
        s.to_parquet(fsurf, index=False)
        res["n_surface_rows"] = len(s)
    return res
