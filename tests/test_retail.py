"""Unit tests for the Retail V2 engine on synthetic panels (no market data)."""
import datetime as dt
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vrp_ltr import retail as RT  # noqa: E402
from vrp_ltr import retail_metrics as RM  # noqa: E402

DAY = dt.date(2030, 1, 2)


def _rp(quotes: dict, settle=400.0, spot=402.0, puts10=None, root_spot=None):
    rows = [(t, k, b, a) for (t, k), (b, a) in quotes.items()]
    q = pd.DataFrame(rows, columns=["t", "strike", "bid", "ask"])
    rp = {"day": DAY, "expiry": DAY, "is_0dte": True, "spot10": root_spot or spot, "r": 0.0,
          "puts10": puts10 if puts10 is not None else pd.DataFrame(columns=["strike", "delta"]),
          "quotes": q, "settle": settle, "spot_1559": settle}
    rp["Q"] = {(t, float(k)): (b, a) for t, k, b, a in rows}
    rp["K"] = {t: np.sort(g["strike"].astype(float).unique()) for t, g in q.groupby("t")}
    return rp


def _spxw(k_spx=3950.0, delta=0.05, spot=4020.0):
    p = pd.DataFrame({"strike": [k_spx - 5, k_spx, k_spx + 5], "delta": [-(delta - 0.01), -delta, -(delta + 0.01)]})
    return {"puts10": p, "spot10": spot, "is_0dte": True}


def _ctx():
    return RT.Ctx(sigma5={}, fhs_z=pd.Series(dtype=float), m_close={}, sigma_bar={}, vix_prev={},
                  sessions=[DAY], pos={DAY: 0})


def _book(t, short=(0.10, 0.12), legs=None):
    legs = legs or {394.0: (0.03, 0.04), 393.0: (0.02, 0.03), 392.0: (0.01, 0.02), 391.0: (0.0, 0.02),
                    390.0: (0.0, 0.01), 389.0: (0.0, 0.01)}
    d = {(t, 395.0): short}
    d.update({(t, k): v for k, v in legs.items()})
    return d


def test_cap2_widest_and_pnl_otm():
    rp = _rp(_book("10:03"))
    rec = RT.run_day(DAY, 0.05, RT.Cfg(root="XSP"), _ctx(), rp_spxw=_spxw(), rp=rp)
    assert rec["traded"] == 1 and rec["short_k"] == 395.0
    assert rec["long_k"] == 390.0                       # widest with (W - nat)*100 + fees <= $500
    assert abs(rec["credit"] - (0.10 - 0.01)) < 1e-12   # natural
    assert rec["max_loss"] <= 500 + 1e-9
    assert abs(rec["pnl"] - (100 * 0.09 - rec["fees_entry"])) < 1e-9   # settles OTM


def test_loss_is_bounded_by_width():
    rp = _rp(_book("10:03"), settle=380.0)
    rec = RT.run_day(DAY, 0.05, RT.Cfg(root="XSP"), _ctx(), rp_spxw=_spxw(), rp=rp)
    assert abs(rec["pnl"] - (100 * (0.09 - 5.0) - rec["fees_entry"])) < 1e-9
    assert -rec["pnl"] <= rec["max_loss"] + 1e-9


def test_min_credit_and_cap_breach():
    rp = _rp(_book("10:03", short=(0.04, 0.05)))
    rec = RT.run_day(DAY, 0.05, RT.Cfg(root="XSP"), _ctx(), rp_spxw=_spxw(), rp=rp)
    assert rec["traded"] == 0 and rec["reason"] == "below-min-credit"
    rec = RT.run_day(DAY, 0.05, RT.Cfg(root="XSP", nav0=10_000.0), _ctx(), rp_spxw=_spxw(), rp=_rp(_book("10:03")))
    assert rec["traded"] == 1 and rec["long_k"] == 393.0  # B = $200 -> width 2


def test_delta_tolerance():
    rec = RT.run_day(DAY, 0.05, RT.Cfg(root="XSP"), _ctx(), rp_spxw=_spxw(delta=0.09), rp=_rp(_book("10:03")))
    assert rec["reason"] == "delta-unavailable"


def test_delayed_limit_touch_is_not_fill():
    q = _book("10:03", short=(0.10, 0.20))        # mid 0.15-0.005 ; natural 0.09 at long 390 ask .01
    for j, b in zip(range(4, 9), (0.10, 0.10, 0.10, 0.10, 0.10)):
        q.update(_book(f"10:0{j}", short=(b, 0.20)))
    rec = RT.run_day(DAY, 0.05, RT.Cfg(root="XSP", level="DL"), _ctx(), rp_spxw=_spxw(), rp=_rp(q))
    assert rec["reason"] == "no-fill"
    L = rec["dl_limit"]
    q.update(_book("10:06", short=(L + 0.01 + 0.01, 0.20)))  # natural = L + 1 tick -> trade-through
    rec = RT.run_day(DAY, 0.05, RT.Cfg(root="XSP", level="DL"), _ctx(), rp_spxw=_spxw(), rp=_rp(q))
    assert rec["traded"] == 1 and rec["fill_t"] == "10:06" and abs(rec["credit"] - (L - 0.01)) < 1e-12


def test_s1_floor_and_fractional():
    rp = _rp(_book("10:03"))
    rec = RT.run_day(DAY, 0.05, RT.Cfg(root="XSP", sizing="S1", nav0=50_000.0), _ctx(), rp_spxw=_spxw(), rp=rp)
    assert rec["n"] == 2
    rec = RT.run_day(DAY, 0.05, RT.Cfg(root="XSP", sizing="S1", nav0=10_000.0), _ctx(), rp_spxw=_spxw(), rp=rp)
    assert rec["reason"] == "size-zero"
    rec = RT.run_day(DAY, 0.05, RT.Cfg(root="XSP", sizing="S1", nav0=10_000.0, fractional=True), _ctx(),
                     rp_spxw=_spxw(), rp=rp)
    assert 0 < rec["n"] < 1


def test_spy_closed_at_1555():
    q = _book("10:03")
    q.update({("15:55", 395.0): (0.50, 0.60), ("15:55", 390.0): (0.0, 0.01)})
    rp = _rp(q, settle=394.0)
    rec = RT.run_day(DAY, 0.05, RT.Cfg(root="SPY"), _ctx(), rp_spxw=_spxw(), rp=rp)
    assert rec["traded"] == 1 and abs(rec["exit_debit"] - 0.60) < 1e-12   # long abandoned (zero bid)
    assert rec["assign_risk"] == 1


def test_dm_and_paired():
    rng = np.random.default_rng(0)
    idx = pd.date_range("2030-01-01", periods=300, freq="B").date
    a = pd.DataFrame({"pnl": rng.normal(1.0, 1.0, 300)}, index=idx)
    b = pd.DataFrame({"pnl": rng.normal(0.0, 1.0, 300)}, index=idx)
    pr = RM.paired(a, b)
    assert pr["p_stationary"] > 0.99 and pr["dm_p"] < 0.01
