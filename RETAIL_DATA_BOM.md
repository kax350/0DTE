# RETAIL_DATA_BOM — production data bill of materials (Retail V2 §16)

Scope: what a $25k retail account needs **live**, every trading day, to run each pre-registered rule.

- Historical research data is already bought (Databento usage-based, ≈ $190 so far, cap $300). It is **not** re-downloaded.
- Prices are non-professional retail rates. Read 2026-10-01; re-check before subscribing.

## 1. Data items

| # | Item | Needed by | Latency needed | Source (primary) | Monthly cost | Fallback |
|---|---|---|---|---|---|---|
| D1 | SPXW 0DTE put chain, L1 NBBO, at 10:00 (A1 short-strike resolution) | all rules | real-time (≤ 1 s) | IBKR **OPRA Top of Book** | **$1.50**, waived at ≥ $20/month commissions | compute delta on the XSP chain at 10:02 (not the frozen rule; would need a new shadow period) |
| D2 | XSP (or SPY) 0DTE put NBBO at 10:03 (fill) | all rules | real-time | same OPRA subscription | (included) | — |
| D3 | SPX index level at 10:00 (XSP spot = SPX/10; BS delta) | all rules | real-time | IBKR **Cboe Streaming Market Indexes** | **$3.50** | SPX implied from SPXW put–call parity (free with D1) |
| D4 | EFFR (BS rate) | all rules (negligible sensitivity) | daily, prior day | FRED | $0 | constant 0 → delta error ≪ 0.001 |
| D5 | FOMC calendar (no trade on scheduled FOMC days) | all rules | yearly | federalreserve.gov | $0 | — |
| D6 | VIX and VIX9D prior close | B2-TS; regime report | prior close | Cboe EOD CSV (free) | $0 | IBKR index data (D3) |
| D7 | SPX 1-min bars, prior 5 sessions (σ_intra5d) | B2-EDGE, R4, S2 | prior day | IBKR historical bars (free with D3), or free HF/other minute data | $0 | daily-bar RV proxy (not the frozen rule) |
| D8 | SPX 1-min history ≥ 1,000 sessions, 10:00→close returns (FHS) | R4 | prior day | same as D7 (one-time backfill + daily append) | $0 | — |
| D9 | SPXW 0DTE ATMF IV at 10:00 | B2-EDGE | real-time | from D1 | (included) | — |
| D10 | SPXW **surface** snapshots at 09:35, 10:00 and prior close for expiries near 1/5/10/20/30/60/90 DTE (hundreds of contracts) | R1, R2, R3 (ML features) | real-time snapshot | IBKR OPRA + **more market-data lines** (default ≈ 100 simultaneous lines; Quote Booster ≈ $30/month per 100 lines), **or Databento live OPRA Standard $199/month** | **$30–$199** | drop surface features (ablation §11: top-5/10/20) |
| D11 | VIX3M, VIX6M, VVIX, VIX1D prior close; VX futures settlements | ML features | prior close | Cboe free CSVs | $0 | — |
| D12 | Jobless claims, PCE release dates, put/call ratios | ML features (macro / regime groups) | weekly / daily | FRED, BEA, Cboe (free) | $0 | drop the macro group (K21) |
| D13 | Own strategy history (rolling ROM, win rate, drawdown features) | ML features | prior settled day (A-LAG) | computed from D1/D2 logs + historical archive | $0 live | — |
| D14 | Annual retrain history (one more year of SPXW chains and surfaces) | ML only | yearly | Databento usage-based | ≈ $15–30/year (measured: SPXW ≈ $10–17/year chains + surfaces) | no retrain (Test A analogue) |
| D15 | Broker execution + fills | all rules | real-time | IBKR (commissions already in the backtest) | in fees | — |

## 2. Cost by product family

| Family | Items | Fixed $/month | Notes |
|---|---|---|---|
| R0 (fixed 5Δ), B2-TS | D1–D6, D15 | **$1.50–$5.00** ($0–3.50 if the OPRA waiver applies) | simplest; no model |
| B2-EDGE, R4 (FHS edge) | + D7–D9 | same as R0 | needs a small daily SPX-minute job |
| R1 / R2 / R3 (LambdaRank ML) | + D10–D14 | **≈ $35–$205** + $15–30/year | a surface snapshot of hundreds of contracts at 09:35/10:00; the main extra cost and failure point |

**Implication (confirmed by the 2023–26 confirmatory run).**

- **Earnings:** the product the frozen procedure selected (XSP R0, 1 lot) earned **≈ $93/year**. The best non-ML gate (B2-EDGE) earned ≈ $172/year.
- **Simple rules:** a $1.50–$5/month data bill ($18–60/year) consumes **20–65%** of that.
- **ML rules:** a $35–$205/month bill would consume the whole P&L many times over. The ML rules lost money anyway (R1 −$2,132, R3 −$493).

So even the cheapest data stack does not leave an economically meaningful edge at $25k.

## 3. Minimising production data

- The non-ML rules (R0, B2-TS, B2-EDGE, R4) need **one** real-time feed (OPRA L1 via the broker) plus free daily files.
- ML features that require the multi-expiry surface (D10) are the expensive part. The ablation (§11) reports whether top-5/10/20 models — which may avoid D10 — keep any alpha.

Sources:

- [IBKR market data pricing](https://www.interactivebrokers.com/en/pricing/research-news-marketdata.php): OPRA L1 $1.50 (waived at $20 commissions), Cboe Streaming Market Indexes $3.50, US Securities Snapshot bundle $10 (waived at $30).
- [Databento OPRA plans](https://databento.com/blog/upcoming-changes-to-pricing-plans-in-january-2025) and the [Databento OPRA catalog](https://databento.com/catalog/opra/OPRA.PILLAR): Standard $199/month live.
- [IBKR Cboe fee schedule](https://www.interactivebrokers.com/en/accounts/fees/CBOEoptfee.php) (exchange fees used in the backtest).
