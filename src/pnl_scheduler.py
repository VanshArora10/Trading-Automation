import schedule
import time
import subprocess

def run_tracker():
    subprocess.run(["python", "src/pnl_tracker.py"])

schedule.every(5).minutes.do(run_tracker)

print("📈 Running pnl_tracker every 5 minutes until 3:30 PM...")

while True:
    schedule.run_pending()
    time.sleep(60)
