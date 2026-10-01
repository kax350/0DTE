# RETAIL_V2_PRIOR_EVIDENCE — what was known before Retailization V2 was frozen

Written 2026-10-01 ~03:45 ET, **before** `RETAIL_V2_PREREGISTRATION.md` was committed and before any
2023-or-later strategy outcome was computed. It records the evidence that shaped the V2 design.
Everything here counts as **SEEN**. Any V2 rule motivated by it is labelled `POST-WF2`.

## 1. Infrastructure already built (reused, not rewritten)

| Component | Status |
|---|---|
| Data | Databento OPRA `cbbo-1m` minute NBBO, full strike band of the shortest expiry, 09:31–16:14 ET. SPXW covers 2017-01 → 2026-09; XSP and SPY cover 2021-01 → 2026-09. SPX 1-min data validated against FRED (median error ≤ 0.33 bp). Cboe VIX family, VX settlements, put/call ratios, FRED EFFR/claims, BEA PCE dates, FOMC calendar. Spend so far $185.90, cap $300 |
| Pipeline | `vrp_ltr/` package: universe and delta resolution, path-aware label, S1–S5 feature selection, LambdaRank + Optuna, confidence gate, paper sizing (7 methods), defined-risk engine (`defined_risk.py`), metrics with PSR/DSR, bootstraps and Diebold–Mariano, trial registry, hash-chained shadow log. 12 unit tests pass |
| Walk-forward | WF1 (test 2021) and WF2 (test 2022) run for both lag policies. WF3, WF4, OOT and EXT_B are **not yet run** |
| Prior pre-registration | `PREREGISTRATION.md` (commit b76635a). Primary $25k candidate named in advance: **X-CAP2, NAT, 10:03, 1 lot**, i.e. an XSP bull put spread, $25k NAV, 1 contract, max loss ≤ 2% NAV, natural fill, 10:03 ET entry. **Kept in V2; not deleted** |

## 2. Negative evidence already seen (2021 = WF1, 2022 = WF2; SPXW, one naked contract)

**Daily P&L in USD at L1 (mid fill, paper fees).**

| Strategy | 2021 P&L | 2021 Sharpe | 2022 P&L | 2022 Sharpe | Worst day 2022 |
|---|---|---|---|---|---|
| B-FIX-05 (always 5Δ) | +14,381 | 2.86 | −19,197 | −1.14 | −12,696 |
| P-LAG M-HEAD (paper-literal lag) | +5,437 (44 trades) | 3.84 | −7,814 (95 trades) | −0.59 | −11,397 |
| **A-LAG M-HEAD (availability-correct)** | +19,555 (244 trades) | 1.63 | **−33,977** (199 trades) | −1.22 | −20,948 |
| A-LAG M-FORCED | +17,041 | 1.32 | −28,736 | −1.00 | −20,638 |
| B-FIX-45 | +16,709 | 0.56 | −64,090 | −1.26 | −20,948 |
| B-RAND (seed 0) | +15,190 | 0.75 | −46,046 | −1.22 | −20,638 |

Findings:

1. **WF1 (2021): no selection alpha.** At the same execution level, always-5Δ (Sharpe 2.86) beats the A-LAG ranker (1.63).
2. **WF2 (2022): the paper's positive result is not reproduced.** The paper reports Sharpe 2.51 (EA sizing) for 2022. We get negative results under both lag policies. Under A-LAG the ranker loses more than always-5Δ (−$33,977 vs −$19,197).
3. **Selection-alpha verdict (M-HEAD vs best training bucket, 2021–22):** paired stationary-bootstrap P(diff > 0) = 0.27–0.31 at L1/L2/L3. **FAIL.**
4. **Paper sizing (P-LAG, $5M):** EA Sharpe 3.36 in 2021 (paper 6.52) and −0.77 in 2022 (paper 2.51). The sizing parameter θ* pins at the top of its grid in every window, as the paper's own appendix shows.
5. **Tail mechanism.** A-LAG picks, 2021–22, P&L by bucket:

   | Bucket | Picks | P&L (USD) |
   |---|---|---|
   | P05 | 271 | +4,625 |
   | P10 | 71 | +6,029 |
   | P15 | 38 | −5,874 |
   | P20 | 11 | −9,309 |
   | P25 | 31 | −1,435 |
   | P40 | 14 | +7,680 |
   | P45 | 5 | −17,577 |

   Mostly low delta. A handful of jumps to 20Δ/45Δ wipe out the profit: 5 P45 picks lose more than 271 P05 picks earn.
6. **Regime (POST-HOC):** 2022 A-LAG by prior-close VIX: mid regime (15–25) −$44,685 over 112 days; high regime (>25) +$10,708 over 87 days. Any "avoid VIX 15–25" rule built from this is **POST-HOC** and not eligible for a PASS decision.
7. **Degenerate rankers.** Early stopping on the final-ES slice gives `best_iteration = 1` (a single tree) in three of four fitted models (A-LAG WF1, A-LAG WF2, P-LAG WF2). The model is close to a one-split rule; what it learns is mostly "which bucket was good recently".
8. **Confidence gate.** Under A-LAG it calibrates to trade rate 1.0 (τ = 0) in both windows, so it never abstains. Under P-LAG it calibrates to 0.3 (2021) and 0.5 (2022). Abstention under P-LAG comes from leaked information (point 9).

## 3. Look-ahead evidence

The paper-literal per-strategy lag (P-LAG) uses an outcome that settles **at today's close** on 1-DTE days (pre-2022 Tue/Thu). Test (`docs/leak_test.json`), on the 423 affected days in 2017–2021:

| Lag policy | Spearman, day-mean lagged ROM vs same-day P&L | p-value |
|---|---|---|
| P-LAG | **+0.302** | 2e-10 |
| A-LAG | −0.062 | 0.21 |
| Normal days (for reference) | −0.129 | — |

- P-LAG is therefore a **replication diagnostic only**.
- We do **not** claim the authors cheated or that their code leaks. We only show that the literal reading of the text admits same-day information, and that the paper's headline numbers are not reproduced under the availability-correct lag.
- **Default for all V2 retail results: A-LAG.**

## 4. Execution evidence (live Cboe delayed snapshot 2026-09-30, ≈15:32 ET; not a test-window date)

**Half-spread as a share of mid ("L3 haircut")**

| Delta | SPXW | XSP | SPY |
|---|---|---|---|
| 5Δ | 6.2% | 11.7% | 13.8% |
| 10Δ | 6.7% | 8.4% | 7.6% |
| 15Δ | 3.3% | 4.7% | 4.3% |

- XSP naked Reg-T margin is about $10.5–11.7k per contract, so a naked short at $25k is ruled out as a retail product.
- XSP 10Δ $5-wide spread: MID credit $19, NAT credit $17, max loss ≈ $484.

## 5. Partial exposure to years after 2022 (disclosed; not hidden)

- **B-FIX-BESTTRAIN.** `results/*/selection_alpha_*.json` lists the best fixed bucket by in-sample one-contract L1 naked Sharpe over 2018..Y−1 for Y = 2023…2026. It was computed while the 2023–2025 SPXW panels were **partially** built. Answer: **P05 in every case.** This reveals a relative ranking over long in-sample windows that partly overlap 2023–2025. It does not reveal the sign or size of any post-2022 P&L. Status: **SEEN-AGGREGATE (partial).**
- **Built but not viewed.** Candidate panels (per-day outcomes) exist for part of 2023–2026 (SPXW) and 2023–2025 (XSP/SPY dp files). No statistic, plot or aggregate of their outcomes has been computed or viewed.
- **Researcher priors.** The researcher knows the paper's reported 2021–2025 numbers and general market history through mid-2026 (e.g. the April 2025 tariff selloff and VIX spike). This is why every V2 rule is frozen in writing before the confirmatory years are evaluated, and why rules are kept few and simple.

## 6. Status of each year for V2

| Period | Status | Role in V2 |
|---|---|---|
| 2017–2020 | training | model fitting only |
| 2021 (WF1), 2022 (WF2) | **SEEN** (SPXW one-contract and sizing). XSP/SPY spread results not yet computed | **DEVELOPMENT / DIAGNOSTIC**; carries no weight in PASS |
| 2023 (WF3), 2024 (WF4) | strategy outcomes **UNSEEN** (see §5 for partial aggregate exposure) | **CONFIRMATORY** |
| 2025 (OOT) | strategy outcomes **UNSEEN**; paper's reported 2025 numbers known | **CONFIRMATORY** |
| 2026-01 → 2026-09 (EXT) | strategy outcomes **UNSEEN** | **CONFIRMATORY** (Test B primary, Test A reported) |
| 2026-10 onward | future | forward shadow |
