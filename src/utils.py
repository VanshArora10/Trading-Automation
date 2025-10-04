# src/utils.py
import pytz
from datetime import datetime, time
import json, csv, os

IST = pytz.timezone("Asia/Kolkata")

def now_ist():
    return datetime.now(tz=IST)

def in_market_hours():
    now = now_ist()
    # Market open 09:15, close 15:30 (Mon-Fri)
    if now.weekday() >= 5:
        return False
    start = now.replace(hour=9, minute=15, second=0, microsecond=0)
    end = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return start <= now <= end

def save_json(obj, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, indent=2)

def append_csv(rows, path):
    # rows: list of dicts
    os.makedirs(os.path.dirname(path), exist_ok=True)
    file_exists = os.path.exists(path)
    with open(path, "a", newline='') as f:
        writer = None
        for row in rows:
            if writer is None:
                writer = csv.DictWriter(f, fieldnames=list(row.keys()))
                if not file_exists:
                    writer.writeheader()
            writer.writerow(row)
