"""
Screen definitions.

Every screen is a function over an indicator frame that returns a boolean
Series aligned to the index, True on the bar the condition FIRES (not every
bar it holds). Firing-edge semantics matter: a golden cross that happened
40 days ago is not a fresh signal, and counting it every day would inflate
every base rate in the calibration.
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
    h, l, c = df["High"], df["Low"], df["Close"]
    up, dn = h.diff(), -l.diff()
    plus = np.where((up > dn) & (up > 0), up, 0.0)
    minus = np.where((dn > up) & (dn > 0), dn, 0.0)
    a = atr(df, n).replace(0, np.nan)
    pdi = 100 * pd.Series(plus, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / a
    mdi = 100 * pd.Series(minus, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / a
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False).mean(), pdi, mdi


def indicators(df):
    o = df.copy()
    c = o["Close"]
    o["sma20"] = c.rolling(20).mean()
    o["sma50"] = c.rolling(50).mean()
    o["sma100"] = c.rolling(100).mean()
    o["sma200"] = c.rolling(200).mean()
    o["ema12"], o["ema26"] = ema(c, 12), ema(c, 26)
    o["macd"] = o["ema12"] - o["ema26"]
    o["macd_sig"] = ema(o["macd"], 9)
    o["macd_hist"] = o["macd"] - o["macd_sig"]
    o["rsi14"] = rsi(c, 14)
    o["rsi2"] = rsi(c, 2)
    o["atr14"] = atr(o, 14)
    o["adx"], o["pdi"], o["mdi"] = adx(o, 14)
    o["turnover"] = (c * o["Volume"]).rolling(20).median()
    o["vol_ratio"] = o["Volume"] / o["Volume"].rolling(20).mean()
    o["hh252"] = c.rolling(252).max()
    o["ll252"] = c.rolling(252).min()
    o["hh20"] = o["High"].rolling(20).max()
    o["ret5"] = c.pct_change(5)
    o["ret21"] = c.pct_change(21)
    o["ret63"] = c.pct_change(63)
    o["ret126"] = c.pct_change(126)
    o["ret252"] = c.pct_change(252)
    o["from_low"] = c / o["ll252"] - 1
    o["from_high"] = c / o["hh252"] - 1
    o["bb_mid"] = c.rolling(20).mean()
    sd = c.rolling(20).std()
    o["bb_lo"], o["bb_hi"] = o["bb_mid"] - 2 * sd, o["bb_mid"] + 2 * sd
    o["vol21"] = c.pct_change().rolling(21).std()
    # a bar is "warm" once every long-window indicator is actually defined.
    # Screens must not fire on the bar an indicator first becomes valid.
    o["warm"] = o[["sma200", "hh252", "ll252", "adx", "turnover"]].notna().all(axis=1)
    return o


def _edge(cond, warm=None):
    """True only on the bar the condition genuinely becomes true.

    The subtlety that bit us: a comparison against a not-yet-defined rolling
    mean (`Close > sma200` while sma200 is NaN) evaluates to False, not NaN.
    So on the bar the indicator finally becomes valid, the condition flips
    False->True and looks exactly like a fresh crossover. With a short price
    history that fires for every stock already in an uptrend at once - it
    reported 207 golden crosses in one session, including ICICIBANK and SBIN,
    whose 50-DMA had been above the 200-DMA for months.

    `warm` marks bars where every long-window indicator is defined; a
    transition is only real if the previous bar was already warm.
    """
    cond = cond.fillna(False)
    fired = cond & ~cond.shift(1).fillna(False)
    if warm is not None:
        fired &= warm.shift(1).fillna(False)
    return fired


# ---------------------------------------------------------------- screens --
def _edge_w(f, cond):
    """_edge with this frame's warm-up mask applied."""
    return _edge(cond, f.get("warm"))


def macd_bullish_cross(f):
    """MACD crosses above its signal line, below/near zero, in a stock that is
    not in a downtrend. Restricting to crosses at or below zero keeps it a
    turn signal rather than a mid-trend re-entry."""
    return _edge_w(f, (f.macd > f.macd_sig) & (f.macd < f.macd.abs().rolling(100).mean())
                 & (f.Close > f.sma200))


def golden_cross(f):
    """50-DMA crosses above 200-DMA."""
    return _edge_w(f, (f.sma50 > f.sma200) & (f.sma200.diff(5) > 0))


def recovery_from_lows(f):
    """Beaten-down name turning up: within 35% of its 52w low, price back
    above the 50-DMA, 50-DMA itself starting to rise, RSI out of the hole."""
    return _edge_w(f, (f.from_low < 0.35) & (f.from_high < -0.25)
                 & (f.Close > f.sma50) & (f.sma50.diff(10) > 0)
                 & (f.rsi14 > 50))


def trend_reversal(f):
    """Downtrend ending: price reclaims the 200-DMA after being below it for
    a stretch, with ADX confirming a real trend and +DI over -DI."""
    below = (f.Close < f.sma200).rolling(60).sum()
    return _edge_w(f, (f.Close > f.sma200) & (below.shift(1) > 35)
                 & (f.adx > 20) & (f.pdi > f.mdi))


def oversold_bounce(f):
    """Oversold inside an intact uptrend - the buyable kind of oversold,
    not a falling knife."""
    return _edge_w(f, (f.rsi14 < 32) & (f.Close > f.sma200) & (f.Close < f.bb_lo))


def breakout_52w(f):
    """New 52-week high on volume."""
    return _edge_w(f, (f.Close >= f.hh252 * 0.999) & (f.vol_ratio > 1.5))


def volume_thrust(f):
    """Big up-day on heavy volume from a base - accumulation signature."""
    return _edge_w(f, (f.vol_ratio > 2.5) & (f.Close.pct_change() > 0.04)
                 & (f.Close > f.sma50))


def golden_pullback(f):
    """Established uptrend pulling back to its 50-DMA - buy-the-dip in a
    confirmed leader."""
    return _edge_w(f, (f.sma50 > f.sma200) & (f.Close > f.sma200)
                 & (f.Close <= f.sma50 * 1.02) & (f.Close >= f.sma50 * 0.97)
                 & (f.ret252 > 0.10))


def momentum_leader(f):
    """Strong 6- and 12-month momentum with the trend structure intact."""
    return _edge_w(f, (f.ret252 > 0.40) & (f.ret126 > 0.15)
                 & (f.Close > f.sma50) & (f.sma50 > f.sma200))


def squeeze_release(f):
    """Volatility contraction resolving upward - Bollinger squeeze break."""
    width = (f.bb_hi - f.bb_lo) / f.bb_mid
    return _edge_w(f, (width.shift(1) < width.rolling(126).quantile(0.20).shift(1))
                 & (f.Close > f.bb_hi.shift(1)) & (f.Close > f.sma200))


PRICE_SCREENS = {
    "MACD bullish crossover": macd_bullish_cross,
    "Golden crossover (50/200)": golden_cross,
    "Recovery from lows": recovery_from_lows,
    "Trend reversal (reclaim 200DMA)": trend_reversal,
    "Oversold bounce (RSI<32 in uptrend)": oversold_bounce,
    "52-week breakout on volume": breakout_52w,
    "Volume thrust / accumulation": volume_thrust,
    "Pullback to 50DMA in uptrend": golden_pullback,
    "Momentum leader": momentum_leader,
    "Volatility squeeze release": squeeze_release,
}
