# src/fetch_live_data.py
import yfinance as yf
import pandas as pd
import pandas_ta as ta
from datetime import datetime
import pytz

IST = pytz.timezone("Asia/Kolkata")

def to_ist(dt):
    if dt.tzinfo is None:
        return IST.localize(dt)
    return dt.astimezone(IST)

def get_ohlcv(ticker, period="7d", interval="5m"):
    """
    Returns a pandas DataFrame with DatetimeIndex in IST and columns: open, high, low, close, volume
    """
    df = yf.download(tickers=ticker, period=period, interval=interval, progress=False, threads=False)
    if df.empty:
        return df

    # Fix: handle tz-naive index
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC").tz_convert(IST)
    else:
        df.index = df.index.tz_convert(IST)

    df = df.rename(columns={
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume"
    })
    return df

def add_indicators(df, needed):
    """
    Add only the indicators listed in 'needed' (set or list).
    """
    if df.empty:
        return df

    if "atr" in needed:
        df["atr"] = ta.atr(df["high"], df["low"], df["close"], length=14)
    if "ema21" in needed:
        df["ema21"] = ta.ema(df["close"], length=21)
    if "ema50" in needed:
        df["ema50"] = ta.ema(df["close"], length=50)
    if "rsi14" in needed:
        df["rsi14"] = ta.rsi(df["close"], length=14)
    if "sma200" in needed:
        df["sma200"] = ta.sma(df["close"], length=200)
    # 👉 add more indicators here as needed

    return df

def get_multi_timeframes(ticker, needed_indicators):
    """
    Return dict with 5m, 15m, 30m, 1d DataFrames (with only required indicators)
    """
    ret = {}
    for tf, period in [("5m", "7d"), ("15m", "14d"), ("30m", "30d"), ("1d", "6mo")]:
        df = get_ohlcv(ticker, period=period, interval=tf)
        df = add_indicators(df, needed_indicators)
        ret[tf] = df
    return ret
