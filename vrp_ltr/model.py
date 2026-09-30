"""LightGBM LambdaRank + Optuna TPE per walk-forward window (PAPER_SPEC §6)."""
from __future__ import annotations

import datetime as dt

import lightgbm as lgb
import numpy as np
import optuna
import pandas as pd

from .config import EARLY_STOP, FIXED_LGB, MAX_ROUNDS, OPTUNA_TRIALS, SKIP

optuna.logging.set_verbosity(optuna.logging.WARNING)


def month_offset(d: dt.date, months: int) -> dt.date:
    y, m = d.year, d.month - months
    while m <= 0:
        m += 12
        y -= 1
    return dt.date(y, m, 1)


def split_window(days: list[dt.date], train_end_year: int) -> dict[str, list[dt.date]]:
    """Gate slice = last 6 months of the training window; search slice = last 6 months of the
    rest; early-stopping slice = last 3 months of the rest (its more recent half)."""
    end = dt.date(train_end_year + 1, 1, 1)
    gate_start = month_offset(end, 6)
    search_start = month_offset(gate_start, 6)
    es_start = month_offset(gate_start, 3)
    ranker = [d for d in days if d < gate_start]
    return {
        "ranker": ranker,
        "gate": [d for d in days if gate_start <= d < end],
        "search_train": [d for d in ranker if d < search_start],
        "search_val": [d for d in ranker if d >= search_start],
        "final_train": [d for d in ranker if d < es_start],
        "final_es": [d for d in ranker if d >= es_start],
    }


def _ds(panel: pd.DataFrame, feats, days) -> tuple[lgb.Dataset, pd.DataFrame]:
    p = panel[panel["date"].isin(set(days))].sort_values(["date", "strategy"])
    grp = p.groupby("date", sort=True).size().values
    ds = lgb.Dataset(p[feats], label=p["grade"].values, group=grp, free_raw_data=False)
    return ds, p


def ndcg_at_1(model, p: pd.DataFrame, feats) -> float:
    s = model.predict(p[feats], num_iteration=model.best_iteration or None)
    p = p.assign(_s=s)
    vals = []
    for _, g in p.groupby("date"):
        top = g.loc[g["_s"].idxmax(), "grade"]
        best = g["grade"].max()
        gain = [0, 1, 3, 7, 15]
        vals.append(gain[int(top)] / gain[int(best)] if best > 0 else 1.0)
    return float(np.mean(vals))


def tune_and_fit(panel: pd.DataFrame, feats: list[str], sl: dict, seed: int,
                 n_trials: int = OPTUNA_TRIALS) -> tuple[lgb.Booster, dict]:
    dtr, _ = _ds(panel, feats, sl["search_train"])
    dva, pva = _ds(panel, feats, sl["search_val"])

    def objective(trial):
        params = dict(FIXED_LGB,
                      num_leaves=trial.suggest_int("num_leaves", 16, 256, log=True),
                      learning_rate=trial.suggest_float("learning_rate", 0.01, 0.10, log=True),
                      min_data_in_leaf=trial.suggest_int("min_data_in_leaf", 20, 200, log=True),
                      feature_fraction=trial.suggest_float("feature_fraction", 0.5, 1.0),
                      bagging_fraction=trial.suggest_float("bagging_fraction", 0.5, 1.0),
                      bagging_freq=trial.suggest_int("bagging_freq", 0, 10),
                      lambda_l1=trial.suggest_float("lambda_l1", 1e-3, 10, log=True),
                      lambda_l2=trial.suggest_float("lambda_l2", 1e-3, 10, log=True),
                      seed=seed, deterministic=True, num_threads=4)
        m = lgb.train(params, dtr, num_boost_round=MAX_ROUNDS, valid_sets=[dva],
                      callbacks=[lgb.early_stopping(EARLY_STOP, verbose=False)])
        return ndcg_at_1(m, pva, feats)

    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=seed))
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)
    best = dict(FIXED_LGB, **study.best_params, seed=seed, deterministic=True, num_threads=4)
    dft, _ = _ds(panel, feats, sl["final_train"])
    des, _ = _ds(panel, feats, sl["final_es"])
    model = lgb.train(best, dft, num_boost_round=MAX_ROUNDS, valid_sets=[des],
                      callbacks=[lgb.early_stopping(EARLY_STOP, verbose=False)])
    return model, {"best_params": study.best_params, "best_ndcg1_search": study.best_value,
                   "best_iteration": model.best_iteration}


def predict(model: lgb.Booster, panel: pd.DataFrame, feats) -> pd.Series:
    return pd.Series(model.predict(panel[feats], num_iteration=model.best_iteration or None), index=panel.index)


def top_picks(panel: pd.DataFrame, scores: pd.Series, forced: bool = False) -> pd.DataFrame:
    """Per day: top-1 strategy, confidence gap top1-top2. forced=True removes SKIP (M-FORCED)."""
    p = panel.assign(_s=scores)
    if forced:
        p = p[p["strategy"] != SKIP]
    rows = []
    for d, g in p.groupby("date"):
        g = g.sort_values("_s", ascending=False)
        gap = g["_s"].iloc[0] - g["_s"].iloc[1] if len(g) > 1 else np.inf
        rows.append({"date": d, "pick": g["strategy"].iloc[0], "gap": gap})
    return pd.DataFrame(rows).set_index("date")
