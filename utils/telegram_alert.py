# src/utils/telegram_alert.py
import os
import requests
from datetime import datetime, timedelta, timezone

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Store last heartbeat timestamp in a file (to limit "no trade" messages)
HEARTBEAT_FILE = "output/last_heartbeat.txt"

def send_telegram_message(text):
    """Send a Telegram message using bot token and chat ID"""
    if not BOT_TOKEN or not CHAT_ID:
        print("⚠️ Telegram not configured properly.")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text}
    try:
        resp = requests.post(url, json=payload, timeout=10)
        print(f"📤 Telegram sent ({resp.status_code}): {text[:50]}")
    except Exception as e:
        print("❌ Telegram send failed:", e)


def can_send_heartbeat():
    """Check if at least 1 hour has passed since last heartbeat"""
    try:
        if not os.path.exists(HEARTBEAT_FILE):
            return True
        last = datetime.fromisoformat(open(HEARTBEAT_FILE).read().strip())
        return datetime.now(timezone.utc) - last > timedelta(hours=1)
    except Exception:
        return True


def update_heartbeat():
    """Update last heartbeat timestamp"""
    os.makedirs("output", exist_ok=True)
    with open(HEARTBEAT_FILE, "w") as f:
        f.write(datetime.now(timezone.utc).isoformat())
