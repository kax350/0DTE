# RETAIL_V3_PREREGISTRATION — shadow-only forward hypotheses (frozen)

**Status.** Layer A found **no eligible structure** (`REPORT_V3.md`). This document registers the only allowed follow-up: **forward shadow logging with zero capital**.

- **Default verdict:** NO TRADABLE VERSION.
- **Holdout:** the Layer B holdout (SPXW 2013–16) is **not** used, because no candidate qualified.

## Hypotheses (frozen; XSP primary, SPXW logged alongside)

| ID | Rule (V3 engine `vrp_ltr/retail3.py` mechanics) | Layer A in-sample (SEEN) |
|---|---|---|
| **S0** | decision 10:00, order 10:03; short 5Δ put (SPXW-resolved, ±0.025); CAP $500 wing; natural fill; min credit $0.05; hold to cash settlement | XSP +$605 / 392 trades; SPXW −$7,010 |
| **S1** | the same at decision 15:00, order 15:03 | XSP +$215 / 38 trades; SPXW +$446 / 556 trades |

Common rules:

- 1 lot; no trade on FOMC days or when there is no same-day expiry;
- **no orders are ever placed**;
- the log records the hypothetical decision, the quotes, the fill and the settlement outcome.

## Forward data and mechanics

**Source:** Cboe free delayed chains (`cdn.cboe.com/api/global/delayed_quotes/options/{_SPX,_XSP}.json`), 15-minute delay.

**For each hypothesis:**

- **Strikes:** a snapshot fetched at T0 + 15 min (quotes as of T0) resolves the SPXW short strike, using our BS delta on mid IV with spot = the snapshot's SPX level.
- **Fill:** a snapshot fetched at T0 + 18 min (quotes as of T0 + 3) gives the natural fill and the CAP wing.

**Outcome:** the next day, the SPX close is used for settlement.

**Deviation from the backtest.** The backtest takes spot from the SPX 1-minute bar at T0; the shadow uses Cboe's delayed SPX level. This is recorded in every log row.

**Log:** hash-chained JSONL `shadow/v3_log.jsonl` (same chain mechanics as `vrp_ltr/shadow.py`).

## Evaluation (only after ≥ 60 sessions and ≥ 30 S0 trades; S1 trades rarely on XSP, so its SPXW twin is also reported)

| Gate | Requirement |
|---|---|
| T1 | hard retail constraints hold (by construction) |
| T2 | annualised net P&L ≥ **$500** at NATURAL after data costs |
| T3 | loss rate: Clopper–Pearson 95% upper bound < break-even loss rate |
| T4 | MaxDD ≤ 10% NAV; largest loss ≤ annual net |
| T6 | natural credit in the shadow vs the backtest engine on the same day: median difference ≤ 1 tick |

- All of T1–T6 → **PROVISIONAL**. A live decision would then need a new pre-registration.
- Anything else → **NO TRADABLE VERSION** (expected).
