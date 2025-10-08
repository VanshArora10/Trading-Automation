import os
import json
import time
import requests
from dotenv import load_dotenv
import requests, os

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
HEARTBEAT_FILE = "output/last_heartbeat.json"

def send_telegram_message(message: str):
    """
    Sends a Telegram message to the configured chat.
    """
    if not BOT_TOKEN or not CHAT_ID:
        print("⚠️ Telegram not configured properly.")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message}

    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            print("✅ Telegram message sent:", message)
        else:
            print(f"❌ Telegram failed ({response.status_code}): {response.text}")
    except Exception as e:
        print("⚠️ Telegram send failed:", e)


def can_send_heartbeat(interval_minutes=60):
    """
    Checks if at least `interval_minutes` have passed since the last heartbeat message.
    """
    if not os.path.exists(HEARTBEAT_FILE):
        return True

    try:
        with open(HEARTBEAT_FILE, "r") as f:
            data = json.load(f)
        last_time = data.get("timestamp", 0)
        if time.time() - last_time >= interval_minutes * 60:
            return True
    except Exception:
        return True

    return False


def update_heartbeat():
    """
    Updates the heartbeat timestamp file.
    """
    os.makedirs(os.path.dirname(HEARTBEAT_FILE), exist_ok=True)
    with open(HEARTBEAT_FILE, "w") as f:
        json.dump({"timestamp": time.time()}, f)


def send_to_google_sheets(signal_list):
    """Send signals to Google Sheet via Apps Script webhook"""
    SHEET_WEBHOOK = os.getenv("SHEET_WEBHOOK_URL")
    if not SHEET_WEBHOOK:
        print("⚠️ Google Sheet webhook not configured.")
        return
    try:
        requests.post(SHEET_WEBHOOK, json=signal_list, timeout=5)
        print("✅ Sent signals to Google Sheet.")
    except Exception as e:
        print("❌ Error sending to Google Sheet:", e)