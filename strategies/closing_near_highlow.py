import pandas as pd
from datetime import datetime

# Strategy only needs OHLC data (no extra indicators)
REQUIRED_INDICATORS = []

def closing_near_highlow_daily(df, threshold=0.1):
    """
    Backtesting version of the strategy:
    - BUY if close is near daily high
    - SELL if close is near daily low
    - HOLD otherwise
    Exit: next day's open
    """
    signals = []
    df = df.rename(columns=str.lower)

    for i in range(len(df) - 1):  # loop until second last row
        today = df.iloc[i]
        tomorrow = df.iloc[i + 1]

        entry = {
            "date": today.name,
            "signal": "HOLD",
            "entry": today["close"]
        }

        day_range = today["high"] - today["low"]

        if day_range > 0:
            if today["close"] >= today["high"] - threshold * day_range:
                entry["signal"] = "BUY"
            elif today["close"] <= today["low"] + threshold * day_range:
                entry["signal"] = "SELL"

        if entry["signal"] in ["BUY", "SELL"]:
            entry["exit"] = tomorrow["open"]
            entry["pnl"] = (
                entry["exit"] - entry["entry"]
                if entry["signal"] == "BUY"
                else entry["entry"] - entry["exit"]
            )
        else:
            entry["exit"] = None
            entry["pnl"] = 0

        signals.append(entry)

    return pd.DataFrame(signals)


def generate_signal(ticker, multi_df, threshold=0.1):
    """
    Live-trading adapter version:
    - Uses the most recent 2 daily candles (previous and current)
    - Emits a single BUY/SELL signal if the latest bar matches the rule
    """
    df = multi_df.get("1d")
    if df is None or df.empty or len(df) < 2:
        return None

    df = df.rename(columns=str.lower)

    # Use the previous day's bar for signal generation
    today = df.iloc[-2]
    current = df.iloc[-1]

    day_range = today["high"] - today["low"]
    if day_range <= 0:
        return None

    signal_type = None
    if today["close"] >= today["high"] - threshold * day_range:
        signal_type = "BUY"
    elif today["close"] <= today["low"] + threshold * day_range:
        signal_type = "SELL"

    if not signal_type:
        return None

    signal = {
        "Stock": ticker,
        "Side": signal_type,
        "Entry": round(float(today["close"]), 2),
        "StopLoss": round(float(today["low"]) if signal_type == "BUY" else float(today["high"]), 2),
        "Target": round(float(today["close"] + (day_range * 1.5)) if signal_type == "BUY"
                        else float(today["close"] - (day_range * 1.5)), 2),
        "Confidence": 0.7,  # adjustable confidence threshold
        "Strategy": "closing_near_highlow_daily",
        "Timestamp": datetime.now().astimezone().isoformat()
    }

    return signal
