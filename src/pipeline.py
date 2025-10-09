import os
import json
import argparse
import pytz
from datetime import datetime, time
import requests
import pandas as pd
from dotenv import load_dotenv
from src.helpers import save_json, append_csv, now_ist
from src.stock_universe import build_watchlist
from src.fetch_live_data import get_multi_timeframes
from src.run_strategies import load_strategy_modules, get_required_indicators
from src.utils.telegram_alert import send_telegram_message, can_send_heartbeat, update_heartbeat
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import yfinance as yf

load_dotenv()

# === Google Sheet Setup ===
SHEET_ID = os.getenv("SHEET_ID")
SHEET_NAME = os.getenv("SHEET_NAME")
SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
sheet = build("sheets", "v4", credentials=creds).spreadsheets()

# === Utility ===
def ist_now():
    return datetime.now(pytz.timezone("Asia/Kolkata"))

def is_market_open():
    now = ist_now()
    return now.weekday() < 5 and time(9, 15) <= now.time() <= time(15, 30)

# === Send to Google Sheet ===
def send_to_google_sheets(signals):
    if not signals:
        return
    rows = [
        [
            s.get("Timestamp", ist_now().strftime("%d/%m/%Y %H:%M:%S")),
            s["Stock"], s["Side"], s["Entry"], s["Target"], s["StopLoss"],
            s.get("Confidence", ""), s["Strategy"], s["StrategyType"]
        ]
        for s in signals
    ]
    try:
        sheet.values().append(
            spreadsheetId=SHEET_ID,
            range=f"{SHEET_NAME}!A2",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": rows}
        ).execute()
        print("✅ Trades appended to Google Sheet.")
    except Exception as e:
        print(f"❌ Google Sheet update failed: {e}")

# === PnL Evaluation ===
def evaluate_pnl(signals):
    results = []
    for s in signals:
        symbol = s["Stock"]
        side = s["Side"]
        entry = s["Entry"]
        target = s["Target"]
        stop = s["StopLoss"]
        strategy = s["Strategy"]
        try:
            df = yf.download(symbol, period="1d", interval="1m", progress=False)
            if df.empty:
                continue
            last_price = round(df["Close"].iloc[-1], 2)

            if side == "BUY":
                if last_price >= target:
                    pnl = round(((target - entry) / entry) * 100, 2)
                    status = "Target Hit"
                elif last_price <= stop:
                    pnl = round(((stop - entry) / entry) * 100, 2)
                    status = "SL Hit"
                else:
                    pnl = round(((last_price - entry) / entry) * 100, 2)
                    status = "Open"
            else:  # SELL
                if last_price <= target:
                    pnl = round(((entry - target) / entry) * 100, 2)
                    status = "Target Hit"
                elif last_price >= stop:
                    pnl = round(((entry - stop) / entry) * 100, 2)
                    status = "SL Hit"
                else:
                    pnl = round(((entry - last_price) / entry) * 100, 2)
                    status = "Open"

            results.append({
                "Stock": symbol,
                "Strategy": strategy,
                "Side": side,
                "Result": status,
                "PnL%": pnl
            })
        except Exception as e:
            print(f"Error evaluating {symbol}: {e}")
    return results

# === Telegram EOD Summary ===
def send_eod_summary(results):
    if not results:
        send_telegram_message("⚠️ No trades today to evaluate.")
        return

    df = pd.DataFrame(results)
    total = len(df)
    hits = len(df[df["Result"] == "Target Hit"])
    losses = len(df[df["Result"] == "SL Hit"])
    open_trades = len(df[df["Result"] == "Open"])
    winrate = round((hits / (hits + losses)) * 100, 2) if (hits + losses) > 0 else 0

    strat_perf = (
        df.groupby("Strategy")["PnL%"]
        .mean()
        .sort_values(ascending=False)
        .round(2)
        .to_dict()
    )

    msg = (
        f"📊 *End of Day Trading Summary*\n\n"
        f"✅ *Target Hits:* {hits}\n"
        f"❌ *Stoploss Hits:* {losses}\n"
        f"⏳ *Open Trades:* {open_trades}\n"
        f"🏆 *Win Rate:* {winrate}%\n"
        f"📈 *Total Trades:* {total}\n\n"
        f"📊 *Strategy Performance:*\n"
    )

    for strat, pnl in strat_perf.items():
        msg += f"• {strat}: {pnl}% avg PnL\n"

    msg += "\n💹 Great work today! System evaluated all trades automatically."
    send_telegram_message(msg)
    print("✅ Telegram EOD summary sent.")


# === Main Runner ===
def run(dry_run=True, pool=None):
    if not is_market_open():
        print("⏸ Market closed — skipping automation run.")
        return []

    print("⚙️ Loading strategies...")
    strategies = load_strategy_modules()
    needed_indicators = get_required_indicators(strategies)

    watchlist = build_watchlist(pool_tickers=pool)
    signals, strat_signals = [], {name: [] for name, _ in strategies}

    for t in watchlist:
        try:
            mdf = get_multi_timeframes(t, needed_indicators)
            for name, mod in strategies:
                sig = mod.generate_signal(t, mdf)
                if not sig:
                    continue

                sig["Strategy"] = sig.get("Strategy", name)
                sig.setdefault("StrategyType", getattr(mod, "STRATEGY_TYPE", "daily"))
                sig.setdefault("StopLoss", round(sig["Entry"] * 0.985, 2))
                sig.setdefault("Target", round(sig["Entry"] * 1.015, 2))
                sig["Timestamp"] = ist_now().strftime("%d/%m/%Y %H:%M:%S")

                # Confidence filter
                if sig.get("Confidence", 0) < 0.4:
                    continue

                signals.append(sig)
                strat_signals[name].append(sig)

        except Exception as e:
            print(f"Error fetching {t}: {e}")

    if not signals:
        print("⚠️ No signals found.")
        return []

    # === Save and Send to Sheet ===
    save_json(signals, "output/live_signals.json")
    append_csv(signals, "output/trade_log.csv")
    send_to_google_sheets(signals)
    print(f"✅ Logged {len(signals)} trades to Google Sheets.")

    # === End-of-Day Evaluation ===
    now = ist_now().time()
    if now >= time(15, 30):
        results = evaluate_pnl(signals)
        send_eod_summary(results)

    print(f"[{now_ist().isoformat()}] ✅ Signals found: {len(signals)}")
    return signals


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Do not send Telegram messages")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
