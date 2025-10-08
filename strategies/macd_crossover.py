# strategies/macd_crossover.py

import pandas as pd
from datetime import datetime

# Tell pipeline that this strategy needs these precomputed indicators
REQUIRED_INDICATORS = ["macd", "signal", "hist", "ema20", "ema50", "atr"]

def generate_signal(ticker, multi_df):
    """
    MACD crossover strategy with trend filter and volatility-based stoploss.
    - Uses precomputed indicators from fetch_live_data.py
    - Runs on 5m timeframe (intra-day)
    """

    df = multi_df.get("5m")
    if df is None or len(df) < 50:
        return None

    # Get last 2 candles for crossover
    prev, curr = df.iloc[-2], df.iloc[-1]

    # Detect MACD crossover
    buy_cross = prev["macd"] < prev["signal"] and curr["macd"] > curr["signal"]
    sell_cross = prev["macd"] > prev["signal"] and curr["macd"] < curr["signal"]

    side = None
    if buy_cross and curr["ema20"] > curr["ema50"]:
        side = "BUY"
    elif sell_cross and curr["ema20"] < curr["ema50"]:
        side = "SELL"
    else:
        return None

    entry = float(curr["close"])
    atr = float(curr["atr"])

    if side == "BUY":
        stoploss = entry - atr
        target = entry + 2 * atr
    else:
        stoploss = entry + atr
        target = entry - 2 * atr

    # Dynamic confidence score (how strong the MACD momentum is)
    hist_strength = abs(curr["hist"]) / (abs(df["hist"].iloc[-10:].mean()) + 1e-6)
    confidence = min(1.0, max(0.6, hist_strength))

    return {
        "Stock": ticker,
        "Side": side,
        "Entry": round(entry, 2),
        "StopLoss": round(stoploss, 2),
        "Target": round(target, 2),
        "Confidence": round(confidence, 2),
        "Strategy": "macd_crossover",
        "Timestamp": datetime.now().astimezone().isoformat(),
    }
