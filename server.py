"""
QuantPy Trading Dashboard - Flask Server
=========================================
Ablage: QuantPy/ (Root, neben dashboard.html)

Setup:
pip install flask python-dotenv yfinance anthropic pandas numpy

Starten:
export ANTHROPIC_API_KEY="sk-ant-..."   (Mac/Linux)
set ANTHROPIC_API_KEY=sk-ant-...        (Windows)
python server.py

Dann im Browser: http://localhost:5000
"""

import os
import json
import threading
import time
from datetime import datetime

from flask import Flask, jsonify, request, send_from_directory
from dotenv import load_dotenv

load_dotenv()

# Quant_bot_ai.py liegt im gleichen Ordner wie server.py
from Quant_bot_ai import TradingConfig, QuantTradingBot

app = Flask(__name__)

# ─── Globaler Bot-State ───────────────────────────────────────────────────────
bot: QuantTradingBot = None
bot_thread: threading.Thread = None
bot_running = False
last_cycle_result = {}
equity_history = []


def _bot_loop():
global bot_running, last_cycle_result, equity_history
while bot_running:
try:
result = bot.run_cycle()
last_cycle_result = result
equity_history.append({
"timestamp": datetime.now().isoformat(),
"value": result["portfolio"]["total_value"]
})
if len(equity_history) > 500:
equity_history = equity_history[-500:]
time.sleep(bot.config.rebalance_interval)
except Exception as e:
print(f"[Bot Error] {e}")
time.sleep(60)


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
return send_from_directory(".", "dashboard.html")


@app.route("/api/status")
def status():
return jsonify({"running": bot_running})


@app.route("/api/start", methods=["POST"])
def start():
global bot, bot_thread, bot_running
if bot_running:
return jsonify({"error": "Bot läuft bereits"}), 400

data     = request.json or {}
capital  = float(data.get("capital", 1000.0))
symbols  = data.get("symbols", ["AAPL", "MSFT", "GOOGL", "NVDA", "TSLA", "SPY"])
interval = int(data.get("interval", 3600))

config = TradingConfig(
symbols=symbols,
initial_capital=capital,
paper_trading=True,
rebalance_interval=interval,
)
bot = QuantTradingBot(config)
bot_running = True
bot_thread = threading.Thread(target=_bot_loop, daemon=True)
bot_thread.start()

return jsonify({"ok": True, "message": f"Bot gestartet mit €{capital:.2f}"})


@app.route("/api/stop", methods=["POST"])
def stop():
global bot_running
bot_running = False
return jsonify({"ok": True, "message": "Bot gestoppt"})


@app.route("/api/run_once", methods=["POST"])
def run_once():
global bot, last_cycle_result, equity_history

data    = request.json or {}
capital = float(data.get("capital", 1000.0))
symbols = data.get("symbols", ["AAPL", "MSFT", "GOOGL", "NVDA", "TSLA", "SPY"])

if bot is None or bot.config.initial_capital != capital:
config = TradingConfig(
symbols=symbols,
initial_capital=capital,
paper_trading=True,
)
bot = QuantTradingBot(config)

result = bot.run_cycle()
last_cycle_result = result
equity_history.append({
"timestamp": datetime.now().isoformat(),
"value":     result["portfolio"]["total_value"]
})
return jsonify(result)


@app.route("/api/portfolio")
def portfolio():
if bot is None:
return jsonify({"cash": 0, "total_value": 0, "num_positions": 0,
"positions": {}, "num_trades": 0, "pnl": 0, "pnl_pct": 0})
return jsonify(bot.portfolio.portfolio_summary)


@app.route("/api/trades")
def trades():
if bot is None:
return jsonify([])
return jsonify([{
"symbol":    t.symbol,
"action":    t.action,
"shares":    round(t.shares, 4),
"price":     round(t.price, 2),
"timestamp": t.timestamp.isoformat(),
"reason":    t.reason,
"pnl":       round(t.pnl, 2),
} for t in bot.portfolio.trades])


@app.route("/api/equity_history")
def get_equity_history():
return jsonify(equity_history)


@app.route("/api/last_cycle")
def last_cycle():
return jsonify(last_cycle_result)


if __name__ == "__main__":
print("=" * 50)
print("  QuantPy Trading Dashboard")
print("  → http://localhost:5000")
print("=" * 50)
app.run(debug=True, port=5000, use_reloader=False)
