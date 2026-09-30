"""NYSE session calendar, trading-time tau, event days. All times America/New_York."""
from __future__ import annotations

import datetime as dt
from functools import lru_cache
from pathlib import Path

import pandas as pd

from .config import MINUTES_PER_SESSION, TRADING_DAYS_PER_YEAR, TZ

REF = Path(__file__).resolve().parents[1] / "data" / "reference"


@lru_cache(maxsize=1)
def _cal():
    import exchange_calendars as xc
    return xc.get_calendar("XNYS")


@lru_cache(maxsize=None)
def sessions(start: str = "2016-01-01", end: str | None = None) -> pd.DatetimeIndex:
    c = _cal()
    last = c.last_session
    end_ts = last if end is None else min(pd.Timestamp(end), last)
    return c.sessions_in_range(start, end_ts)


@lru_cache(maxsize=None)
def session_bounds(day: dt.date) -> tuple[pd.Timestamp, pd.Timestamp]:
    """(open, close) in America/New_York for a session date."""
    c = _cal()
    ts = pd.Timestamp(day)
    return (c.session_open(ts).tz_convert(TZ), c.session_close(ts).tz_convert(TZ))


@lru_cache(maxsize=None)
def is_session(day: dt.date) -> bool:
    return pd.Timestamp(day) in sessions()


def next_sessions(day: dt.date, n: int) -> list[dt.date]:
    s = sessions()
    i = s.searchsorted(pd.Timestamp(day))
    return [d.date() for d in s[i:i + n]]


def session_minutes(day: dt.date) -> int:
    o, c = session_bounds(day)
    return int((c - o).total_seconds() // 60)


def trading_time_years(now: pd.Timestamp, expiry_day: dt.date) -> float:
    """tau in trading time (PAPER_SPEC §2 [AMBIG] frozen convention).

    Minutes of regular session remaining until the expiry session's close, summed over
    sessions, divided by 390*252. Overnight / weekends contribute zero.
    """
    now = now.tz_convert(TZ) if now.tzinfo else now.tz_localize(TZ)
    today = now.date()
    o, c = session_bounds(today) if is_session(today) else (None, None)
    head = max((c - max(now, o)).total_seconds() / 60.0, 0.0) if c is not None and expiry_day >= today else 0.0
    return (head + _full_minutes_between(today, expiry_day)) / (MINUTES_PER_SESSION * TRADING_DAYS_PER_YEAR)


@lru_cache(maxsize=None)
def _full_minutes_between(today: dt.date, expiry_day: dt.date) -> float:
    """Regular-session minutes of sessions strictly after `today` up to and including expiry."""
    total = 0.0
    for d in sessions(str(today), str(expiry_day)):
        if d.date() == today:
            continue
        o, c = session_bounds(d.date())
        total += (c - o).total_seconds() / 60.0
    return total


@lru_cache(maxsize=1)
def fomc_table() -> pd.DataFrame:
    df = pd.read_csv(REF / "fomc_dates.csv", parse_dates=["date"])
    df["date"] = df["date"].dt.date
    return df


def fomc_excluded_days() -> set[dt.date]:
    """Days removed upstream from the universe (PREREGISTRATION §1.3):
    scheduled statement days + the cancelled-but-scheduled 2020-03-18 slot."""
    t = fomc_table()
    return set(t.loc[t["kind"].isin(["scheduled", "cancelled"]), "date"])


def is_early_close(day: dt.date) -> bool:
    return session_minutes(day) < MINUTES_PER_SESSION
