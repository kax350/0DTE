# PREREGISTRATION — frozen before any historical option quote is loaded

Frozen: 2026-09-30 (America/New_York), git commit that first adds this file.
No option **outcome** data (bid/ask paths, settlements vs strikes, P&L) had been loaded
when this file was written. See `RESEARCH_LEDGER.md` for what *had* been seen.

Rules for amending this file:
1. Any change after data load is an **amendment** appended at the bottom, never an edit in place.
2. Each amendment states: date, reason, and whether any result for the affected period had
   already been computed or viewed.
3. Results produced under an amended rule for a period already viewed are labelled
   **POST-HOC**. They cannot support PASS.

The executable counterpart is `vrp_ltr/registry.py`. It enumerates every variant listed here
and supplies the trial count used by the Deflated Sharpe Ratio.

---

## 0. Data (all times America/New_York)

| Need | Source | Notes |
|---|---|---|
| SPXW / XSP / SPY option NBBO, 1-minute | Databento `OPRA.PILLAR`, schema `cbbo-1m` (consolidated BBO sampled at 1-min) | available 2013-04 →; condition file `data/reference/databento_opra_condition.csv` |
| Contract list | Databento `definition` (daily) | expiry taken from the OCC raw symbol (YYMMDD), **not** the UTC `expiration` timestamp |
| SPX 1-minute | `thillsss/SPX-MES-VIX-data` (HF), CT → ET | validated vs FRED SP500 closes: median |err| ≤ 0.33 bp per year, max 12.8 bp |
| Settlement S_settle | official SPX close (FRED `SP500`; HF 16:00 bar as fallback) | XSP settle = SPX close / 10 |
| SPY path / exits | Databento `OPRA` quotes for options; SPY underlying from Databento `EQUS`/`XNAS` or FRED-free substitute, decided in amendment if needed | |
| VIX family, VVIX | Cboe free CSVs | |
| VIX futures | Cboe CFE free historical settlement files | |
| EFFR, NSA claims (ICNSA) | FRED | |
| Put/call ratios | Cboe daily market statistics | if unobtainable → feature dropped (documented deviation) |
| CPI / NFP / PCE dates | BLS/BEA release archives | if unobtainable → feature dropped (documented deviation) |

Data validation (before any strategy is run): the pilot month **2019-06** (inside the first training window) is checked for
(a) put–call-parity forward vs SPX 1-minute index at 10:00 (|F·e^{−rT} − S|/S), 
(b) crossed/locked-quote rate,
(c) strikes available ≥ 0.05Δ OTM at 10:00,
(d) 0DTE availability pattern (Mon/Wed/Fri pre-2022).
Failure of (a) beyond 25 bp median → stop and report.

## 1. R0 — exact replication of the paper (SPXW)

Implements `PAPER_SPEC.md` exactly. Frozen resolutions of every [AMBIG] item:

1.1 τ = trading-time (`vrp_ltr/calendar.py::trading_time_years`).
1.2 Quote filter: bid > 0 and ask > bid; IV must solve from mid. Tie in |Δ| distance → lower strike. Duplicate strikes across buckets allowed.
1.3 FOMC exclusion: scheduled statement days + the cancelled 2020-03-18 slot (`fomc_dates.csv` kinds `scheduled`, `cancelled`). Unscheduled actions are not excluded.
1.4 `p_entry` in the label = 10:00 mid. Intermediate marks = ask at each 1-minute bar 10:01…15:59, terminal = settlement intrinsic. Missing asks forward-filled. Overnight (1-DTE) = one bar step.
1.5 Grade thresholds from the ranker-fit slice (training window minus the 6-month gate slice). The SKIP-in-grade-1 assertion is checked and logged.
1.6 S3 relevance on the continuous score. S4 clustering = connected components at |ρ| ≥ 0.85. S5 folds = expanding thirds of the training dates; final set = S1–S4(full) ∩ {fold survival ≥ 2}.
1.7 Optuna TPE seed = 20260825 + window index. 50 trials. NDCG@1 on the search slice.
1.8 Gate: trade-rate grid {0.3,…,1.0}; τ = (1−rate) quantile of Δŷ on the gate slice; objective Sortino of one-contract L1 net P&L of top-1 picks (SKIP = 0).
1.9 Two **feature-timing** variants (see PAPER_AUDIT R4):
  * **R0-P** (paper-literal): per-strategy outcome features lagged 1 session by entry date.
  * **R0-A** (availability-correct): a trade's outcome is usable only from the first 10:00 after its settlement.
  Headline replication = R0-P. The R0-A minus R0-P difference is a primary audit statistic.
1.10 Two **OOT gate** variants: **G-UNION** (paper `tab:gate`: union of WF test-year predictions) and **G-LAST6** (§3.5 text: last 6 months of 2024). Headline = G-UNION.
1.11 Sizing: all 7 paper methods with the paper's grids and the 16% equal-vol calibration, NAV0 $5M, Reg-T margin cap, paper fees. This is used only to compare against the paper's table.
1.12 Features that cannot be built from the listed sources are dropped and listed in `docs/feature_coverage.md`. No substitute features are invented.
1.13 Settlement for 1-DTE (pre-2022) = next session's official close.

## 2. Baselines (same universe, same execution levels)

| ID | Rule |
|---|---|
| B-FIX-05 … B-FIX-45 | always the same delta bucket (8 baselines) |
| B-RAND | uniform random over the 8 puts, seeds 0–99 (distribution reported) |
| B-ROLLBEST | bucket with the highest trailing-30-session mean one-contract L1 net P&L, known at 10:00 (A-LAG timing) |
| B-ROLLSHARPE | paper's Rolling-Sharpe: highest trailing-30-session Sharpe |
| B-MOM | bucket with the best most-recent settled one-contract P&L |
| B-FIX-BESTTRAIN | per window, the single fixed bucket with the best training-window one-contract Sharpe (honest ex-ante "best delta") |
| M-FORCED | ranker, argmax over the 8 puts only (SKIP row removed at inference, no gate) |
| M-SKIP | ranker with SKIP row, **no** gate |
| M-HEAD | ranker with SKIP row + gate (paper headline) |

## 3. Execution levels (all real quotes; no model prices anywhere)

Single short put: **L1** mid + paper fees · **P75** 0.75·bid+0.25·ask + paper fees · **L2** bid + paper fees · **L3** bid − 1 tick + full fees
(`config.fee_per_contract(level="full")`: IBKR commission + Cboe exchange fee + $0.05 clearing/regulatory).
Vertical: **MID** mid-combo · **NAT** bid_s − ask_l · **NAT1** natural − 1 tick. MID/NAT use paper fees; NAT1 uses full fees.
**Double-cost** stress: credit = mid − 2·(mid − L3 fill); fees × 2.
**Delay** stress: the decision and strikes are fixed from the 10:00:00 snapshot; the fill uses the quote of the same contracts at 10:01, 10:03 and 10:05, each at L2 and L3 (NAT/NAT1 for spreads).
A quote timestamp **t** means the consolidated BBO in force at t (the cbbo-1m record for the minute ending at t). Verified against raw semantics during the pilot and documented.
No fill if the fill price is ≤ 0 (single) or the credit is ≤ 0 (vertical). That day counts as no-trade and is logged.

## 4. $25k adaptations (NAV0 = $25,000; 0 or 1 contract; no leverage beyond 1 lot)

Short leg always = the ranker's pick from the **SPXW** model (M-HEAD), mapped to the same |Δ| target on the product's own 10:00 chain. Product-native retraining is a separate variant (§4.4).

| ID | Structure | Risk rule |
|---|---|---|
| X-NAKED | XSP short put, 1 lot | research/shadow benchmark only; **never a live candidate** |
| X-W5 | XSP put vertical, long = K_s − 5 exactly (missing strike → SKIP) | — |
| X-W10 | XSP vertical, long = K_s − 10 | — |
| X-CAP1 / X-CAP2 / X-CAP4 | "risk-capped adaptation": widest listed long strike with (W − natural credit)·100 + fees ≤ {1,2,4}% · NAV_{t−1}; none → SKIP | per-trade theoretical max loss ≤ cap |
| S-W5 / S-W10 / S-CAP{1,2,4} × EXIT{1545,1555} | same on SPY; position closed at the 15:45 or 15:55 quote (NAT/NAT1 or MID), never held into the close | American/physical: no assignment exposure because the position is flat before 16:00 |
| X-*-EDGE | the variant above plus the EA edge gate: trade only if F̂_train(ℰ_t) ≥ 0.50 (training-window median), 1 lot | threshold from training data only |

**Primary $25k candidate (named in advance):** **X-CAP2 at NAT execution, 10:03 fill, 1 lot.**
The PASS decision is made on this candidate alone. Every other variant is reported. If only a non-primary variant clears the gates, the verdict is at best **WEAK PASS**, pending forward shadow confirmation.

Discretisation loss: the EA method at $25k with integer contracts, compared with EA using fractional contracts (ideal), same picks.

4.4 Product-native variants (lower priority): XSP-native ranker retrained on XSP labels (features from SPXW). QQQ (Tier 3) needs its own addendum before any QQQ download. TQQQ excluded (Tier 4).

## 5. Kill tests (all must be reported for the primary candidate)

K1 NAT/L2 fills · K2 one tick worse (NAT1/L3) · K3 full commission + exchange fees · K4–K6 fills at 10:01 / 10:03 / 10:05 · K7 2020 stress (reported on the in-sample model, flagged in-sample) · K8 2022 · K9 2024 · K10 2025 holdout · K11 2026 extension (Test A and B) · K12 stationary bootstrap (Politis–Romano, mean block 10 sessions, 10,000 draws, seed 7) and moving-block bootstrap (block 20) of mean daily net P&L · K13 parameter perturbation (below) · K14 remove the 5 best days · K15 remove the 10 best days · K16 double transaction costs. Also: top-5 profit days / total profit; worst day; CVaR95/99; skew; kurtosis; max consecutive losses.

K13 perturbations (each run once, all reported): Optuna seed +1 and +2; correlation threshold 0.80 and 0.90; rolling 3-year window; delta targets shifted +0.025 and −0.025; for X-CAP2: cap 1.5% and 2.5%; for X-W5: W4 and W6.

## 6. 2026 external time extension

* **Test A (frozen):** the OOT model (trained through 2024), its gate and its sizing, applied unchanged to 2026-01-02 → last available session.
* **Test B (protocol retrain):** window EXT_B, training 2018–2025 with the full protocol (selection, Optuna, gate on the last 6 months of 2025, sizing), then a single prediction pass over 2026.
* Both models are saved and hashed (`models/*.sha256`) **before** any 2026 outcome is computed. 2026 is called an "external time extension", never "prospective".

## 7. Statistics

Sharpe is reported both arithmetic (mean·252 / sd·√252) and the paper's geometric (aRC/aSD). Both are computed per year for 2021, 2022, 2023, 2024, 2025 and 2026 separately. Also: CAGR (per-observation and calendar), Sortino, MaxDD, VaR/CVaR 95/99, skew, kurtosis, win rate, trade count, average premium, average margin, P&L by delta bucket, P&L by VIX regime (<15, 15–25, >25, on the prior close — the paper's same-day-close version is also shown and labelled), P&L by year.
PSR vs 0 and vs the best fixed-delta baseline. DSR with N_trials = `registry.n_trials()` (every variant evaluated in this project, counted automatically). Diebold–Mariano (h=1) for ranker vs each baseline, Bonferroni-corrected.

## 8. Decision rules (user's section L, applied to the primary candidate)

PASS requires all of the following:
1. net of costs, mean daily P&L > 0;
2. walk-forward 2021–24 Sharpe > 1.0;
3. 2025 Sharpe > 1.0;
4. 2026 Sharpe > 0 (Test A **and** Test B);
5. ≥ 4 of the 5 calendar years 2021–2025 net positive;
6. MaxDD < 10%;
7. every trade's theoretical max loss ≤ the budget;
8. edge > 0 at NAT;
9. edge > 0 at the 10:01 and 10:03 fills, and not destroyed at 10:05;
10. positive after removing the 5 best days;
11. stationary-bootstrap P(mean > 0) ≥ 0.95.

**WEAK PASS:** the primary fails only criterion 2 and/or 3 with the Sharpe between 0.5 and 1.0, all other criteria pass; **or** only a non-primary pre-registered variant passes all criteria. Either case requires ≥ 60 sessions of forward shadow log before any live use.
**FAIL:** anything else.
Selection-alpha verdict (section E): M-HEAD one-contract vs B-FIX-BESTTRAIN one-contract. It passes only if the paired stationary-bootstrap P(diff > 0) ≥ 0.95 on 2021–2024 **and** diff > 0 in 2025. If this fails, sizing results are reported but carry no weight.

## 9. Forward shadow protocol

`vrp_ltr/shadow.py`: each session at 10:16 ET, the Cboe delayed chains (10:01-stamped quotes) for SPX/XSP/SPY are captured. The frozen model's decision is written to `shadow/log.jsonl`. At 16:30 ET the outcome is appended. Every record carries the SHA-256 of the previous record, so the log is append-only and tamper-evident. Records are never edited; corrections are new records.

---
## Amendments
(none)
