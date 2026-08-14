"""
Screen definitions.

Every screen returns a boolean Series, True only on the bar the condition
FIRES. A golden cross that happened 40 days ago is not a fresh signal, and
counting it every day would inflate every base rate in the calibration.

Curation is evidence-led. Screens that measured NEGATIVE against the
same-date market baseline (recovery-from-lows, trend-reversal) were removed
outright. MACD and golden cross measured at zero and are kept anyway,
labelled - they are the two most requested screens in existence and
"widely believed, does not work" is a finding worth keeping visible.

Additions are drawn from the family the calibration says the edge actually
lives in - volume, momentum, breakout - plus the setups Indian traders use
heavily (Supertrend, NR7, inside bar) so they get MEASURED rather than
assumed.
"""
import numpy as np
import pandas as pd


# ------------------------------------------------------------- indicators --
def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def rsi(close, n=14):
    d = close.diff()
    up, dn = d.clip(lower=0), -d.clip(upper=0)
    au = up.ewm(alpha=1 / n, adjust=False).mean()
    ad = dn.ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + au / ad.replace(0, np.nan))).fillna(50)


def atr(df, n=14):
    h, l, c = df["High"], df["Low"], df["Close"]
    pc = c.shift()
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def adx(df, n=14):
    h, l = df["High"], df["Low"]
    up, dn = h.diff(), -l.diff()
    plus = np.where((up > dn) & (up > 0), up, 0.0)
    minus = np.where((dn > up) & (dn > 0), dn, 0.0)
    a = atr(df, n).replace(0, np.nan)
    pdi = 100 * pd.Series(plus, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / a
    mdi = 100 * pd.Series(minus, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / a
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False).mean(), pdi, mdi


def supertrend(df, period=10, mult=3.0):
    """Supertrend(10,3). Ubiquitous on Indian charting platforms, so it is
    here to be measured rather than taken on faith. Returns the direction
    series: True = bullish."""
    a = atr(df, period)
    hl2 = (df["High"] + df["Low"]) / 2
    upper, lower = hl2 + mult * a, hl2 - mult * a
    c = df["Close"].to_numpy()
    ub, lb = upper.to_numpy(), lower.to_numpy()
    fub, flb = ub.copy(), lb.copy()
    for i in range(1, len(c)):
        fub[i] = ub[i] if (ub[i] < fub[i - 1] or c[i - 1] > fub[i - 1]) else fub[i - 1]
        flb[i] = lb[i] if (lb[i] > flb[i - 1] or c[i - 1] < flb[i - 1]) else flb[i - 1]
    dirn = np.ones(len(c), dtype=bool)
    for i in range(1, len(c)):
        if c[i] > fub[i - 1]:
            dirn[i] = True
        elif c[i] < flb[i - 1]:
            dirn[i] = False
        else:
            dirn[i] = dirn[i - 1]
    return pd.Series(dirn, index=df.index)


def indicators(df, bench=None):
    """bench: optional benchmark Close series (NIFTY) for relative strength."""
    o = df.copy()
    c, h, l, v = o["Close"], o["High"], o["Low"], o["Volume"]
    for n in (10, 20, 50, 150, 200):
        o[f"sma{n}"] = c.rolling(n).mean()
    o["macd"] = ema(c, 12) - ema(c, 26)
    o["macd_sig"] = ema(o["macd"], 9)
    o["rsi14"] = rsi(c, 14)
    o["atr14"] = atr(o, 14)
    o["adx"], o["pdi"], o["mdi"] = adx(o, 14)
    o["turnover"] = (c * v).rolling(20).median()
    o["vol20"] = v.rolling(20).mean()
    o["vol_ratio"] = v / o["vol20"]
    o["hh252"], o["ll252"] = c.rolling(252).max(), c.rolling(252).min()
    o["hh20"] = h.rolling(20).max()
    o["from_high"] = c / o["hh252"] - 1
    o["from_low"] = c / o["ll252"] - 1
    for n in (5, 21, 63, 126, 252):
        o[f"ret{n}"] = c.pct_change(n)
    o["bb_mid"] = c.rolling(20).mean()
    sd = c.rolling(20).std()
    o["bb_lo"], o["bb_hi"] = o["bb_mid"] - 2 * sd, o["bb_mid"] + 2 * sd
    o["bb_width"] = (o["bb_hi"] - o["bb_lo"]) / o["bb_mid"]
    o["rng"] = h - l
    o["body"] = (c - o["Open"]).abs()
    o["range10"] = (h.rolling(10).max() - l.rolling(10).min()) / c
    o["range10_prev"] = o["range10"].shift(20)
    o["st_bull"] = supertrend(o)
    # relative strength vs the index - O'Neil's RS line
    if bench is not None:
        b = bench.reindex(o.index).ffill()
        rs = c / b
        o["rs"] = rs
        o["rs_hh252"] = rs.rolling(252).max()
        o["rs_new_high"] = rs >= o["rs_hh252"] * 0.995
        o["rel_ret63"] = c.pct_change(63) - b.pct_change(63)
    else:
        o["rs_new_high"] = False
        o["rel_ret63"] = np.nan
    o["warm"] = o[["sma200", "hh252", "ll252", "adx", "turnover",
                   "range10_prev"]].notna().all(axis=1)
    return o


def _edge(cond, warm=None):
    """True only on the bar the condition genuinely becomes true.

    Two traps are guarded here, both of which produced plausible-looking
    wrong output rather than a crash:

    1. A comparison against a not-yet-defined rolling mean (`Close > sma200`
       while sma200 is NaN) evaluates False, not NaN. On the bar the
       indicator becomes valid the condition flips False->True and mimics a
       fresh crossover, firing for every stock already in an uptrend at once.
       `warm` suppresses that.
    2. `cond.shift(1)` on a bool Series yields object dtype. pandas 2.x
       silently downcast it back on .fillna(); pandas 3.0 does not, so `~`
       fell through to Python bitwise and returned -1/-2, both truthy,
       degenerating _edge to `cond`. shift(fill_value=) + astype(bool) is
       version-proof.
    """
    cond = cond.fillna(False).astype(bool)
    prev = cond.shift(1, fill_value=False).astype(bool)
    fired = cond & ~prev
    if warm is not None:
        w = warm.fillna(False).astype(bool)
        fired &= w.shift(1, fill_value=False).astype(bool)
    return fired


def _e(f, cond):
    return _edge(cond, f.get("warm"))


def _uptrend(f):
    """Minervini-style trend template, the common gate for long setups."""
    return ((f.Close > f.sma50) & (f.sma50 > f.sma150) & (f.sma150 > f.sma200)
            & (f.sma200.diff(21) > 0) & (f.from_low > 0.30))


# ============================================== TIER 1: demonstrated edge ==
def volume_thrust(f):
    """Big up-day on heavy volume from above the 50-DMA - accumulation."""
    return _e(f, (f.vol_ratio > 2.5) & (f.Close.pct_change() > 0.04)
              & (f.Close > f.sma50))


def breakout_52w(f):
    """New 52-week high on volume. Darvas / O'Neil / Minervini core setup."""
    return _e(f, (f.Close >= f.hh252 * 0.999) & (f.vol_ratio > 1.5))


def momentum_leader(f):
    """Strong 6- and 12-month momentum with trend structure intact."""
    return _e(f, (f.ret252 > 0.40) & (f.ret126 > 0.15)
              & (f.Close > f.sma50) & (f.sma50 > f.sma200))


# ==================================== NEW: breakout anticipation / volume ==
def vcp(f):
    """Volatility Contraction Pattern (Minervini).

    Price coiling near its high: successive tighter ranges on drying volume,
    inside a confirmed uptrend. The canonical 'about to break out' setup and
    the most rigorous of the near-breakout family."""
    contraction = f.range10 < 0.6 * f.range10_prev
    dry = f.Volume.rolling(5).mean() < 0.85 * f.vol20
    return _e(f, _uptrend(f) & (f.from_high > -0.15) & contraction & dry
              & (f.range10 < 0.10))


def near_breakout_price(f):
    """Within 3% of the 52-week high but not through it, coiled tight.
    The 'watch list' version of a breakout - fires before the move."""
    return _e(f, (f.from_high > -0.03) & (f.from_high < -0.002)
              & (f.range10 < 0.08) & (f.Close > f.sma50) & (f.sma50 > f.sma200))


def near_breakout_volume(f):
    """Volume building while price stays in a tight range - accumulation
    ahead of the move rather than confirmation after it."""
    building = f.Volume.rolling(3).mean() > 1.3 * f.vol20
    return _e(f, building & (f.range10 < 0.06) & (f.Close > f.sma50)
              & (f.from_high > -0.20))


def pocket_pivot(f):
    """Pocket pivot (Kacher & Morales): an up-day whose volume exceeds the
    largest DOWN-day volume of the prior 10 sessions, taken near the 10-DMA
    inside an uptrend. Designed to get in before the standard breakout."""
    down_vol = f.Volume.where(f.Close < f.Close.shift(), 0)
    return _e(f, (f.Close > f.Close.shift())
              & (f.Volume > down_vol.rolling(10).max())
              & (f.Close >= f.sma10 * 0.98) & (f.Close > f.sma50)
              & (f.sma50 > f.sma200))


def darvas_breakout(f):
    """Darvas box: the 20-day high has been flat (a ceiling) for at least
    10 sessions, then price closes through it on volume."""
    ceiling = f.hh20.shift(1)
    flat = (ceiling.diff().abs().rolling(10).max() / ceiling) < 0.005
    return _e(f, (f.Close > ceiling) & flat & (f.vol_ratio > 1.3)
              & (f.Close > f.sma50))


def rs_new_high(f):
    """Relative strength line at a new high (O'Neil). The stock is making a
    new high AGAINST the index - often precedes the price breakout."""
    return _e(f, f.rs_new_high.fillna(False) & (f.Close > f.sma50)
              & (f.sma50 > f.sma200) & (f.from_high > -0.15))


# ================================== NEW: widely used in Indian markets ====
def supertrend_flip(f):
    """Supertrend(10,3) flips bullish while above the 200-DMA. Included
    because it is near-universal on Indian platforms and therefore worth
    having an actual number attached to."""
    return _e(f, f.st_bull & (f.Close > f.sma200) & (f.adx > 20))


def nr7_breakout(f):
    """NR7: today's range is the narrowest of the last 7, then price takes
    out that bar's high. Range contraction into expansion - a staple of
    Indian swing trading."""
    nr7 = f.rng == f.rng.rolling(7).min()
    return _e(f, nr7.shift(1).fillna(False) & (f.Close > f.High.shift(1))
              & (f.Close > f.sma50))


def inside_bar_breakout(f):
    """Inside bar (compression) resolved upward inside an uptrend."""
    inside = (f.High < f.High.shift(1)) & (f.Low > f.Low.shift(1))
    return _e(f, inside.shift(1).fillna(False) & (f.Close > f.High.shift(1))
              & (f.Close > f.sma50) & (f.sma50 > f.sma200))


# ============================================ NEW: candlestick at support ==
def bullish_engulfing(f):
    """Bullish engulfing at the 50-DMA in an uptrend. Candlestick patterns
    in isolation are noise; gating on trend + support is the only version
    worth testing."""
    prev_red = f.Close.shift(1) < f.Open.shift(1)
    engulf = (f.Close > f.Open) & (f.Close >= f.Open.shift(1)) & (f.Open <= f.Close.shift(1))
    at_support = (f.Low <= f.sma50 * 1.02) & (f.Close > f.sma50 * 0.98)
    return _e(f, prev_red & engulf & at_support & (f.sma50 > f.sma200))


def hammer_at_support(f):
    """Hammer: long lower wick, small body, close in the upper third,
    printed at the 50-DMA inside an uptrend."""
    lower_wick = f[["Open", "Close"]].min(axis=1) - f.Low
    upper_wick = f.High - f[["Open", "Close"]].max(axis=1)
    hammer = (lower_wick > 2 * f.body) & (upper_wick < f.body) & (f.rng > 0)
    at_support = (f.Low <= f.sma50 * 1.02) & (f.Close > f.sma50 * 0.98)
    return _e(f, hammer & at_support & (f.sma50 > f.sma200) & (f.Close > f.sma200))


# =========================== KEPT AS DOCUMENTED NEGATIVES (do not alert) ===
def macd_bullish_cross(f):
    """Measured at zero edge over 19,978 signals. Kept visible on purpose."""
    return _e(f, (f.macd > f.macd_sig)
              & (f.macd < f.macd.abs().rolling(100).mean()) & (f.Close > f.sma200))


def golden_cross(f):
    """Measured at zero edge over 3,625 signals. Kept visible on purpose."""
    return _e(f, (f.sma50 > f.sma200) & (f.sma200.diff(5) > 0))


PRICE_SCREENS = {
    # tier 1 - demonstrated edge
    "Volume thrust / accumulation": volume_thrust,
    "52-week breakout on volume": breakout_52w,
    "Momentum leader": momentum_leader,
    # breakout anticipation
    "VCP (volatility contraction)": vcp,
    "Near breakout - price": near_breakout_price,
    "Near breakout - volume": near_breakout_volume,
    "Pocket pivot": pocket_pivot,
    "Darvas box breakout": darvas_breakout,
    "RS line new high": rs_new_high,
    # widely used in India
    "Supertrend flip (10,3)": supertrend_flip,
    "NR7 breakout": nr7_breakout,
    "Inside bar breakout": inside_bar_breakout,
    # candlestick, gated on trend + support
    "Bullish engulfing at 50DMA": bullish_engulfing,
    "Hammer at 50DMA": hammer_at_support,
    # kept as documented negatives
    "MACD bullish crossover": macd_bullish_cross,
    "Golden crossover (50/200)": golden_cross,
}
