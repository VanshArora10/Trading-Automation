import pandas as pd
from datetime import datetime

REQUIRED_INDICATORS = []

def closing_near_highlow_daily(df, threshold=0.1):
    """
    Daily strategy:
    - If day's close is near high → BUY
    - If day's close is near low → SELL
    - Else HOLD
    Exit: next day's open
    """
    signals = []
    df = df.rename(columns=str.lower).dropna(subset=["high", "low", "close", "open"])

    for i in range(len(df) - 1):
        today = df.iloc[i]
        tomorrow = df.iloc[i + 1]

        entry_price = float(today["close"])
        high_price = float(today["high"])
        low_price = float(today["low"])
        open_price_next = float(tomorrow["open"])
        day_range = high_price - low_price

        entry = {"date": today.name, "signal": "HOLD", "entry": entry_price}

        if day_range > 0:
            if entry_price >= high_price - threshold * day_range:
                entry["signal"] = "BUY"
            elif entry_price <= low_price + threshold * day_range:
                entry["signal"] = "SELL"

        if entry["signal"] in ["BUY", "SELL"]:
            entry["exit"] = open_price_next
            entry["pnl"] = open_price_next - entry_price if entry["signal"] == "BUY" else entry_price - open_price_next
        else:
            entry["exit"] = None
            entry["pnl"] = 0

        signals.append(entry)

    return pd.DataFrame(signals)


def generate_signal(ticker, multi_df, threshold=0.1):
    """
    Live adapter:
    Uses only last two daily bars to generate a one-row signal.
    """
    df = multi_df.get("1d")
    if df is None or df.empty or len(df) < 2:
        return None

    df = df.rename(columns=str.lower).dropna(subset=["high", "low", "close", "open"])
    today = df.iloc[-2]
    tomorrow = df.iloc[-1]

    close_price = float(today["close"])
    high_price = float(today["high"])
    low_price = float(today["low"])
    open_next = float(tomorrow["open"])
    day_range = high_price - low_price

    if day_range <= 0:
        return None

    signal_type = None
    if close_price >= high_price - threshold * day_range:
        signal_type = "BUY"
    elif close_price <= low_price + threshold * day_range:
        signal_type = "SELL"

    if not signal_type:
        return None

    return {
        "Stock": ticker,
        "Side": signal_type,
        "Entry": round(close_price, 2),
        "ExitNextOpen": round(open_next, 2),
        "Confidence": 0.7,
        "Strategy": "closing_near_highlow_daily",
        "Timestamp": datetime.now().astimezone().isoformat(),
    }
