# RESEARCH_LEDGER — append-only log of every decision, data access and spend

Times America/New_York. Each entry: what changed, why, and whether any out-of-sample
(2021–2026) option **outcome** had been seen at that moment.

| # | Time | Entry | OOS outcomes seen? |
|---|---|---|---|
| 1 | 2026-09-30 15:43 | Repo empty (`null` file only). Paper arXiv:2608.24786v1 downloaded (PDF + TeX, sha256 in PAPER_SPEC). | no |
| 2 | 15:45 | Read paper fully, including all tables and appendices. **Researcher prior knowledge disclosed:** the paper's reported results (all years, 2025 included). The analyst also has general knowledge of market history through mid-2026 (e.g. the April 2025 selloff). Both are why every rule below is frozen from the paper text rather than chosen. | paper's own numbers only |
| 3 | 15:48 | Captured the live Cboe delayed chains for _SPX/_XSP/SPY/QQQ (quotes ≈15:32 ET 2026-09-30). Used only for spread/fee/margin measurement. The date is outside every test window (Databento history ends 2026-09-30 09:30). | no |
| 4 | 15:52 | Searched free sources (HF, Kaggle, Zenodo, DoltHub): none has historical intraday SPXW/XSP/SPY quotes. Recorded as a DATA GAP at the time. | no |
| 5 | 15:55 | User offered Polygon/IBKR/TradingView. Checked: Polygon quotes need the Advanced tier and start 2022-03-07. The IBKR connector gives only OHLCV for live contracts. TradingView has no option history. | no |
| 6 | 16:05 | PAPER_SPEC.md written; [AMBIG] choices frozen there. | no |
| 7 | 16:15 | `scripts/audit_paper_numbers.py` → PAPER_AUDIT.md. Found: paper internally consistent; 2025 variance dominated by ~one day; possible settlement-timing leak (R4). | paper's own numbers only |
| 8 | 16:30 | FOMC reference built from federalreserve.gov (`data/reference/fomc_dates.csv`). | no |
| 9 | 16:40 | HF SPX 1-min validated vs FRED closes (2016–2026). Only close-price agreement and bar counts inspected; no returns or strategy statistics computed. | no |
| 10 | 16:45 | User supplied a Databento key (stored outside the repo, never committed). OPRA.PILLAR `cbbo-1m` covers 2013-04 →, so the DATA GAP is closed. Test spend: one definition file 2024-06-03 SPXW (≈$0.03). It contains contract definitions only; no quotes were retrieved. | no |
| 11 | 16:50 | Cost sized by `metadata.get_cost` (free). User approved a **$300 cap** for Databento. | no |
| 12 | 16:55 | PREREGISTRATION.md frozen (this commit). Primary $25k candidate named in advance: X-CAP2, NAT, 10:03, 1 lot. | no |
| 13 | 17:00 | Databento downloader built (budget-capped, retries). Bugs found and fixed during the pilot: calendar end-date bound; a many-to-many merge that blew memory (OOM kill); tz loss. Per-request `get_cost` replaced by a row-count cost estimate (+10% margin, calibrated against get_cost). | no |
| 14 | 17:05 | Pilot SPXW 2019-06 (training period) downloaded and validated: parity spot vs SPX 1-min median 0.72 bp (p95 2.18 bp); 0 crossed quotes; 0DTE M/W/F pattern correct; 5Δ available 20/20 days. `docs/validation_SPXW_2019-06-01_2019-06-30.csv`. Pipeline smoke-tested on 2019-06-03/04 (training data). | no |
| 15 | 17:05 | Clarifications fixed before any outcome data is used (not changes to PREREG): (a) surface DTE target picks the expiry with the nearest calendar DTE, ties → shorter (so on M/W/F the "1-DTE" point equals 0-DTE); (b) CPI/NFP release dates unavailable (BLS 403) → 4 calendar features not built unless a FRED key is supplied; SPX/VIX put-call ratios not built (8 features); (c) morning RV uses the paper's literal Σ formula. | no |
| 16 | 17:10 | Bulk download launched: SPXW 2017-01 → 2026-09; XSP and SPY 2021-01 → 2026-09. | no |
| 17 | 17:45 | **Data-licensing incident.** Commits c16d362 and 27a2c0a pushed 284 processed quote files derived from Databento OPRA data, and b76635a pushed a small Cboe delayed-quote table, to a **public** repository. Fix going forward: the files are untracked and git-ignored (they stay on local disk). Rewriting history to purge them was blocked by the permission system and is left to the user. | no |

## Spend log (Databento, USD)

| Date | Request | Cost | Cumulative |
|---|---|---|---|
| 2026-09-30 | definition SPXW.OPT 2024-06-03 | 0.03 | 0.03 |
| 2026-09-30 | pilot SPXW 2019-06 (incl. restarts) | 1.52 | 1.55 |
| running | see `data/reference/databento_spend.csv` (every request) | | |

## Trial counter
Maintained automatically by `vrp_ltr/registry.py` (every variant that produces a P&L series is counted, including failed/abandoned ones).
