"""Real-quote microstructure check on one Cboe delayed snapshot (2026-09-30 ~15:32 ET).

What this IS: actual displayed bid/ask for SPXW, XSP, SPY puts, pushed through the
frozen universe resolver, fee and margin code. It measures the execution cost of each
delta bucket per product.
What this is NOT: a backtest, a 10:00 snapshot, or evidence of edge. One timestamp only.

Expiry E1 (next session, ~7 trading hours left) is used as a trading-time proxy
for a 10:00 0DTE (6 hours left); E0 (today, ~27 minutes left) is shown for completeness.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vrp_ltr.config import PRODUCTS, USER_NAV0, fee_per_contract  # noqa: E402
from vrp_ltr.data import cboe_snapshot  # noqa: E402
from vrp_ltr.execution import regt_short_put_margin, spread_fill  # noqa: E402
from vrp_ltr.universe import build_universe, risk_capped_long_strike, vertical_long_strike  # noqa: E402

SNAP = ROOT / "data" / "raw" / "cboe_delayed" / "2026-09-30"
OUT = ROOT / "docs" / "snapshot_2026-09-30"
EFFR = 0.0388  # FRED EFFR 2026-09-29
FILES = {"SPXW": "_SPX_154815.json", "XSP": "_XSP_154816.json", "SPY": "SPY_154816.json"}


def candidate_table(root: str, chain: pd.DataFrame, meta: dict, expiry) -> pd.DataFrame:
    prod = PRODUCTS[root]
    c = chain[(chain["root"] == root) & (chain["expiration"] == expiry)]
    u = build_universe(c.drop(columns="root"), meta["spot"], EFFR, meta["quotes_as_of_et"])
    t = u.candidates.copy()
    S = meta["spot"]
    t["otm_pct"] = (S - t["strike"]) / S
    t["spread"] = t["ask"] - t["bid"]
    t["spread_pct_mid"] = t["spread"] / t["mid"]
    t["abs_delta"] = t["delta"].abs()
    t["cboe_abs_delta"] = t["cboe_delta"].abs()
    t["premium_mid_$"] = t["mid"] * prod.multiplier
    t["fee_L1_$"] = [fee_per_contract(prod, p, "paper") for p in t["mid"]]
    l3_px = t["bid"] - np.array([prod.tick(b) for b in t["bid"]])
    t["credit_L3_$"] = np.maximum(l3_px, 0) * prod.multiplier
    t["fee_L3_$"] = [fee_per_contract(prod, p, "full") for p in l3_px.clip(lower=0)]
    t["net_L1_$"] = t["premium_mid_$"] - t["fee_L1_$"]
    t["net_L3_$"] = t["credit_L3_$"] - t["fee_L3_$"]
    t["L3_haircut_pct_of_L1"] = 1 - t["net_L3_$"] / t["net_L1_$"]
    t["regt_margin_$"] = [regt_short_put_margin(p, S, k, prod.multiplier) for p, k in zip(t["mid"], t["strike"])]
    t.insert(0, "root", root)
    t.insert(1, "expiry", expiry)
    return t


def verticals(root: str, chain: pd.DataFrame, meta: dict, expiry, cands: pd.DataFrame) -> pd.DataFrame:
    prod = PRODUCTS[root]
    c = chain[(chain["root"] == root) & (chain["expiration"] == expiry)]
    u = build_universe(c.drop(columns="root"), meta["spot"], EFFR, meta["quotes_as_of_et"])
    puts = u.puts
    rows = []
    for _, cand in cands.iterrows():
        ks = cand["strike"]
        s = puts[np.isclose(puts["strike"], ks)].iloc[0]
        specs = [("W5", vertical_long_strike(puts, ks, 5.0)), ("W10", vertical_long_strike(puts, ks, 10.0))]
        for cap in (0.01, 0.02, 0.04):
            specs.append((f"CAP{int(cap * 100)}%", risk_capped_long_strike(puts, ks, cap * USER_NAV0, prod.multiplier)))
        for name, kl in specs:
            rec = {"root": root, "strategy": cand["strategy"], "short_K": ks, "variant": name, "long_K": kl}
            if kl is None:
                rec["status"] = "SKIP (no valid long strike)"
                rows.append(rec)
                continue
            l = puts[np.isclose(puts["strike"], kl)].iloc[0]
            w = ks - kl
            for lvl in ("MID", "NAT", "NAT1"):
                cr = spread_fill(s["bid"], s["ask"], l["bid"], l["ask"], lvl, prod)
                rec[f"credit_{lvl}_$"] = None if cr is None else round(cr * prod.multiplier, 2)
            fee_full = fee_per_contract(prod, s["bid"], "full") + fee_per_contract(prod, l["ask"], "full")
            nat = rec["credit_NAT_$"]
            ml = None if nat is None else round(w * prod.multiplier - nat + fee_full, 2)
            rec.update({"width": w, "fees_L3_$": round(fee_full, 2), "max_loss_NAT_$": ml,
                        "max_loss_pct_NAV": None if ml is None else round(ml / USER_NAV0, 4),
                        "status": "OK" if nat is not None else "SKIP (natural credit <= 0)"})
            rows.append(rec)
    return pd.DataFrame(rows)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    all_c, all_v, metas = [], [], {}
    for root, f in FILES.items():
        chain, meta = cboe_snapshot.parse(SNAP / f)
        metas[root] = meta
        exps = sorted(chain.loc[chain["root"] == root, "expiration"].unique())
        e0, e1 = exps[0], exps[1]
        for e in (e0, e1):
            ct = candidate_table(root, chain, meta, e)
            all_c.append(ct)
            if e == e1 and root in ("XSP", "SPY", "SPXW"):
                all_v.append(verticals(root, chain, meta, e, ct))
    C = pd.concat(all_c, ignore_index=True)
    V = pd.concat(all_v, ignore_index=True)
    C.to_csv(OUT / "candidates.csv", index=False)
    V.to_csv(OUT / "verticals.csv", index=False)
    cols = ["root", "expiry", "strategy", "strike", "otm_pct", "bid", "ask", "spread", "spread_pct_mid",
            "abs_delta", "cboe_abs_delta", "premium_mid_$", "net_L1_$", "net_L3_$", "L3_haircut_pct_of_L1",
            "regt_margin_$"]
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)
    for root, m in metas.items():
        print(f"{root}: spot {m['spot']}, quotes as of {m['quotes_as_of_et']}")
    print(C[cols].round(4).to_string(index=False))
    print(V.to_string(index=False))


if __name__ == "__main__":
    main()
