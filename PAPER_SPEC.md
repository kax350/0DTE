# PAPER_SPEC — Wysocki (2026), arXiv:2608.24786v1

"Harvesting the Volatility Risk Premium: A Learning-to-Rank Approach"
Source read: LaTeX source `paper/tex_source/main.tex` (sha256 `896b5d66…2ece`) and every
table in `paper/tex_source/tables/`. PDF archived at `paper/arXiv-2608.24786v1.pdf`.

References use the paper's own section titles and LaTeX equation/table labels
(`eq:…`, `tab:…`, `alg:…`) because compiled equation numbers can shift.
Tags:

* **[SPEC]** — stated explicitly in the paper; implemented as written.
* **[AMBIG]** — the paper is silent or self-contradictory; the replication choice is
  stated and frozen in `PREREGISTRATION.md` *before* any option data is seen.
* **[INCONS]** — two passages of the paper disagree (listed again in `PAPER_AUDIT.md`).

---

## 1. Data sources (§4.1 "The S&P 500 Index and SPXW Options", App. B)

| Item | Paper | Tag |
|---|---|---|
| Option data | "minute-frequency … 1-minute OHLC bars and intraday quote data, obtained directly from CBOE" | [SPEC] |
| Underlying | SPX 1-minute mid (App. B "Conventions": `S_t` = intraday SPX mid quote; `P_t` = SPX close) | [SPEC] |
| VIX family | VIX, VIX1D, VIX9D, VIX3M, VIX6M, VVIX daily closes; VIX futures settlements M1–M3 | [SPEC] |
| Macro | EFFR (FRED, daily, decimal); NSA weekly initial jobless claims, ffilled | [SPEC] |
| Put/call ratios | daily SPX and VIX option PCR (source unstated) | [AMBIG] → CBOE daily market statistics |
| Event calendar | FOMC, CPI, NFP, PCE release dates | [SPEC] (source unstated → Fed/BLS/BEA official calendars) |
| Benchmarks | CBOE PUT, CBOE WPUT (total return), SPX buy-and-hold with dividends accrued daily; all converted to excess of EFFR/252 | [SPEC] (`tab:headline_metrics` note, App. A) |
| Sample | 2017 warm-up; 2018–2025 used; §5.1 | [SPEC] |

## 2. Universe (§3.1 "Universe of Options Subject to Ranking")

* **Decision time** 10:00 ET every trading day. [SPEC]
* **Candidates**: 8 short puts, one per target |Δ| ∈ {0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.45} (first display eq. of §3.1), plus `SKIP`. Put-only (calls tested in trial phase and dropped). [SPEC]
* **Expiration**: "the universe resolver scans the SPXW chain and selects the shortest available DTE". Same-session expiry on 62.0% of days 2018–2021, 87.2% in 2022, 100% from 2023. Remaining days resolve to a 1-session expiry; never longer. [SPEC]
  * Listing facts used by the paper: Tue added 2022-04-18, Thu added 2022-05-11 (paper cites Cboe). [SPEC]
  * [AMBIG] "shortest available DTE" at 10:00 of day t: an expiry at today's 16:00 counts as DTE 0. Pre-2022 Tue/Thu → next session's expiry (1 DTE). Holiday-shifted expiries are handled by listing, not rules.
* **Strikes**: every listed SPXW strike of that expiration is eligible. [SPEC]
* **Strike resolution** (`§3.1` second display eq.): `K* = argmin_K | |Δ_BS(K)| − Δ_tgt |`.
  * Δ_BS: Black–Scholes put delta; IV recovered from the **10:00 ET option mid**; r = EFFR; **no dividends** (App. B "Conventions"). [SPEC]
  * τ "measured in trading time on the NYSE calendar". [AMBIG] Exact convention not given. Frozen choice: τ = (minutes of regular session remaining until 16:00 ET on expiry date, summed over sessions) / (390 × 252) years. Overnight carries 0 trading time. Sensitivity: calendar-time τ (pre-registered as a diagnostic only).
  * [AMBIG] tie-break between two strikes equidistant in |Δ| → lower strike (further OTM). Duplicate strikes across candidates (e.g. 0.40 and 0.45 resolving to the same K on a thin chain) are allowed; the paper does not dedupe.
  * [AMBIG] quote filters (zero bid, crossed/locked markets) are not described. Frozen: exclude strikes whose 10:00 bid ≤ 0 or ask ≤ bid, and strikes whose IV fails to solve.
* **FOMC days** are excluded upstream from the candidate universe (§4.2 "Calendar and event flags" bullet). [SPEC] The 2:00 pm FOMC statement dates (scheduled meetings) are used; [AMBIG] unscheduled/emergency meetings (e.g. 2020-03-03, 2020-03-15) — frozen: exclude only scheduled-meeting statement days, as the paper says "FOMC days".
* **Settlement**: held to expiry, closed against official PM cash settlement. Gross P&L (§3.1 last display eq.): `P&L_gross = Q·100·[p_entry − max(K − S_settle, 0)]`. [SPEC]
  * [AMBIG] `S_settle` source. SPXW PM settlement = official SPX closing value. Frozen: official SPX daily close.

## 3. Ranking target (§3.2 "Ranking Target Construction")

For each (strategy s, day t):

1. Mark series (display eq. "mark"): `[p_entry, a_1, …, a_{N−1}, max(K − S_settle, 0)]`, where `a_i` = option **ask** at 1-minute bar i after 10:00, terminal mark = settlement intrinsic. [SPEC]
   * [AMBIG] `p_entry` in the label: entry premium "received". The headline execution is mid. Frozen: `p_entry` = 10:00 mid in the label (execution level L1). The label is **not** recomputed under L2/L3 execution. This matches the paper's execution-drag procedure, which re-prices without retraining (§6.4).
   * [AMBIG] Bar i's ask: last quoted ask at or before the bar's close timestamp. Missing bars are forward-filled within the day.
   * For a 1-DTE position the series spans the overnight gap; bars exist only in regular sessions. [AMBIG] Frozen: the overnight is one bar step (16:00 → next 09:31 ask).
2. Per-bar P&L: `Δp_i = mark_{i−1} − mark_i`; telescopes to `p_entry − intrinsic`. [SPEC]
3. Score (`eq:score_sortino_bars`): `s = GrossPnL / (TDD + ε)`, `TDD = sqrt(Σ min(Δp_i, 0)²)`, ε = 1e-8. [SPEC]
   * Note: if no bar is negative, TDD = 0 and s = GrossPnL / 1e-8 (enormous, e.g. 1e8). The paper keeps this. Grades are quantile-based, so the magnitude does not matter beyond rank. [SPEC as written]
4. SKIP row: s = 0 appended per day. Excluded from threshold estimation. [SPEC]
5. Thresholds (`eq:thresholds`): θ_p = quantile_p of non-SKIP scores over the **training** window (the ranker-training portion), p ∈ {10, 40, 60, 90}. Frozen at training time. [SPEC]
   * [AMBIG] which slice: "derived once per walk-forward training window". Frozen: the ranker-fit slice (training window minus gate slice). The early-stopping slice is part of the ranker's data and is included.
6. Grades (`eq:grade_assignment`): 4 if s > θ90; 3 if θ60 < s ≤ θ90; 2 if θ40 < s ≤ θ60; 1 if θ10 < s ≤ θ40; 0 if s ≤ θ10. [SPEC]
   * The paper asserts that SKIP (s = 0) always lands in grade 1, i.e. θ10 < 0 ≤ θ40 in every window. [SPEC — must be verified in the replication; logged if violated.]

## 4. Features (§4.2, App. B, `tab:feature_timing`)

~190 candidate features in 15 groups (10 CS + 5 PS) plus two derived families
(within-day ranks `_wd_rank`, three tail-risk features). Full list: App. B; the
implementation inventory is in `vrp_ltr/features.py` (`FEATURE_CATALOG`).

Timing rules (App. B preamble + `tab:feature_timing`) — **binding for the replication**:

| Block | Available | Lag |
|---|---|---|
| Calendar/event flags | known in advance | 0 |
| Morning 09:30–09:59 SPX window (10:00 mark := 09:59 close mid) | 10:00 t | 0 |
| Morning 09:35→10:00 surface changes | 10:00 t | 0 |
| VIX/VVIX closes used in morning block | close t | ≥1 day |
| SPX index, VIX spot family, VIX futures, macro, closing surface, RV–IV, higher moments, VIX curvature, trend | close t | ≥1 day |
| 10:00 IV-surface snapshot, entry Greeks, entry liquidity, intra-strategy context | 10:00 t | 0 |
| Per-strategy rolling statistics | "trade outcome, day t" | ≥1 day |
| Regime-conditional sensitivities | close t | ≥1 day |

* Per-strategy features are NaN on SKIP; `_wd_rank` features give SKIP rank 8.5. [SPEC]
* **[AMBIG — suspected leakage channel, see PAPER_AUDIT §4]**: per-strategy rolling statistics are lagged "≥1 trading day" relative to the *trade date*. On 1-DTE days (≈38% of 2018–2021 sessions) a trade opened on t−1 settles at the close of t. Its outcome is therefore **not** known at 10:00 on t. Frozen replication choice: **two** implementations, both pre-registered:
  * `P-LAG` (paper-literal): lag by entry date (reproduces the paper, including any leak).
  * `A-LAG` (availability-correct): a trade's outcome enters features only from the first 10:00 **after its settlement**.
  The gap between them is a primary audit statistic.
* [AMBIG] Regime interactions "close t, lag ≥1": frozen as the product of the entry-time PS quantity at t and the CS regime variable lagged 1 day.
* [AMBIG] `morning_vix_change` described as "09:35-to-10:00 change in VIX" in §4.2. App. B defines it as the lagged one-day change in VIX close [INCONS]. Frozen: App. B definition (lagged close, no intraday VIX needed).

## 5. Feature selection (§3.3, `alg:feature_selection`) — re-run per window

* S1: drop if null rate on training (real, non-SKIP) rows > 0.30.
* S2: drop if Var < 1e-6 or mode frequency > 0.99.
* S3: CS: |Spearman(f_t, ȳ_t)| across days, where ȳ_t is the day-mean label; PS: median over days of within-day Spearman(f, y). Drop |ρ| < 0.05. [AMBIG] "label" y = graded label (0–4) or continuous score? Frozen: continuous score s, non-SKIP rows (the ranking is identical in Spearman except for ties).
* S4: within-scope Spearman correlation clustering at |ρ| ≥ 0.85; keep max |ρ(S3)| representative; tie-break catalog-group priority → data quality → name. Group caps: position 8, vol_surface 4, vix 6, calendar 8, default 5 (drop lowest |ρ|). [AMBIG] clustering algorithm unspecified. Frozen: connected components of the graph |ρ_ij| ≥ 0.85.
* S5: 3 expanding-time folds inside the training window; run S1–S4 on each; keep features surviving in ≥ 2 of 3. [AMBIG] fold boundaries. Frozen: training dates split into thirds; fold k = first k/3 of dates. [AMBIG] Is S5 applied to the S4 output of the full window (intersection) or to the union? Frozen: final set = (S1–S4 on the full window) ∩ {f : fold-survival ≥ 2}.
* Expected output: ~50–60 features per window; 27 survive in all 5 windows (§7.2).

## 6. Model (§3.4, `tab:hyperparameters`)

* LightGBM, `objective=lambdarank`, boosting gbdt, `metric=ndcg`, `eval_at=[1,3]`, `lambdarank_truncation_level=5`, `label_gain=[0,1,3,7,15]` (`eq:label_gain`). One query group per trading day (9 rows). [SPEC]
* Optuna TPE, **50 trials per window**, objective NDCG@1 on inner-validation slice. Search space: num_leaves [16,256] log; learning_rate [0.01,0.10] log; min_data_in_leaf [20,200] log; feature_fraction [0.5,1.0]; bagging_fraction [0.5,1.0]; bagging_freq {0..10}; lambda_l1 [1e-3,10] log; lambda_l2 [1e-3,10] log; rounds ≤ 2000, early stopping patience 50. [SPEC] ("Subsampling fraction" / "Row subsampling fraction" read as feature_fraction / bagging_fraction [AMBIG].)
* Slices inside each training window (§3.4 last two paragraphs): the final **6 months** are the gate-calibration slice (withheld from feature selection and ranker training). Of the remainder, the last 6 months form the HP-search slice; each trial trains on data before it. The final model is refit on all ranker data with the **last 3 months** held back for early stopping (= more recent half of the search slice). [SPEC]
  * [AMBIG] Is the final refit trained on data *including* the first 3 months of the search slice? Text says "refit with those hyperparameters, with the last 3 months held back for early stopping", so yes.
  * [AMBIG] Optuna seed not given. Frozen: seed = 20260825 + window index; sensitivity is covered by the HP-trials perturbations.

## 7. Confidence gate (§3.5, §7.1, `tab:gate`)

* Confidence `Δŷ_t = ŷ(1) − ŷ(2)` (`eq:confidence_signal`). Abstain if Δŷ_t < τ*_w. [SPEC]
* τ*_w chosen on the 6-month gate slice by maximizing Sortino of the implied top-1 **NetPnL** series over an **8-point trade-rate grid** (§5.3 trial count: "an 8-point trade-rate grid scored on Sortino in each of the five windows"). [SPEC]
  * [AMBIG] grid values. Table values 1.0000, 0.5041, 0.3058, 0.4000 → frozen grid {0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 1.00}; τ = empirical quantile of Δŷ on the gate slice at (1 − rate).
  * [AMBIG] NetPnL of what size? Frozen: one-contract net P&L at L1 execution, SKIP picks = 0.
* **[INCONS]** OOT 2025 threshold: §3.5 says per-window on the last 6 months. `tab:gate` note says the OOT threshold is calibrated on "the union of the four walk-forward held-out slices", 965 days, which is the size of the WF *test* years. Frozen: both variants are pre-registered. `G-PAPER-OOT` = union of WF test-year predictions (as in `tab:gate`). `G-SPEC` = the last 6 months of 2024.

## 8. Walk-forward (§3.6, `tab:walkforward`, `alg:walk_forward`)

| Window | Train | Predict |
|---|---|---|
| WF1 | 2018–2020 | 2021 |
| WF2 | 2018–2021 | 2022 |
| WF3 | 2018–2022 | 2023 |
| WF4 | 2018–2023 | 2024 |
| OOT | 2018–2024 | 2025 (single shot, no retraining) |

Expanding window, annual retrain. Per window: selection → Optuna → refit → gate → sizing θ*. NAV chained across windows. Warm-up 2017 for rolling features only. [SPEC]

## 9. Execution, margin, fees (§3.6, §3.7.1)

* Entry fill: **mid** (headline, 50% spread coverage). Drag tests: 75% coverage (`0.75·bid + 0.25·ask`) and bid (§6.4, `tab:execution`). [SPEC]
* No exit (held to cash settlement), so no exit fee. [SPEC]
* Reg-T put margin (`eq:put_margin`): `M = 100·[P + max(0.15·S − max(0, S−K), 0.10·K)]`. [SPEC]
  * Note: the paper uses 0.10·K as the floor; the Cboe/IBKR customer rule for broad-based index puts uses 10% of the **strike** (aggregate put exercise price), so this is consistent.
* Margin cap `Q ≤ floor(NAV_{t−1}/M)`. [SPEC]
* Fees (`eq:fee_tier`): $0.25 if P < 0.05; $0.50 if 0.05 ≤ P < 0.10; $0.65 if P ≥ 0.10 per contract; $1.00 minimum per non-empty trade; **entry only**. [SPEC]
  * **Omission**: no exchange fee (Cboe SPX/SPXW proprietary-product customer fee), no ORF/OCC/FINRA fees. The replication adds them in L3 (see PREREGISTRATION §3).
* Initial NAV $5,000,000. [SPEC]

## 10. Sizing (§3.7.2, `tab:sizing_grids`)

Seven methods, each with one θ fitted per window by grid search to minimize
|σ_train(θ) − 0.16| (`eq:equal_vol_calibration`), σ_train from a full training-window
backtest on in-sample predictions. [SPEC]

| Method | Q_des | θ grid |
|---|---|---|
| FMU (`eq:fmu`) | ⌊f·NAV/M⌋ | f ∈ {0.02,…,0.60} step 0.02 |
| VT (`eq:vt`) | ⌊f·0.16/√252·NAV / (|δ|·S·σ_intra5d·100)⌋ | f ∈ {0.1,…,2.5} step 0.1 |
| SRS (`eq:srs`) | ⌊f·𝒮·NAV/M⌋, 𝒮 = min(C95, max(1, R/median_train R)), R = σ0DTE_ATM / (VIX9D/100) | {0.02,…,0.50} |
| **EA** (`eq:ea`, headline) | ⌊u·NAV/M⌋, u = u_max·F̂_train(ℰ), ℰ = (σ0DTE_ATM − σ_intra5d√252)/(σ_intra5d√252) | u_max ∈ {0.05,…,0.80} |
| GB (`eq:gb`) | ⌊b·NAV/L⌋, L = (|δ|kS + ½|Γ|(kS)²)·100, k = train p95 of daily max adverse move | {0.005,…,0.100} |
| HK / QK (`eq:ck`) | ⌊f_t·NAV/M⌋, f_t = min(f_CK, max(0, α·μ/σ²)) on rolling 252-day return-on-margin, α = 0.5 / 0.25 | {0.05,…,0.80} |

[AMBIG] σ_intra,5d ("5-day realized intraday volatility of SPX") — frozen: RMS of 1-minute
log returns over the prior 5 sessions, scaled to a daily σ (×√390). This is in daily units
because formula VT multiplies it directly with S; EA multiplies by √252 to annualize.
[AMBIG] σ0DTE_ATM: ATM-forward IV on the selected expiry at 10:00.
[AMBIG] HK/QK "abstention threshold" (§5.4 mentions one; not defined). Frozen: Q = 0 when f_t = 0.

## 11. Metrics (App. A)

* Daily return = ΔNAV/NAV_{t−1}; strategy returns are **already excess** (collateral earns r_f); benchmarks minus EFFR/252. [SPEC]
* aRC geometric; aSD sample std ×√252; aDD = √252·RMS(min(r,0)) over all N days. [SPEC]
* **Sharpe = aRC / aSD** (geometric numerator; App. A "Risk-adjusted return ratios"). The paper states the arithmetic analogue for EA-OOT is 5.489 vs 5.761. **Both conventions are reported in this project.**
* Sortino = aRC / aDD. MaxDD on the NAV curve.
* PSR (Bailey & López de Prado 2012) with daily arithmetic SR, non-excess kurtosis, N = number of days; SR* = benchmark's daily SR on the same slice. DSR with N_t = 75, V = 1/(N−1), Euler–Mascheroni form (App. A). [SPEC]
* Diebold–Mariano on daily P&L differentials, h = 1, Bonferroni over 3 benchmarks. [SPEC]
* VIX regimes on **entry-day close** (after the decision; reporting only): <15, 15–25, >25. RV terciles: 5-day intraday RV, equal-quantile within slice. [SPEC]

## 12. Baselines (§5.6, `tab:headline_metrics`)

Random; Always-P25d; Always-P45d; Momentum; Rolling-Sharpe (highest 30-day rolling
Sharpe candidate). They "disable the ranker, the gate, or both, but otherwise share the
same option universe and execution". [AMBIG] Their sizing is not stated. Their ~16% vol
suggests the same sizing layer calibrated to 0.16. Momentum is not defined. Frozen
definitions: `PREREGISTRATION.md` §2.

## 13. Robustness reported by the paper (§6)

Training window 2y; rolling 3y; vol anchor 12%/20%; HP trials 25/100; correlation
threshold 0.90/0.95; calibration Sharpe-max/Sortino-max; execution 75%/bid; 15-group
ablation; 2×2 gate × tail-risk ablation (`tab:mechanism_decomposition`).
DSR trial count N_t = 75 (§5.3).

## 14. Headline numbers to reproduce (targets, not assumptions)

| | WF 2021–24 | OOT 2025 |
|---|---|---|
| EA Sharpe (geom) | 3.1048 | 5.7612 |
| EA ann. return / vol / MaxDD | 10.91% / 3.51% / 2.28% | 10.48% / 1.82% / 1.43% |
| FMU Sharpe | 2.5119 | 5.0632 |
| Always-P25d Sharpe | −0.019 | 0.000 |
| Random Sharpe | 0.084 | 0.342 |
| Rolling-Sharpe | 0.557 | 0.613 |
| EA per-year | 2021 6.52 · 2022 2.51 · 2023 1.79 · 2024 0.41 | 2025 5.76 |
| Gate τ* / trade rate | 2021 0/1.00 · 2022 0.201/0.504 · 2023 0.161/0.306 · 2024 0.014/0.400 | 0/1.00 |
| EA trades / days | 451 / 964 | 220 / 237 |
| FMU trades / days | 479 / 964 | 237 / 237 |
