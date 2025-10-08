import os
import json
import random
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta

# Paths setup
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CONFIG_DIR = os.path.join(BASE_DIR, "config")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

CORE_CONFIG = os.path.join(CONFIG_DIR, "core_stocks.json")
POOL_CONFIG = os.path.join(CONFIG_DIR, "pool_stocks.json")
FINAL_WATCHLIST = os.path.join(OUTPUT_DIR, "final_watchlist.json")

# Default fallback if no pool config is found
DEFAULT_POOL = [
    "RELIANCE.NS", "INFY.NS", "TCS.NS", "HDFCBANK.NS", "ICICIBANK.NS",
    "SBIN.NS", "BHARTIARTL.NS", "TATAMOTORS.NS", "ITC.NS", "LT.NS",
    "KOTAKBANK.NS", "HCLTECH.NS", "ADANIENT.NS", "TITAN.NS", "SUNPHARMA.NS",
    "HDFCLIFE.NS", "MARUTI.NS", "WIPRO.NS", "ULTRACEMCO.NS", "POWERGRID.NS"
]


# ------------------------------
# 🧩 Loaders
# ------------------------------
def load_core():
    """Load core_stocks.json (always include these stocks)."""
    try:
        with open(CORE_CONFIG, "r") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def load_pool():
    """Load pool_stocks.json if exists, else fallback to DEFAULT_POOL."""
    try:
        with open(POOL_CONFIG, "r") as f:
            data = json.load(f)
            if isinstance(data, list) and len(data) > 0:
                return data
    except Exception:
        pass
    return DEFAULT_POOL


# ------------------------------
# 📊 Dynamic Stock Selector
# ------------------------------
def is_close_to_52w_high_low(df, pct_threshold=3.0):
    """Return True if the last close is within pct_threshold% of 52w high or low."""
    if df is None or df.empty:
        return False
    try:
        close = df["Close"].iloc[-1]
        last_252 = df["Close"].tail(252)
        if last_252.empty:
            return False
        high52 = last_252.max()
        low52 = last_252.min()
        pct_high = (high52 - close) / high52 * 100
        pct_low = (close - low52) / low52 * 100
        return pct_high <= pct_threshold or pct_low <= pct_threshold
    except Exception:
        return False


def get_dynamic_tickers(pool_tickers=None, top_n=8,
                        vol_multiplier=1.3, price_move_pct=1.5,
                        use_52w=True, pct_52w=3.0):
    """
    Scans tickers from pool_tickers and selects active ones based on:
      - Volume spike
      - Price change
      - 52-week proximity
    Returns top_n ranked by score.
    """
    pool = pool_tickers or load_pool()
    scored = []
    period_str = "60d"

    for t in pool:
        try:
            df = yf.download(t, period=period_str, interval="1d", progress=False, threads=False)
            if df is None or df.empty:
                continue

            if "Volume" not in df.columns or "Close" not in df.columns:
                continue

            df = df.dropna(subset=["Close", "Volume"])
            if df.shape[0] < 10:
                continue

            avg_vol = df["Volume"].tail(20).mean()
            latest = df.iloc[-1]
            prev_close = df["Close"].iloc[-2] if df.shape[0] > 1 else latest["Close"]

            vol_ratio = latest["Volume"] / (avg_vol + 1e-9)
            move_pct = ((latest["Close"] - prev_close) / prev_close) * 100 if prev_close else 0

            score = 0
            if vol_ratio >= vol_multiplier:
                score += vol_ratio
            if abs(move_pct) >= price_move_pct:
                score += abs(move_pct) / price_move_pct
            if use_52w and is_close_to_52w_high_low(df, pct_threshold=pct_52w):
                score += 0.8

            if score > 0:
                scored.append({"ticker": t, "score": score})

        except Exception:
            continue

    # Sort and pick top N
    scored.sort(key=lambda x: x["score"], reverse=True)
    dynamic = [s["ticker"] for s in scored[:top_n]]

    # Fallback if empty
    if not dynamic:
        dynamic = random.sample(pool, min(top_n, len(pool)))

    return dynamic


# ------------------------------
# 🧠 Build Final Watchlist
# ------------------------------
def build_watchlist(pool_tickers=None, top_n=8, **kwargs):
    """
    Builds the final watchlist:
      ✅ Core stocks (from core_stocks.json)
      ✅ Dynamic stocks (based on daily activity)
    Writes output/final_watchlist.json and returns list.
    """
    core = load_core()
    dynamic = get_dynamic_tickers(pool_tickers=pool_tickers, top_n=top_n, **kwargs)

    final = []
    for t in core + dynamic:
        if t not in final:
            final.append(t)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(FINAL_WATCHLIST, "w") as f:
        json.dump(final, f, indent=2)

    print(f"✅ Final Watchlist Built ({len(final)} stocks):")
    print(json.dumps(final, indent=2))
    return final


if __name__ == "__main__":
    wl = build_watchlist(top_n=10)
    print("✅ Final Watchlist:", wl)
