"""
Re-measure each screen's base rate. Slow (~20 min); run from the maintenance
workflow on demand, not on a schedule.

Method note, because it is easy to get wrong: excess is the signal's forward
return minus the SAME-DATE cross-sectional mean. Date-matching separates stock
selection from market timing. Mean-vs-mean is mandatory — scoring a mean
against a *median* baseline makes a random control group score t=+17 purely
because stock returns are right-skewed. The control is computed below so that
failure mode stays visible.
"""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D  # noqa: E402
from screens import PRICE_SCREENS, indicators  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CALIB = os.path.join(ROOT, "data", "calibration.json")
HZ, TARGET, MAXH = 126, 0.10, 126
MIN_TURNOVER, MIN_PRICE = 2.5e7, 50.0


def main():
    px = D.load_prices()
    frames = {}
    for s, df in px.items():
        f = indicators(df)
        f = f[(f.turnover > MIN_TURNOVER) & (f.Close > MIN_PRICE)]
        if len(f) > 300:
            frames[s] = f
    print(f"{len(frames)} symbols pass liquidity")

    fwd, hits, days = {}, {}, {}
    for s, f in frames.items():
        o, h, c = (f["Open"].to_numpy(), f["High"].to_numpy(), f["Close"].to_numpy())
        n = len(f)
        entry = np.roll(o, -1)
        entry[-1] = np.nan
        v = np.full(n, np.nan)
        v[:n - HZ] = np.roll(c, -HZ)[:n - HZ] / entry[:n - HZ] - 1
        fwd[s] = pd.Series(v, index=f.index)
        hv, dv = np.full(n, np.nan), np.full(n, np.nan)
        for i in range(200, n - 1):
            e = entry[i]
            if not np.isfinite(e) or e <= 0:
                continue
            k = min(MAXH, n - i - 1)
            r = np.nonzero(h[i + 1:i + 1 + k] >= e * (1 + TARGET))[0]
            hv[i] = 1.0 if len(r) else 0.0
            dv[i] = (int(r[0]) + 1) if len(r) else np.nan
        hits[s], days[s] = pd.Series(hv, index=f.index), pd.Series(dv, index=f.index)

    PAN = pd.DataFrame(fwd)
    DATE_MEAN = PAN.mean(axis=1)
    HP, DP = pd.DataFrame(hits), pd.DataFrame(days)

    # control: random stock-days. Must land at t ~ 0.
    flat = PAN.stack().dropna()
    samp = flat.sample(n=min(12000, len(flat)), random_state=0)
    cx = samp.to_numpy() - DATE_MEAN.reindex(
        samp.index.get_level_values(0)).to_numpy()
    cx = cx[np.isfinite(cx)]
    ct = cx.mean() / (cx.std(ddof=1) / np.sqrt(len(cx)))
    print(f"CONTROL (should be ~0): mean {100*cx.mean():+.2f}%  t={ct:+.1f}")
    if abs(ct) > 2:
        print("  WARNING: control is significant -> baseline construction is wrong")

    out = {"_meta": {"measured_on": str(pd.Timestamp.today().date()),
                     "symbols": len(frames), "control_t": round(float(ct), 2),
                     "baseline": {
                         "P_touch_plus10pct_within_126d": round(100 * float(HP.stack().mean()), 1),
                         "median_days_to_plus10pct": int(DP.stack().median()),
                         "median_126d_return_pct": round(100 * float(flat.median()), 2)}}}

    for name, fn in PRICE_SCREENS.items():
        rs, hs, ds = [], [], []
        for s, f in frames.items():
            try:
                fired = fn(f).to_numpy()
            except Exception:
                continue
            idx = np.nonzero(fired)[0]
            idx = idx[(idx >= 200) & (idx < len(f) - 1)]
            if not len(idx):
                continue
            dts = f.index[idx]
            rs.append(fwd[s].reindex(dts).to_numpy()
                      - DATE_MEAN.reindex(dts).to_numpy())
            hs.append(hits[s].reindex(dts).to_numpy())
            ds.append(days[s].reindex(dts).to_numpy())
        if not rs:
            continue
        x = np.concatenate(rs)
        x = x[np.isfinite(x)]
        hh = np.concatenate(hs)
        dd = np.concatenate(ds)
        if len(x) < 200:
            continue
        t = x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))
        verdict = "EDGE" if t > 2 else ("NEGATIVE" if t < -2 else "NO EDGE")
        out[name] = {"edge_pct": round(100 * float(x.mean()), 2),
                     "t": round(float(t), 1), "verdict": verdict,
                     "signals": int(len(x)),
                     "p_hit10": round(100 * float(np.nanmean(hh)), 1),
                     "median_days": int(np.nanmedian(dd))}
        print(f"  {verdict:<9} {name:<38} {100*x.mean():+.2f}%  t={t:+.1f}  n={len(x)}")

    with open(CALIB, "w") as f:
        json.dump(out, f, indent=1)
    print(f"wrote {CALIB}")


if __name__ == "__main__":
    main()
