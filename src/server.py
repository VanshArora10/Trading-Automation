# src/server.py
from flask import Flask
import threading
from src.pipeline import run

app = Flask(__name__)

@app.route('/')
def home():
    return "✅ Trading automation is alive!", 200

@app.route('/run')
def trigger_run():
    # Run the trading job in background
    threading.Thread(target=run, kwargs={"dry_run": False}).start()
    return "🚀 Trading job started successfully", 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
