"""Frozen constants. Every value cites PAPER_SPEC.md / PREREGISTRATION.md.

Changing anything here after option data has been loaded must be logged in
RESEARCH_LEDGER.md with the reason and whether OOS results had been seen.
"""
from __future__ import annotations

from dataclasses import dataclass, field

TZ = "America/New_York"

# ---- Universe (PAPER_SPEC §2) --------------------------------------------------------
DELTA_TARGETS: tuple[float, ...] = (0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.45)
SKIP = "SKIP"
STRATEGIES: tuple[str, ...] = tuple(f"P{int(round(d * 100)):02d}" for d in DELTA_TARGETS) + (SKIP,)
ENTRY_TIME = "10:00"
MORNING_WINDOW = ("09:30", "09:59")  # 10:00 mark := 09:59 close mid (App. B)
MINUTES_PER_SESSION = 390
TRADING_DAYS_PER_YEAR = 252

# ---- Label (PAPER_SPEC §3) ------------------------------------------------------------
EPS = 1e-8
GRADE_PERCENTILES = (10, 40, 60, 90)
LABEL_GAIN = [0, 1, 3, 7, 15]

# ---- Selection pipeline (PAPER_SPEC §5) -----------------------------------------------
NULL_RATE_MAX = 0.30
VAR_MIN = 1e-6
MODE_FREQ_MAX = 0.99
RELEVANCE_MIN = 0.05
CORR_CLUSTER = 0.85
GROUP_CAPS = {"position": 8, "vol_surface": 4, "vix": 6, "calendar": 8}
GROUP_CAP_DEFAULT = 5
STABILITY_FOLDS = 3
STABILITY_MIN = 2

# ---- Model (PAPER_SPEC §6) -------------------------------------------------------------
OPTUNA_TRIALS = 50
MAX_ROUNDS = 2000
EARLY_STOP = 50
GATE_MONTHS = 6
SEARCH_MONTHS = 6
EARLYSTOP_MONTHS = 3
FIXED_LGB = dict(objective="lambdarank", boosting_type="gbdt", metric="ndcg",
                 eval_at=[1, 3], lambdarank_truncation_level=5, label_gain=LABEL_GAIN,
                 verbosity=-1)

# ---- Gate (PAPER_SPEC §7) ---------------------------------------------------------------
GATE_TRADE_RATES = (0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 1.00)

# ---- Walk-forward (PAPER_SPEC §8) ---------------------------------------------------------
WINDOWS = {
    "WF1": (2018, 2020, 2021),
    "WF2": (2018, 2021, 2022),
    "WF3": (2018, 2022, 2023),
    "WF4": (2018, 2023, 2024),
    "OOT": (2018, 2024, 2025),
    # Extension (PREREGISTRATION §6) — TEST B retrain; TEST A reuses the OOT model.
    "EXT_B": (2018, 2025, 2026),
}

# ---- Sizing grids (tab:sizing_grids) -------------------------------------------------------
def _grid(a: float, b: float, step: float) -> tuple[float, ...]:
    n = int(round((b - a) / step)) + 1
    return tuple(round(a + i * step, 6) for i in range(n))


SIZING_GRIDS = {
    "FMU": _grid(0.02, 0.60, 0.02),
    "VT": _grid(0.1, 2.5, 0.1),
    "SRS": _grid(0.02, 0.50, 0.02),
    "EA": _grid(0.05, 0.80, 0.05),
    "GB": _grid(0.005, 0.100, 0.005),
    "HK": _grid(0.05, 0.80, 0.05),
    "QK": _grid(0.05, 0.80, 0.05),
}
VOL_ANCHOR = 0.16
PAPER_NAV0 = 5_000_000.0
USER_NAV0 = 25_000.0


# ---- Products --------------------------------------------------------------------------------
@dataclass(frozen=True)
class Product:
    root: str                      # option root in data feeds
    underlying: str                # index / ETF symbol for S
    multiplier: int
    style: str                     # "european_cash" | "american_physical"
    tick_below_3: float            # minimum tick for premium < $3.00
    tick_at_or_above_3: float
    strike_step_hint: float        # typical 0DTE strike spacing near the money
    exchange_fee: dict = field(default_factory=dict)  # see fee_per_contract()

    def tick(self, price: float) -> float:
        return self.tick_below_3 if price < 3.0 else self.tick_at_or_above_3


# Exchange fees: IBKR pass-through of Cboe schedule, public customer
# (https://www.interactivebrokers.com/en/accounts/fees/CBOEoptfee.php, read 2026-09-30).
#   SPXW: $0.45 if premium >= $1 else $0.36, plus $0.14 SPXW execution surcharge.
#   XSP:  $0.07 (orders < 10 contracts receive a $0.30 rebate; NOT credited — conservative).
#   SPY/QQQ: multi-listed; conservative taker fee assumption $0.50 (PREREGISTRATION §3).
SPXW = Product("SPXW", "SPX", 100, "european_cash", 0.05, 0.10, 5.0,
               {"lt1": 0.36 + 0.14, "ge1": 0.45 + 0.14})
XSP = Product("XSP", "XSP", 100, "european_cash", 0.01, 0.05, 1.0, {"lt1": 0.07, "ge1": 0.07})
SPY = Product("SPY", "SPY", 100, "american_physical", 0.01, 0.01, 1.0, {"lt1": 0.50, "ge1": 0.50})
QQQ = Product("QQQ", "QQQ", 100, "american_physical", 0.01, 0.01, 1.0, {"lt1": 0.50, "ge1": 0.50})
PRODUCTS = {p.root: p for p in (SPXW, XSP, SPY, QQQ)}

# Clearing + regulatory (OCC ~0.02-0.025, ORF, FINRA TAF on sells) — conservative lump.
CLEARING_REG_PER_CONTRACT = 0.05


def ibkr_commission(premium: float) -> float:
    """IBKR US options commission tiers used by the paper (eq:fee_tier)."""
    if premium < 0.05:
        return 0.25
    if premium < 0.10:
        return 0.50
    return 0.65


def fee_per_contract(product: Product, premium: float, level: str) -> float:
    """Per-contract, per-leg, per-side fee.

    level "paper": commission only (paper's eq:fee_tier; $1 order minimum applied elsewhere).
    level "full":  commission + exchange fee + clearing/regulatory (execution level L3).
    """
    c = ibkr_commission(premium)
    if level == "paper":
        return c
    ex = product.exchange_fee["ge1" if premium >= 1.0 else "lt1"]
    return c + ex + CLEARING_REG_PER_CONTRACT


ORDER_MIN_FEE = 1.00
