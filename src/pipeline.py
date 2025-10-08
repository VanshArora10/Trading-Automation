import os
import requests
import json
import argparse
import pytz
from datetime import datetime, time
from src.helpers import save_json, append_csv, now_ist
from src.stock_universe import build_watchlist
from src.fetch_live_data import get_multi_timeframes
from src.run_strategies import load_strategy_modules, get_required_indicators
from src.utils.telegram_alert import (
    send_telegram_message,
    can_send_heartbeat,
    update_heartbeat,
)

# === Tracking files ===
LAST_DAILY_SIGNAL_FILE = "output/last_daily_signal.txt"
LAST_INTRADAY_FILE = "output/last_intraday_signals.json"


# === Utility functions ===
def ist_now():
    return datetime.now(pytz.timezone("Asia/Kolkata"))


def already_sent_today():
    """Check if daily strategy alert was already sent"""
    today = ist_now().date()
    if os.path.exists(LAST_DAILY_SIGNAL_FILE):
        with open(LAST_DAILY_SIGNAL_FILE, "r") as f:
            if f.read().strip() == str(today):
                return True
    return False


def mark_daily_sent_today():
    """Mark that daily signals were sent today"""
    today = ist_now().date()
    os.makedirs("output", exist_ok=True)
    with open(LAST_DAILY_SIGNAL_FILE, "w") as f:
        f.write(str(today))


def is_market_open():
    """Indian market open hours (Mon–Fri, 9:15–15:30 IST)"""
    now = ist_now()
    return now.weekday() < 5 and time(9, 15) <= now.time() <= time(15, 30)


def load_last_intraday_signals():
    """Load previously sent intraday signals (avoid repeat alerts)"""
    if os.path.exists(LAST_INTRADAY_FILE):
        try:
            with open(LAST_INTRADAY_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_intraday_signals(sent_dict):
    """Save sent intraday signals"""
    os.makedirs("output", exist_ok=True)
    with open(LAST_INTRADAY_FILE, "w") as f:
        json.dump(sent_dict, f, indent=2)


def send_to_google_sheets(signals):
    """Send trade signals to Google Sheets via webhook"""
    sheet_url = os.getenv("SHEET_WEBHOOK_URL")
    if not sheet_url:
        print("⚠️ Google Sheet webhook URL not set. Skipping sheet upload.")
        return

    try:
        resp = requests.post(sheet_url, json=signals, timeout=10)
        if resp.status_code == 200:
            print("✅ Uploaded to Google Sheets successfully.")
        else:
            print(f"⚠️ Google Sheet upload failed: {resp.status_code} - {resp.text}")
    except Exception as e:
        print("❌ Error sending to Google Sheets:", e)


# === Main runner ===
def run(dry_run=True, pool=None):
    # Skip runs outside market hours
    if not is_market_open():
        msg = "⏸ Market closed — skipping runs outside trading hours."
        stamp_file = "output/last_closed_notice.txt"
        today = ist_now().date()
        if not os.path.exists(stamp_file) or open(stamp_file).read().strip() != str(today):
            send_telegram_message(msg)
            with open(stamp_file, "w") as f:
                f.write(str(today))
        else:
            print("Market closed — already notified today.")
        return []

    print("DEBUG: Loading strategies...")
    strategies = load_strategy_modules()
    print("DEBUG: Strategies loaded:", [name for name, _ in strategies])
    needed_indicators = get_required_indicators(strategies)

    # Build watchlist
    watchlist = build_watchlist(pool_tickers=pool)
    signals, strat_signals = [], {name: [] for name, _ in strategies}

    # Load previously sent intraday alerts
    sent_intraday = load_last_intraday_signals()
    today_key = str(ist_now().date())
    if today_key not in sent_intraday:
        sent_intraday[today_key] = []

    # Run all strategies
    for t in watchlist:
        try:
            mdf = get_multi_timeframes(t, needed_indicators)
            for name, mod in strategies:
                try:
                    sig = mod.generate_signal(t, mdf)
                    if not sig:
                        continue

                    sig["Strategy"] = sig.get("Strategy", name)
                    sig.setdefault("StrategyType", getattr(mod, "STRATEGY_TYPE", "daily"))
                    sig.setdefault("StopLoss", round(sig["Entry"] * 0.985, 2))
                    sig.setdefault("Target", round(sig["Entry"] * 1.015, 2))

                    if sig.get("Confidence", 0) < 0.6:
                        continue

                    signals.append(sig)
                    strat_signals[name].append(sig)
                except Exception as e:
                    print(f"ERROR in {name} for {t}: {e}")
        except Exception as e:
            print(f"ERROR fetching data for {t}: {e}")

    # Deduplicate by stock + side
    unique = {}
    for s in signals:
        key = f"{s['Stock']}|{s['Side']}"
        if key not in unique or s["Confidence"] > unique[key]["Confidence"]:
            unique[key] = s
    final = list(unique.values())

    # Save logs locally
    os.makedirs("output/strategy_logs", exist_ok=True)
    save_json(final, "output/live_signals.json")

    if signals:
        append_csv(final, "output/trade_log.csv")
        for strat_name, sigs in strat_signals.items():
            if sigs:
                append_csv(sigs, f"output/strategy_logs/{strat_name}_log.csv")

    # === Telegram & Google Sheets ===
    if not dry_run:
        daily_signals = [s for s in final if s["StrategyType"] == "daily"]
        intraday_signals = [s for s in final if s["StrategyType"] == "intraday"]

        # --- DAILY ---
        if daily_signals and not already_sent_today():
            msgs = []
            for s in daily_signals:
                msgs.append(
                    f"📊 *Daily Signal*\n🏷️ {s['Stock']}\n📈 {s['Side']}\n"
                    f"💰 Entry: {s['Entry']}\n🎯 Target: {s['Target']}\n🛑 StopLoss: {s['StopLoss']}\n"
                    f"⚡ Confidence: {s['Confidence']}\n🧠 {s['Strategy']}"
                )
            send_telegram_message("🚀 *Daily Trading Signals!*\n\n" + "\n\n".join(msgs))
            send_to_google_sheets(daily_signals)
            mark_daily_sent_today()

        # --- INTRADAY ---
        new_intraday = []
        for s in intraday_signals:
            key = f"{s['Stock']}|{s['Side']}|{s['Strategy']}"
            if key not in sent_intraday[today_key]:
                new_intraday.append(s)
                sent_intraday[today_key].append(key)

        if new_intraday:
            msgs = []
            for s in new_intraday:
                msgs.append(
                    f"⚡ *Intraday Signal*\n🏷️ {s['Stock']}\n📈 {s['Side']}\n"
                    f"💰 Entry: {s['Entry']}\n🎯 Target: {s['Target']}\n🛑 StopLoss: {s['StopLoss']}\n"
                    f"⚡ Confidence: {s['Confidence']}\n🧠 {s['Strategy']}"
                )
            send_telegram_message("\n\n".join(msgs))
            send_to_google_sheets(new_intraday)
            save_intraday_signals(sent_intraday)

        # --- HEARTBEAT ---
        if not signals and can_send_heartbeat():
            send_telegram_message("⏳ No trades found yet — system active ✅")
            update_heartbeat()

    print(f"[{now_ist().isoformat()}] ✅ Signals found: {len(signals)}")
    return final


# === Entry point ===
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Do not send Telegram messages")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
