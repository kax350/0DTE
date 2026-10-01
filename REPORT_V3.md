# REPORT_V3 — can any structure make this a retail-usable $25k product? (Layer A, SEEN data)

- **Protocol:** `RETAIL_V3_LAYER_A_PROTOCOL.md`, frozen at ledger #32 before any V3 variant was computed.
- **Run:** 2021-01-04 → 2026-09-23. XSP: 1,227 sessions with a same-day expiry. SPXW twin: 1,267 sessions.
- **Grid:** 72 variants per product = 4 decision times × 3 short deltas × {put spread, call spread, iron condor} × {hold, stop-at-2×-credit}.
- **Common rules:** 1 lot, max loss ≤ $500 at fill, natural fills at T0 + 3 min, full IBKR + exchange + clearing fees, minimum credit $0.05.
- **Outputs:** `results/retail_v3/layerA/{summary_XSP.csv, summary_SPXW.csv, detail_*.json, selection.json}`.

## Verdict

**No variant is eligible → NO TRADABLE VERSION.**

Not one of the 72 XSP variants meets all four pre-specified conditions:

1. positive in both halves;
2. bootstrap P ≥ 0.95;
3. loss-rate upper bound below break-even;
4. SPXW twin positive.

The protocol therefore sends nothing to the 2013–16 holdout. That download was **not purchased**, saving budget.

## Key numbers

**XSP, total net P&L 2021–2026, 1 lot. Best eight of 72:**

| Variant (T0 \| Δ \| structure \| exit) | Trades | Total | Per year | Bootstrap P | Tail test | SPXW twin |
|---|---|---|---|---|---|---|
| 15:00 \| 15Δ \| put spread \| hold | 505 | +$667 | +$137 | 0.82 | fail (11.9% vs 11.1%) | **−$7,348** |
| 10:00 \| 5Δ \| put spread \| hold (≈ V2 R0) | 392 | +$605 | +$124 | 0.80 | fail | **−$7,010** |
| 15:00 \| 10Δ \| put spread \| hold | 286 | +$405 | +$83 | 0.82 | fail | −$6,265 |
| 10:00 \| 5Δ \| call spread \| hold | 486 | +$330 | +$68 | 0.69 | fail | −$10,813 |
| 14:00 \| 10Δ \| put spread \| hold | 566 | +$266 | +$55 | 0.63 | fail | −$7,738 |
| 15:00 \| 5Δ \| put spread \| hold | 38 | +$215 | +$44 | 1.00 (0 losses) | fail (7.6% vs 1.2%) | +$446 (556 trades, P = 0.69) |
| 14:00 \| 5Δ \| condor \| hold | 9 | +$105 | +$22 | — | fail | −$8,684 |
| 10:00 \| 5Δ \| condor \| hold | 153 | +$105 | +$21 | 0.58 | fail | −$15,377 |

**Multiple-testing checks (XSP grid):**

- White Reality Check p = **0.99**: the best variant is indistinguishable from zero after searching 72.
- PBO (CSCV, 12,870 splits) = 0.003. This is low only because the uniformly terrible stop variants make the ranking stable. It says nothing about whether the best variant is profitable.
- Cumulative trials are now 2,246.

**Patterns across the grid (XSP, summed over hold variants):**

| Factor | Finding |
|---|---|
| Structure | puts −$6.2k; **calls −$21.8k; condors −$22.7k** (no call-side premium; selling upside loses) |
| Short delta | 5Δ −$2.1k; **10Δ −$20.0k; 15Δ −$28.6k** (more premium = more loss) |
| Exit | **STOP2 is catastrophic everywhere**: −$28.7k to +$59. At ≈ $0.05–0.40 credits the bid–ask spread alone triggers the stop, which then pays the spread again to exit |
| Time of day | later is less bad, but no time is robustly positive |
| XSP vs SPXW | **every** profitable XSP variant except one is deeply negative on SPXW with the same strikes and structure |

The XSP profits come from the $0.05 minimum-credit floor, which on XSP selects only rich-premium days. On SPXW ($0.05 is one tick) the same rule trades almost every day and loses. That is a selection artefact of the credit floor, not a structural edge in the index-option VRP.

## Economics: why no tuning can fix it at $25k

**Under the retail limits (max loss $500/trade, 1 trade/day, integer lots):**

- **Best realised per-trade mean:** $1.3–1.5 for structures with hundreds of trades.
- **What T2 would need:** the handoff's economic bar (≥ $500/yr net after data costs) needs ≈ $5–7 per trade at 75–100 trades/yr. That is 4–5× more than any tested structure delivers in-sample, before allowing for selection bias.
- **A larger account does not help:** the edge per dollar of risk (≈ 0.3% per trade) is the binding quantity, not the account size.

## What remains (shadow-only, zero capital)

`RETAIL_V3_PREREGISTRATION.md` registers two **shadow-only** hypotheses for forward monitoring, and `scripts/shadow_v3.py` logs them daily, without ordering:

- **S0** = 10:03 XSP 5Δ put spread, hold (V2 R0);
- **S1** = 15:03 5Δ put spread, hold. This is the only variant positive on both XSP and SPXW.

Even if both are confirmed forward, their in-sample expectation (≈ $40–125/yr) is far below a meaningful retail return. The default and expected verdict stays **NO TRADABLE VERSION**.
