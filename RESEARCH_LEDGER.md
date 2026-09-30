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

## Spend log (Databento, USD)

| Date | Request | Cost | Cumulative |
|---|---|---|---|
| 2026-09-30 | definition SPXW.OPT 2024-06-03 | 0.03 | 0.03 |

## Trial counter
Maintained automatically by `vrp_ltr/registry.py` (every variant that produces a P&L series is counted, including failed/abandoned ones).
