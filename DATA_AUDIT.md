# DATA_AUDIT — 数据审计

> 结论：**期权报价的 DATA GAP 已经由你的 Databento 账户（按量计费）解决。不需要再买任何东西。**
> 论文用的是 Cboe 1 分钟报价；我们用 Databento `OPRA.PILLAR` 的 `cbbo-1m`（全市场合并 NBBO，每分钟采样）。
> 它覆盖 2013-04 至今，包括 SPXW、XSP、SPY、QQQ 的全部合约。

## 1. 需要什么数据（最低要求）

| 用途 | 最低要求 | 我们的来源 | 状态 |
|---|---|---|---|
| 候选构建、IV、delta（10:00） | 最短到期所有 put 的 10:00 bid/ask | Databento cbbo-1m | ✅ |
| 路径标签（Sortino-on-bars，ask 标记） | 所选合约 10:01–15:59 每分钟 ask | Databento cbbo-1m | ✅ |
| 执行压力（bid、bid−1 tick、10:01/10:03/10:05） | 同合约在这些分钟的 bid/ask | Databento cbbo-1m | ✅ |
| 价差结构（XSP/SPY 两腿） | 两腿同一分钟的真实 bid/ask | Databento cbbo-1m | ✅ |
| SPY 15:45/15:55 退出 | 两腿在退出分钟的 bid/ask | Databento cbbo-1m | ✅ |
| 波动率曲面特征（09:35、10:00、收盘，DTE 1–90） | 多个到期、OTM 行权价的快照 | Databento cbbo-1m | ✅ |
| SPX 1 分钟指数（morning 特征、入场 S） | 09:30–16:00 分钟 | HF `thillsss/SPX-MES-VIX-data` | ✅（已验证，见 §3） |
| SPX 结算价 | 官方收盘 | FRED `SP500` | ✅ |
| VIX / VIX9D / VIX3M / VIX6M / VVIX / VIX1D | 日收盘 | Cboe 免费 CSV | ✅（VIX1D 仅自 2022-05-13 起） |
| VIX 期货 M1–M3 | 日结算 | Cboe CFE 免费文件 | ✅ 2015-06 至 2026-09，2,837 天 |
| EFFR、初请失业金（NSA） | 日/周 | FRED | ✅ |
| FOMC 日期 | 声明日 | federalreserve.gov | ✅ `data/reference/fomc_dates.csv` |
| PCE 发布日 | 发布日 | BEA 新闻存档 | ✅ 138 次（2015–2026） |
| CPI / NFP 发布日 | 发布日 | BLS 拒绝自动访问（403），Wayback 被出口策略拦截 | ⚠️ 需要免费 FRED API key，否则这 4 个特征不构建（已预先声明为偏差） |
| SPX/VIX 每日 put/call ratio | 日 | Cboe 市场统计 | ⚠️ 未获取。按预注册 §1.12，这 8 个 PCR 特征不构建 |

## 2. 数据源逐一审计

| 来源 | 结论 | 依据 |
|---|---|---|
| **Databento OPRA.PILLAR**（你的 key） | **采用**。`cbbo-1m` 自 2013-04-01 起；数据质量表显示 2017–2026 只有 5 个交易日为 degraded，其余 "missing" 都是休市日（`data/reference/databento_opra_condition.csv`） | API `metadata.get_dataset_range` / `get_dataset_condition` |
| Polygon / Massive | 不够：期权 **quotes** 只有 Advanced 档（$199/月）才有，且 "Records date back to March 7, 2022"。其他档只有成交聚合（不是 bid/ask） | massive.com 文档与定价页 |
| ThetaData | 可行的备选：Options Standard（$80/月）有 2016-01-01 起的逐笔 NBBO；Value（$40/月）只从 2020 起 | thetadata.net 订阅页 |
| IBKR（你的连接器） | 只能取**当前在交易**合约的 OHLCV（成交价 K 线），没有 BID/ASK 类型，也没有过期合约历史。只适合前向影子记录 | 连接器工具定义 |
| TradingView Premium | 没有期权报价历史，无 API | — |
| HF / Kaggle / Zenodo / DoltHub 免费数据 | 没有多年的日内 0DTE 报价：只有 EOD 链或几 MB 的样本 | 已检索（RESEARCH_LEDGER #4） |
| Cboe 延迟报价 JSON（免费） | 只有当下快照（15 分钟延迟）。用于今天的真实价差测量和前向影子记录 | `data/raw/cboe_delayed/2026-09-30/` |

### 关于 Databento 订阅页（你问需要买哪个）

**都不需要。** 那些 $199/月的是 **实时(live)** 订阅。
本研究只用 **历史** 数据，你的账户已经按用量付费访问。
- `OPRA` live：只在做实时自动交易时才需要，而本项目明确不做。前向影子记录用免费的 Cboe 延迟报价即可。
- `CFE`：VIX 期货历史结算 Cboe 官网免费提供，已下载。
- `US Equities`：SPY 标的价格可以由期权的 put-call parity 反推，不需要单独购买。
- Corporate actions / Security master：与本研究无关。

唯一有用、而且免费的：**FRED API key**（https://fredaccount.stlouisfed.org/apikeys ，注册即得）。它能补上 CPI/NFP 发布日这 4 个日历特征。不补也不影响主体结论（论文中这些特征不在 27 个常驻特征里；常驻的是 `days_until_next_pce`，这个已经有了）。

## 3. 已完成的真实数据验证

### 3.1 SPX 1 分钟数据 vs 官方收盘（FRED SP500）

| 年 | 交易日 | 有 ≥380 根 bar 的天数 | 16:00 水平 vs FRED 收盘中位误差 | 最大误差 |
|---|---|---|---|---|
| 2017 | 251 | 249 | 0.33 bp | 6.3 bp |
| 2018 | 251 | 248 | 0.27 bp | 3.9 bp |
| 2019 | 252 | 249 | 0.28 bp | 12.8 bp |
| 2020 | 253 | 251 | 0.21 bp | 10.5 bp |
| 2021 | 252 | 251 | 0.16 bp | 1.1 bp |
| 2022 | 251 | 249 | 0.29 bp | 12.3 bp |
| 2023 | 250 | 248 | 0.16 bp | 2.6 bp |
| 2024 | 252 | 248 | 0.04 bp | 0.8 bp |
| 2025 | 250 | 247 | 0.03 bp | 0.4 bp |
| 2026（至 09-23） | 182 | 182 | 0.10 bp | 1.4 bp |

4,710 个交易日中有 4,699 天具备完整的 30 根开盘 bar（09:30–09:59）。

### 3.2 今天的真实报价快照（2026-09-30，约 15:32 ET，Cboe 延迟数据）

完整表格：`docs/snapshot_2026-09-30/`。
这里用次日到期合约（剩余约 7 个交易小时）作为「10:00 的 0DTE」的交易时间近似。**只有一个时间点**，只能说明成本结构，不能说明 edge。

- 我实现的 BS-from-mid delta 与 Cboe 发布的 delta 相差 ≤ 0.005（全部品种）。
- 最差执行（bid − 1 tick，含全部费用）相对 mid 成交的净权利金折扣：

| Δ | SPXW | XSP | SPY |
|---|---|---|---|
| 5 | 6.2% | 11.7% | 13.8% |
| 10 | 6.7% | 8.4% | 7.6% |
| 15 | 3.3% | 4.7% | 4.3% |
| 20 | 3.3% | 3.5% | 3.3% |
| 30 | 2.0% | 2.1% | 2.0% |

- XSP 裸卖 1 张的 Reg-T 保证金约 $10.5–11.7k，约为 $25k 账户的 45%。**裸卖对 $25k 不可行**（只保留作研究基准）。
- XSP 5 点价差 ≈ 最大亏损 $480（1.9% NAV），10 点 ≈ $940（3.8% NAV），与预注册的 2% / 4% 风险版本几乎重合。
  低 delta 时对冲腿会吃掉大比例权利金：10Δ 裸卖 mid $26，5 点价差 mid 只有 $19，natural 为 $17。

### 3.3 Databento 报价时间语义（已实测）

`cbbo-1m` 记录的 `ts_recv` 恰好落在整分钟边界上（例如 10:00:00）。
bid/ask 是该时刻生效的合并最优报价，`ts_event` 是该时刻之前的最后一次更新。
因此「10:00 的报价」「10:03 的报价」定义明确，无需插值。

### 3.4 试点（2019-06，训练期内）

结果见 `docs/validation_SPXW_2019-06-01_2019-06-30.csv`，包括：
put-call parity 反推的现货与 SPX 分钟数据的偏差、crossed/locked 报价比例、|Δ| 覆盖范围、到期结构。

## 4. 成本与预算

用户批准上限 **$300**，代码内硬性执行（`vrp_ltr/data/databento_dl.py`）。
每次请求都先用 `get_cost` 报价，再记入 `data/reference/databento_spend.csv`。
估算：SPXW 2017–2026 约 $150，XSP 约 $45，SPY 约 $35。

## 5. 安全

Databento key 只存放在仓库之外的临时文件里，从未写入任何被提交的文件（每次提交前都做 `git grep` 检查）。
**建议在研究下载完成后，到 Databento 后台轮换（rotate）这个 key**，因为它曾出现在聊天记录中。
