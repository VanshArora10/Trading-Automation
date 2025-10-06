import os
import argparse
import pytz
from datetime import datetime, time
from src.helpers import save_json, append_csv, now_ist
from src.stock_universe import build_watchlist
from src.fetch_live_data import get_multi_timeframes
from src.run_strategies import load_strategy_modules, get_required_indicators
from src.utils.telegram_alert import send_telegram_message, can_send_heartbeat, update_heartbeat


# ✅ Check if Indian market is open (Mon–Fri, 9:15 AM to 3:30 PM IST)
def is_market_open():
    ist = pytz.timezone("Asia/Kolkata")
    now = datetime.now(ist)
    return now.weekday() < 5 and time(9, 15) <= now.time() <= time(15, 30)


def run(dry_run=True, pool=None):
    # 🕘 Skip if market is closed — send notice only once per day
    if not is_market_open():
        msg = "⏸ Market closed — skipping runs outside trading hours."
        stamp_file = "output/last_closed_notice.txt"
        today = datetime.now(pytz.timezone("Asia/Kolkata")).date()

        # send only once per day
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

    # ✅ Build stock universe
    watchlist = build_watchlist(pool_tickers=pool)
    signals, strat_signals = [], {name: [] for name, _ in strategies}

    # ✅ Run all strategies across all stocks
    for t in watchlist:
        try:
            mdf = get_multi_timeframes(t, needed_indicators)
            for name, mod in strategies:
                try:
                    sig = mod.generate_signal(t, mdf)
                    print(f"DEBUG: {name} on {t} returned:", sig)
                    if sig and sig.get("Confidence", 0) >= 0.6:
                        sig["Strategy"] = sig.get("Strategy", name)
                        # add safety defaults if missing
                        sig.setdefault("StopLoss", round(sig["Entry"] * 0.985, 2))  # 1.5% stop loss
                        sig.setdefault("Target", round(sig["Entry"] * 1.015, 2))   # 1.5% target
                        signals.append(sig)
                        strat_signals[name].append(sig)
                except Exception as e:
                    print(f"ERROR in strategy {name} for {t}: {e}")
        except Exception as e:
            print(f"ERROR fetching data for {t}: {e}")

    # ✅ Deduplicate by stock + side
    unique = {}
    for s in signals:
        key = f"{s['Stock']}|{s['Side']}"
        if key not in unique or s.get("Confidence", 0) > unique[key].get("Confidence", 0):
            unique[key] = s
    final = list(unique.values())

    # ✅ Always store logs
    os.makedirs("output/strategy_logs", exist_ok=True)
    save_json(final, "output/live_signals.json")

    if signals:
        append_csv(final, "output/trade_log.csv")
        for strat_name, sigs in strat_signals.items():
            if sigs:
                append_csv(sigs, f"output/strategy_logs/{strat_name}_log.csv")

    # ✅ Telegram notification
    if not dry_run:
        if signals:
            # Build detailed message for all trades
            trade_msgs = []
            for s in final:
                msg = (
                    f"📊 *Trade Signal*\n"
                    f"🏷️ Stock: {s['Stock']}\n"
                    f"📈 Side: {s['Side']}\n"
                    f"💰 Entry: {s.get('Entry', 'N/A')}\n"
                    f"🎯 Target: {s.get('Target', 'N/A')}\n"
                    f"🛑 StopLoss: {s.get('StopLoss', 'N/A')}\n"
                    f"⚡ Confidence: {s.get('Confidence', 'N/A')}\n"
                    f"🧠 Strategy: {s['Strategy']}\n"
                    f"🕒 Time: {now_ist().strftime('%Y-%m-%d %H:%M:%S')}"
                )
                trade_msgs.append(msg)

            # Combine and send all at once
            send_telegram_message("🚀 *Trading Signals Generated!*\n\n" + "\n\n".join(trade_msgs))
        else:
            # Send "active" heartbeat once every hour only
            if can_send_heartbeat():
                send_telegram_message("⏳ No trades found yet — system active ✅")
                update_heartbeat()

    print(f"[{now_ist().isoformat()}] ✅ Signals found: {len(signals)}")
    return final


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Do not send Telegram messages")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
