# RETAIL_TAIL_RISK — confirmatory period 2023-01-03 → 2026-09-23 (Retail V2 §10, §23)

**Primary configuration:** XSP bull put spread · CAP2 (max loss ≤ $500) · 1 lot · NATURAL at 10:03 · NAV0 $25,000 · A-LAG · min credit $0.05.

- **Evaluation days:** 903 XSP sessions (FOMC days and data gaps excluded; `results/retail_v2/conf/excluded_days_XSP.json`).
- **Sources:** `results/retail_v2/conf/{summary.json, verdict.json, tables_*.csv}`.
- **Units:** USD per day. One trade per day at most, so the worst trade equals the worst day.

## 1. Loss structure (XSP, primary)

**Activity and return**

| Metric | R0 (always 5Δ) | B2-EDGE | R4-1.0 (FHS edge) | R1 (ranker) | R3 (≤15Δ ranker) |
|---|---|---|---|---|---|
| Trades | 285 | 123 | 52 | 367 | 449 |
| Trades / month | 6.6 | 2.9 | 1.2 | 8.5 | 10.4 |
| Total P&L | **+$346** | +$638 | +$368 | **−$2,132** | −$493 |
| Mean credit | $0.068 | $0.070 | $0.084 | $0.095 | $0.088 |
| Win rate | 98.6% | 99.2% | 100% | 94.6% | 95.5% |
| Average win | $5.50 | $5.71 | $7.08 | $7.37 | $7.33 |
| Average loss | −$300 | −$59 | — (no loss in sample) | −$234 | −$182 |

**Worst outcomes**

| Metric | R0 | B2-EDGE | R4-1.0 | R1 | R3 |
|---|---|---|---|---|---|
| Worst trade (= worst day) | −$494 | −$59 | +$3.46 | −$494 | −$494 |
| Worst week | −$468 | −$55 | $0 | −$622 | −$468 |
| Worst month | −$409 | −$55 | $0 | −$684 | −$623 |
| MaxDD | $606 (2.4%) | $59 (0.2%) | $0 | $2,495 (10.0%) | $1,149 (4.6%) |
| Single trade's share of MaxDD | 82% | 100% | — | 20% | 42% |

**Tail statistics**

| Metric | R0 | B2-EDGE | R4-1.0 | R1 | R3 |
|---|---|---|---|---|---|
| CVaR95 / CVaR99 (per trade) | −$83 / −$436 | −$7 / −$59 | n/a | −$260 / −$486 | −$165 / −$452 |
| Largest 5 losses | −$1,200 | −$59 | $0 | −$2,343 | −$2,184 |
| Largest 5 losses / total P&L | **3.5×** | 0.09× | 0 | n/a (total < 0) | n/a |
| PSR(0) / DSR | 0.67 / 0.006 | 1.00 / 0.94 | 1.00 / 1.00 | 0.02 / 0.00 | 0.32 / 0.00 |

**Largest loss / annual P&L, R0:**

- 2025: one −$494 trade against +$74 for the year (**6.7×**).
- 2026: −$269 against +$197 (1.4×).
- 2024: the year is negative (−$171).

## 2. The arithmetic of a 5Δ $5-wide spread

- One XSP CAP2 spread collects on average **$0.068 → ≈ $5.50 after fees** and risks **≈ $494**.
- Break-even needs a loss frequency below ≈ avg win / (avg win + avg loss) ≈ **1.8%** (R0 loss severity $300).

**Observed loss frequency vs break-even (Clopper–Pearson 95% upper bound; XSP, primary):**

| Rule | Trades | Losses | Observed | 95% upper | Break-even | Can the data rule out "loss rate > break-even"? |
|---|---|---|---|---|---|---|
| R0 | 285 | 4 | 1.4% | 3.2% | 1.8% | **No** |
| B2-EDGE | 123 | 1 | 0.8% | 3.8% | 1.9% | **No** |
| R4-1.0 | 52 | 0 | 0% | 5.6% | 2.3% | **No** |
| R1 | 367 | 20 | 5.4% | 7.8% | 2.4% | (already worse than break-even) |

- B2-EDGE and R4 show Sharpe 3.6–3.8 and bootstrap P = 1.00. That is **an artefact of 0–1 losses in the sample.** A bootstrap cannot resample a loss it has never seen.
- **One** full loss (≈ −$494) erases 78% of B2-EDGE's 3.7-year profit and 134% of R4-1.0's.
- This is the short-volatility hidden tail in its purest form.

## 3. Adverse moves (SPX 10:00 → close, confirmatory days)

**Index moves:**

| Quantity | Value |
|---|---|
| 10:00→close return, 5th / 1st percentile | −1.00% / −1.90% |
| Intraday low after 10:00, 5th / 1st percentile | −1.37% / −2.17% |
| Worst 10:00→close move | −4.94% |

**Moves relative to each rule's short strike:**

| Quantity | R0 (5Δ) | R1 | R3 |
|---|---|---|---|
| Median short-strike distance (OTM) | 1.43% | 1.18% | 1.16% |
| Days the close breached the short strike | 1.75% | 6.3% | 5.6% |
| p95 / p99 of move ÷ strike distance | 0.72 / 1.13 | 1.04 / 2.49 | 1.02 / 1.74 |
| Trades losing more than half the max loss | 1.05% | 2.7% | 1.6% |

## 4. P&L by selected delta (the 'high delta disguises tail risk' check)

| Bucket | R1 trades | R1 P&L | R1 loss rate | R3 trades | R3 P&L |
|---|---|---|---|---|---|
| 5Δ | 219 | −$19 | 1.8% | 247 | +$127 |
| 10Δ | 123 | −$564 | 7.3% | 166 | −$362 |
| 15Δ | 13 | −$439 | 23% | 36 | −$259 |
| 20Δ | 5 | −$47 | 20% | — | — |
| 25Δ | 3 | −$434 | 33% | — | — |
| 30Δ | 1 | +$42 | 0% | — | — |
| 45Δ | 3 | **−$671** | 67% | — | — |

- Every bucket above 5Δ loses money.
- R1's 3 picks at 45Δ cost about as much as 120 picks at 10Δ. This confirms the 2021–22 pattern on unseen data: rare high-delta jumps carry the tail.

## 5. Regimes (prior-close VIX; diagnostic only, POST-HOC for any rule)

| Rule | VIX < 15 (268 days) | 15–25 (595 days) | > 25 (40 days) |
|---|---|---|---|
| R0 | +$105 (31 trades) | +$77 (227) | +$163 (27) |
| B2-EDGE | +$15 | +$562 | +$61 |
| R1 | −$599 | −$1,572 | +$38 |
| R4-1.0 | +$47 | +$310 | +$11 |

## 6. Execution sensitivity (XSP, total P&L over the confirmatory period)

| Rule | MID | **NAT 10:03** | DL 10:01 | DL 10:03 | DL 10:05 | STRESS (slip×2) | K1 fees×2 | K4 NAT 10:01 | K5 NAT 10:05 |
|---|---|---|---|---|---|---|---|---|---|
| R0 | +$541 | **+$346** | −$847 | +$237 | −$279 | +$137 | −$27 | −$105 | −$324 |
| B2-EDGE | +$845 | **+$638** | −$23 | +$411 | +$402 | +$279 | +$476 | +$264 | +$337 |
| R4-1.0 | +$373 | **+$368** | −$209 | +$246 | +$281 | +$210 | +$298 | −$100 | +$450 |
| R1 | −$1,578 | **−$2,132** | −$2,457 | −$2,228 | −$2,875 | −$2,471 | −$2,608 | −$2,639 | −$2,673 |

**Delayed-limit fill rates** (trade-through rule; touch is not a fill):

- R0: 33–37%; R1: 48–50%.
- The ranker's DL fills are adverse. At 10:03, R1's NATURAL P&L averages −$10.2 on filled days and +$2.4 on missed days: the limit order fills on the days the market moves against the position.

**Minimum-credit fragility (R0):** P&L is +$346 at $0.05 and **−$1,923** at $0.02 (781 trades, MaxDD $2,284). R0's positive sign depends on the frozen $0.05 floor, which acts as an implicit "trade only when premium is rich" gate.

## 7. Capital use

Defined risk, 1 lot:

| Item | Value |
|---|---|
| Max loss committed per trade | ≈ $490–$500 (2.0% of NAV) |
| Margin (W × 100) | $500 |
| Utilisation per trade day (median / p95 / max) | 2.0% / 2.0% / 2.0% |
| Cash idle | ≥ 98% at all times |

No overnight exposure. XSP settles in cash; SPY is closed at 15:55.

## 8. Other products (same R0 rule, 1 lot, CAP2)

| Product | Trades | Total P&L | Sharpe | MaxDD | Years positive |
|---|---|---|---|---|---|
| SPY (15:55 exit) | 641 | **−$2,007** | −1.06 | $2,255 | 0/4 |
| SPXW 5-point (benchmark) | 785 | **−$4,035** | −1.02 | $4,407 | 0/4 |

- On SPY the exit spread at 15:55 and the 14% frequency of small losses kill the trade.
- On SPXW the $0.05 floor never binds, so it trades almost every day and loses.
