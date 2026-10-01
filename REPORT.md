# REPORT — Wysocki (2026) "Harvesting the VRP: a Learning-to-Rank approach" — replication, audit and $25k retailization

Branch `claude/funny-sagan-gliw0b`.

| Item | Where |
|---|---|
| Frozen rules | `PREREGISTRATION.md` (v1, commit b76635a); `RETAIL_V2_PREREGISTRATION.md` (V2, commit 6038190, amendment A1) |
| Decision log | `RESEARCH_LEDGER.md` (#1–#30) |
| Trial count | 1,619 recorded variants (`results/trials.jsonl`, used in DSR) |

All times are America/New_York. All fills use real Databento OPRA minute NBBO; no model prices are used as fills. Fees are IBKR commission + exchange + clearing.

---

## 结论摘要（中文）

**最终判定：FAIL / NO RETAIL EDGE。**

论文的核心结果无法独立复现：

- 2022 年在任何口径下都是负的。
- 2025 年 Sharpe 5.76 只有在"论文字面滞后 + Edge Allocation + θ 顶格"的组合下部分出现（3.60，仅 64 笔交易）；采用可用性正确的滞后（A-LAG）后降为 1.16。
- 排序模型（ranker）在 2021–2026 任何一段都**没有**跑赢固定 5Δ。

把它改造成 $25k 可执行产品（XSP 5Δ 价差，1 手，最大亏损 ≤ $500，10:03 natural 成交）后：

- 2023-01→2026-09 共 903 个交易日，总收益 **+$346（约 $93/年，0.37%/年）**。
- Sharpe 0.27，bootstrap P = 0.73。
- 只有 32% 的交易日能下出合格订单。
- 手续费 ×2、晚 1–2 分钟成交都会变负；SPY 版本 −$2,007。

所有 ML 变体（R1/R2/R3）都不优于固定 5Δ。2023–26 唯一为正的是两个非 ML 的"权利金是否够肥"闸门（B2-EDGE、R4），但它们：

- 在 2021–22 开发期都是亏的（−$105 / −$243）；
- 每年只赚约 $100–170；
- 样本里几乎没有亏损，一次满额亏损（−$494）就能抹掉大部分利润；
- 预注册的配对检验也没有通过。

**结论：不能让机器人独立下单。** 这个 edge 依赖 SPXW + $5M 连续仓位 + 论文字面的时间对齐 + 特定历史段；到了 $25k 整数手、真实买卖价和手续费下，基本不存在。

---

## 1. Paper audit (`PAPER_SPEC.md`, `PAPER_AUDIT.md`)

**What checks out:**

- **Arithmetic:** Sharpe = aRC/aSD is consistent; PSR and DSR recompute (0.859 vs 0.856).

**Red flags:**

- **Outlier:** the 2025 out-of-time (OOT) variance is dominated by one loss of ≈ 12.7σ.
- **Execution drag:** the reported drag implies mean P&L of about 8–15× the half-spread.
- **Sizing parameter:** θ* pins at the grid top in every window.
- **Look-ahead (red flag R4):** the per-strategy lag (P-LAG) can leak same-day settlement on 1-DTE days.

**Leak test (`docs/leak_test.json`), on the 423 affected days:**

| Lag | Spearman (lagged ROM vs same-day P&L) | p-value |
|---|---|---|
| P-LAG | **+0.302** | 2e-10 |
| A-LAG | −0.062 | 0.21 |

We do not claim the authors' code leaks. The literal text admits it, and **every retail result uses the availability-correct lag (A-LAG).**

## 2. Data audit (`DATA_AUDIT.md`)

**Sources:**

- **Options:** Databento OPRA `cbbo-1m`, SPXW 2017–2026 and XSP/SPY 2021–2026; total spend **$222.46** of the $300 cap.
- **SPX 1-min:** validated against FRED (median error ≤ 0.33 bp).

**Data gaps:**

- **XSP 2026-03-16:** zero vendor records.
- **SPX 1-min:** ends 2026-09-23.
- **BLS CPI/NFP dates:** blocked (4 features not built).
- **XSP NBBO at exactly 10:00:00:** degraded on macro-release days (→ amendment A1).
- **Licensing:** processed OPRA files were pushed to the public repo in commits c16d362/27a2c0a. They are now ignored; a history rewrite is pending the owner's decision.

## 3. Exact replication — SPXW, one naked contract (`results/<policy>/one_contract_G-UNION_ext{A,B}.csv`)

**P&L by period, mid fill (L1), USD:**

| Strategy | 2021 | 2022 | 2023 | 2024 | 2025 OOT | 2026 YTD (Test B) |
|---|---|---|---|---|---|---|
| B-FIX-05 (always 5Δ) | +14,381 | −19,197 | −660 | −625 | −165 | +13,982 |
| A-LAG M-HEAD (ranker) | +19,555 | −33,977 | −2,685 | −7,319 | −5,400 | +10,633 |
| P-LAG M-HEAD | +5,437 | −7,814 | −2,602 | +2,078 | −2,965 | 0 (gate abstains) |

**Walk-forward totals and Sharpe:**

| Strategy | WF 2021–24 total | 2025 Sharpe |
|---|---|---|
| B-FIX-05 | −6,101 | −0.01 |
| A-LAG M-HEAD | −24,426 | −0.29 |
| P-LAG M-HEAD | −2,901 | −0.27 |

**Paper sizing (Edge Allocation, $5M), geometric Sharpe:**

| Source | 2021 | 2022 | 2023 | 2024 | WF 2021–24 | 2025 |
|---|---|---|---|---|---|---|
| **Paper** | 6.52 | 2.51 | 1.79 | 0.41 | 3.10 | **5.76** |
| Ours, P-LAG | 3.36 | −0.77 | 1.05 | 0.81 | 0.12 | **3.60** (64 trades, DSR 0.59) |
| Ours, A-LAG | 2.24 | −1.26 | 0.51 | −0.38 | −0.26 | **1.16** (DSR 0.06) |

θ* = 0.80 (grid top) in every window.

## 4. Baselines and selection alpha

- **Ranker vs best fixed bucket** (paired stationary bootstrap, 2021–24):
  - A-LAG: **P = 0.16**, and the 2025 difference is negative → **FAIL**.
  - P-LAG: P = 0.56; 2025 negative → FAIL.
- **Best training bucket:** P05 in every window.
- **Random baseline:** random-bucket choice (B-RAND) loses −$18,750 over 2021–24.
- **Retail paired test** (XSP spread, 2023–26): R1 vs R0, P(R1 > R0) = **0.004**, i.e. significantly *worse*.

## 5–6. 2025 holdout and 2026 extension (Tests A and B)

- **2025:** the ranker is negative at one contract under both lags.
- **2026 YTD:** everything is positive (calm market). Always-5Δ +$13,982 vs A-LAG ranker +$10,633 (Test B) / +$15,375 (Test A).
- **On the XSP retail spread in 2026:**

  | Rule | 2026 P&L |
  |---|---|
  | R0 | +$197 |
  | R1 Test B / Test A | +$63 / +$279 |
  | R3 Test B / Test A | +$176 / +$266 |

  There is no consistent increment from ML.

## 7–9. XSP transfer, $25k risk-capped and SPY fallback (Retail V2, confirmatory 2023-01 → 2026-09)

Details are in `RETAIL_TAIL_RISK.md` and `RETAIL_PRODUCT_SPEC.md`. Primary configuration: XSP · CAP2 ($500 max loss) · 1 lot · NAT 10:03 · A-LAG.

| Rule | Trades | P&L | Sharpe | MaxDD | Worst | P(vs R0) | Note |
|---|---|---|---|---|---|---|---|
| B0 flat | 0 | 0 | — | 0 | 0 | — | |
| **R0 always 5Δ** | 285 | **+$346** | 0.27 | $606 | −$494 | — | the product the procedure selected |
| B2-EDGE (VRP-percentile gate) | 123 | +$638 | 3.84 | $59 | −$59 | 0.64 | 1 loss in sample |
| B2-TS (VIX9D ≤ VIX) | 203 | +$332 | 0.31 | $624 | −$494 | 0.43 | |
| R1 ranker | 367 | **−$2,132** | −0.85 | $2,495 | −$494 | 0.004 | |
| R2-A ranker gate (s5Δ > sSKIP) | 285 | +$346 | 0.27 | $606 | −$494 | — | identical to R0: never abstains |
| R2-B ranker + confidence gate | 246 | +$135 | 0.10 | $628 | −$494 | 0.00 | |
| R3 ranker ≤ 15Δ | 449 | −$493 | −0.23 | $1,149 | −$494 | 0.14 | POST-WF2 hypothesis |
| R4-1.0 / 1.5 / 2.0 (FHS edge) | 52 / 28 / 12 | +$368 / +$229 / +$125 | 3.6 / 2.7 / 1.8 | $0 | > 0 | 0.48 / 0.40 / 0.34 | zero losses in sample |
| R0-SNAP1000 (frozen original) | 281 | −$571 | −0.36 | $979 | −$494 | — | 10:00 snapshot artefact |
| **SPY R0** (15:55 exit) | 641 | **−$2,007** | −1.06 | $2,255 | −$497 | — | 0/4 years positive |
| SPXW R0 (5-pt, benchmark) | 785 | −$4,035 | −1.02 | $4,407 | −$498 | — | 0/4 years positive |

**Frozen selection:** no candidate passes the incremental-alpha test vs R0 (P ≥ 0.95 and DM p < 0.05 and ≥ 3/4 years), so the product is R0.

**R0 against the PASS criteria:**

| Criterion | Result |
|---|---|
| P1 executable | **0.32** (fail) |
| P2 bootstrap | **0.73** (fail) |
| P3 years positive | 3/4 (pass) |
| P4 | pass |
| P5 MaxDD | 2.4% (pass) |
| P6 critical kill tests | **fail** (K1, K4, K5, K25) |
| SPY | **negative** |

**→ FAIL / NO RETAIL EDGE.**

**Development years 2021–22** (complete data, same rules; no weight in the verdict) give the same verdict:

| Product | Rule | 2021–22 P&L |
|---|---|---|
| XSP | R0 | +$260 (107 trades) |
| XSP | **B2-EDGE** | **−$105** |
| XSP | **R4-1.0** | **−$243** |
| XSP | R1 | −$222 |
| XSP | R3 | −$306 |
| SPY | R0 | −$928 |
| SPXW | R0 | −$2,976 |

The two non-ML gates that looked best in 2023–26 **lost money in 2021–22**.

## 10. Kill tests

**v1's 16 kill tests mapped to V2, on R0 / XSP:**

| v1 test | V2 test | Result |
|---|---|---|
| (1) natural fill | primary | +$346 |
| (2) one tick worse | K7 | +$503 |
| (3) full fees | primary | included |
| (4–6) 10:01 / 10:03 / 10:05 | K4 / primary / K5 | −$105 / +$346 / −$324 |
| (7) 2020 | — | training period; not a test year |
| (8) 2022 | dev | XSP R0 2021–22 +$372 (66 trades) |
| (9) 2024 | — | −$171 |
| (10) 2025 | — | +$74 |
| (11) 2026 | — | +$197 |
| (12) bootstrap | — | stationary 0.73 / block 0.73 |
| (13) perturbation | K14 2.5Δ / 7.5Δ | −$1,094 / +$34 |
| (13) perturbation | min credit $0.02 | −$1,923 |
| (14) minus best 5 | K12 | +$279 |
| (15) minus best 10 | — | +$221 |
| (16) double costs | K16 | −$18 |

**V2 tests K1–K25 for every candidate:** `results/retail_v2/conf/verdict.json`.

- **R0:** critical tests fail (K1, K4, K5, K25); 62% of the non-critical tests survive.
- **R1 and R3:** fail essentially every test.
- **ML-only retrains** (K15, K19–K22 and the §11 ablation): run on the confirmatory windows (ledger #30); results in the table below and `results/retail_v2/conf/model_*`. **R1 and R3 fail all of them. R2-A/R2-B "survive" only because they mostly reproduce R0.** None of this enters the verdict, because the selected product is non-ML.

**ML robustness retrains** (K15, K19–K22) and the **feature ablation (§11)**:

- **Setup:** confirmatory windows only. G-UNION gate calibration uses WF3–WF4 as the prior test years, because WF1/WF2 variant models were not fitted (ledger #30–#31).
- **Metric:** XSP primary total P&L 2023-01 → 2026-09; R0 = +$346.

| Model | R1 | R2-A | R2-B | R3 |
|---|---|---|---|---|
| Full (main) | −$2,132 | +$346 (≡ R0) | +$135 | −$493 |
| K15 corr 0.80 / 0.90 | −$306 / −$1,966 | +$335 / +$346 | +$579 / +$641 | −$1,100 / −$1,871 |
| K19 rolling 3-year | −$1,850 | +$346 | +$385 | −$1,021 |
| K20 seed + 1 | −$1,815 | +$346 | +$437 | −$2,621 |
| K21 no macro | −$456 | +$346 | +$394 | −$1,065 |
| K22 / §11 top-20 | −$544 | +$346 | +$226 | −$345 |
| §11 top-10 | +$42 | +$346 | +$338 | −$1,002 |
| §11 top-5 | +$131 | +$346 | −$22 | −$705 |
| 2026 Test A (frozen OOT model) | −$1,916 | +$346 | +$150 | −$404 |

Reading the table:

- **R1 and R3** are below R0 in every variant.
- **R2-A** is identical to R0 in almost every variant: the ranker never puts SKIP above 5Δ.
- **R2-B** beats R0 in 5 of 9 model variants. The margin is +$39 to +$295 over 3.7 years, paired P ≤ 0.64, and it is negative in the main model. That is noise, not an edge.
- **Simpler models lose less.** The smaller the feature set, the closer the model gets to always-5Δ. Top-5 needs only the 0DTE chain, SPX and VIX, but is still below R0.
- **Model size:** the fitted models are tiny (best iteration 1–26 trees).

**PSR / DSR (XSP, primary, n_trials = 1,619):**

| Rule | PSR(0) | DSR |
|---|---|---|
| R0 | 0.67 | 0.006 |
| B2-EDGE | 1.00 | 0.94 |
| R4-1.0 | 1.00 | 1.00 |

The B2-EDGE and R4 values are unreliable: they rest on 0–1 losses in the sample (`RETAIL_TAIL_RISK.md` §2).

## 11. Final verdict

**FAIL / NO RETAIL EDGE.** No manual guide is produced.

## 12. The 10 questions from the original brief

1. **Can we independently reproduce the paper's core result?** **No.**
   - The ranker's selection alpha is absent in every test year.
   - 2022 is negative under both lags (the paper reports +2.51).
   - The walk-forward EA Sharpe is 0.12 (P-LAG) / −0.26 (A-LAG), against the paper's 3.10.
2. **How much of Sharpe 5.76 (2025) is reproducible?**
   - About 60% (**3.60**) under the paper-literal lag (P-LAG) + EA + θ at the grid top, on 64 trades (DSR 0.59).
   - **1.16** under A-LAG.
   - At one contract (no sizing) 2025 is **negative** (−0.27 / −0.29).
   - Whatever survives is a sizing effect on a handful of days, not selection.
3. **Does the ranker beat fixed delta?** **No.**
   - P(diff > 0) = 0.16 (A-LAG, 2021–24), and 2025 is negative.
   - In retail form R1 is significantly worse than R0 (P = 0.004).
   - Every bucket above 5Δ loses money in 2023–26 (45Δ: 3 trades, −$671).
4. **Does SKIP contribute?** Not under A-LAG.
   - With SKIP/gate vs forced trading: −$24,426 vs −$12,634 (2021–24) and −$5,400 vs −$2,942 (2025).
   - The ranker essentially never ranks SKIP above 5Δ (R2-A ≡ R0).
   - Under P-LAG the gate helps 2021–24 (−$2,901 vs −$18,903). That is consistent with leaked information.
5. **Does Edge Allocation matter, or is selection enough?** EA matters more than selection, but it does not create a robust edge.
   - It turns 2025 from negative (one contract) into Sharpe 3.6 (P-LAG) / 1.16 (A-LAG).
   - Over 2021–24 it is ~0.
   - θ* pins at the grid top, and the result is sensitive to the gate and lag.
6. **How large is the $25k integer-position loss?**
   - **Naked:** SPXW naked is impossible at $25k (Reg-T margin ≫ NAV). XSP naked needs ≈ $11k margin per contract, so EA becomes 0/1.
   - **Defined-risk** (S1, W = $5): integer vs fractional:

     | NAV | Integer | Fractional |
     |---|---|---|
     | $25k | +$346 | +$389 (−11%) |
     | $10k | **0 trades** | +$142 |
     | $50k | +$760 | +$779 |

   - The binding constraint is not rounding. It is that only one $5-wide 5Δ lot fits a 2% cap, and narrower widths (1%: W = $2, 0.5%: W = $1) rarely clear the $0.05 credit floor (44 and 1 trades in 3.7 years).
7. **Does XSP keep the SPXW edge?**
   - There is no robust SPXW edge to keep.
   - XSP R0 is marginally positive (+$346) only because the $0.05 credit floor filters to rich-premium days. The same rule on SPXW 5-pt spreads loses −$4,035.
   - XSP's 10:00:00 quotes are unreliable on macro-release days.
8. **Does a defined-risk spread keep the edge?** No.
   - The long wing plus costs absorb the 5Δ premium.
   - Average credit is $0.068 against $494 risk. Break-even loss frequency is 1.8%, observed 1.4% (95% upper bound 3.2%).
9. **Is SPY a usable fallback?** **No.** −$2,007, every year negative; the forced 15:55 exit costs dominate.
10. **Realistic out-of-sample expectations for a $25k account.** Confirmatory, the product the procedure selected (XSP R0, 1 lot, NAT 10:03):

    | Quantity | Value |
    |---|---|
    | Annual return | **≈ +$93/yr (+0.37%)**, before ≈ $18–60/yr of data |
    | Average trading-day P&L | **+$0.38** (per trade +$1.21) |
    | Sharpe | **0.27** (bootstrap P = 0.73) |
    | Max drawdown | **$606 (2.4%)** |
    | Worst day | **−$494 (−2.0%)** |
    | Trade frequency | **6.6/month** (32% of sessions) |

    The best gated variant (B2-EDGE): ≈ +$172/yr, 2.9 trades/month. Its one-loss sample cannot rule out a loss rate above break-even.

## V2 final question

> 如果我明天只有 $25,000，这个研究能不能变成一个我敢让机器人独立下一张 XSP/SPY spread 的系统？

**不能。** 死在以下几层（按影响排序）：

1. **ML 选择层**
   - ranker 在 2021–2026 从未稳定跑赢固定 5Δ。
   - R1 显著更差（P = 0.004）。
   - ranker 当闸门用时永远选择交易（R2-A ≡ R0），等于没有闸门。
2. **交易成本与执行**
   - 5Δ $5 宽价差平均只收 $0.068。
   - 手续费 ×2、晚 1–2 分钟（10:01/10:05）、限价单 trade-through 成交，任何一项都让结果变负。
3. **尾部风险**
   - 一次满额亏损（$494）≈ 89 次平均盈利。
   - 盈亏平衡需要亏损率 < 1.8%，而数据的 95% 上界是 3.2%，无法证明 edge 存在。
4. **整数手与资本约束**
   - $25k 在 2% 风险下只能放 1 手 $5 宽。
   - 降到 1% 或 0.5% 风险后几乎无法下单。
5. **SPY**：净负。
6. **数据时点**：XSP 10:00:00 报价在数据发布日失真（已用 A1 修正，但仍 FAIL）。

可以做的只有前向影子记录（不下单），见 `RETAIL_PRODUCT_SPEC.md` §3：每天用 hash-chain 日志记录 R0 / B2-EDGE / R4 的信号与 10:03 真实报价，至少 60 个交易日后再按新的预注册重新评估。
