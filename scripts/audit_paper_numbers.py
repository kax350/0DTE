"""Internal-consistency audit of the numbers published in arXiv:2608.24786v1.

Uses only numbers printed in the paper's tables (paper/tex_source/tables/*.tex).
No option data is needed. Output: docs/paper_audit_numbers.json (+ stdout).

Checks
  A. Sharpe convention: reported Sharpe == aRC / aSD for every row.
  B. PSR consistency: under Bailey & Lopez de Prado (2012), for one strategy slice
     the three PSRs (vs BH, PUT, WPUT) share one denominator D, so
     Phi^-1(PSR_b) / (SR - SR*_b) must be the same for all b. Also back out D^2.
  C. DSR recomputation from the implied D with N_t = 75 (App. A formula).
  D. Distribution shape implied by D^2 = 1 - g3*SR + (g4-1)/4*SR^2, and the
     single-outlier interpretation (how large one day must be to reproduce D^2).
  E. Annualisation: reported CAGR uses N_days/252 years; calendar-time CAGR.
  F. Day counts vs the NYSE calendar minus FOMC days.
  G. Execution-drag implied mean-P&L / half-spread ratio.
  H. Additive decomposition arithmetic (tab:mechanism_decomposition).
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from scipy import optimize, stats

OUT = Path(__file__).resolve().parents[1] / "docs" / "paper_audit_numbers.json"

# ---- tab:headline_metrics (Sharpe, Sortino, aRC, aSD, MaxDD) -----------------------
HEADLINE = {
    # name: (WF: sharpe, sortino, ret, vol, mdd), (OOT: ...)
    "EA": ((3.1048, 4.5234, 0.1091, 0.0351, 0.0228), (5.7612, 7.0291, 0.1048, 0.0182, 0.0143)),
    "FMU": ((2.5119, 2.9925, 0.1319, 0.0525, 0.0691), (5.0632, 6.0447, 0.1795, 0.0354, 0.0196)),
    "SRS": ((2.7597, 3.4259, 0.1270, 0.0460, 0.0614), (5.2622, 6.9824, 0.1755, 0.0334, 0.0172)),
    "VT": ((2.2102, 2.4040, 0.1489, 0.0674, 0.0900), (4.6669, 4.9068, 0.2388, 0.0512, 0.0343)),
    "GB": ((2.0554, 2.2676, 0.1366, 0.0665, 0.0899), (5.0147, 5.8707, 0.2995, 0.0597, 0.0338)),
    "HK": ((1.9464, 2.2562, 0.1200, 0.0616, 0.0860), (4.3711, 5.1981, 0.2091, 0.0478, 0.0271)),
    "QK": ((1.8965, 2.1857, 0.1186, 0.0625, 0.0925), (4.3084, 5.1671, 0.1993, 0.0463, 0.0273)),
    "Random": ((0.0844, 0.0912, 0.0131, 0.1550, 0.3935), (0.3415, 0.3626, 0.0570, 0.1669, 0.1091)),
    "Always-P25d": ((-0.0191, -0.0203, -0.0030, 0.1571, 0.3438), (0.0005, 0.0005, 0.0001, 0.1663, 0.1273)),
    "Always-P45d": ((-0.0405, -0.0456, -0.0064, 0.1581, 0.3396), (0.1577, 0.1752, 0.0248, 0.1572, 0.1146)),
    "Momentum": ((-0.0051, -0.0057, -0.0008, 0.1616, 0.2894), (-0.3982, -0.4276, -0.0669, 0.1681, 0.1490)),
    "Rolling-Sharpe": ((0.5569, 0.5991, 0.0698, 0.1254, 0.2383), (0.6128, 0.6258, 0.0545, 0.0890, 0.0830)),
    "BH": ((0.6221, 0.8871, 0.1011, 0.1625, 0.3086), (0.4622, 0.6787, 0.0884, 0.1912, 0.2008)),
    "PUT": ((0.6795, 0.9091, 0.0675, 0.0993, 0.1994), (0.1754, 0.2605, 0.0252, 0.1436, 0.1642)),
    "WPUT": ((0.1449, 0.1879, 0.0145, 0.1003, 0.2285), (0.1312, 0.1593, 0.0151, 0.1152, 0.1339)),
}
# ---- tab:deployment_confidence ------------------------------------------------------
PSR = {
    ("EA", "WF"): {"BH": 0.9999, "PUT": 0.9998, "WPUT": 1.0000, "DSR": 0.9962},
    ("EA", "OOT"): {"BH": 0.9636, "PUT": 0.9710, "WPUT": 0.9721, "DSR": 0.8563},
    ("FMU", "WF"): {"BH": 0.9837, "PUT": 0.9806, "WPUT": 0.9967, "DSR": 0.9168},
    ("FMU", "OOT"): {"BH": 0.9836, "PUT": 0.9887, "WPUT": 0.9893, "DSR": 0.8638},
    ("SRS", "WF"): {"BH": 0.9934, "PUT": 0.9919, "WPUT": 0.9989, "DSR": 0.9561},
    ("SRS", "OOT"): {"BH": 0.9944, "PUT": 0.9966, "WPUT": 0.9968, "DSR": 0.9128},
}
N_DAYS = {"WF": 964, "OOT": 237}  # tab:regime_vix day counts
N_TRIALS = 75
EULER = 0.5772156649


def daily_arith_sr(arc: float, avol: float) -> float:
    """Approximate daily arithmetic Sharpe from annual geometric return and vol.

    mu_d ~= ln(1+aRC)/252 + sigma_d^2/2 (lognormal compounding correction).
    """
    sd = avol / math.sqrt(252)
    mu = math.log1p(arc) / 252 + sd * sd / 2
    return mu / sd


def e_max_sr(n_obs: int, n_trials: int) -> float:
    v = 1.0 / (n_obs - 1)
    return math.sqrt(v) * ((1 - EULER) * stats.norm.ppf(1 - 1 / n_trials)
                           + EULER * stats.norm.ppf(1 - 1 / (n_trials * math.e)))


def check_a() -> dict:
    out = {}
    for k, (wf, oot) in HEADLINE.items():
        for sl, row in (("WF", wf), ("OOT", oot)):
            sh, so, r, v, _ = row
            out[f"{k}/{sl}"] = {"reported": sh, "aRC/aSD": round(r / v, 4),
                                "abs_err": round(abs(sh - r / v), 4)}
    return out


def check_bcd() -> dict:
    out = {}
    for (m, sl), cells in PSR.items():
        n = N_DAYS[sl]
        idx = 0 if sl == "WF" else 1
        sr = daily_arith_sr(HEADLINE[m][idx][2], HEADLINE[m][idx][3])
        ratios, zs = {}, {}
        for b in ("BH", "PUT", "WPUT"):
            p = min(cells[b], 1 - 1e-6)
            srb = daily_arith_sr(HEADLINE[b][idx][2], HEADLINE[b][idx][3])
            z = stats.norm.ppf(p)
            zs[b] = z
            ratios[b] = z / (sr - srb) if p < 0.99995 else None
        valid = [x for x in ratios.values() if x is not None]
        k_ratio = float(np.median(valid)) if valid else None
        rec = {"daily_SR_arith": round(sr, 5), "annual_SR_arith": round(sr * math.sqrt(252), 3),
               "z_over_gap": {b: (None if v is None else round(v, 3)) for b, v in ratios.items()}}
        if k_ratio:
            d = math.sqrt(n - 1) / k_ratio
            d2 = d * d
            sr_star = e_max_sr(n, N_TRIALS)
            dsr = stats.norm.cdf((sr - sr_star) * math.sqrt(n - 1) / d)
            rec.update({
                "implied_D": round(d, 3), "implied_D2": round(d2, 3),
                "D2_if_gaussian": round(1 + 2 / 4 * sr * sr, 3),
                "E_max_SR_daily(N_t=75)": round(sr_star, 4),
                "DSR_recomputed": round(dsr, 4), "DSR_reported": cells["DSR"],
                # frontier: kurtosis needed for given skew
                "kurtosis_needed_if_skew": {
                    str(g3): round(1 + 4 * (d2 - 1 + g3 * sr) / (sr * sr), 1)
                    for g3 in (0, -2, -5, -8, -12)
                },
            })
        out[f"{m}/{sl}"] = rec
    return out


def single_outlier(n: int, sr_daily: float, target_d2: float) -> dict:
    """Find one-outlier sample (n-1 Gaussian-ish days + 1 loss day) matching SR and D^2.

    Returns loss-day size in units of total daily sd and the implied skew/kurtosis.
    Uses deterministic quantile-spaced 'normal' days to avoid sampling noise.
    """
    base = stats.norm.ppf((np.arange(1, n) - 0.5) / (n - 1))

    def build(loss_mult: float, s0: float) -> np.ndarray:
        x = np.concatenate([base * s0, [-loss_mult]])
        return x

    def moments(x: np.ndarray):
        sd = x.std(ddof=1)
        z = (x - x.mean()) / x.std(ddof=0)
        return sd, float(np.mean(z ** 3)), float(np.mean(z ** 4))

    def resid(loss_mult: float) -> float:
        x = build(loss_mult, 1.0)
        sd, g3, g4 = moments(x)
        return (1 - g3 * sr_daily + (g4 - 1) / 4 * sr_daily ** 2) - target_d2

    lm = optimize.brentq(resid, 0.5, 200.0)
    x = build(lm, 1.0)
    sd, g3, g4 = moments(x)
    share = lm ** 2 / np.sum((x - x.mean()) ** 2)
    return {"loss_day_in_other_day_sd": round(lm, 2), "loss_day_in_total_sd": round(lm / sd, 2),
            "skew": round(g3, 2), "kurtosis": round(g4, 1),
            "share_of_total_variance_from_one_day": round(float(share), 3)}


def check_e() -> dict:
    # EA 5-year NAV 5.0M -> 8.15M; paper states 10.8% geometric annualised.
    n = N_DAYS["WF"] + N_DAYS["OOT"]
    growth = (1 + 0.1091) ** (N_DAYS["WF"] / 252) * (1 + 0.1048) ** (N_DAYS["OOT"] / 252)
    return {"reported_terminal_multiple": 1.630, "reconstructed_multiple": round(growth, 4),
            "CAGR_per_252_obs": round(growth ** (252 / n) - 1, 4),
            "CAGR_calendar_5y": round(growth ** (1 / 5) - 1, 4),
            "sharpe_overstatement_factor_if_obs_per_year_is_240": round(math.sqrt(252 / 240), 4)}


def check_f() -> dict:
    import exchange_calendars as xc
    cal = xc.get_calendar("XNYS")
    res = {}
    for label, years, reported in (("WF", range(2021, 2025), 964), ("OOT", [2025], 237)):
        sessions = sum(len(cal.sessions_in_range(f"{y}-01-01", f"{y}-12-31")) for y in years)
        early = sum(1 for y in years for d in cal.sessions_in_range(f"{y}-01-01", f"{y}-12-31")
                    if cal.session_close(d).tz_convert("America/New_York").hour < 16)
        fomc = 8 * len(list(years))
        res[label] = {"nyse_sessions": sessions, "minus_8_fomc_per_year": sessions - fomc,
                      "minus_early_closes_too": sessions - fomc - early, "reported_days": reported,
                      "unexplained": sessions - fomc - early - reported}
    return res


def check_g() -> dict:
    # tab:execution: mid vs bid Sharpe with Q fixed. If vol unchanged, drag = dPremium / mean_PnL.
    rows = {"EA": (3.105, 2.725, 5.761, 5.311), "FMU": (2.512, 2.104, 5.063, 4.616),
            "SRS": (2.760, 2.349, 5.262, 4.918)}
    out = {}
    for m, (wf_mid, wf_bid, oot_mid, oot_bid) in rows.items():
        out[m] = {"WF_drag": round(1 - wf_bid / wf_mid, 3), "OOT_drag": round(1 - oot_bid / oot_mid, 3),
                  "implied_meanPnL_over_halfspread_WF": round(wf_mid / (wf_mid - wf_bid), 1),
                  "implied_meanPnL_over_halfspread_OOT": round(oot_mid / (oot_mid - oot_bid), 1)}
    return out


def check_h() -> dict:
    wf = 0.623 - 0.463 + 0.136 + 2.809
    oot = 5.221 + 0.652 + 0.012 - 0.124
    return {"WF_sum": round(wf, 3), "WF_reported": 3.105, "OOT_sum": round(oot, 3), "OOT_reported": 5.761,
            "share_of_WF_from_interaction": round(2.809 / 3.105, 3),
            "WF_neither_control": 0.623, "CBOE_PUT_WF": 0.680}


def main() -> None:
    res = {"A_sharpe_convention": check_a(), "BCD_psr_dsr": check_bcd()}
    ea = res["BCD_psr_dsr"]["EA/OOT"]
    res["D_single_outlier_EA_OOT"] = single_outlier(N_DAYS["OOT"], ea["daily_SR_arith"], ea["implied_D2"])
    fmu = res["BCD_psr_dsr"]["FMU/OOT"]
    res["D_single_outlier_FMU_OOT"] = single_outlier(N_DAYS["OOT"], fmu["daily_SR_arith"], fmu["implied_D2"])
    res["E_annualisation"] = check_e()
    res["F_day_counts"] = check_f()
    res["G_execution_drag"] = check_g()
    res["H_decomposition"] = check_h()
    worst = max(v["abs_err"] for v in res["A_sharpe_convention"].values())
    res["A_max_abs_err"] = worst
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, indent=2))
    print(json.dumps({k: v for k, v in res.items() if k != "A_sharpe_convention"}, indent=2))
    print("A: max |Sharpe - aRC/aSD| =", worst)


if __name__ == "__main__":
    main()
