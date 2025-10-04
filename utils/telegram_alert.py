# src/utils/telegram_alert.py
import os
import requests

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram_message(text: str):
    """
    Send a message to your Telegram bot.
    """
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("⚠️ Telegram credentials missing in env!")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}

    try:
        resp = requests.post(url, data=data, timeout=10)
        if resp.status_code == 200:
            print(f"✅ Telegram alert sent: {text}")
            return True
        else:
            print(f"❌ Failed to send Telegram message: {resp.text}")
            return False
    except Exception as e:
        print(f"🚨 Error sending Telegram message: {e}")
        return False
