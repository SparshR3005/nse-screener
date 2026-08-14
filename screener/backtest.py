"""
Strategy backtest layer: every screen tested as a TRADEABLE RULE, with a
stop, a target and real costs.

This is deliberately different from calibrate.py. Calibration answers "does
this pattern precede better-than-average returns" by holding a fixed number
of sessions with no stop. That measures signal quality and nothing else.

It also hides the thing that decides whether a screen is tradeable: every
screen in this repo shows a median max-adverse-excursion around -7.5%, so a
tight stop gets hit on most eventual winners. Only a run with an actual stop
reveals that, and that is what this file does.

Per trade:
  entry   next session's OPEN after the signal, plus slippage
  stop    ATR- or percent-based, checked intrabar against the LOW
  target  R-multiple or percent, checked intrabar against the HIGH
  costs   full delivery schedule incl. STT and DP, on a stated position size

Conservative intrabar assumption: if a bar's range spans BOTH stop and
target, the STOP is assumed to fill first. Gaps through the stop fill at the
open, not the stop price.
"""
import argparse
import json
import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
from costs import delivery_cost  # noqa: E402
from screens import PRICE_SCREENS, indicators  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data")

POSITION = 25_000.0      # rupees per trade; DP + brokerage floors matter at this size
SLIP = 0.0005            # 5 bps per side
MIN_TURNOVER, MIN_PRICE = 2.5e7, 50.0
MAXH = 126               # hard time stop, sessions


# ------------------------------------------------------------ exit policies
# stop_atr / target_R  -> stop = n x ATR below entry, target = m x risk
# stop_pct / target_pct-> fixed percentages (O'Neil style)
# trail_atr            -> chandelier: exit n x ATR below the highest high
POLICIES = {
    "2ATR stop / 3R target":  dict(stop_atr=2.0, target_r=3.0),
    "2ATR stop / 2R target":  dict(stop_atr=2.0, target_r=2.0),
    "1.5ATR stop / 3R target": dict(stop_atr=1.5, target_r=3.0),
    "3ATR stop / 4R target":  dict(stop_atr=3.0, target_r=4.0),
    "8% stop / 20% target":   dict(stop_pct=0.08, target_pct=0.20),
    "3ATR chandelier trail":  dict(stop_atr=3.0, trail_atr=3.0),
    "no stop, hold 63d":      dict(hold=63),
}


def simulate(o, h, l, c, atr0, i, pol):
    """One trade from signal bar i. Returns (exit_px, bars_held, reason)."""
    n = len(c)
    if i + 1 >= n:
        return None
    entry = o[i + 1] * (1 + SLIP)
    if not np.isfinite(entry) or entry <= 0:
        return None

    hold = pol.get("hold", MAXH)
    stop = target = None
    if "stop_atr" in pol:
        stop = entry - pol["stop_atr"] * atr0[i]
    elif "stop_pct" in pol:
        stop = entry * (1 - pol["stop_pct"])
    if stop is not None and "target_r" in pol:
        target = entry + pol["target_r"] * (entry - stop)
    elif "target_pct" in pol:
        target = entry * (1 + pol["target_pct"])

    trail = pol.get("trail_atr")
    peak = entry
    end = min(i + 1 + hold, n)
    for k in range(i + 1, end):
        peak = max(peak, h[k])
        if trail is not None:
            cand = peak - trail * atr0[k]
            if stop is None or cand > stop:
                stop = cand
        # stop checked first: pessimistic when a bar spans both levels
        if stop is not None and l[k] <= stop:
            fill = min(stop, o[k]) if o[k] < stop else stop   # gap-through
            return fill * (1 - SLIP), k - i, "stop"
        if target is not None and h[k] >= target:
            return target * (1 - SLIP), k - i, "target"
    j = end - 1
    return c[j] * (1 - SLIP), j - i, "time"


def run(years=11, position=POSITION):
    px = D.fetch_prices(D.universe(), years=years)
    bench = D.fetch_benchmark(years=years)
    print(f"{len(px)} symbols, benchmark {'ok' if bench is not None else 'MISSING'}")

    frames = {}
    for s, df in px.items():
        f = indicators(df, bench)
        f = f[(f.turnover > MIN_TURNOVER) & (f.Close > MIN_PRICE) & f.warm]
        if len(f) > 300:
            frames[s] = f
    print(f"{len(frames)} pass liquidity + warm-up\n")

    # ---------------------------------------------------------- CONTROL --
    # Random entries from the same universe and period, run through the SAME
    # exit machinery. Without this the table measures the 2015-26 bull market:
    # hold anything 63 days and it shows +6%, which is why MACD and golden
    # cross - both measured at zero edge - look profitable in absolute terms.
    # Only screen-minus-control is evidence of a screen doing any work.
    rng = np.random.default_rng(7)
    pool = []
    for s, f in frames.items():
        arrs = (f["Open"].to_numpy(), f["High"].to_numpy(), f["Low"].to_numpy(),
                f["Close"].to_numpy(), f["atr14"].to_numpy())
        n = len(f)
        for i in rng.choice(np.arange(0, max(n - 2, 1)),
                            size=min(60, max(n - 2, 1)), replace=False):
            if np.isfinite(arrs[4][i]) and arrs[4][i] > 0:
                pool.append((s, int(i), arrs))
    print(f"control sample: {len(pool):,} random entries")

    control = {}
    for pname, pol in POLICIES.items():
        nets = []
        for s, i, (o, h, l, c, a) in pool:
            r = simulate(o, h, l, c, a, i, pol)
            if r is None:
                continue
            ex, bars, why = r
            entry = o[i + 1] * (1 + SLIP)
            qty = max(int(position // entry), 1)
            gin, gout = entry * qty, ex * qty
            nets.append(100 * (gout - gin - delivery_cost(gin, gout)) / gin)
        arr = np.array(nets)
        control[pname] = dict(n=len(arr), net_pct=round(float(arr.mean()), 3),
                              sd=float(arr.std(ddof=1)))
        print(f"  control  {pname:<26} net {arr.mean():+.2f}%  (n={len(arr):,})")
    print()

    results = defaultdict(dict)
    for name, fn in PRICE_SCREENS.items():
        sigs = []
        for s, f in frames.items():
            try:
                fired = fn(f).to_numpy()
            except Exception:
                continue
            idx = np.nonzero(fired)[0]
            if not len(idx):
                continue
            arrs = (f["Open"].to_numpy(), f["High"].to_numpy(),
                    f["Low"].to_numpy(), f["Close"].to_numpy(),
                    f["atr14"].to_numpy())
            for i in idx:
                if i + 2 < len(f) and np.isfinite(arrs[4][i]) and arrs[4][i] > 0:
                    sigs.append((s, i, arrs))
        if len(sigs) < 100:
            print(f"  {name:<32} only {len(sigs)} signals - skipped")
            continue

        for pname, pol in POLICIES.items():
            rows = []
            for s, i, (o, h, l, c, a) in sigs:
                r = simulate(o, h, l, c, a, i, pol)
                if r is None:
                    continue
                ex, bars, why = r
                entry = o[i + 1] * (1 + SLIP)
                qty = max(int(position // entry), 1)
                gin, gout = entry * qty, ex * qty
                fees = delivery_cost(gin, gout)
                pnl = gout - gin - fees
                rows.append((100 * pnl / gin, 100 * (gout - gin) / gin, bars, why))
            if not rows:
                continue
            net = np.array([r[0] for r in rows])
            gross = np.array([r[1] for r in rows])
            bars = np.array([r[2] for r in rows])
            why = [r[3] for r in rows]
            wins, losses = net[net > 0], net[net <= 0]
            ctl = control.get(pname, {})
            excess = float(net.mean()) - ctl.get("net_pct", 0.0)
            # Welch t on screen mean vs control mean
            se = np.sqrt(net.var(ddof=1) / len(net)
                         + ctl.get("sd", 0.0) ** 2 / max(ctl.get("n", 1), 1))
            results[name][pname] = dict(
                n=len(net),
                net_pct=round(float(net.mean()), 3),
                control_pct=ctl.get("net_pct"),
                excess_pct=round(excess, 3),
                t_vs_control=round(excess / se, 1) if se > 0 else None,
                gross_pct=round(float(gross.mean()), 3),
                cost_drag=round(float(gross.mean() - net.mean()), 3),
                win_pct=round(100 * len(wins) / len(net), 1),
                avg_win=round(float(wins.mean()), 2) if len(wins) else 0.0,
                avg_loss=round(float(losses.mean()), 2) if len(losses) else 0.0,
                profit_factor=(round(float(wins.sum() / -losses.sum()), 2)
                               if len(losses) and losses.sum() < 0 else None),
                t_stat=round(float(net.mean() / (net.std(ddof=1) / np.sqrt(len(net)))), 1),
                med_bars=int(np.median(bars)),
                exit_stop=round(100 * why.count("stop") / len(why)),
                exit_target=round(100 * why.count("target") / len(why)),
                exit_time=round(100 * why.count("time") / len(why)),
            )
        best = max(results[name].items(), key=lambda kv: kv[1]["excess_pct"])
        print(f"  {name:<32} {len(sigs):>6} sigs | best: {best[0]:<24} "
              f"excess {best[1]['excess_pct']:+.2f}%  t={best[1]['t_vs_control']:+.1f}")

    with open(os.path.join(OUT, "strategy_backtest.json"), "w") as f:
        json.dump({"position_size": position, "slippage_bps": SLIP * 1e4,
                   "policies": {k: str(v) for k, v in POLICIES.items()},
                   "results": results}, f, indent=1)
    return results


def report(results):
    pd.set_option("display.width", 250, "display.max_columns", 30)
    print("\n" + "=" * 132)
    print(f"STRATEGY BACKTEST - net %/trade after full costs, Rs {POSITION:,.0f} position, "
          f"{SLIP*1e4:.0f}bps slippage/side")
    print("=" * 132)
    rows = []
    for screen, pols in results.items():
        for pol, r in pols.items():
            rows.append(dict(screen=screen, exit=pol, **r))
    df = pd.DataFrame(rows)
    if df.empty:
        print("no results")
        return df
    print("\n--- BEST EXIT PER SCREEN (ranked by net expectancy) ---")
    best = df.sort_values("excess_pct", ascending=False).groupby("screen").head(1)
    print(best.sort_values("excess_pct", ascending=False)[
        ["screen", "exit", "n", "net_pct", "control_pct", "excess_pct", "t_vs_control", "win_pct", "avg_win", "avg_loss", "profit_factor", "med_bars", "exit_stop", "exit_target"]].to_string(index=False))

    print("\n--- WHICH EXIT POLICY IS BEST OVERALL? (mean net across screens) ---")
    print(df.groupby("exit").agg(
        screens=("screen", "nunique"),
        mean_net=("net_pct", "mean"),
        mean_excess=("excess_pct", "mean"),
        median_excess=("excess_pct", "median"),
        mean_win=("win_pct", "mean"),
        mean_hold=("med_bars", "mean")).round(2).sort_values(
        "mean_excess", ascending=False).to_string())
    df.to_csv(os.path.join(OUT, "strategy_backtest.csv"), index=False)
    return df


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=11)
    ap.add_argument("--position", type=float, default=POSITION)
    a = ap.parse_args()
    report(run(a.years, a.position))
