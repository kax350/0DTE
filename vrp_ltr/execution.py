"""Execution levels, fees, margin, settlement (PAPER_SPEC §9, PREREGISTRATION §3-4).

Short single put:
  L1  paper headline: sell at mid,          commission-only fees (eq:fee_tier), $1 order minimum
  L2  sell at displayed BID,                commission-only fees
  L3  sell at BID - 1 tick,                 full fees (commission + exchange + clearing/reg)
  P75 paper's 75%-coverage drag test: 0.75*bid + 0.25*ask (reported for comparison)
Vertical (sell K_s put, buy K_l put) — both legs from real quotes:
  MID  mid-combo credit  = mid_s - mid_l
  NAT  natural credit    = bid_s - ask_l
  NAT1 natural - 1 tick
Fees always per leg. No exit fee when held to cash settlement.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .config import ORDER_MIN_FEE, Product, fee_per_contract

SINGLE_LEVELS = ("L1", "P75", "L2", "L3")
SPREAD_LEVELS = ("MID", "NAT", "NAT1")


def single_fill(bid: float, ask: float, level: str, product: Product) -> float | None:
    mid = 0.5 * (bid + ask)
    if level == "L1":
        px = mid
    elif level == "P75":
        px = 0.75 * bid + 0.25 * ask
    elif level == "L2":
        px = bid
    elif level == "L3":
        px = bid - product.tick(bid)
    else:
        raise ValueError(level)
    return px if px > 0 else None  # cannot sell for <= 0 -> no trade


def spread_fill(bid_s: float, ask_s: float, bid_l: float, ask_l: float, level: str,
                product: Product) -> float | None:
    if level == "MID":
        c = 0.5 * (bid_s + ask_s) - 0.5 * (bid_l + ask_l)
    elif level == "NAT":
        c = bid_s - ask_l
    elif level == "NAT1":
        c = bid_s - ask_l - product.tick(max(bid_s - ask_l, 0.0))
    else:
        raise ValueError(level)
    return c if c > 0 else None


def fees(product: Product, legs: list[tuple[float, int]], level: str) -> float:
    """legs: [(premium_per_share, contracts)]. level 'paper' or 'full'. $1 order minimum."""
    fee_level = "full" if level in ("L3", "NAT1", "full") else "paper"
    total = sum(fee_per_contract(product, abs(p), fee_level) * q for p, q in legs if q > 0)
    n = sum(q for _, q in legs)
    return max(total, ORDER_MIN_FEE) if n > 0 else 0.0


def put_intrinsic(K: float, S: float) -> float:
    return max(K - S, 0.0)


def regt_short_put_margin(P: float, S: float, K: float, mult: int = 100) -> float:
    """eq:put_margin: 100*[P + max(0.15 S - OTM, 0.10 K)]."""
    otm = max(0.0, S - K)
    return mult * (P + max(0.15 * S - otm, 0.10 * K))


def vertical_max_loss(width: float, credit: float, mult: int = 100) -> float:
    return max(width - credit, 0.0) * mult


def vertical_margin(width: float, mult: int = 100) -> float:
    """Reg-T for a put credit spread: width x multiplier (credit received offsets cash)."""
    return width * mult


@dataclass
class TradeResult:
    gross: float        # $ per position before fees
    fees: float
    net: float
    credit: float       # per share
    max_loss: float     # $ theoretical (spreads) or NaN (naked)
    margin: float       # $ buying-power effect


def settle_short_put(credit: float, K: float, S_settle: float, qty: int, product: Product,
                     fee_level: str) -> TradeResult:
    m = product.multiplier
    gross = qty * m * (credit - put_intrinsic(K, S_settle))
    f = fees(product, [(credit, qty)], fee_level)
    return TradeResult(gross, f, gross - f, credit, math.nan, math.nan)


def settle_put_spread(credit: float, Ks: float, Kl: float, S_settle: float, qty: int,
                      prem_s: float, prem_l: float, product: Product, fee_level: str) -> TradeResult:
    m = product.multiplier
    payoff = put_intrinsic(Ks, S_settle) - put_intrinsic(Kl, S_settle)
    gross = qty * m * (credit - payoff)
    f = fees(product, [(prem_s, qty), (prem_l, qty)], fee_level)
    width = Ks - Kl
    return TradeResult(gross, f, gross - f, credit, vertical_max_loss(width, credit, m) * qty,
                       vertical_margin(width, m) * qty)


def close_put_spread_at(credit: float, Ks: float, Kl: float, exit_quotes: dict, qty: int,
                        entry_prem: tuple[float, float], product: Product, level: str) -> TradeResult:
    """SPY-style early exit (15:45/15:55): buy back short at ask, sell long at bid (NAT/NAT1),
    or mid-combo (MID). Entry and exit fees charged on both legs."""
    bs_, as_, bl, al = (exit_quotes[k] for k in ("bid_s", "ask_s", "bid_l", "ask_l"))
    if level == "MID":
        debit = 0.5 * (bs_ + as_) - 0.5 * (bl + al)
    else:
        debit = as_ - bl
        if level == "NAT1":
            debit += product.tick(max(debit, 0.0))
    debit = max(debit, 0.0)
    m = product.multiplier
    gross = qty * m * (credit - debit)
    f = (fees(product, [(entry_prem[0], qty), (entry_prem[1], qty)], level)
         + fees(product, [(as_, qty), (bl, qty)], level))
    width = Ks - Kl
    return TradeResult(gross, f, gross - f, credit, vertical_max_loss(width, credit, m) * qty,
                       vertical_margin(width, m) * qty)
