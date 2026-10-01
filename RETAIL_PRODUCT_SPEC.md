# RETAIL_PRODUCT_SPEC — $25k 0DTE product (Retail V2 §25)

## STATUS: **NOT APPROVED — FAIL / NO RETAIL EDGE.** Do not trade this with real money.

The frozen V2 procedure (`RETAIL_V2_PREREGISTRATION.md` + A1) selected **R0, the fixed 5Δ XSP bull put spread**: no candidate beat it (§7). R0 then failed:

- **P1 (executable on ≥ 80% of intended days):** 31.6%. On 62% of days the natural credit is below $0.05.
- **P2 (bootstrap P(mean > 0) ≥ 0.95):** 0.73.
- **P6 (critical kill tests):** fails K1 fees×2, K4 10:01, K5 10:05 and K25 block bootstrap.
- **SPY validation:** −$2,007.

No `MANUAL_EXECUTION_GUIDE.md` or `DAILY_CHECKLIST.md` is produced (they require PASS or WEAK PASS).

The specification below records **exactly what was tested**, so that a forward shadow log can be compared against it. It is not a recommendation.

## 1. The product the procedure selected (R0) — tested specification

| Field | Value |
|---|---|
| Instrument | XSP 0DTE puts (European, cash-settled, PM settlement = SPX close / 10) |
| Decision time | 10:00:00 ET, using data time-stamped ≤ 10:00 |
| Entry | one order at 10:03 ET, natural price (sell at bid / buy at ask) |
| Structure | bull put spread: SELL K_s put, BUY K_l put, same 0DTE expiry, 1 lot |
| Short strike | SPXW 10:00 put with \|Δ\| closest to 0.05 (BS on mid IV, r = EFFR, trading-time τ); tolerance ±0.025 Δ. Mapped to XSP: nearest listed strike to K_SPXW / 10 |
| Long strike | widest listed strike below K_s with natural credit > 0 and (K_s − K_l − credit)·100 + fees ≤ $500. At $25k this is a $5-wide spread |
| Max risk | $500 per day (2% of NAV0), checked at the actual fill; if breached → NO TRADE |
| Contracts | 1 (integer only) |
| Minimum credit | $0.05 per spread at the actual fill, else NO TRADE |
| Skip conditions | scheduled-FOMC day · no same-day expiry · 5Δ not resolvable within ±0.025 · no valid long strike · credit < $0.05 · max loss > $500 |
| Exit | none: held to cash settlement. No intervention after the fill |
| Max trades/day | 1 |
| Expected trades/month | 6.6 (32% of sessions), confirmatory 2023–26 |
| Required data | OPRA L1 (SPXW + XSP) via broker, SPX index level, EFFR, FOMC calendar — **≈ $1.50–$5/month** (`RETAIL_DATA_BOM.md`) |

**Confirmatory results (2023-01 → 2026-09, 903 sessions):**

| Metric | Value |
|---|---|
| Total P&L | **+$346 ≈ +$93/year (+0.37%/yr on $25k)** |
| Sharpe | 0.27 |
| Bootstrap P(mean > 0) | 0.73 |
| DSR | 0.006 |
| Worst trade (= worst day) | **−$494** (−2.0% NAV) |
| Worst month | −$409 |
| Worst drawdown | **$606 (2.4%)** |
| Largest 5 losses | −$1,200, i.e. **3.5×** the total profit |

**What the trader would do each day:**

1. At 10:00 read the SPXW 5Δ strike.
2. Check FOMC.
3. At 10:03 send one 1-lot $5-wide XSP put credit spread at natural.
4. Skip the day if the credit is below $0.05.
5. Do nothing until settlement.

## 2. Why it fails, and where (V2 §30)

| Layer | Finding (confirmatory, A-LAG) | Dead? |
|---|---|---|
| Signal (VRP at 5Δ) | 5Δ XSP spread: average credit $0.068, ≈ $5.50 per win vs ≈ $300 per loss (up to $494). Break-even loss frequency ≈ 1.8%; observed 1.4%, 95% upper bound 3.2%. The premium is too thin to prove an edge | **weak / unproven** |
| ML selection | R1 −$2,132, R3 −$493 vs R0 +$346; paired P(R1 > R0) = 0.004. R2-A ≡ R0: the ranker never ranks SKIP above 5Δ. R2-B −$210 vs R0 | **dead** |
| Transaction costs | MID +$541 → NAT +$346 → fees×2 −$27 → slippage×2 + fees×2 −$18. The edge is about one fee or one tick wide | **dead** |
| Execution timing | NAT 10:01 −$105, NAT 10:05 −$324, delayed limit 10:01 −$847 (fill rate 33%) | **dead** |
| Integer sizing / capital | at $25k only one $5-wide lot fits the 2% cap; at 1% (W = $2) 44 trades in 3.7 years; at 0.5% 1 trade | binding |
| Tail risk | one max loss = 89 average wins; single trade = 82% of MaxDD | binding |
| Data timing | XSP NBBO is degraded exactly at 10:00:00 on release days (A1); the original 10:00-snapshot rule R0-SNAP1000 loses −$571 | fixed by A1, still FAIL |
| SPY fallback | −$2,007, 0/4 years positive (15:55 exit costs, 14% small-loss rate) | **dead** |
| Parameter fragility | min credit $0.02 instead of $0.05 → −$1,923 | fragile |

## 3. Shadow-only hypotheses (POST-CONFIRMATORY; never a live product without a new pre-registration)

These two **non-ML** gates were pre-registered as candidates. They showed positive confirmatory P&L but **failed the pre-registered incremental-alpha test vs R0** (paired P = 0.64 and 0.48). Both have ≤ 1 loss in sample, so their high Sharpe ratios are not evidence (`RETAIL_TAIL_RISK.md` §2).

| ID | Rule (on top of the R0 spec) | 2023–26 trades | P&L | Note |
|---|---|---|---|---|
| B2-EDGE | trade only if F̂_{2018..Y−1}((ATMF IV_0DTE,10:00 − σ5·√252) / (σ5·√252)) ≥ 0.50 | 123 | +$638 (≈ $172/yr) | 1 loss (−$59); one full loss would erase 78% |
| R4-1.0 | trade only if FHS edge ≥ 1.0 × (mid − natural + fees) | 52 | +$368 (≈ $99/yr) | 0 losses; 95% upper loss rate 5.6% vs break-even 2.3% |

**Both gates lost money in the 2021–22 development years** (XSP B2-EDGE −$105, R4-1.0 −$243). Their 2023–26 profit is therefore not stable across periods.

Both gates also make money on SPY (R4-2.0 +$321) and SPXW (R4-1.0 +$741, 49 trades, no losses) in 2023–26. That is consistent with a real but tiny VRP-timing effect. Even if it is real, it is ≈ 0.4–0.7% per year on $25k at 1 lot. That is about the size of the data bill plus one bad fill.

## 4. Automation target (V2 §26)

**Not built.** The automation target applies only to a PASS / WEAK PASS candidate. This study builds no broker connection and places no orders (original constraint).

The hash-chained shadow logger (`vrp_ltr/shadow.py`) can record the R0, B2-EDGE and R4-1.0 signals daily for the P8 forward check.
