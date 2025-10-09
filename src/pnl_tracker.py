import os
import json
import pandas as pd
import pytz
from datetime import datetime, time
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import yfinance as yf

# === Load environment ===
load_dotenv()

SHEET_ID = os.getenv("SHEET_ID")
SHEET_NAME = os.getenv("SHEET_NAME")
SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

# === Google Sheets Auth ===
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
service = build("sheets", "v4", credentials=creds)
sheet = service.spreadsheets()

# === Fetch data safely ===
def fetch_signals():
    result = sheet.values().get(
        spreadsheetId=SHEET_ID,
        range=f"{SHEET_NAME}!A2:M"
    ).execute()

    values = result.get("values", [])
    if not values:
        return pd.DataFrame()

    # Define columns dynamically
    base_cols = [
        "Timestamp", "Stock", "Side", "Entry", "Target", "Stoploss",
        "Confidence", "Strategy", "StrategyType"
    ]
    extra_cols = ["LivePrice", "Result", "PnL%", "Status"]
    all_cols = base_cols + extra_cols

    # Fill missing columns if sheet has fewer
    for row in values:
        while len(row) < len(all_cols):
            row.append("")

    df = pd.DataFrame(values, columns=all_cols)

    # Convert numeric fields
    for col in ["Entry", "Target", "Stoploss", "Confidence", "LivePrice"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


# === Fetch latest live price ===
def fetch_live_price(symbol):
    try:
        df = yf.download(symbol, period="1d", interval="1m", progress=False)
        return round(df["Close"].iloc[-1], 2)
    except Exception as e:
        print(f"Error fetching {symbol}: {e}")
        return None


# === Evaluate live trade performance ===
def evaluate(df):
    live_prices = []

    # Fetch latest price for each stock
    for symbol in df["Stock"]:
        price = fetch_live_price(symbol)
        if isinstance(price, (list, pd.Series)):
            price = float(price[-1]) if len(price) > 0 else float("nan")
        live_prices.append(price if price is not None else float("nan"))

    df["LivePrice"] = pd.to_numeric(live_prices, errors="coerce")

    def compute(row):
        try:
            lp = float(row["LivePrice"])
            entry = float(row["Entry"])
            target = float(row["Target"])
            stop = float(row["Stoploss"])
            side = str(row["Side"]).upper()
        except Exception:
            return "Open", 0.0

        if pd.isna(lp) or lp == 0:
            return "Open", 0.0

        if side == "BUY":
            if lp >= target:
                pnl = ((target - entry) / entry) * 100
                return "Target Hit", pnl
            elif lp <= stop:
                pnl = ((stop - entry) / entry) * 100
                return "SL Hit", pnl
            else:
                pnl = ((lp - entry) / entry) * 100
                return "Open", pnl
        elif side == "SELL":
            if lp <= target:
                pnl = ((entry - target) / entry) * 100
                return "Target Hit", pnl
            elif lp >= stop:
                pnl = ((entry - stop) / entry) * 100
                return "SL Hit", pnl
            else:
                pnl = ((entry - lp) / entry) * 100
                return "Open", pnl
        else:
            return "Open", 0.0

    df[["Result", "PnL%"]] = df.apply(lambda x: pd.Series(compute(x)), axis=1)

    # Round PnL% to 2 decimals
    df["PnL%"] = df["PnL%"].round(2)

    return df


# === Update back to Google Sheet ===
def update_sheet(df):
    rows = df[["LivePrice", "Result", "PnL%"]].fillna("").astype(str).values.tolist()
    sheet.values().update(
        spreadsheetId=SHEET_ID,
        range=f"{SHEET_NAME}!J2:L{len(rows)+1}",
        valueInputOption="RAW",
        body={"values": rows}
    ).execute()


# === Telegram summary ===
def send_summary(df):
    from src.utils.telegram_alert import send_telegram_message

    total = len(df)
    hits = len(df[df["Result"] == "Target Hit"])
    losses = len(df[df["Result"] == "SL Hit"])
    open_trades = len(df[df["Result"] == "Open"])
    winrate = round((hits / (hits + losses)) * 100, 2) if (hits + losses) > 0 else 0

    msg = (
        f"📊 *EOD Trading Summary*\n\n"
        f"✅ *Profitable Trades (Target Hit):* {hits}\n"
        f"❌ *Losing Trades (Stoploss Hit):* {losses}\n"
        f"⏳ *Open Trades:* {open_trades}\n"
        f"🏆 *Win Rate:* {winrate}%\n"
        f"📈 *Total Trades Tracked:* {total}\n\n"
        f"Good job today, keep the system running strong 💪"
    )
    send_telegram_message(msg)


# === Main runner ===
def run():
    df = fetch_signals()
    if df.empty:
        print("⚠️ No trades found in Google Sheet.")
        return

    df = evaluate(df)
    update_sheet(df)
    print("✅ Sheet updated with live PnL & status.")

    now = datetime.now(pytz.timezone("Asia/Kolkata")).time()
    # Send Telegram summary only after 3:30 PM
    if now >= time(15, 30):
        send_summary(df)


if __name__ == "__main__":
    run()
