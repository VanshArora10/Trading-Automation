# src/strategies/closing_near_highlow.py
import pandas as pd
from datetime import datetime
import numpy as np

# No external indicator requirement; we compute ATR fallback if needed.
REQUIRED_INDICATORS = []


def _safe_float(x):
    """Convert scalar/1-element Series to float safely."""
    try:
        # If pandas Series or numpy scalar
        if hasattr(x, "iloc"):
            return float(x.iloc[0])
        return float(x)
    except Exception:
        return None


def _compute_atr(df, length=14):
    """
    Compute simple ATR from daily DataFrame.
    Returns ATR as float (based on last `length` rows). If not possible, returns None.
    """
    if df is None or df.empty:
        return None
    d = df.rename(columns=str.lower).dropna(subset=["high", "low", "close"])
    if d.shape[0] < 2:
        return None

    # True range per row (current high-low, current high - prev close, prev close - current low)
    h = d["high"]
    l = d["low"]
    c = d["close"]
    prev_c = c.shift(1)
    tr1 = h - l
    tr2 = (h - prev_c).abs()
    tr3 = (l - prev_c).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = true_range.rolling(length, min_periods=1).mean().iloc[-1]
    if pd.isna(atr):
        return None
    return float(atr)


def generate_signal(ticker, multi_df, threshold=0.10, rr=2.0, min_confidence=0.6):
    """
    Live pipeline adapter.
    - multi_df: dict containing at least '1d' DataFrame (newest last)
    - threshold: fraction of day range to consider "near high/low" (0.10 = 10%)
    - rr: target / risk reward ratio (target = entry + rr * risk for BUY)
    Returns: dict with fields or None
    """
    df = multi_df.get("1d")
    if df is None or df.empty or len(df) < 2:
        return None

    # Work with lowercase column names, ensure OHLC exist
    d = df.rename(columns=str.lower).dropna(subset=["open", "high", "low", "close"])
    if d.shape[0] < 2:
        return None

    # Use previous full day (signal) and current row to estimate next open
    today = d.iloc[-2]   # the day used to form the signal
    next_bar = d.iloc[-1]  # the most recent bar (next open placeholder)

    close_price = _safe_float(today["close"])
    high_price = _safe_float(today["high"])
    low_price = _safe_float(today["low"])
    next_open = _safe_float(next_bar["open"])

    if None in (close_price, high_price, low_price, next_open):
        return None

    day_range = high_price - low_price
    if day_range <= 0:
        return None

    # proximity check
    buy_cond = close_price >= (high_price - threshold * day_range)
    sell_cond = close_price <= (low_price + threshold * day_range)

    if not (buy_cond or sell_cond):
        return None

    # ATR for stoploss sizing (fallback to day_range if ATR not available)
    atr = None
    # Accept precomputed ATR column if present on daily rows
    if "atr" in d.columns:
        atr = _safe_float(today.get("atr", None))
    if atr is None:
        atr = _compute_atr(d, length=14)
    if atr is None or atr == 0:
        # fallback small percentage of price
        atr = max(day_range, max(1e-6, abs(close_price) * 0.01))

    # Risk per share (choose conservative factor)
    risk_buffer = max(1.5 * atr, abs(close_price) * 0.005)  # 1.5*ATR or 0.5% whichever larger

    if buy_cond:
        side = "BUY"
        entry = close_price  # you can switch to next_open if you want to signal execution at open
        stoploss = entry - risk_buffer
        if stoploss <= 0:
            stoploss = round(entry * 0.99, 2)  # safety fallback
        target = entry + rr * (entry - stoploss)
        exit_rule = "Target/Stop or manual exit"

    else:
        side = "SELL"
        entry = close_price
        stoploss = entry + risk_buffer
        target = entry - rr * (stoploss - entry)
        exit_rule = "Target/Stop or manual exit"

    # crude confidence: proximity + normalized ATR (smaller ATR relative to price -> higher confidence)
    proximity_score = (threshold * day_range - abs(high_price - close_price) if side == "BUY" else threshold * day_range - abs(close_price - low_price))
    # normalize proximity_score between 0 and threshold*day_range
    prox_norm = max(0.0, min(1.0, proximity_score / (threshold * day_range)))
    atr_ratio = min(1.0, (abs(close_price) / (atr + 1e-9)) / 100.0)  # lower atr -> higher ratio, scaled
    confidence = 0.4 + 0.5 * prox_norm + 0.1 * atr_ratio
    confidence = max(0.0, min(1.0, confidence))

    signal = {
        "Stock": ticker,
        "Side": side,
        "Action": "ENTER",               # clarifies what to do
        "Entry": round(float(entry), 2),
        "StopLoss": round(float(stoploss), 2),
        "Target": round(float(target), 2),
        "ExitRule": exit_rule,
        "Confidence": round(float(confidence), 2),
        "Strategy": "closing_near_highlow_refined",
        "Timestamp": datetime.now().astimezone().isoformat()
    }

    # Let pipeline decide a min confidence threshold; still return signal even if lower.
    return signal
