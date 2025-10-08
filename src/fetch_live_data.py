import yfinance as yf
import pandas as pd
import pandas_ta as ta
from datetime import datetime

def get_multi_timeframes(ticker, required_indicators=None):
    """
    Fetches OHLCV data for multiple timeframes and precomputes key indicators.
    Supported timeframes: 1d, 1h, 5m
    Returns a dictionary of DataFrames.
    """

    intervals = {"1d": "1y", "1h": "60d", "5m": "7d"}
    data = {}

    for tf, period in intervals.items():
        try:
            df = yf.download(
                tickers=ticker,
                period=period,
                interval=tf,
                progress=False,
                threads=False
            )

            if df is None or df.empty:
                continue

            df = df.rename(columns=str.lower).dropna(subset=["close"])
            df["time"] = df.index

            # ✅ Precompute commonly used indicators
            df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
            df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
            df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()

            # MACD (12,26,9)
            df["ema12"] = df["close"].ewm(span=12, adjust=False).mean()
            df["ema26"] = df["close"].ewm(span=26, adjust=False).mean()
            df["macd"] = df["ema12"] - df["ema26"]
            df["signal"] = df["macd"].ewm(span=9, adjust=False).mean()
            df["hist"] = df["macd"] - df["signal"]

            # RSI (14)
            df["rsi"] = ta.rsi(df["close"], length=14)

            # ATR (14)
            df["atr"] = ta.atr(df["high"], df["low"], df["close"], length=14)

            df.dropna(inplace=True)
            data[tf] = df

        except Exception as e:
            print(f"Error fetching {ticker} for {tf}: {e}")
            continue

    return data
