"""
Regression tests. Run in CI before the screener, because both bugs these
cover produced plausible-looking output rather than a crash.

  python screener/test_screens.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from market import project_last_volume, session_state  # noqa: E402
from screens import _edge, indicators  # noqa: E402

FAIL = []


def check(name, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        print(f"        got  {got}\n        want {want}")
        FAIL.append(name)


print(f"pandas {pd.__version__} | numpy {np.__version__}\n")
print("_edge fires on the transition, not while the condition holds")
cond = pd.Series([False, False, True, True, True, False, True])
check("single fire per rising edge", list(_edge(cond)),
      [False, False, True, False, False, False, True])
check("all-True series fires only at bar 0",
      list(_edge(pd.Series([True, True, True]))), [True, False, False])
check("all-False never fires",
      any(_edge(pd.Series([False, False, False]))), False)

print("\nwarm-up mask suppresses the transition out of warm-up")
cond2 = pd.Series([False, False, True, True, True])
warm = pd.Series([False, False, True, True, True])
check("no fire on first warm bar", list(_edge(cond2, warm)),
      [False, False, False, False, False])
warm2 = pd.Series([True, True, True, True, True])
check("fires normally once warm", list(_edge(cond2, warm2)),
      [False, False, True, False, False])

print("\nvolume projection")
for dtype in ("int64", "float64"):
    df = pd.DataFrame({"Open": [100.0] * 3, "High": [101.0] * 3,
                       "Low": [99.0] * 3, "Close": [100.0] * 3,
                       "Volume": pd.Series([1000, 1000, 250]).astype(dtype)})
    out = project_last_volume(df, 0.25)
    check(f"{dtype} projects last bar", round(float(out['Volume'].iat[-1])), 1000)
    check(f"{dtype} leaves source untouched", int(df["Volume"].iat[-1]), 250)
    check(f"{dtype} leaves earlier bars alone", int(out["Volume"].iat[0]), 1000)
check("closed session is a no-op",
      int(project_last_volume(
          pd.DataFrame({"Open": [1.0], "High": [1.0], "Low": [1.0],
                        "Close": [1.0], "Volume": [500]}), 1.0)["Volume"].iat[0]), 500)

print("\nsession clock (IST)")
import datetime as dt  # noqa: E402
from market import IST  # noqa: E402
check("pre-open", session_state(dt.datetime(2026, 8, 14, 8, 30, tzinfo=IST))[0], "pre")
check("mid-session", session_state(dt.datetime(2026, 8, 14, 12, 45, tzinfo=IST))[0], "open")
check("after close", session_state(dt.datetime(2026, 8, 14, 15, 35, tzinfo=IST))[0], "closed")
check("saturday", session_state(dt.datetime(2026, 8, 15, 11, 0, tzinfo=IST))[0], "closed")

print("\nindicators expose a warm mask")
rng = np.random.default_rng(0)
n = 400
px = pd.DataFrame({"Open": 100 + rng.normal(0, 1, n).cumsum(),
                   "High": 0.0, "Low": 0.0, "Close": 0.0,
                   "Volume": rng.integers(1e5, 1e6, n)},
                  index=pd.bdate_range("2024-01-01", periods=n))
px["Close"] = px["Open"] + rng.normal(0, 0.5, n)
px["High"] = px[["Open", "Close"]].max(axis=1) + 0.5
px["Low"] = px[["Open", "Close"]].min(axis=1) - 0.5
f = indicators(px)
check("warm column present", "warm" in f.columns, True)
check("warm is False during warm-up", bool(f["warm"].iloc[0]), False)
check("warm is True at the end", bool(f["warm"].iloc[-1]), True)

print()
if FAIL:
    print(f"{len(FAIL)} FAILED: {FAIL}")
    sys.exit(1)
print("all passed")
