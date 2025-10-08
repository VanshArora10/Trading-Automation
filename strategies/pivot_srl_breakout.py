import pandas as pd
from datetime import datetime
import pytz

STRATEGY_TYPE = "intraday"
REQUIRED_INDICATORS = []  # uses vanilla price data only

def compute_pivots(prev_day_df):
    """Compute standard pivot, resistance, support levels from previous day."""
    h = float(prev_day_df["high"].iloc[-1])
    l = float(prev_day_df["low"].iloc[-1])
    c = float(prev_day_df["close"].iloc[-1])
    pivot = (h + l + c) / 3.0
    r1 = 2 * pivot - l
    s1 = 2 * pivot - h
    r2 = pivot + (h - l)
    s2 = pivot - (h - l)
    # you can compute more levels if desired
    return pivot, r1, s1, r2, s2

def generate_signal(ticker, multi_df, rr=2.0):
    """
    Pivot / SR breakout strategy:
    - Uses daily bars for previous day to compute pivot, R/S
    - Uses intraday (e.g., 5m) bars to catch breakout above resistance or below support
    - Entry when price crosses pivot + confirmation
    """
    # Need daily for pivots
    df1 = multi_df.get("1d")
    df5 = multi_df.get("5m")
    if df1 is None or df1.empty or df5 is None or df5.empty:
        return None

    # dropna
    df1 = df1.dropna(subset=["high", "low", "close"])
    if df1.shape[0] < 2:
        return None

    # Get previous day's data (last full day)
    prev = df1.iloc[-2:]  # get last 2 days or more
    pivot, r1, s1, r2, s2 = compute_pivots(prev)

    # In intraday 5-min df, monitor breakouts
    d5 = df5.copy().rename(columns=str.lower).dropna(subset=["open", "high", "low", "close"])
    last = d5.iloc[-1]
    c = float(last["close"])

    # Breakout conditions
    long_break = c > pivot and c > r1
    short_break = c < pivot and c < s1

    side = None
    if long_break:
        side = "BUY"
    elif short_break:
        side = "SELL"
    else:
        return None

    entry = c
    # Use range (R1−S1) or distance from pivot for risk sizing
    sr_range = r1 - s1 if side == "BUY" else s1 - r1
    sl_buffer = abs(sr_range) * 0.5  # half of the pivot range
    if sl_buffer <= 0:
        return None

    if side == "BUY":
        stoploss = entry - sl_buffer
        target = entry + rr * (entry - stoploss)
    else:
        stoploss = entry + sl_buffer
        target = entry - rr * (stoploss - entry)

    # Confidence: based on how far from pivot / how wide pivot range is
    dist_from_pivot = abs(entry - pivot)
    confidence = 0.5 + 0.5 * min(dist_from_pivot / (abs(sr_range) + 1e-9), 1.0)
    confidence = max(0.0, min(1.0, confidence))

    ist = pytz.timezone("Asia/Kolkata")
    return {
        "Stock": ticker,
        "Side": side,
        "Entry": round(entry, 2),
        "StopLoss": round(stoploss, 2),
        "Target": round(target, 2),
        "Confidence": round(confidence, 2),
        "Strategy": "pivot_srl_breakout",
        "Timestamp": datetime.now(ist).isoformat(),
    }
