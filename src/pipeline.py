import os
import requests
import argparse
from datetime import datetime, time
from src.helpers import save_json, append_csv, now_ist
from src.stock_universe import build_watchlist
from src.fetch_live_data import get_multi_timeframes
from src.run_strategies import load_strategy_modules, get_required_indicators
from src.utils.telegram_alert import send_telegram_message, can_send_heartbeat, update_heartbeat


# ✅ Check Indian market open hours (Mon–Fri, 9:15 AM–3:30 PM IST)
def is_market_open():
    now = now_ist()
    current_time = now.time()
    market_open = time(9, 15)
    market_close = time(15, 30)
    # Monday = 0, Sunday = 6
    return now.weekday() < 5 and market_open <= current_time <= market_close


def run(dry_run=True, pool=None):
    # 🕘 Skip execution if market closed
    if not is_market_open():
        msg = "⏸ Market closed — skipping this run."
        print(msg)
        send_telegram_message(msg)
        return []

    print("DEBUG: Loading strategies...")
    strategies = load_strategy_modules()
    print("DEBUG: Strategies loaded:", [name for name, _ in strategies])
    needed_indicators = get_required_indicators(strategies)

    watchlist = build_watchlist(pool_tickers=pool)
    signals = []
    strat_signals = {name: [] for name, _ in strategies}

    for t in watchlist:
        try:
            mdf = get_multi_timeframes(t, needed_indicators)
            for name, mod in strategies:
                try:
                    sig = mod.generate_signal(t, mdf)
                    print(f"DEBUG: {name} on {t} returned:", sig)
                    if sig and sig.get("Confidence", 0) >= 0.6:
                        sig["Strategy"] = sig.get("Strategy", name)
                        signals.append(sig)
                        strat_signals[name].append(sig)
                except Exception as e:
                    print(f"ERROR in strategy {name} for {t}: {e}")
                    continue
        except Exception as e:
            print(f"ERROR fetching data for {t}: {e}")
            continue

    # Deduplicate by ticker + side
    unique = {}
    for s in signals:
        key = f"{s['Stock']}|{s['Side']}"
        if key not in unique or s.get("Confidence", 0) > unique[key].get("Confidence", 0):
            unique[key] = s
    final = list(unique.values())

    # Always save JSON (even if empty)
    if not final:
        final = [{"Message": "No trades found"}]
        if can_send_heartbeat():
            send_telegram_message("⏳ No trades found yet — bot active ✅")
            update_heartbeat()

    save_json(final, "output/live_signals.json")

    if signals:
        append_csv(final, "output/trade_log.csv")

    os.makedirs("output/strategy_logs", exist_ok=True)
    for strat_name, sigs in strat_signals.items():
        if sigs:
            append_csv(sigs, f"output/strategy_logs/{strat_name}_log.csv")

    # ✅ Telegram alerts
    if not dry_run:
        if signals:
            send_telegram_message(f"🚀 {len(signals)} trading signals generated successfully!")
        else:
            import random
            if random.random() < 0.3:
                send_telegram_message("⚠️ No trading signals found this run, but the pipeline executed fine.")

    print(f"[{now_ist().isoformat()}] Signals found: {len(signals)}")
    return final


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Do not send Telegram messages")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
