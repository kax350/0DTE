"""Unit tests for code correctness. Fixtures are hand-made numbers, NOT market data or results."""
import datetime as dt
import math

import numpy as np
import pandas as pd
import pytest

from vrp_ltr import bs, gate, label, metrics
from vrp_ltr.calendar import fomc_excluded_days, trading_time_years
from vrp_ltr.config import PRODUCTS, fee_per_contract
from vrp_ltr.execution import regt_short_put_margin, spread_fill, single_fill
from vrp_ltr.universe import resolve_strikes, risk_capped_long_strike, shortest_expiry


def test_bs_put_call_parity_and_iv_roundtrip():
    S, K, T, r, s = 5000.0, 4950.0, 6 / (390 * 252 / 60) / 60, 0.05, 0.18
    T = 360 / (390 * 252)
    c, p = bs.price(S, K, T, r, s, "C"), bs.price(S, K, T, r, s, "P")
    assert c - p == pytest.approx(S - K * math.exp(-r * T), abs=1e-8)
    iv = bs.implied_vol(p, S, K, T, r, "P")
    assert iv == pytest.approx(s, rel=1e-6)
    assert np.isnan(bs.implied_vol(0.0, S, K, T, r, "P"))  # below intrinsic/zero → NaN


def test_trading_time_0dte_at_10am():
    now = pd.Timestamp("2024-06-03 10:00", tz="America/New_York")
    assert trading_time_years(now, dt.date(2024, 6, 3)) == pytest.approx(360 / (390 * 252))
    # 1-DTE adds a full session, overnight contributes nothing
    assert trading_time_years(now, dt.date(2024, 6, 4)) == pytest.approx(750 / (390 * 252))


def test_sortino_on_bars_telescopes_and_penalises_path():
    marks_a = label.mark_series(2.0, np.array([1.5, 1.0, 0.5]), 0.0)
    marks_b = label.mark_series(2.0, np.array([3.0, 4.0, 1.0]), 0.0)
    sa, ga, ta = label.sortino_on_bars(marks_a)
    sb, gb, tb = label.sortino_on_bars(marks_b)
    assert ga == pytest.approx(2.0) and gb == pytest.approx(2.0)  # same terminal P&L
    assert ta == 0 and tb == pytest.approx(math.sqrt(1 + 1))
    assert sa > sb  # stressed path scores lower


def test_grades_boundaries():
    thr = np.array([-1.0, 0.5, 1.0, 2.0])
    s = np.array([-2, -1, -0.5, 0.0, 0.5, 0.7, 1.0, 1.5, 2.0, 3.0])
    assert label.grade(s, thr).tolist() == [0, 0, 1, 1, 1, 2, 2, 3, 3, 4]
    assert label.skip_grade_check(thr)


def test_shortest_expiry_and_strike_resolution_tie_lower():
    today = dt.date(2021, 6, 8)  # Tuesday pre-2022: no same-day SPXW expiry
    assert shortest_expiry([dt.date(2021, 6, 7), dt.date(2021, 6, 9), dt.date(2021, 6, 11)], today) == dt.date(2021, 6, 9)
    puts = pd.DataFrame({"strike": [100, 101, 102], "delta": [-0.10, -0.20, -0.30], "mid": [1, 2, 3]})
    c = resolve_strikes(puts, targets=(0.15, 0.30))
    assert c["strike"].tolist() == [100, 102]  # 0.15 ties 0.10/0.20 → lower strike


def test_fomc_exclusion_contains_known_days():
    ex = fomc_excluded_days()
    assert dt.date(2025, 3, 19) in ex and dt.date(2020, 3, 18) in ex
    assert dt.date(2020, 3, 3) not in ex  # unscheduled action not excluded (PREREG §1.3)


def test_fills_fees_margin():
    xsp, spxw = PRODUCTS["XSP"], PRODUCTS["SPXW"]
    assert single_fill(1.00, 1.10, "L1", spxw) == pytest.approx(1.05)
    assert single_fill(1.00, 1.10, "L3", spxw) == pytest.approx(0.95)
    assert single_fill(0.01, 0.02, "L3", xsp) is None  # would sell at 0.00
    assert spread_fill(0.60, 0.62, 0.40, 0.42, "NAT", xsp) == pytest.approx(0.18)
    assert fee_per_contract(spxw, 1.2, "full") == pytest.approx(0.65 + 0.59 + 0.05)
    # Reg-T: 100*(P + max(0.15 S - OTM, 0.10 K))
    assert regt_short_put_margin(2.0, 5000, 4900) == pytest.approx(100 * (2.0 + max(750 - 100, 490)))


def test_risk_capped_long_strike_widest_within_cap():
    puts = pd.DataFrame({"strike": [95, 96, 97, 98, 99, 100], "bid": [.01, .02, .04, .08, .15, .30],
                         "ask": [.02, .03, .05, .09, .16, .31]})
    # short 100 @ bid .30; width w long ask a: loss=(w - (.30-a))*100
    k = risk_capped_long_strike(puts, 100, cap_dollars=250, multiplier=100)
    assert k == 98  # W=2: (2-0.21)*100=179 ok; W=3: (3-0.26)*100=274 > 250


def test_gate_prefers_abstaining_on_bad_low_confidence_days():
    d = pd.date_range("2020-01-01", periods=10)
    gaps = pd.Series([0.9, 0.8, 0.7, 0.6, 0.5, 0.1, 0.1, 0.1, 0.1, 0.1], index=d)
    pnl = pd.Series([1, 1, 1, 1, 1, -5, -5, -5, -5, -5], index=d, dtype=float)
    res = gate.calibrate(gaps, pnl)
    assert res["rate"] <= 0.5


def test_metrics_psr_dsr_bootstrap():
    rng = np.random.default_rng(0)
    x = rng.normal(0.001, 0.01, 500)
    assert 0.5 < metrics.psr(x) <= 1.0
    assert metrics.dsr(x, 100) < metrics.psr(x)
    b = metrics.stationary_bootstrap_means(x, reps=2000)
    assert abs(b.mean() - x.mean()) < 3 * x.std() / math.sqrt(len(x))
    assert metrics.remove_best_days(np.array([1, 5, 2, 9]), 2).tolist() == [1, 2]
    assert metrics.max_drawdown(np.array([0.1, -0.5, 0.2])) == pytest.approx(0.5)


def test_shadow_hash_chain(tmp_path, monkeypatch):
    from vrp_ltr import shadow
    monkeypatch.setattr(shadow, "LOG", tmp_path / "log.jsonl")
    shadow.append({"type": "t", "x": 1})
    shadow.append({"type": "t", "x": 2})
    assert shadow.verify()
    lines = (tmp_path / "log.jsonl").read_text().splitlines()
    lines[0] = lines[0].replace('"x": 1', '"x": 9')
    (tmp_path / "log.jsonl").write_text("\n".join(lines) + "\n")
    assert not shadow.verify()


def test_defined_risk_cap_and_settlement():
    import datetime as dt
    from vrp_ltr.defined_risk import run
    d = dt.date(2024, 6, 3)
    q = pd.DataFrame({"t": ["10:00"] * 4 + ["10:03"] * 4, "strike": [95, 96, 97, 100] * 2,
                      "bid": [.02, .04, .08, .60, .02, .04, .08, .60], "ask": [.03, .05, .09, .62, .03, .05, .09, .62]})
    dp = {d: {"cands": {"P10": 100.0}, "quotes": q, "settle": 98.0, "spot": 101.0}}
    picks = pd.Series({d: "P10"})
    r = run(picks, dp, "XSP", "CAP2", "NAT", "10:03", nav0=25_000).iloc[0]
    # widest long strike with (W - credit)*100 + fees <= $500: W=5 (95): credit .57 → 443 + fees ok
    assert r["long_k"] == 95 and r["traded"] == 1
    assert r["max_loss"] <= 500 + 1e-9
    # settle 98: short 100 put pays 2.00, long 95 worthless → pnl = (0.57 - 2.00)*100 - fees
    assert r["pnl"] == pytest.approx((0.57 - 2.0) * 100 - r["max_loss"] + (5 - 0.57) * 100, abs=1e-6)
    w5 = run(picks, dp, "XSP", "W5", "MID", "10:00", nav0=25_000).iloc[0]
    assert w5["credit"] == pytest.approx(0.61 - 0.025)
