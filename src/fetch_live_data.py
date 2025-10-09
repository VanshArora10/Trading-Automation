import yfinance as yf
import pandas as pd   # ✅ ADD THIS
import pandas_ta as ta
from datetime import datetime

def get_multi_timeframes(ticker, required_indicators=None):
    """
    Fetch OHLCV data for multiple timeframes and precompute indicators.
    Supported: 1d, 1h, 5m
    Returns a dict of DataFrames with computed EMA, MACD, RSI, ATR.
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
                threads=False,
                auto_adjust=False
            )

            # ✅ Flatten MultiIndex columns if present
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [col[0].lower() for col in df.columns]
            else:
                df.columns = [col.lower() for col in df.columns]

            if df is None or df.empty:
                print(f"⚠️ No data fetched for {ticker} [{tf}]")
                continue

            # ✅ Check essential columns
            required_cols = {"open", "high", "low", "close", "volume"}
            if not required_cols.issubset(df.columns):
                print(f"⚠️ Missing essential columns for {ticker} [{tf}]: {list(df.columns)}")
                continue

            df.dropna(subset=["close"], inplace=True)
            df["time"] = df.index

            # === Indicators ===
            df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
            df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
            df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()

            df["ema12"] = df["close"].ewm(span=12, adjust=False).mean()
            df["ema26"] = df["close"].ewm(span=26, adjust=False).mean()
            df["macd"] = df["ema12"] - df["ema26"]
            df["signal"] = df["macd"].ewm(span=9, adjust=False).mean()
            df["hist"] = df["macd"] - df["signal"]

            df["rsi"] = ta.rsi(df["close"], length=14)
            df["atr"] = ta.atr(df["high"], df["low"], df["close"], length=14)

            df.dropna(inplace=True)
            data[tf] = df

        except Exception as e:
            print(f"❌ Error fetching {ticker} for {tf}: {e}")
            continue

    if not data:
        print(f"🚫 No valid timeframes available for {ticker}")
    else:
        print(f"✅ Data fetched for {ticker}: {list(data.keys())}")

    return data
