# strategies/market_structure_orderblock.py
import math
import pandas as pd
from datetime import datetime
from typing import Optional, Dict, Any

# tell pipeline what indicators you need (helps fetcher)
REQUIRED_INDICATORS = ["atr"]

# strategy meta (used by pipeline)
STRATEGY_TYPE = "intraday"  # this runs intraday (1h-based signals)

# user-tweakable parameters
ZIGZAG_LENGTH = 9
FIB_FACTOR = 0.273
MIN_BARS = ZIGZAG_LENGTH * 2 + 5  # minimal bars to detect swings
CONFIDENCE_BASE = 0.5
MIN_MOVE_PCT_FOR_CONFIDENCE = 0.3  # 0.3% move gives some confidence boost


def _rolling_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Simple ATR (returns last ATR series). Expects columns: high, low, close."""
    high = df["high"]
    low = df["low"]
    close = df["close"]
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(period, min_periods=1).mean()
    return atr


def _find_zigzag_extrema(close: pd.Series, length: int = 9):
    """
    Very simple zigzag: mark local maxima/minima where the close is the max/min
    over a centered window of size 2*length+1.
    Returns two lists of indices: peaks, troughs
    """
    n = len(close)
    peaks = []
    troughs = []
    if n < (length * 2 + 1):
        return peaks, troughs

    # convert to numpy for speed
    arr = close.values
    for i in range(length, n - length):
        window = arr[i - length : i + length + 1]
        center = arr[i]
        if center == window.max():
            peaks.append(i)
        if center == window.min():
            troughs.append(i)
    return peaks, troughs


def generate_signal(ticker: str, multi_df: dict, zigzag_length: int = ZIGZAG_LENGTH,
                    fib_factor: float = FIB_FACTOR) -> Optional[Dict[str, Any]]:
    """
    Expects multi_df["1h"] to be a DataFrame with columns: open, high, low, close, volume (case-insensitive)
    Returns None if no valid signal found, otherwise returns a dict:
    {
      "Stock": ticker,
      "Side": "BUY" / "SELL",
      "Entry": float,
      "StopLoss": float,
      "Target": float,
      "Confidence": float (0..1),
      "Strategy": "market_structure_orderblock",
      "StrategyType": "intraday",
      "Timestamp": "..."
    }
    """

    df = multi_df.get("1h")
    if df is None or df.empty or len(df) < MIN_BARS:
        return None

    # normalize column names to lower-case
    df = df.rename(columns=str.lower).dropna(subset=["open", "high", "low", "close"])
    if df.shape[0] < MIN_BARS:
        return None

    close = df["close"]
    high = df["high"]
    low = df["low"]

    # find zigzag extrema (peaks/troughs)
    peaks, troughs = _find_zigzag_extrema(close, length=zigzag_length)
    if not peaks and not troughs:
        return None

    # choose last significant swing high and low (exclude last bar index)
    last_index = len(df) - 1

    # find last peak index strictly before last bar
    last_peak_idx = None
    for idx in reversed(peaks):
        if idx < last_index:
            last_peak_idx = idx
            break

    # find last trough index strictly before last bar
    last_trough_idx = None
    for idx in reversed(troughs):
        if idx < last_index:
            last_trough_idx = idx
            break

    # Need both a recent peak and trough to compute a zone range
    if last_peak_idx is None or last_trough_idx is None:
        return None

    peak_price = float(close.iloc[last_peak_idx])
    trough_price = float(close.iloc[last_trough_idx])

    # define range between last peak and trough
    zone_range = abs(peak_price - trough_price)
    if zone_range <= 0:
        return None

    # define green and red zones (we treat the last trough as bullish/order-block zone,
    # and the last peak as bearish/order-block zone).
    # We'll treat breakout when price moves past the zone by fib_factor * range.
    last_close = float(close.iloc[-1])
    last_open = float(df["open"].iloc[-1])

    # breakout thresholds
    buy_threshold = trough_price + fib_factor * zone_range
    sell_threshold = peak_price - fib_factor * zone_range

    # compute a risk proxy (small move percent)
    prev_close = float(close.iloc[-2])
    move_pct = (last_close - prev_close) / (prev_close + 1e-9) * 100.0

    # ATR for sizing / confidence
    try:
        atr = float(_rolling_atr(df, period=14).iloc[-1])
    except Exception:
        atr = zone_range * 0.01 if zone_range > 0 else 1.0

    # decide signal
    side = None
    entry_price = None
    stoploss = None
    target = None

    # BUY: price breaks above recent trough/order-block zone
    if last_close > buy_threshold:
        side = "BUY"
        entry_price = last_close
        # Stoploss = trough price (conservative)
        stoploss = trough_price
        # risk = entry - stoploss
        risk = max(0.0001, entry_price - stoploss)
        target = round(entry_price + 2.0 * risk, 4)

    # SELL: price breaks below recent peak/order-block zone
    elif last_close < sell_threshold:
        side = "SELL"
        entry_price = last_close
        stoploss = peak_price
        risk = max(0.0001, stoploss - entry_price)
        target = round(entry_price - 2.0 * risk, 4)

    if side is None:
        return None

    # Confidence: base plus small boost if recent move is significant relative to ATR or % move
    conf = CONFIDENCE_BASE
    # boost by move_pct (normalized)
    conf += min(0.45, abs(move_pct) / max(1.0, MIN_MOVE_PCT_FOR_CONFIDENCE * 10.0))
    # boost if breakout distance bigger than small multiple of ATR
    breakout_dist = abs(entry_price - (trough_price if side == "BUY" else peak_price))
    if atr > 0:
        conf += min(0.35, breakout_dist / (atr * 4.0))

    conf = max(0.0, min(1.0, conf))

    signal = {
        "Stock": ticker,
        "Side": side,
        "Entry": round(entry_price, 4),
        "StopLoss": round(stoploss, 4),
        "Target": round(target, 4),
        "Confidence": round(conf, 2),
        "Strategy": "market_structure_orderblock",
        "StrategyType": "intraday",
        "Timestamp": datetime.now().astimezone().isoformat(),
        "Notes": {
            "last_peak_idx": int(last_peak_idx),
            "last_trough_idx": int(last_trough_idx),
            "peak_price": round(peak_price, 4),
            "trough_price": round(trough_price, 4),
            "zone_range": round(zone_range, 4),
            "buy_threshold": round(buy_threshold, 4),
            "sell_threshold": round(sell_threshold, 4),
            "atr": round(atr, 6),
            "last_close": round(last_close, 4),
            "move_pct": round(move_pct, 4),
        },
    }

    return signal
