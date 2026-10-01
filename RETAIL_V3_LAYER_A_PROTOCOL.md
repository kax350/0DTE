# RETAIL_V3_LAYER_A_PROTOCOL — structure exploration on SEEN data (frozen before running)

Written and committed **before** any V3 variant is computed. The commit hash goes into `RESEARCH_LEDGER.md`.

- **Context:** `HANDOFF_PROMPT_V3.md` §4–§5.
- **Data:** 2021-01-04 → 2026-09-23 (XSP and SPXW, Databento minute NBBO). Already **SEEN** at the retail level.
- **Purpose:** generate at most 3 candidates. **Nothing in Layer A can produce a PASS.**
- **Confirmation:** candidates are confirmed only on the **unseen SPXW 2013-04 → 2016-12 holdout** (Layer B) and the **forward shadow** (Layer C). Both are defined in `RETAIL_V3_PREREGISTRATION.md`, which is written after this run and before any holdout data is downloaded.

## Hypothesis (from V2, stated before running)

V2 failed on per-trade economics: a 5Δ $5-wide put spread at 10:03 collects ≈ $0.07 against ≈ $494 of risk. The edge is only about one tick wide.

V3 asks whether a **different entry time, short delta, structure or pre-specified exit** gives a materially better reward-to-risk under the same retail limits. The limits are:

- $25k NAV;
- 1 integer lot;
- max loss at fill ≤ $500;
- defined risk;
- natural fills;
- full fees;
- A-LAG irrelevant (no model).

No ML and no gates are used in Layer A.

## Fixed grid: 72 variants per product, products XSP (primary) and SPXW (holdout twin)

| Factor | Levels |
|---|---|
| Decision time T0 (order at T0 + 3 min) | 10:00, 12:00, 14:00, 15:00. Sessions closing at 13:00 trade only the 10:00/12:00 variants |
| Short \|Δ\| target | 0.05, 0.10, 0.15 (tolerance ±0.025) |
| Structure | **PS** bull put spread · **CS** bear call spread · **IC** iron condor (PS + CS at the same \|Δ\| target, same width on both sides) |
| Exit | **HOLD** to cash settlement · **STOP2**: close both legs at natural at the first minute after the fill where the position's mid value ≥ 3 × entry credit (a loss of 2 × credit at mid) |

**Common rules for every variant** (V2 mechanics, generalised):

- **Strikes:** short strikes are resolved on the **SPXW chain at T0**: |Δ| from Black–Scholes on mid IV, spot = SPX 1-min level at T0, r = EFFR, trading-time τ.
  - XSP strike = nearest listed XSP strike to K_SPXW / 10 at the order minute.
  - SPXW uses its own strike.
- **Width:** CAP2. The widest listed wing with natural credit > 0 at the order minute and max loss at fill ≤ $500 (2% of NAV0).
  - For IC: one common width; max loss = W·100 − total credit·100 + fees.
- **Fills:** NATURAL (sell at bid, buy at ask) at T0 + 3 min.
  - Minimum credit **$0.05 per sold spread**. For IC both sides must qualify, else NO TRADE.
- **Fees:**
  - entry: IBKR commission (tier by premium, $1 order minimum) + exchange fee + $0.05 clearing per contract per leg;
  - STOP2 exits pay the same on the legs traded;
  - long legs with zero bid are abandoned at no value;
  - cash settlement is free.
- **Calendar:**
  - no trade on scheduled-FOMC days or when the product has no same-day expiry;
  - minute data must exist (DATA GAP days are excluded and listed).
- **One position per day per variant.** P&L is in USD per day; FLAT = 0.

## Metrics reported for all 144 series

- **P&L:** trades, total and mean daily P&L, win rate, average win and loss, credit, worst trade, MaxDD.
- **Statistics:**
  - stationary bootstrap P(mean > 0) (mean block 10, 10,000 draws);
  - yearly P&L;
  - P&L in the halves **H1 = 2021-01 → 2023-12** and **H2 = 2024-01 → 2026-09**.
- **Tail test:** Clopper–Pearson 95% upper bound of the loss rate vs the break-even loss rate.
  - Break-even = avg win / (avg win + |avg loss|).
  - |avg loss| = the observed mean loss if there are ≥ 5 losses, else the mean theoretical max loss (conservative).
- **Multiple testing, XSP grid:**
  - **PBO** by CSCV: 16 contiguous blocks, all C(16, 8) splits, Sharpe of daily P&L; Bailey et al. 2017.
  - **White Reality Check** p-value for "best variant mean > 0": stationary bootstrap, 2,000 draws.
  - DSR with the cumulative trial count.

## Pre-specified candidate selection (XSP)

A variant is **eligible** only if all of the following hold:

1. total net P&L > 0 in **both** H1 and H2;
2. stationary bootstrap P(mean > 0) ≥ 0.95;
3. the Clopper–Pearson 95% upper loss rate is below the break-even loss rate;
4. its **SPXW twin** (same T0/Δ/structure/exit) has total P&L > 0. This is required so that the Layer B holdout can test it. A variant failing only this condition may go to forward shadow, but not to Layer B.

**Ranking.** Eligible variants are ranked by the 5th percentile of the stationary-bootstrap distribution of mean daily P&L (conservative lower bound). The **top 3** become V3 candidates.

**If no variant is eligible:** the V3 Layer A result is **"no structure survives on seen data"**. Only a forward-shadow hypothesis may be registered, and the honest default verdict remains NO TRADABLE VERSION.

Layer A's economic threshold (handoff T2: ≥ $500/yr net after data costs) is reported but not used for selection. It is applied in Layers B and C.
