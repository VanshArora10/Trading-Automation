import pandas as pd
from datetime import datetime, time
import pytz

# Tag so pipeline can detect behavior
STRATEGY_TYPE = "intraday"

# No external indicator dependencies
REQUIRED_INDICATORS = []

def generate_signal(ticker, multi_df, threshold_vol=1.2, rr=2.0):
    """
    ORB + Trend Filter strategy.
    - Use 5m timeframe data in multi_df["5m"]
    - First 9:15–9:30 interval defines OR range
    - After that, breakout entry
    - Apply trend filter via 20 EMA vs 50 EMA
    - One signal per stock per day (handled by pipeline dedupe)
    Returns dict with keys: Stock, Side, Entry, StopLoss, Target, Confidence, Strategy, Timestamp
    """

    df = multi_df.get("5m")
    if df is None or df.empty:
        return None

    # Convert to a working copy
    d = df.copy().rename(columns=str.lower)
    # Drop missing
    d = d.dropna(subset=["open", "high", "low", "close", "volume"])
    n = len(d)
    if n < 10:
        return None

    # Timezone assumption: multi_df timestamps are in IST or local matching your pipeline
    # Identify the opening range period: between 9:15 and 9:30 AM
    ist = pytz.timezone("Asia/Kolkata")
    def is_in_or_period(ts):
        t = ts.astimezone(ist).time()
        return time(9, 15) <= t < time(9, 30)

    or_rows = d[d.index.map(is_in_or_period)]
    if or_rows.empty:
        return None

    # Determine OR high/low
    or_high = float(or_rows["high"].max())
    or_low = float(or_rows["low"].min())

    # After 9:30, check next bars
    # Use data after OR period
    post_or = d[d.index.map(lambda ts: ts.astimezone(ist).time() >= time(9, 30))]
    if post_or.empty:
        return None

    # Use the most recent bar for breakout test
    last = post_or.iloc[-1]
    close = float(last["close"])
    high = float(last["high"])
    low = float(last["low"])
    vol = float(last["volume"])

    # Trend filter: compute EMAs on full df
    d["ema20"] = d["close"].ewm(span=20, adjust=False).mean()
    d["ema50"] = d["close"].ewm(span=50, adjust=False).mean()

    last_ema20 = float(d["ema20"].iloc[-1])
    last_ema50 = float(d["ema50"].iloc[-1])

    # Determine breakout
    long_break = close > or_high
    short_break = close < or_low

    # Enforce trend filter
    if long_break and not (last_ema20 > last_ema50):
        return None
    if short_break and not (last_ema20 < last_ema50):
        return None

    side = "BUY" if long_break else ("SELL" if short_break else None)
    if side is None:
        return None

    entry = close  # entry at close of breakout bar
    # risk sizing: difference to the OR boundary
    if side == "BUY":
        risk = entry - or_low
        stoploss = or_low
        target = entry + rr * risk
    else:
        risk = or_high - entry
        stoploss = or_high
        target = entry - rr * risk

    if risk <= 0:
        return None

    # Confidence score: combine trend strength + volume ratio
    # volume ratio = vol / average volume of OR period
    avg_vol_or = or_rows["volume"].mean() if len(or_rows) > 0 else 1
    vol_ratio = vol / (avg_vol_or + 1e-9)

    # Trend strength factor = abs(ema20 - ema50) / ema50
    trend_strength = abs(last_ema20 - last_ema50) / (last_ema50 + 1e-9)

    # Confidence formula (tune coefficients)
    confidence = 0.5 + 0.3 * min(vol_ratio, 2.0) + 0.2 * min(trend_strength * 100, 1.0)
    # Cap between 0 and 1
    confidence = max(0.0, min(1.0, confidence))

    signal = {
        "Stock": ticker,
        "Side": side,
        "Entry": round(entry, 2),
        "StopLoss": round(stoploss, 2),
        "Target": round(target, 2),
        "Confidence": round(confidence, 2),
        "Strategy": "orb_trend_filter",
        "Timestamp": datetime.now(ist).isoformat()
    }

    return signal
