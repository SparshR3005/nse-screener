"""Data layer: universe, prices, fundamentals. Built to tolerate a cloud runner."""
import io
import json
import os
import pickle
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests
import yfinance as yf

warnings.filterwarnings("ignore")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
os.makedirs(DATA, exist_ok=True)

UNIVERSE_JSON = os.path.join(DATA, "universe.json")
PRICES_PKL = os.path.join(DATA, "prices.pkl")
FUND_JSON = os.path.join(DATA, "fundamentals.json")
QUARTERLY_JSON = os.path.join(DATA, "quarterly.json")

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0"}
NSE_500 = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"

FUND_FIELDS = ["trailingPE", "forwardPE", "priceToBook", "returnOnEquity",
               "revenueGrowth", "earningsGrowth", "earningsQuarterlyGrowth",
               "profitMargins", "debtToEquity", "marketCap", "trailingEps",
               "bookValue", "sector", "industry"]


def universe(refresh=False):
    """NSE's own constituent file, with the committed copy as fallback.

    GitHub runners are outside India and NSE may refuse them; the committed
    universe.json means a fetch failure degrades to yesterday's list rather
    than an empty run.
    """
    if refresh:
        try:
            r = requests.get(NSE_500, headers=UA, timeout=25)
            if r.status_code == 200 and len(r.content) > 500:
                df = pd.read_csv(io.StringIO(r.text))
                col = [c for c in df.columns if "symbol" in c.lower()][0]
                syms = sorted({str(x).strip().upper() for x in df[col] if str(x).strip()})
                if len(syms) > 300:
                    with open(UNIVERSE_JSON, "w") as f:
                        json.dump(syms, f, indent=0)
                    print(f"universe refreshed from NSE: {len(syms)}")
                    return syms
            print(f"NSE refresh failed (HTTP {r.status_code}); using committed list")
        except Exception as e:
            print(f"NSE refresh failed ({type(e).__name__}); using committed list")
    with open(UNIVERSE_JSON) as f:
        return json.load(f)


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def fetch_prices(syms, period="400d", retries=3):
    """Yahoo throttles cloud IPs; retry each batch before giving up on it."""
    out = {}
    for batch in _chunks([s + ".NS" for s in syms], 40):
        for attempt in range(retries):
            try:
                raw = yf.download(batch, period=period, interval="1d",
                                  auto_adjust=True, group_by="column",
                                  threads=True, progress=False)
                if raw is None or not len(raw):
                    raise RuntimeError("empty frame")
                break
            except Exception as e:
                if attempt == retries - 1:
                    print(f"  batch failed after {retries}: {type(e).__name__}")
                    raw = None
                else:
                    time.sleep(3 * (attempt + 1))
        if raw is None:
            continue
        for t in batch:
            try:
                df = raw.xs(t, axis=1, level=1)
            except (KeyError, TypeError):
                continue
            df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
            df = df[df["Volume"] > 0]
            if len(df) >= 260:
                out[t[:-3]] = df
    return out


def save_prices(px):
    with open(PRICES_PKL, "wb") as f:
        pickle.dump(px, f)


def load_prices():
    with open(PRICES_PKL, "rb") as f:
        return pickle.load(f)


def _info(sym):
    try:
        i = yf.Ticker(sym + ".NS").info
        return sym, {k: i.get(k) for k in FUND_FIELDS}
    except Exception:
        return sym, None


def _quarterly(sym):
    try:
        q = yf.Ticker(sym + ".NS").quarterly_financials
        if q is None or q.empty:
            return sym, None
        key = ([k for k in q.index if str(k).strip() == "Net Income"]
               or [k for k in q.index if "Net Income" in str(k)])
        if not key:
            return sym, None
        return sym, {str(c)[:10]: float(v) for c, v in q.loc[key[0]].dropna().items()}
    except Exception:
        return sym, None


def _pool(fn, syms, workers=6):
    out, done = {}, 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for fu in as_completed([ex.submit(fn, s) for s in syms]):
            s, d = fu.result()
            done += 1
            if d:
                out[s] = d
            if done % 100 == 0:
                print(f"  {done}/{len(syms)} ({len(out)} ok)", flush=True)
    return out


def refresh_fundamentals(syms):
    fu = _pool(_info, syms)
    with open(FUND_JSON, "w") as f:
        json.dump(fu, f)
    qt = _pool(_quarterly, syms)
    with open(QUARTERLY_JSON, "w") as f:
        json.dump(qt, f)
    return fu, qt


def load_json(path, default=None):
    if not os.path.exists(path):
        return default if default is not None else {}
    with open(path) as f:
        return json.load(f)
