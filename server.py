"""
QuantPy Trading Dashboard - Flask Server
=========================================
Location: QuantPy/ (root, next to dashboard.html)

Setup:
pip install flask flask-session python-dotenv yfinance anthropic pandas numpy

.env file:
ANTHROPIC_API_KEY=sk-ant-...
SECRET_KEY=your_random_string
QUANT_USER=Kaia
QUANT_PASSWORD=your_password

Start:
python server.py

Then open: http://localhost:5000
"""

import os
import threading
import time
import secrets
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, jsonify, request, send_from_directory, session
from flask_session import Session
from dotenv import load_dotenv

load_dotenv()

from Quant_bot_ai import TradingConfig, QuantTradingBot

app = Flask(__name__)

# ─── Session config ───────────────────────────────────────────────────────────
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))
app.config["SESSION_TYPE"]               = "filesystem"
app.config["SESSION_FILE_DIR"]           = "./.flask_sessions"
app.config["SESSION_PERMANENT"]          = False
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)
app.config["SESSION_COOKIE_HTTPONLY"]    = True
app.config["SESSION_COOKIE_SAMESITE"]    = "Lax"
Session(app)

os.makedirs(".flask_sessions", exist_ok=True)

# ─── Auth helper ──────────────────────────────────────────────────────────────
def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("authenticated"):
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated

# ─── Global bot state ─────────────────────────────────────────────────────────
bot: QuantTradingBot         = None
bot_thread: threading.Thread = None
bot_running                  = False
last_cycle_result            = {}
equity_history               = []


def _bot_loop():
    global bot_running, last_cycle_result, equity_history
    while bot_running:
        try:
            result = bot.run_cycle()
            last_cycle_result = result
            equity_history.append({
                "timestamp": datetime.now().isoformat(),
                "value":     result["portfolio"]["total_value"],
            })
            if len(equity_history) > 500:
                equity_history = equity_history[-500:]
            time.sleep(bot.config.rebalance_interval)
        except Exception as e:
            print(f"[Bot Error] {e}")
            time.sleep(60)


# ─── Auth routes ──────────────────────────────────────────────────────────────

@app.route("/api/auth/login", methods=["POST"])
def auth_login():
    data     = request.json or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")

    valid_user = os.environ.get("QUANT_USER", "")
    valid_pass = os.environ.get("QUANT_PASSWORD", "")

    if not valid_user or not valid_pass:
        return jsonify({"error": "Server credentials not configured"}), 500

    if username.lower() != valid_user.lower() or password != valid_pass:
        time.sleep(0.3)
        return jsonify({"error": "Invalid username or password"}), 401

    session.clear()
    session["authenticated"] = True
    session["user"]          = valid_user
    return jsonify({"message": "Login successful", "user": valid_user}), 200


@app.route("/api/auth/logout", methods=["POST"])
def auth_logout():
    session.clear()
    return jsonify({"message": "Logged out"}), 200


@app.route("/api/auth/me")
def auth_me():
    if session.get("authenticated"):
        return jsonify({"authenticated": True, "user": session.get("user")}), 200
    return jsonify({"authenticated": False}), 200


# ─── Frontend ─────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(".", "dashboard.html")


# ─── API routes (all protected) ───────────────────────────────────────────────

@app.route("/api/status")
@require_auth
def status():
    return jsonify({"running": bot_running})


@app.route("/api/start", methods=["POST"])
@require_auth
def start():
    global bot, bot_thread, bot_running
    if bot_running:
        return jsonify({"error": "Bot is already running"}), 400

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
    bot         = QuantTradingBot(config)
    bot_running = True
    bot_thread  = threading.Thread(target=_bot_loop, daemon=True)
    bot_thread.start()
    return jsonify({"ok": True, "message": f"Bot started with ${capital:.2f}"})


@app.route("/api/stop", methods=["POST"])
@require_auth
def stop():
    global bot_running
    bot_running = False
    return jsonify({"ok": True, "message": "Bot stopped"})


@app.route("/api/run_once", methods=["POST"])
@require_auth
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
        "value":     result["portfolio"]["total_value"],
    })
    return jsonify(result)


@app.route("/api/portfolio")
@require_auth
def portfolio():
    if bot is None:
        return jsonify({"cash": 0, "total_value": 0, "num_positions": 0,
                        "positions": {}, "num_trades": 0, "pnl": 0, "pnl_pct": 0})
    return jsonify(bot.portfolio.portfolio_summary)


@app.route("/api/trades")
@require_auth
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
@require_auth
def get_equity_history():
    return jsonify(equity_history)


@app.route("/api/last_cycle")
@require_auth
def last_cycle():
    return jsonify(last_cycle_result)


if __name__ == "__main__":
    if not os.environ.get("SECRET_KEY"):
        print("WARNING: SECRET_KEY not set in .env!")
    if not os.environ.get("QUANT_USER") or not os.environ.get("QUANT_PASSWORD"):
        print("WARNING: QUANT_USER / QUANT_PASSWORD not set in .env!")
    print("=" * 50)
    print("  QuantPy Trading Dashboard")
    print("  -> http://localhost:5000")
    print("=" * 50)
    app.run(debug=True, port=5000, use_reloader=False)
