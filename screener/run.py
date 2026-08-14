"""
Live screener run. Called by the intraday workflow 7x a session and once
after the close.

Emits only NEW signals: a symbol/screen pair alerts once per day, so seven
runs don't produce seven copies of the same hit.
"""
import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
import market as M  # noqa: E402
from screens import PRICE_SCREENS, indicators  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA, DOCS = os.path.join(ROOT, "data"), os.path.join(ROOT, "docs")
STATE = os.path.join(DATA, "state.json")
LATEST = os.path.join(DATA, "latest.json")
CALIB = os.path.join(DATA, "calibration.json")

MIN_TURNOVER, MIN_PRICE = 2.5e7, 50.0
FRESH_BARS = 2          # fired on the current bar or the one before


def roe(f):
    e, b = f.get("trailingEps"), f.get("bookValue")
    try:
        return float(e) / float(b) if e is not None and b else None
    except (TypeError, ZeroDivisionError):
        return None


def fundamental_hits(fund, quarterly):
    out = {"High growth + High RoE + Low PE": [],
           "Quality compounder": [],
           "Loss to profit (turnaround)": []}
    for s, f in fund.items():
        mc = f.get("marketCap")
        if mc and mc < 5e9:
            continue
        pe, rg, de, r = (f.get("trailingPE"), f.get("revenueGrowth"),
                         f.get("debtToEquity"), roe(f))
        # RoE above ~60% on this computation is nearly always a near-zero
        # book value, not a real business. Exclude rather than headline it.
        if r is not None and r > 0.60:
            r = None
        if pe and 0 < pe < 30 and rg and rg > 0.15 and r and r > 0.15:
            out["High growth + High RoE + Low PE"].append(
                dict(symbol=s, PE=round(pe, 1), rev_growth=round(100 * rg, 1),
                     RoE=round(100 * r, 1), sector=f.get("sector")))
        if r and r > 0.18 and de is not None and de < 50 and pe and 0 < pe < 60:
            out["Quality compounder"].append(
                dict(symbol=s, PE=round(pe, 1), RoE=round(100 * r, 1),
                     DE=round(de / 100, 2), sector=f.get("sector")))
    for s, q in (quarterly or {}).items():
        ser = [q[k] for k in sorted(q)]
        if len(ser) < 4:
            continue
        if all(x > 0 for x in ser[-2:]) and any(x < 0 for x in ser[:-2]):
            out["Loss to profit (turnaround)"].append(
                dict(symbol=s, last_2q_cr=[round(x / 1e7, 1) for x in ser[-2:]],
                     worst_prior_cr=round(min(ser[:-2]) / 1e7, 1),
                     sector=(fund.get(s) or {}).get("sector")))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh-prices", action="store_true")
    ap.add_argument("--edge-only", action="store_true",
                    help="alert only on screens with demonstrated edge")
    args = ap.parse_args()

    syms = D.universe()
    if args.refresh_prices or not os.path.exists(D.PRICES_PKL):
        print(f"fetching prices for {len(syms)} symbols ...")
        px = D.fetch_prices(syms)
        if len(px) < 100:
            print(f"ABORT: only {len(px)} symbols returned; refusing to "
                  "overwrite cache or emit alerts off a broken pull")
            sys.exit(1)
        D.save_prices(px)
    else:
        px = D.load_prices()

    state_name, frac = M.session_state()
    provisional = state_name == "open"
    print(f"session={state_name} volume_elapsed={frac:.0%} "
          f"provisional={provisional} symbols={len(px)}")

    calib = D.load_json(CALIB, {})
    fund = D.load_json(D.FUND_JSON, {})
    quarterly = D.load_json(D.QUARTERLY_JSON, {})
    # RS screens compare each stock to the index; without this they are inert
    bench = D.fetch_benchmark(years=3)

    frames, asof = {}, None
    for s, df in px.items():
        if len(df) < D.MIN_BARS:
            continue
        if provisional:
            df = M.project_last_volume(df, frac)
        f = indicators(df, bench)
        last = f.iloc[-1]
        if not (last.turnover > MIN_TURNOVER and last.Close > MIN_PRICE):
            continue
        frames[s] = f
        asof = f.index[-1] if asof is None else max(asof, f.index[-1])

    today = str(asof.date()) if asof is not None else "?"
    state = D.load_json(STATE, {})
    if state.get("date") != today:
        state = {"date": today, "seen": []}
    seen = set(tuple(x) for x in state["seen"])

    report = {"as_of": today, "session": state_name,
              "volume_elapsed_pct": round(100 * frac),
              "provisional": provisional, "screens": {}, "new": []}

    for name, fn in PRICE_SCREENS.items():
        c = calib.get(name, {})
        verdict = c.get("verdict", "UNCALIBRATED")
        if args.edge_only and verdict != "EDGE":
            continue
        hits = []
        for s, f in frames.items():
            try:
                fired = fn(f)
            except Exception:
                continue
            if not fired.iloc[-FRESH_BARS:].any():
                continue
            last = f.iloc[-1]
            h = dict(symbol=s, close=round(float(last.Close), 1),
                     rsi=round(float(last.rsi14)), adx=round(float(last.adx)),
                     ret1y=(round(100 * float(last.ret252))
                            if np.isfinite(last.ret252) else None),
                     from_52wh=round(100 * float(last.from_high)),
                     turnover_cr=round(float(last.turnover) / 1e7, 1),
                     sector=(fund.get(s) or {}).get("sector"))
            hits.append(h)
            if (name, s) not in seen:
                seen.add((name, s))
                report["new"].append(dict(screen=name, verdict=verdict,
                                          edge=c.get("edge_pct"), **h))
        hits.sort(key=lambda r: -(r["turnover_cr"] or 0))
        report["screens"][name] = dict(verdict=verdict, edge_pct=c.get("edge_pct"),
                                       t=c.get("t"), n=len(hits), hits=hits)
        print(f"  {verdict:<13} {name:<38} {len(hits):>3} hits")

    if fund:
        report["fundamental_screens"] = {
            k: dict(n=len(v), hits=v) for k, v in
            fundamental_hits(fund, quarterly).items()}

    state["seen"] = [list(x) for x in seen]
    with open(STATE, "w") as f:
        json.dump(state, f)
    with open(LATEST, "w") as f:
        json.dump(report, f, indent=1, default=str)

    print(f"\n{len(report['new'])} NEW signal(s) this run")
    return report


if __name__ == "__main__":
    main()
