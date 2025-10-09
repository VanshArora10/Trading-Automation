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
sheet = None

if not SERVICE_ACCOUNT_FILE or not os.path.exists(SERVICE_ACCOUNT_FILE):
    print("⚠️ Service account file not found — Google Sheet update skipped.")
else:
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    service = build("sheets", "v4", credentials=creds)
    sheet = service.spreadsheets()
    print("✅ Google Sheets API authenticated successfully.")


# === Fetch data safely ===
def fetch_signals():
    if sheet is None:
        print("⚠️ Google Sheet client not initialized.")
        return pd.DataFrame()

    try:
        result = sheet.values().get(
            spreadsheetId=SHEET_ID,
            range=f"{SHEET_NAME}!A2:M"
        ).execute()
    except Exception as e:
        print(f"❌ Error reading sheet: {e}")
        return pd.DataFrame()

    values = result.get("values", [])
    if not values:
        print("⚠️ No values found in Google Sheet.")
        return pd.DataFrame()

    base_cols = [
        "Timestamp", "Stock", "Side", "Entry", "Target", "Stoploss",
        "Confidence", "Strategy", "StrategyType"
    ]
    extra_cols = ["LivePrice", "Result", "PnL%", "Status"]
    all_cols = base_cols + extra_cols

    # Pad rows
    for row in values:
        while len(row) < len(all_cols):
            row.append("")

    df = pd.DataFrame(values, columns=all_cols)
    for col in ["Entry", "Target", "Stoploss", "Confidence", "LivePrice"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


# === Fetch latest live price ===
def fetch_live_price(symbol):
    try:
        data = yf.download(symbol, period="1d", interval="1m", progress=False)
        if data.empty:
            print(f"⚠️ No data for {symbol}")
            return None
        return round(data["Close"].iloc[-1], 2)
    except Exception as e:
        print(f"❌ Error fetching {symbol}: {e}")
        return None


# === Evaluate live trade performance ===
def evaluate(df):
    print("📊 Evaluating live PnL for trades...")

    live_prices = []
    for symbol in df["Stock"]:
        try:
            data = yf.download(symbol, period="1d", interval="1m", progress=False)
            if data.empty:
                print(f"⚠️ No data for {symbol}, setting LivePrice = NaN")
                live_prices.append(float("nan"))
                continue

            # Extract last closing price safely
            last_price = data["Close"].iloc[-1]
            if isinstance(last_price, (pd.Series, list)):
                last_price = float(last_price[-1])
            live_prices.append(round(float(last_price), 2))

        except Exception as e:
            print(f"❌ Error fetching {symbol}: {e}")
            live_prices.append(float("nan"))

    # ✅ Ensure it's a flat numeric list
    if len(live_prices) != len(df):
        print(f"⚠️ Mismatch in data lengths ({len(live_prices)} vs {len(df)}). Padding with NaN.")
        while len(live_prices) < len(df):
            live_prices.append(float("nan"))

    df["LivePrice"] = pd.to_numeric(pd.Series(live_prices), errors="coerce")

    # === Compute PnL & Status ===
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
                return "Target Hit", ((target - entry) / entry) * 100
            elif lp <= stop:
                return "SL Hit", ((stop - entry) / entry) * 100
            else:
                return "Open", ((lp - entry) / entry) * 100
        elif side == "SELL":
            if lp <= target:
                return "Target Hit", ((entry - target) / entry) * 100
            elif lp >= stop:
                return "SL Hit", ((entry - stop) / entry) * 100
            else:
                return "Open", ((entry - lp) / entry) * 100
        return "Open", 0.0

    df[["Result", "PnL%"]] = df.apply(lambda x: pd.Series(compute(x)), axis=1)
    df["PnL%"] = df["PnL%"].round(2)

    print("✅ PnL evaluation completed successfully.")
    return df



# === Update back to Google Sheet ===
def update_sheet(df):
    if sheet is None:
        print("⚠️ Google Sheet client not available.")
        return

    try:
        rows = df[["LivePrice", "Result", "PnL%"]].fillna("").astype(str).values.tolist()
        sheet.values().update(
            spreadsheetId=SHEET_ID,
            range=f"{SHEET_NAME}!J2:L{len(rows)+1}",
            valueInputOption="RAW",
            body={"values": rows}
        ).execute()
        print(f"✅ Updated {len(rows)} rows in Google Sheet with PnL data.")
    except Exception as e:
        print(f"❌ Error updating Google Sheet: {e}")


# === Telegram summary ===
def send_summary(df):
    from src.utils.telegram_alert import send_telegram_message

    total = len(df)
    hits = len(df[df["Result"] == "Target Hit"])
    losses = len(df[df["Result"] == "SL Hit"])
    open_trades = len(df[df["Result"] == "Open"])
    winrate = round((hits / (hits + losses)) * 100, 2) if (hits + losses) > 0 else 0

    msg = (
        f"📊 *End-of-Day Trading Summary*\n\n"
        f"✅ *Target Hits:* {hits}\n"
        f"❌ *Stoploss Hits:* {losses}\n"
        f"⏳ *Open Trades:* {open_trades}\n"
        f"🏆 *Win Rate:* {winrate}%\n"
        f"📈 *Total Trades:* {total}\n\n"
        f"🧠 *Performance looks great! Keep monitoring tomorrow.*"
    )
    send_telegram_message(msg)
    print("✅ Telegram summary sent successfully.")


# === Main runner ===
def run():
    df = fetch_signals()
    if df.empty:
        print("⚠️ No trades found in Google Sheet.")
        return

    df = evaluate(df)
    update_sheet(df)

    now = datetime.now(pytz.timezone("Asia/Kolkata")).time()
    if now >= time(15, 30):
        send_summary(df)
    else:
        print("⏳ Market open — skipping EOD summary for now.")


if __name__ == "__main__":
    run()
