"""Path-aware Sortino-on-bars label, SKIP injection, frozen grade thresholds (PAPER_SPEC §3)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import EPS, GRADE_PERCENTILES, SKIP


def mark_series(p_entry: float, asks_after_entry: np.ndarray, settle_intrinsic: float) -> np.ndarray:
    """[p_entry, a_1..a_{N-1}, intrinsic]: intermediate bars at the ask (cost-to-close)."""
    a = np.asarray(asks_after_entry, dtype=float)
    return np.concatenate([[p_entry], a, [settle_intrinsic]])


def sortino_on_bars(marks: np.ndarray, eps: float = EPS) -> tuple[float, float, float]:
    """Returns (score, gross_pnl, tdd) per share. dp_i = mark_{i-1} - mark_i (short)."""
    dp = -np.diff(marks)
    gross = float(dp.sum())
    tdd = float(np.sqrt(np.sum(np.minimum(dp, 0.0) ** 2)))
    return gross / (tdd + eps), gross, tdd


def label_contract(p_entry: float, ask_path: pd.Series, settle_intrinsic: float) -> dict:
    """ask_path: ask per 1-minute bar strictly after the entry bar through the last pre-close bar.

    Missing bars are forward-filled; if the path is empty only the terminal step counts.
    """
    a = ask_path.ffill().dropna().values if len(ask_path) else np.array([])
    m = mark_series(p_entry, a, settle_intrinsic)
    s, g, t = sortino_on_bars(m)
    return {"score": s, "gross_pnl": g, "tdd": t, "n_bars": len(m) - 1}


def add_skip_rows(panel: pd.DataFrame, date_col: str = "date") -> pd.DataFrame:
    """Append one SKIP row per day with score 0 and gross 0 (PS features NaN)."""
    days = panel[date_col].unique()
    skip = pd.DataFrame({date_col: days, "strategy": SKIP, "score": 0.0, "gross_pnl": 0.0})
    return pd.concat([panel, skip], ignore_index=True, sort=False)


def fit_thresholds(scores_non_skip: np.ndarray) -> np.ndarray:
    """theta_{10,40,60,90} on the training window's non-SKIP scores (eq:thresholds)."""
    x = np.asarray(scores_non_skip, dtype=float)
    x = x[np.isfinite(x)]
    return np.percentile(x, GRADE_PERCENTILES)


def grade(scores: np.ndarray, thr: np.ndarray) -> np.ndarray:
    """eq:grade_assignment. Boundaries: (thr_k, thr_{k+1}] -> k+1; <= thr_10 -> 0."""
    s = np.asarray(scores, dtype=float)
    return np.searchsorted(thr, s, side="left").astype(int)


def skip_grade_check(thr: np.ndarray) -> bool:
    """Paper asserts SKIP (score 0) always lands in grade 1: thr_10 < 0 <= thr_40."""
    return bool(thr[0] < 0 <= thr[1])
