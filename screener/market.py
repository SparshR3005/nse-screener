"""
Session awareness + intraday volume projection.

Why this file exists: the screens are calibrated on COMPLETED daily bars.
Run at 10:30 IST, today's bar holds barely a quarter of the day's volume, so
`volume / 20-day average` reads low and the three screens that actually have
edge - all volume-based - silently fail to fire in the morning.

We correct by projecting today's volume to a full-session estimate using the
typical U-shaped NSE intraday volume curve (heavy at the open and the close,
thin in the middle). Signals produced before the close are marked PROVISIONAL:
they can un-fire by 15:30, and the calibrated base rates assume a close.
"""
import datetime as dt

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
OPEN_T = dt.time(9, 15)
CLOSE_T = dt.time(15, 30)

# cumulative share of a day's volume traded by each IST clock time.
# Approximate NSE profile: ~20% in the first 45 min, ~18% in the last 30.
_CURVE = [
    (9, 15, 0.00), (9, 30, 0.10), (10, 0, 0.20), (10, 30, 0.28),
    (11, 0, 0.35), (11, 30, 0.41), (12, 0, 0.46), (12, 30, 0.51),
    (13, 0, 0.56), (13, 30, 0.62), (14, 0, 0.67), (14, 30, 0.74),
    (15, 0, 0.82), (15, 30, 1.00),
]


def now_ist():
    return dt.datetime.now(IST)


def session_state(ts=None):
    """-> ('pre'|'open'|'closed', fraction_of_volume_elapsed)"""
    ts = ts or now_ist()
    if ts.weekday() >= 5:
        return "closed", 1.0
    t = ts.time()
    if t < OPEN_T:
        return "pre", 0.0
    if t >= CLOSE_T:
        return "closed", 1.0
    mins = (ts.hour * 60 + ts.minute)
    for i in range(len(_CURVE) - 1):
        h0, m0, f0 = _CURVE[i]
        h1, m1, f1 = _CURVE[i + 1]
        a, b = h0 * 60 + m0, h1 * 60 + m1
        if a <= mins <= b:
            frac = f0 + (f1 - f0) * (mins - a) / max(b - a, 1)
            return "open", max(frac, 0.02)
    return "open", 1.0


def project_last_volume(df, frac):
    """Scale the final (partial) bar's volume up to a full-session estimate.

    Only touches the last row, and only while the session is open. Returns a
    copy so the caller's frame is never mutated in place.
    """
    if frac >= 1.0 or len(df) == 0:
        return df
    out = df.copy()
    out.iloc[-1, out.columns.get_loc("Volume")] = (
        out["Volume"].iat[-1] / frac)
    return out
