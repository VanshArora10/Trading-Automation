import pandas as pd
from datetime import datetime

# Strategy only needs OHLC, no special indicators
REQUIRED_INDICATORS = []

def closing_near_highlow_daily(df, threshold=0.1):
    """
    Daily strategy (backtest style):
    - If day's close is near high → BUY
    - If day's close is near low → SELL
    - Else HOLD
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
            if entry["signal"] == "BUY":
                entry["pnl"] = entry["exit"] - entry["entry"]
            else:
                entry["pnl"] = entry["entry"] - entry["exit"]
        else:
            entry["exit"] = None
            entry["pnl"] = 0

        signals.append(entry)

    return pd.DataFrame(signals)


def generate_signal(ticker, multi_df, threshold=0.1):
    """
    Live pipeline adapter:
    - Uses only the latest daily bar
    - Generates a one-row signal dict if condition met
    """
    df = multi_df.get("1d")
    if df is None or df.empty or len(df) < 2:
        return None

    # Use last two days: today for signal, tomorrow placeholder for exit
    today = df.iloc[-2]
    tomorrow = df.iloc[-1]

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

    # Build live signal dict
    signal = {
        "Stock": ticker,
        "Side": signal_type,
        "Entry": round(float(today["close"]), 2),
        "ExitNextOpen": round(float(tomorrow["open"]), 2),
        "Confidence": 0.7,  # static for now
        "Strategy": "closing_near_highlow_daily",
        "Timestamp": datetime.now().astimezone().isoformat()
    }

    return signal
