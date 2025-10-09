import os
import json
import argparse
import pytz
from datetime import datetime, time
import requests
import pandas as pd
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import yfinance as yf

# === Local imports ===
from src.helpers import save_json, append_csv, now_ist
from src.stock_universe import build_watchlist
from src.fetch_live_data import get_multi_timeframes
from src.run_strategies import load_strategy_modules, get_required_indicators
from src.utils.telegram_alert import send_telegram_message

# === Setup ===
load_dotenv()
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

# === Google Sheets ===
def send_to_google_sheets(signals):
    """Append all signals to the Google Sheet"""
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
        print(f"✅ {len(signals)} trades appended to Google Sheet.")
    except Exception as e:
        print(f"❌ Google Sheet update failed: {e}")

# === Telegram Alerts (High Confidence Only) ===
def send_high_confidence_trades(signals, min_confidence=0.8, limit=5):
    """Send only high-confidence trades to Telegram."""
    high_conf = [s for s in signals if s.get("Confidence", 0) >= min_confidence]
    if not high_conf:
        print("⚠️ No high-confidence trades to send.")
        return

    # Sort & limit
    top_signals = sorted(high_conf, key=lambda x: x["Confidence"], reverse=True)[:limit]

    msg = "🚀 *High-Confidence Trade Signals*\n\n"
    for s in top_signals:
        msg += (
            f"🏷️ {s['Stock']} ({s['Strategy']})\n"
            f"📈 *{s['Side']}* | 💰 Entry: {s['Entry']}\n"
            f"🎯 Target: {s['Target']} | 🛑 SL: {s['StopLoss']}\n"
            f"⚡ Confidence: {s.get('Confidence', 0):.2f}\n\n"
        )
    msg += f"📊 Showing top {len(top_signals)} high-confidence trades."

    try:
        send_telegram_message(msg)
        print(f"✅ Sent {len(top_signals)} high-confidence trades to Telegram.")
    except Exception as e:
        print(f"⚠️ Telegram send failed: {e}")

# === Evaluate PnL ===
def evaluate_pnl(signals):
    results = []
    for s in signals:
        try:
            df = yf.download(s["Stock"], period="1d", interval="1m", progress=False, auto_adjust=True)
            if df.empty:
                continue
            last_price = round(df["Close"].iloc[-1], 2)

            entry, target, stop, side = s["Entry"], s["Target"], s["StopLoss"], s["Side"]

            if side == "BUY":
                if last_price >= target:
                    pnl, status = ((target - entry) / entry) * 100, "Target Hit"
                elif last_price <= stop:
                    pnl, status = ((stop - entry) / entry) * 100, "SL Hit"
                else:
                    pnl, status = ((last_price - entry) / entry) * 100, "Open"
            else:  # SELL
                if last_price <= target:
                    pnl, status = ((entry - target) / entry) * 100, "Target Hit"
                elif last_price >= stop:
                    pnl, status = ((entry - stop) / entry) * 100, "SL Hit"
                else:
                    pnl, status = ((entry - last_price) / entry) * 100, "Open"

            results.append({
                "Stock": s["Stock"], "Strategy": s["Strategy"], "Side": side,
                "Result": status, "PnL%": round(pnl, 2)
            })
        except Exception as e:
            print(f"Error evaluating {s['Stock']}: {e}")
    return results

# === EOD Summary ===
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
        f"📊 *End-of-Day Summary*\n\n"
        f"✅ Target Hits: {hits}\n"
        f"❌ Stoploss Hits: {losses}\n"
        f"⏳ Open Trades: {open_trades}\n"
        f"🏆 Win Rate: {winrate}%\n"
        f"📈 Total Trades: {total}\n\n"
        f"📊 *Strategy Performance:*\n"
    )
    for strat, pnl in strat_perf.items():
        msg += f"• {strat}: {pnl}% avg PnL\n"
    msg += "\n💹 System evaluated all trades automatically."
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
    signals = []

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

                # Skip low-confidence signals
                if sig.get("Confidence", 0) < 0.3:
                    continue

                signals.append(sig)
        except Exception as e:
            print(f"Error processing {t}: {e}")

    if not signals:
        print("⚠️ No signals found.")
        return []

    save_json(signals, "output/live_signals.json")
    append_csv(signals, "output/trade_log.csv")
    send_to_google_sheets(signals)
    send_high_confidence_trades(signals, min_confidence=0.8, limit=3)

    print(f"✅ Logged {len(signals)} trades to Google Sheet.")

    # === Auto-run PnL Tracker ===
    try:
        print("\n🔁 Running automatic PnL tracker after trade generation...")
        from src.pnl_tracker import run as run_pnl
        run_pnl()
        print("✅ PnL tracker completed successfully.\n")
    except Exception as e:
        print(f"⚠️ Error running PnL tracker automatically: {e}")

    # === EOD Summary at 3:30 PM ===
    now = ist_now().time()
    if now >= time(15, 30):
        results = evaluate_pnl(signals)
        send_eod_summary(results)

    print(f"[{now_ist().isoformat()}] ✅ Signals found: {len(signals)}")
    return signals

# === Entry Point ===
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Skip Telegram messages")
    args = parser.parse_args()

    now = datetime.now(pytz.timezone("Asia/Kolkata")).time()
    if time(9, 15) <= now <= time(15, 30):
        print("📈 Market open — running trading pipeline...")
        run(dry_run=args.dry_run)
    else:
        print("⏸ Market closed — skipping trade + PnL updates.")
