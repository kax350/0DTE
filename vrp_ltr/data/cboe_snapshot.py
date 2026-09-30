"""Parser for Cboe delayed-quote chain JSON (cdn.cboe.com/api/global/delayed_quotes/options/<SYM>.json).

Free, 15-minute delayed. Used for (a) today's real microstructure snapshot and
(b) the forward shadow log. NOT a historical source.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

import pandas as pd

OCC = re.compile(r"^([A-Z]+?)(\d{6})([CP])(\d{8})$")
DELAY = pd.Timedelta(minutes=15)


def parse(path: str | Path) -> tuple[pd.DataFrame, dict]:
    raw = json.loads(Path(path).read_text())
    d = raw["data"]
    stamp = pd.Timestamp(raw["timestamp"]).tz_localize("UTC").tz_convert("America/New_York")
    rows = []
    for o in d["options"]:
        m = OCC.match(o["option"])
        if not m:
            continue
        root, ymd, right, k = m.groups()
        rows.append({
            "root": root,
            "expiration": dt.datetime.strptime(ymd, "%y%m%d").date(),
            "right": right,
            "strike": int(k) / 1000.0,
            "bid": float(o["bid"]), "ask": float(o["ask"]),
            "bid_size": float(o["bid_size"]), "ask_size": float(o["ask_size"]),
            "cboe_iv": float(o["iv"]), "cboe_delta": float(o["delta"]),
            "volume": float(o["volume"]), "open_interest": float(o["open_interest"]),
        })
    meta = {"symbol": d["symbol"], "spot": float(d["current_price"]),
            "fetched_at_et": stamp, "quotes_as_of_et": stamp - DELAY,
            "prev_close": float(d["prev_day_close"])}
    return pd.DataFrame(rows), meta
