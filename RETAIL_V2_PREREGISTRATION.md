# RETAIL_V2_PREREGISTRATION — $25k defined-risk 0DTE product (frozen before 2023+ outcomes)

Frozen 2026-10-01 ET. The commit hash of this file is recorded in `RESEARCH_LEDGER.md`
(entry #25). Only after that commit may any 2023–2026 strategy outcome be computed.

- **Evidence that shaped this design:** `RETAIL_V2_PRIOR_EVIDENCE.md`.
- **Precedence:** this document supersedes `PREREGISTRATION.md` §4, §5 and §8 for the retail verdict. The paper-replication parts of `PREREGISTRATION.md` (R0 replication, P-LAG and A-LAG walk-forward, paper sizing) stay in force as **mechanism audit / benchmark / falsification**.
- **Allowed conclusions:** `PASS`, `WEAK PASS`, `FAIL`. **`NO RETAIL EDGE` is an allowed and pre-accepted outcome.**

---

## 0. Data status and evaluation periods

| Period | Label | Use |
|---|---|---|
| 2017-01 → 2020-12 | TRAIN | ranker training only |
| 2021, 2022 | **DEVELOPMENT / SEEN** | engine debugging and diagnostics. Reported, but **carries no weight** in any V2 decision |
| **2023-01-03 → 2026-09-29** | **CONFIRMATORY** | the only period used for selection and for the PASS / WEAK PASS / FAIL verdict |
| 2026-10-01 → | FORWARD SHADOW | live-consistency check (§13) |

**Exposure disclosed before freezing** (see `RETAIL_V2_PRIOR_EVIDENCE.md` §5):

- partial aggregate exposure through B-FIX-BESTTRAIN, which showed P05 best in-sample;
- researcher knowledge of the paper's numbers and of general market history.

No 2023+ strategy P&L has been computed or viewed.

**Evaluation day set E.** NYSE sessions in the period, excluding scheduled-FOMC days (`fomc_excluded_days()`).

- A day is in E for a product only if all of these exist:
  - the product's own 0DTE chain at 10:00;
  - the SPXW decision inputs (model features/scores);
  - a settlement value (XSP) or 15:55 quotes (SPY).
- Every candidate on a product is evaluated on **exactly the same E**. Missing days are listed, never silently dropped.
- Days where the product has no same-day expiry are **NO TRADE**. This applies to XSP and SPY in 2021–22 only; all three products have daily expiries throughout 2023+.

**Lag policy:** **A-LAG only** for every V2 result. P-LAG appears only in the replication audit.

## 1. Instruments

| Role | Instrument | Settlement | Notes |
|---|---|---|---|
| **Primary** | **XSP** 0DTE puts | European, cash, PM (SPX close / 10) | hold to expiry, no early-assignment risk |
| Independent validation | **SPY** 0DTE puts | American, physical | spread **closed at the 15:55 quote** at natural; never held into the close (no expiry exercise). Assignment-risk days are counted (§10) |
| Benchmark only | **SPXW** 0DTE puts | European, cash, PM | signal discovery + institutional benchmark; **never a V2 candidate** |

## 2. Daily decision protocol (identical for every candidate)

1. **09:30–10:00:** read data. Only information time-stamped ≤ 10:00:00 is used. Daily series (VIX family, claims, EFFR, SPX close) use the prior session.
2. **10:00:**
   - compute features and ranker scores (SPXW model);
   - compute the product's 10:00 put chain: IV from mid; Black–Scholes put delta with r = EFFR prior and trading-time τ; spot = SPX/10 for XSP, put–call parity for SPY;
   - choose the short and long strikes from the 10:00 snapshot.
3. **10:03 (primary fill time):** one order for **one vertical spread position** (≤ 1 per day). After the fill there is **no intervention**:
   - XSP is held to settlement;
   - SPY is closed mechanically at 15:55.
4. If any check in §4 fails: **NO TRADE**, with the reason logged. FLAT days count as $0 P&L.

**Short strike.** The listed put whose 10:00 |Δ| is closest to the target (ties → lower strike).

- **Delta tolerance:** if |Δ_actual − Δ_target| > 0.025, the day is **NO TRADE (`delta-unavailable`)**. This avoids the 2021 XSP case, where all targets collapsed onto the lowest listed strike.
- The paper's SPXW replication keeps the paper rule (no tolerance).

## 3. Structures and sizing

All structures are **bull put spreads** (short K_s, long K_l < K_s, same 0DTE expiry).

**Integer contracts only. No naked short. No portfolio netting. No intraday leverage beyond the spread's own max loss.**

**Risk budget** B = r · NAV0, with r ∈ {0.5%, 1.0%, **2.0% (primary)**}. NAV0 is fixed (no compounding of the risk unit). NAV path = NAV0 + cumulative P&L.

| Sizing | Construction | Contracts |
|---|---|---|
| **S0 (primary)** | **CAP-r**: widest listed K_l < K_s with natural credit > 0 at 10:00 and (K_s − K_l − c_nat,10:00)·100 + fees ≤ B | 1 |
| S1 | fixed width W = 5 (XSP $5, SPY $5; SPXW 5 pts) | n = floor(B / max loss per spread at the actual fill); n = 0 → NO TRADE |
| S2 (secondary) | fixed width W = 5 | n = floor(B · min(1, σ̄ / σ_t) / max loss per spread). σ_t = σ_intra5d (prior 5 sessions of 1-min SPX RV); σ̄ = median σ_intra5d over 2018..Y−1. n = 0 → NO TRADE |
| Paper sizing | — | replication only (unchanged) |

**Max loss at the actual fill:**

- max loss = (W − c_fill)·100·n + entry fees, plus exit fees for SPY.
- Cap check: if max loss > B → **NO TRADE (`fill-breaches-cap`)**.
- **Minimum credit** c_fill ≥ **$0.05** per spread, else **NO TRADE (`below-min-credit`)**. Sensitivity at $0.02 and $0.10 is reported only.

**NAV grid:** NAV0 ∈ {$10k, **$25k**, $50k}.

- Integer contracts vs fractional n* = B / max loss on the S1 structure, reported as the discretisation loss.
- Fractional results are **never** a candidate.

## 4. Execution model (real minute NBBO, Databento `cbbo-1m`)

Strikes are fixed from 10:00. A quote at minute t is the NBBO in force at t.

**Fees (all levels):** IBKR fixed commission tiers + exchange fee + $0.05 clearing/regulatory per contract per leg (`fee_per_contract(level="full")`), with a $1 order minimum.

- **XSP:** settlement at expiry costs no fee.
- **SPY:** the 15:55 close pays fees on each leg traded. The long leg is sold only if its bid > 0; otherwise it is abandoned at zero value, which is conservative.

| Level | Credit per spread at fill time t | Role |
|---|---|---|
| MID | (bid_s + ask_s)/2 − (bid_l + ask_l)/2 | theoretical upper bound **only** |
| **NATURAL** | bid_s − ask_l | **primary** |
| DELAYED LIMIT (DL@t0), t0 ∈ {10:01, 10:03, 10:05} | see below | execution realism |
| STRESS | mid − 2·(mid − natural) | slippage × 2 |

**DELAYED LIMIT (DL), "touch ≠ fill":**

1. At t0, limit L = natural(t0) + ⌊(mid(t0) − natural(t0)) / 2⌋_tick (tick $0.01 for XSP/SPY, $0.05 for SPXW).
2. If L = natural(t0), the order is marketable: fill at L at t0.
3. Otherwise the order works over minutes t0+1 … t0+5. It fills at L at the first minute where natural(t) ≥ L + 1 tick (the market trades **through** the limit). A touch (natural(t) = L) is **not** a fill.
4. No fill by t0+5 → cancel → **NO FILL** (logged; P&L 0). No chasing or re-pricing.
5. **Adverse-selection penalty:** every DL fill is booked at L − 1 tick. P&L then follows the realised path.
6. Reported:
   - fill rate;
   - P&L of filled days;
   - NATURAL P&L of the **missed** days vs the filled days (adverse-selection diagnostic).

**P&L per day:**

- **XSP / SPXW:** 100·n·(c_fill − [max(K_s − S_T, 0) − max(K_l − S_T, 0)]) − fees. S_T = settlement (SPX close; XSP = SPX/10).
- **SPY:** 100·n·(c_fill − d_15:55) − entry fees − exit fees.
  - The exit debit at natural is d_15:55 = ask_s,15:55 − bid_l,15:55, capped to [0, W].
  - If quotes are missing, d = spread intrinsic at the 15:59 parity spot (conservative).

## 5. Candidate families (all A-LAG; all on the same structure and execution unless stated)

The ranker is the existing SPXW LambdaRank pipeline. Models:

| Model | Train | Test |
|---|---|---|
| WF1 | 2018–20 | 2021 |
| WF2 | 2018–21 | 2022 |
| WF3 | 2018–22 | 2023 |
| WF4 | 2018–23 | 2024 |
| OOT | 2018–24 | 2025 |
| EXT_B | 2018–25 | 2026 |

- **2026 Test B (EXT_B, annual protocol retrain) is the primary 2026 model**, because it is how the product would be operated. Test A (frozen OOT model) is reported.
- Per-candidate scores s_d(k) are saved for every test day.

| ID | Rule | Label |
|---|---|---|
| **B0** | always FLAT | baseline |
| **R0 = B1** | always 5Δ bull put spread | **benchmark; the default product** |
| **B2-EDGE** | R0, traded only if F̂(ℰ_t) ≥ 0.50, with ℰ_t = (ATMF IV_0DTE,10:00 − σ_intra5d·√252) / (σ_intra5d·√252). F̂ is the ECDF over 2018..Y−1 | simple vol gate (v1 X-*-EDGE rule) |
| B2-TS | R0, traded only if VIX9D_close(t−1) ≤ VIX_close(t−1) | simple vol gate, V2-new |
| **R1** | ranker M-HEAD pick (G-UNION confidence gate, as in v1); short Δ = the picked bucket's target; SKIP → FLAT | original ranker, retail execution |
| **R2-A** | R0, traded only if s(P05) > s(SKIP) | **ranker as TRADE/FLAT gate** (key direction) |
| R2-B | R0, traded only if the M-HEAD pick ≠ SKIP | ranker + confidence gate as gate |
| **R3** | argmax of s over {P05, P10, P15, SKIP}; SKIP → FLAT; no buckets ≥ 20Δ | `POST-WF2 HYPOTHESIS` |
| **R4-h**, h ∈ {1.0, 1.5, 2.0} | R0, traded only if Ê ≥ h·Ĉ (defined below) | fixed structure + edge gate |

**R4 definitions:**

- Ĉ = (c_mid,10:00 − c_nat,10:00)·100 + entry fees.
- Ê = (c_mid,10:00 − E_FHS[payoff])·100.
- E_FHS is a filtered historical simulation over the trailing 1,000 sessions before t (minimum 500) of SPX:
  - r_i = ln(S_close,i / S_10:00,i), with S_10:00 = close of the 09:59 bar;
  - z_i = r_i / (σ_intra5d,i·√(m_i/390)), with m_i = minutes from 10:00 to the close;
  - S_T = S_10:00,t·exp(z_i·σ_intra5d,t·√(m_t/390));
  - the payoff is the spread payoff at S_T.
- LambdaRank scores are ordinal and carry no dollar meaning. A ranker-calibrated dollar edge would need a model the paper does not define, so **R4 uses the non-ML FHS edge**. No dollar-edge model is invented.

**Bucket → delta targets:** P05 = 0.05, …, P45 = 0.45. R1 can therefore trade high delta. CAP-r still bounds its max loss. It is reported with a per-bucket decomposition so that high delta cannot disguise tail risk.

## 6. Primary configuration

**XSP · CAP2 (r = 2%, B = $500) · S0 (1 lot) · NATURAL at 10:03 · NAV0 $25,000 · A-LAG · min credit $0.05 · hold to settlement.**

(This is the v1 primary X-CAP2/NAT/10:03/1-lot, kept and refined with the delta tolerance and the minimum credit.)

## 7. Comparisons vs always-5Δ (R0)

For every X ≠ R0 the comparison uses the same days E, product, execution level, fees, NAV0, risk budget and construction rule. FLAT = $0.

- Paired daily difference d_t = P&L_X,t − P&L_R0,t.
- Stationary bootstrap: mean block 10, 10,000 draws, seed 7 → P(mean d > 0).
- Moving-block bootstrap: block 20, 10,000 draws, seed 11 → P(mean d > 0).
- Diebold–Mariano with Newey–West HAC, lag L = ⌊4·(T/100)^{2/9}⌋, one-sided (H1: mean d > 0).
- Per calendar year: sign of mean d (2023, 2024, 2025, 2026 YTD).

**Incremental-alpha rule.** X has incremental alpha over R0 only if, on the confirmatory period at the primary configuration, all three hold:

1. stationary-bootstrap P ≥ 0.95;
2. DM one-sided p < 0.05;
3. mean d > 0 in ≥ 3 of the 4 calendar years.

**Otherwise X is rejected in favour of R0** (or B2 if B2 qualifies), and **no ML selector is used.**

ML demotion ladder, reported in this order:

1. full selector (R1);
2. conservative selector (R3);
3. TRADE/FLAT gate (R2-A, R2-B);
4. fixed 5Δ (R0).

## 8. Selection procedure (not highest Sharpe)

1. **Hard retail constraints.** Any violation eliminates the candidate:
   - integer contracts;
   - defined risk;
   - max loss at fill ≤ B on every trade;
   - no naked or fractional positions;
   - ≤ 1 trade/day.
2. Start from **R0**. Among {B2-EDGE, B2-TS, R1, R2-A, R2-B, R3, R4-1.0, R4-1.5, R4-2.0}, keep only those with incremental alpha over R0 (§7).
3. If none qualifies, the product is **R0**. If several qualify, rank by the hierarchy:
   1. NATURAL net expectancy;
   2. paired alpha vs R0 (stationary-bootstrap P);
   3. MaxDD;
   4. tail concentration (largest-5 losses / total P&L);
   5. execution robustness (number of K1–K8 survived);
   6. simplicity (B2 < R4 < R2 < R3 < R1).

   Ties go to the simpler candidate.

## 9. PASS / WEAK PASS / FAIL (evaluated on the chosen product, primary configuration, confirmatory period)

| # | Criterion |
|---|---|
| P1 | $25k executable: a valid integer defined-risk order exists on ≥ 80% of the days the rule wants to trade |
| P2 | NATURAL net mean daily P&L > 0 **and** stationary-bootstrap P(mean > 0) ≥ 0.95 |
| P3 | net P&L > 0 in ≥ 3 of the 4 calendar years 2023, 2024, 2025, 2026 YTD |
| P4 | no single-trade dependence: P&L > 0 after removing the best 5 trades (K12) **and** after removing the best month (K9) |
| P5 | MaxDD ≤ 15% of NAV0 ($3,750 at $25k) |
| P6 | **critical kill tests** survive (total net P&L > 0, or as stated): K1, K2, K4, K5, K7, K9, K10, K12, K25. **And** ≥ 2/3 of the applicable non-critical kill tests survive |
| P7 | A-LAG only (by construction) |
| P8 | forward shadow: ≥ 60 sessions, median \|simulated − shadow natural credit\| ≤ 1 tick. **Cannot be met inside this study.** A historical pass is therefore stated as "PASS (historical) — live use gated on P8" |

**Verdicts:**

- **PASS:** the chosen product is an ML family member (R1/R2/R3) that has incremental alpha (§7) **and** meets P1–P7.
- **WEAK PASS:** P1–P7 are met but the chosen product is non-ML (R0, B2, R4). Positive expectancy exists, but ML has no increment, so deploy the simple strategy. A product with P2's bootstrap P in [0.90, 0.95) and all else met is also WEAK PASS.
- **FAIL / `NO RETAIL EDGE`:** anything else. The report names where it died: signal / ML selection / transaction costs / integer sizing / tail risk / data timing / execution / capital constraints.
- **SPY validation:** the same chosen rule on SPY (§1). If SPY's NATURAL mean P&L ≤ 0, the verdict carries `NOT CONFIRMED ON SPY` and is capped at WEAK PASS.
- A manual execution guide (`MANUAL_EXECUTION_GUIDE.md`, `DAILY_CHECKLIST.md`) is written **only** on PASS or WEAK PASS.

## 10. Kill tests K1–K25 (on the chosen product and always on R0)

Survival = total net P&L > 0 over the confirmatory period unless stated.

| K | Test | K | Test |
|---|---|---|---|
| K1* | fees × 2 | K14 | delta targets ± 0.025 (R0: 2.5Δ and 7.5Δ; R1/R3: each bucket shifted) |
| K2* | slippage × 1.5 (credit = mid − 1.5·(mid − nat)) | K15 | ML retrain with correlation-cluster threshold 0.80 and 0.90 |
| K3 | slippage × 2 (= STRESS) | K16 | doubled transaction cost (slippage × 2 and fees × 2) |
| K4* | entry 10:01 (NATURAL) | K17 | NAV0 $10k (CAP2 → B = $200) |
| K5* | entry 10:05 (NATURAL) | K18 | NAV0 $50k (CAP2 → B = $1,000; and S1 on W5) |
| K6 | one strike worse: K_s moved one listed strike toward the money, K_l moved by the same amount | K19 | ML retrain with rolling 3-year training window |
| K7* | credit − $0.01 | K20 | ML retrain with Optuna seed + 1 |
| K8 | credit − $0.02 | K21 | ML retrain without the `macro` feature group |
| K9* | remove best calendar month | K22 | ML retrain with top-20 features only (§11) |
| K10* | remove best calendar year | K23 | fixed 5Δ instead of the ranker (ML candidates: survive if ML − R0 > 0) |
| K11 | remove worst calendar year (reported) | K24 | model as gate only (R1/R3: survive if they beat R2-A) |
| K12* | remove best 5 trades | K25* | moving-block bootstrap (block 20): P(mean > 0) ≥ 0.90 |
| K13 | remove worst 5 trades (reported; measures tail dependence) | | |

`*` = critical (§9 P6).

- K15 and K19–K22 apply only to ML families. They are run for all six windows and evaluated for R1, R2-A, R2-B and R3. For a non-ML chosen product they are marked N/A.

**Also reported per candidate:**

- per-trade, daily, weekly and monthly loss; worst trade, day, week and month;
- MaxDD ($, %) and the single-trade contribution to MaxDD (largest single loss inside the MaxDD episode / MaxDD);
- CVaR95 and CVaR99;
- largest loss / annual P&L, largest 3 losses / annual P&L, largest 5 losses / total P&L;
- win rate; trades and trades/month; fill rate;
- PSR and DSR (n_trials from `results/trials.jsonl`).

For SPY: the number of days the 15:59 spot fell between K_l and K_s (partial-assignment exposure had the spread been held).

## 11. Feature ablation (ML families)

- Within each window, rank the full A-LAG model's features by LightGBM gain importance (ties broken by `features.json` order; training data only).
- Retrain with the **top 5 / top 10 / top 20** features (skipping S1–S5; same Optuna protocol and seed).
- Evaluate R1, R2-A and R3 for each version and compare:
  - alpha vs R0;
  - year-by-year stability;
  - production data cost (sources needed, from `RETAIL_DATA_BOM.md`);
  - complexity (number of features and data feeds).
- Ablation results are secondary trials. They can only **demote** ML (a cheaper model with equal alpha is preferred); they cannot promote a candidate that failed §7.

## 12. Regimes (diagnostic only)

- Buckets use the decision-time-known **prior-close VIX**: < 15, 15–25, > 25. Same-day close VIX is used for post-trade diagnosis only.
- P&L and paired alpha are reported per regime.
- Any regime filter (e.g. "avoid VIX 15–25") is **POST-HOC** and not eligible for PASS.

## 13. Forward shadow (after the study)

- Daily at 10:00 the frozen product rule writes signal, strikes, 10:03 quotes, decision, hypothetical fill and outcome to the hash-chained log (`vrp_ltr/shadow.py`).
- Quotes come from the live feed or the Cboe delayed snapshot at ≥ 10:18.
- P8 is evaluated after ≥ 60 sessions.

## 14. Rules against retroactive fixing

- After the confirmatory outcomes are computed, no rule, threshold, family, window or parameter in this file changes.
- **Implementation bugs** may be fixed. Each fix is logged as an amendment below, with before/after numbers for every affected candidate, and the verdict uses the fixed code.
- Any new idea arising from 2023+ results is labelled `POST-CONFIRMATORY` and goes only to the forward shadow.

## 15. Automation target (only if PASS / WEAK PASS)

`RETAIL_PRODUCT_SPEC.md` specifies:

- 09:59 load data;
- 10:00 features → gate → FLAT (log reason, stop) or construct spread → verify max loss, min credit and liquidity;
- 10:03 submit;
- cancel at cutoff if unfilled (log NO FILL);
- no override;
- hash-chained log of signal / quote / decision / order / fill.

**This study builds no broker connection and places no orders** (original constraint). Only the specification and a dry-run signal generator are delivered.

## Amendments

**A1 (2026-10-01 ~04:40 ET; made before any 2023+ strategy outcome was computed; ledger #26).**

*Trigger.* A data audit of quote quality only (`scripts/quote_quality.py` → `docs/quote_quality_1000.csv`; widths and two-sided counts, no P&L) found that the **XSP NBBO at exactly 10:00:00 is frequently degraded**: $1–2-wide auto-quotes with size 1. Two examples are 2024-09-04 and 2025-03-03, both days with 10:00 ET macro releases. Quotes are normal again by 10:01–10:03. SPXW and SPY show no 10:00 effect. Under the frozen text, the XSP short strike and the CAP width would be chosen from a broken snapshot, which is a data-timing artefact and not a property of the product.

*Change.*

- (a) **Short strike** is resolved on the **SPXW 10:00 chain**: |Δ| closest to target, ties → lower strike, tolerance 0.025 applied to the SPXW delta. It is then mapped to the product:
  - XSP: K_s = listed XSP strike nearest K_SPXW / 10 (tie → lower);
  - SPY: K_s = listed SPY strike nearest K_SPXW · (S_SPY,10 / S_SPX,10) (tie → lower);
  - SPXW benchmark: K_SPXW.
- (b) **Everything quote-dependent** uses the product's quotes at the **order-submission minute**: 10:03 primary, 10:01/10:05 in K4/K5, t0 for DL. This covers the CAP long strike, the minimum credit, the max-loss check, and R4's Ĉ and Ê (c_mid, c_nat). All of it is known when the order is sent.
- (c) The frozen original (product's own 10:00 snapshot for strike, delta and CAP width) is kept as a reported variant **R0-SNAP1000**. It has no role in selection.

Nothing else changes.
