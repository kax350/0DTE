"""Fetch the free auxiliary series used by the feature catalog (PREREGISTRATION §0).

  VX futures (Cboe CFE per-expiry CSVs) → data/processed/vx_curve.parquet (M1..M3 settle, D1)
  FRED: EFFR, SP500, ICNSA → data/raw/*.csv
  Cboe VIX family closes → data/raw/cboe_idx/*.csv (already fetched by hand; refreshed here)
  BLS CPI / Employment Situation and BEA PCE release dates → data/reference/macro_release_dates.csv
"""
from __future__ import annotations

import datetime as dt
import io
import re
import sys
import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
UA = {"User-Agent": "Mozilla/5.0 (research; contact botjohn33@gmail.com)"}


def get(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=timeout).read()


def fred(series: str) -> None:
    (RAW / f"{series}.csv").write_bytes(get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"))


def vix_family() -> None:
    d = RAW / "cboe_idx"
    d.mkdir(parents=True, exist_ok=True)
    for s in ("VIX", "VIX9D", "VIX3M", "VIX6M", "VVIX", "VIX1D"):
        (d / f"{s}_History.csv").write_bytes(
            get(f"https://cdn.cboe.com/api/global/us_indices/daily_prices/{s}_History.csv"))


def vx_expiries(start_year: int = 2016, end_year: int = 2027) -> list[dt.date]:
    """Standard monthly VX final settlement: Wednesday 30 days before the 3rd Friday of the next month.
    Candidates ±2 days are probed to catch holiday shifts."""
    out = []
    for y in range(start_year, end_year + 1):
        for m in range(1, 13):
            ny, nm = (y + (m == 12), 1 if m == 12 else m + 1)
            first = dt.date(ny, nm, 1)
            fri = first + dt.timedelta(days=(4 - first.weekday()) % 7 + 14)
            out.append(fri - dt.timedelta(days=30))
    return out


def vx_curve() -> None:
    frames = []
    for e in vx_expiries():
        got = None
        for delta in (0, -1, 1, -2):
            d = e + dt.timedelta(days=delta)
            try:
                b = get(f"https://cdn.cboe.com/data/us/futures/market_statistics/historical_data/VX/VX_{d}.csv", 30)
                if len(b) > 200:
                    got = (d, b)
                    break
            except Exception:  # noqa: BLE001
                continue
        if got is None:
            continue
        d, b = got
        df = pd.read_csv(io.BytesIO(b))
        df["expiry"] = d
        frames.append(df[["Trade Date", "Settle", "expiry"]])
    vx = pd.concat(frames, ignore_index=True)
    vx.columns = ["date", "settle", "expiry"]
    vx["date"] = pd.to_datetime(vx["date"]).dt.date
    vx = vx[vx["settle"] > 0]
    rows = []
    for day, g in vx.groupby("date"):
        g = g[g["expiry"] >= day].sort_values("expiry")
        if len(g) < 3:
            continue
        m = g["settle"].values[:3]
        d1 = len(pd.bdate_range(day, g["expiry"].iloc[0])) - 1
        rows.append({"date": day, "M1": m[0], "M2": m[1], "M3": m[2], "D1": max(d1, 1)})
    out = pd.DataFrame(rows)
    (ROOT / "data" / "processed").mkdir(parents=True, exist_ok=True)
    out.to_parquet(ROOT / "data" / "processed" / "vx_curve.parquet", index=False)
    print("vx curve rows", len(out), out["date"].min(), out["date"].max())


MONTHS_RE = r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s+(\d{4})"


def macro_release_dates() -> None:
    """PCE (BEA 'Personal Income and Outlays', product id 451) from the BEA news archive.
    CPI / NFP: BLS blocks automated access (403); taken from the FRED API only if
    $FRED_API_KEY is set (release ids 10 = CPI, 50 = Employment Situation)."""
    import json
    import os
    rows = []
    for page in range(0, 40):
        url = f"https://www.bea.gov/news/archive?field_related_product_target_id=451&page={page}"
        try:
            t = get(url).decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            print("bea page", page, "failed", e)
            break
        ds = [dt.datetime.strptime(" ".join(m.groups()), "%B %d %Y").date() for m in re.finditer(MONTHS_RE, t)]
        if not ds:
            break
        rows += [{"event": "pce", "date": d} for d in ds]
        if min(ds).year < 2016:
            break
    key = os.environ.get("FRED_API_KEY")
    if key:
        for ev, rid in (("cpi", 10), ("nfp", 50)):
            u = (f"https://api.stlouisfed.org/fred/release/dates?release_id={rid}&api_key={key}"
                 f"&file_type=json&include_release_dates_with_no_data=false&limit=10000")
            j = json.loads(get(u))
            rows += [{"event": ev, "date": dt.date.fromisoformat(x["date"])} for x in j.get("release_dates", [])]
    df = pd.DataFrame(rows).drop_duplicates().sort_values(["event", "date"])
    df = df[(df["date"] >= dt.date(2015, 1, 1))]
    df.to_csv(ROOT / "data" / "reference" / "macro_release_dates.csv", index=False)
    print(df.groupby("event")["date"].agg(["count", "min", "max"]))


if __name__ == "__main__":
    what = sys.argv[1:] or ["fred", "vix", "vx", "macro"]
    if "fred" in what:
        for s in ("EFFR", "SP500", "ICNSA"):
            fred(s)
    if "vix" in what:
        vix_family()
    if "vx" in what:
        vx_curve()
    if "macro" in what:
        macro_release_dates()
