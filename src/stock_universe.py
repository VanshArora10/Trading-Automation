# src/stock_universe.py
import os
import json
import math
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta

# Resolve project root and config paths (works when running as package or script)
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CONFIG_DIR = os.path.join(BASE_DIR, "config")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
CORE_CONFIG = os.path.join(CONFIG_DIR, "core_stocks.json")
POOL_CONFIG = os.path.join(CONFIG_DIR, "pool_stocks.json")
FINAL_WATCHLIST = os.path.join(OUTPUT_DIR, "final_watchlist.json")

# Default pool if user hasn't provided pool_stocks.json
DEFAULT_POOL = [
    "RELIANCE.NS", "INFY.NS", "TCS.NS", "HDFCBANK.NS", "ICICIBANK.NS",
    "BHARTIARTL.NS", "SBIN.NS", "ICICIGI.NS", "ITC.NS", "LT.NS"
]

def load_core():
    """Load core_stocks.json (fallback to empty list if missing)."""
    try:
        with open(CORE_CONFIG, "r") as f:
            data = json.load(f)
            if not isinstance(data, list):
                return []
            return data
    except FileNotFoundError:
        return []
    except Exception:
        return []

def load_pool():
    """Load pool_stocks.json or return DEFAULT_POOL."""
    try:
        with open(POOL_CONFIG, "r") as f:
            data = json.load(f)
            if not isinstance(data, list) or len(data) == 0:
                return DEFAULT_POOL
            return data
    except FileNotFoundError:
        return DEFAULT_POOL
    except Exception:
        return DEFAULT_POOL

def is_close_to_52w_high_low(df, pct_threshold=2.0):
    """
    Return True if the most recent close is within pct_threshold (%) of 52-week high or low.
    df: daily dataframe with at least 252 rows ideally.
    """
    if df is None or df.empty:
        return False
    try:
        close = df["Close"].iloc[-1]
        last_252 = df["Close"].tail(252)
        if last_252.empty:
            return False
        high52 = last_252.max()
        low52 = last_252.min()
        if high52 <= 0 or low52 <= 0:
            return False
        pct_high = (high52 - close) / high52 * 100
        pct_low = (close - low52) / low52 * 100
        return (pct_high <= pct_threshold) or (pct_low <= pct_threshold)
    except Exception:
        return False

def get_dynamic_tickers(pool_tickers=None, top_n=8,
                        vol_multiplier=1.5, lookback_days=60,
                        price_move_pct=3.0, use_52w=True, pct_52w=2.0):
    """
    Scan pool_tickers and return a list of stocks meeting dynamic criteria.
    Criteria (any of):
      - Today's volume > vol_multiplier * 20-day avg volume
      - Today's price change % > price_move_pct (absolute)
      - Close is within pct_52w% of 52-week high/low (optional)
    Returns up to top_n tickers sorted by score (volume*move combination).
    """
    pool = pool_tickers or load_pool()
    scored = []

    # We request lookback_days + a little extra for rolling calculations
    period_days = max(lookback_days, 30) + 5
    period_str = f"{period_days}d"

    for t in pool:
        try:
            # fetch daily bars
            df = yf.download(tickers=t, period=period_str, interval="1d", progress=False, threads=False)
            if df is None or df.empty:
                continue

            # Basic defensive checks
            if "Volume" not in df.columns or "Close" not in df.columns:
                continue

            # Compute simple metrics
            df = df.dropna(subset=["Close", "Volume"])
            if df.shape[0] < 10:
                continue

            # compute 20-day avg volume (use rolling)
            if df["Volume"].size >= 20:
                avg_vol = df["Volume"].rolling(20).mean().iloc[-1]
            else:
                avg_vol = df["Volume"].mean()

            latest = df.iloc[-1]
            prev_close = df["Close"].iloc[-2] if df.shape[0] >= 2 else latest["Close"]
            vol = float(latest["Volume"])
            close = float(latest["Close"])
            move_pct = 0.0
            if prev_close and prev_close != 0:
                move_pct = (close - prev_close) / prev_close * 100

            # Score components
            vol_ratio = vol / (avg_vol + 1e-9)
            score = 0.0

            # Volume spike rule
            vol_spike = vol_ratio >= vol_multiplier
            if vol_spike:
                score += (vol_ratio - vol_multiplier) * 2.0 + 1.0

            # Price move rule
            if abs(move_pct) >= price_move_pct:
                score += abs(move_pct) / price_move_pct

            # 52-week proximity (optional)
            prox52 = False
            if use_52w:
                try:
                    prox52 = is_close_to_52w_high_low(df, pct_threshold=pct_52w)
                except Exception:
                    prox52 = False
                if prox52:
                    score += 0.8

            # If any rule triggers, add to scored
            if score > 0:
                scored.append({
                    "ticker": t,
                    "score": score,
                    "vol_ratio": vol_ratio,
                    "move_pct": move_pct,
                    "prox52": prox52
                })

        except Exception:
            # skip ticker on any error (yfinance occasionally fails); continue scanning next
            continue

    # Sort by score descending and take top_n
    scored.sort(key=lambda x: x["score"], reverse=True)
    selected = [s["ticker"] for s in scored[:top_n]]
    return selected

def build_watchlist(pool_tickers=None, top_n=8, **kwargs):
    """
    Load core ticks from config and add dynamic picks (top_n).
    Writes output/final_watchlist.json and returns the list.
    """
    core = load_core()
    dynamic = get_dynamic_tickers(pool_tickers=pool_tickers, top_n=top_n, **kwargs)
    # union preserving core order first
    final = []
    for t in core + dynamic:
        if t not in final:
            final.append(t)

    # persist
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    try:
        with open(FINAL_WATCHLIST, "w") as f:
            json.dump(final, f, indent=2)
    except Exception:
        pass

    return final

if __name__ == "__main__":
    # quick local test
    wl = build_watchlist(top_n=5)
    print("Final watchlist:", wl)
# --- IGNORE ---