"""
QuantPy Control Panel - Flask backend
=====================================
Start:   python server.py        ->  http://127.0.0.1:5000
Setup:   see README.md (.env, python setup_2fa.py)

Security model: password + TOTP (2FA is mandatory), brute-force lockout,
CSRF header, HttpOnly/SameSite cookies, loopback-only by default.
Do NOT expose this server to the internet without TLS and a reverse proxy.
"""
from __future__ import annotations

import hmac
import html
import os
import re
import secrets
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, request, send_from_directory, session

load_dotenv()

from quantpy.risk import (AuditLog, LEGAL_DOC_VERSION, RiskLimits, live_trading_enabled)  # noqa: E402

try:                                   # heavy / optional imports
    from Quant_bot_ai import QuantTradingBot, TradingConfig, setup_logging
except Exception as _exc:              # pragma: no cover - keeps the UI usable
    QuantTradingBot = TradingConfig = None
    setup_logging = lambda *a, **k: None   # noqa: E731
    _IMPORT_ERROR = _exc
else:
    _IMPORT_ERROR = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Strict",
    SESSION_COOKIE_SECURE=os.environ.get("QUANTPY_HTTPS", "0") == "1",
    MAX_CONTENT_LENGTH=64 * 1024,
)
audit = AuditLog(os.environ.get("QUANTPY_AUDIT_PATH", "audit/audit_log.jsonl"))

# ─── Auth helpers ─────────────────────────────────────────────────────────────
SYMBOL_RE = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")
_fail: dict = defaultdict(list)          # ip -> timestamps of failures
_last_totp: dict = {}                    # user -> last accepted time-step (replay guard)
MAX_FAILS, LOCK_SECONDS = 5, 300


def _ip() -> str:
    return request.remote_addr or "?"


def _locked(ip: str) -> bool:
    now = time.time()
    _fail[ip] = [t for t in _fail[ip] if now - t < LOCK_SECONDS]
    return len(_fail[ip]) >= MAX_FAILS


def _check_password(supplied: str) -> bool:
    """Prefers QUANT_PASSWORD_HASH (bcrypt); falls back to QUANT_PASSWORD."""
    h = os.environ.get("QUANT_PASSWORD_HASH", "")
    if h:
        try:
            import bcrypt
            return bcrypt.checkpw(supplied.encode(), h.encode())
        except Exception:
            return False
    plain = os.environ.get("QUANT_PASSWORD", "")
    return bool(plain) and hmac.compare_digest(supplied.encode(), plain.encode())


def _totp_secret(user: str):
    path = os.path.join(os.environ.get("QUANTPY_SECRETS_DIR", os.path.join(BASE_DIR, ".secrets")),
                        f"{user.lower()}.totp")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    return None


def _verify_totp(user: str, code: str) -> bool:
    import pyotp
    secret = _totp_secret(user)
    if not secret or not re.fullmatch(r"\d{6}", code or ""):
        return False
    totp = pyotp.TOTP(secret)
    now = time.time()
    for off in (-1, 0, 1):
        step = int(now // 30) + off
        if hmac.compare_digest(totp.at(step * 30), code):
            if _last_totp.get(user, -1) >= step:     # replay
                return False
            _last_totp[user] = step
            return True
    return False


def require_auth(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if not session.get("authenticated"):
            return jsonify({"error": "Unauthorized"}), 401
        return f(*a, **kw)
    return wrapper


def require_legal(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if session.get("legal_ack") != LEGAL_DOC_VERSION:
            return jsonify({"error": "Please accept the risk & legal notice first.",
                            "code": "legal_required"}), 403
        return f(*a, **kw)
    return wrapper


@app.before_request
def csrf_guard():
    if request.method in ("POST", "PUT", "DELETE") and \
            request.headers.get("X-Requested-With") != "QuantPy":
        return jsonify({"error": "Missing CSRF header"}), 403


@app.after_request
def headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Cache-Control"] = "no-store"
    return resp


# ─── Auth routes ──────────────────────────────────────────────────────────────
@app.post("/api/auth/login")
def auth_login():
    ip = _ip()
    if _locked(ip):
        return jsonify({"error": "Too many attempts. Try again in a few minutes."}), 429
    data = request.get_json(silent=True) or {}
    user = str(data.get("username", "")).strip()
    valid_user = os.environ.get("QUANT_USER", "")
    if not valid_user or not (os.environ.get("QUANT_PASSWORD") or os.environ.get("QUANT_PASSWORD_HASH")):
        return jsonify({"error": "Server credentials not configured"}), 500
    ok_user = hmac.compare_digest(user.lower().encode(), valid_user.lower().encode())
    ok_pw = _check_password(str(data.get("password", "")))
    if not (ok_user and ok_pw):
        _fail[ip].append(time.time())
        audit.record("login_failed", ip=ip)
        time.sleep(0.4)
        return jsonify({"error": "Invalid username or password"}), 401
    if _totp_secret(valid_user) is None:
        return jsonify({"error": "2FA is not set up. Run: python setup_2fa.py"}), 500
    session.clear()
    session["pre_auth_user"] = valid_user
    session["pre_auth_ts"] = time.time()
    return jsonify({"message": "Password OK - enter 2FA code", "need_2fa": True})


@app.post("/api/auth/verify_2fa")
def auth_verify_2fa():
    ip, user = _ip(), session.get("pre_auth_user")
    if _locked(ip):
        return jsonify({"error": "Too many attempts. Try again in a few minutes."}), 429
    if not user or time.time() - session.get("pre_auth_ts", 0) > 300:
        session.clear()
        return jsonify({"error": "Login expired - start again."}), 401
    code = str((request.get_json(silent=True) or {}).get("code", "")).strip()
    if not _verify_totp(user, code):
        _fail[ip].append(time.time())
        audit.record("2fa_failed", user=user, ip=ip)
        return jsonify({"error": "Invalid or already used code"}), 401
    session.clear()
    session.permanent = True
    session["authenticated"], session["user"] = True, user
    audit.record("login_ok", user=user, ip=ip)
    return jsonify({"message": "Login successful", "user": user})


@app.post("/api/auth/logout")
def auth_logout():
    session.clear()
    return jsonify({"message": "Logged out"})


@app.get("/api/auth/me")
def auth_me():
    if session.get("authenticated"):
        return jsonify({"authenticated": True, "user": session.get("user"),
                        "legal_ok": session.get("legal_ack") == LEGAL_DOC_VERSION})
    return jsonify({"authenticated": False})


# ─── Frontend & legal text ────────────────────────────────────────────────────
@app.get("/")
def index():
    return send_from_directory(BASE_DIR, "dashboard.html")


@app.get("/legal")
def legal():
    path = os.path.join(BASE_DIR, "docs", "LEGAL_DE.md")
    with open(path, "r", encoding="utf-8") as f:
        body = html.escape(f.read())
    return Response(
        "<!doctype html><meta charset=utf-8><title>QuantPy - Rechtliche Hinweise</title>"
        "<body style='font:15px/1.5 system-ui;max-width:860px;margin:2rem auto;padding:0 1rem'>"
        f"<pre style='white-space:pre-wrap;font:inherit'>{body}</pre></body>", mimetype="text/html")


# ─── Bot state ────────────────────────────────────────────────────────────────
bot = None
bot_thread = None
stop_event = threading.Event()
state_lock = threading.Lock()
last_cycle_result: dict = {}
equity_history: list = []
last_error = ""


def _record_cycle(result: dict) -> None:
    global last_cycle_result
    last_cycle_result = result
    equity_history.append({"timestamp": datetime.now().isoformat(),
                           "value": result["portfolio"]["total_value"]})
    del equity_history[:-500]


def _bot_loop():
    global last_error
    while not stop_event.is_set():
        wait = bot.config.rebalance_interval
        try:
            _record_cycle(bot.run_cycle())
            last_error = ""
        except Exception as e:
            last_error = str(e)
            audit.record("cycle_error", error=str(e))
            wait = 60
        stop_event.wait(wait)


def _parse_params(data: dict):
    try:
        capital = float(data.get("capital", 1000))
        interval = int(data.get("interval", 300))
    except (TypeError, ValueError):
        raise ValueError("capital/interval must be numbers")
    if not 100 <= capital <= 1_000_000:
        raise ValueError("capital must be between 100 and 1,000,000")
    symbols = [str(s).strip().upper() for s in (data.get("symbols") or [])]
    symbols = list(dict.fromkeys(s for s in symbols if s))[:60]
    if not symbols or any(not SYMBOL_RE.match(s) for s in symbols):
        raise ValueError("invalid symbol list")
    return capital, symbols, max(60, min(interval, 86_400))


def _make_bot(capital, symbols, interval):
    if QuantTradingBot is None:
        raise RuntimeError(f"Bot unavailable: {_IMPORT_ERROR}")
    paper = "paper-api" in os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    cfg = TradingConfig(symbols=symbols, initial_capital=capital,
                        rebalance_interval=interval, paper_trading=paper)
    return QuantTradingBot(cfg, audit=audit)


@app.get("/api/status")
@require_auth
def status():
    paper = "paper-api" in os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    live_ok, why = live_trading_enabled(RiskLimits.from_env())
    return jsonify({"running": bool(bot_thread and bot_thread.is_alive()),
                    "paper": paper, "live_enabled": live_ok, "last_error": last_error,
                    "legal_ok": session.get("legal_ack") == LEGAL_DOC_VERSION,
                    "legal_version": LEGAL_DOC_VERSION})


@app.post("/api/legal/accept")
@require_auth
def legal_accept():
    if not (request.get_json(silent=True) or {}).get("accepted"):
        return jsonify({"error": "Acceptance required"}), 400
    session["legal_ack"] = LEGAL_DOC_VERSION
    audit.record("legal_acknowledged", user=session.get("user"), version=LEGAL_DOC_VERSION)
    return jsonify({"ok": True})


@app.post("/api/start")
@require_auth
@require_legal
def start():
    global bot, bot_thread
    with state_lock:
        if bot_thread and bot_thread.is_alive():
            return jsonify({"error": "Bot is already running"}), 400
        try:
            capital, symbols, interval = _parse_params(request.get_json(silent=True) or {})
            bot = _make_bot(capital, symbols, interval)
        except (ValueError, EnvironmentError, RuntimeError) as e:
            return jsonify({"error": str(e)}), 400
        stop_event.clear()
        bot_thread = threading.Thread(target=_bot_loop, daemon=True)
        bot_thread.start()
    audit.record("bot_started", user=session.get("user"), symbols=symbols, interval=interval)
    mode = "PAPER" if bot.alpaca.is_paper else "LIVE"
    return jsonify({"ok": True, "message": f"Bot started ({mode}), interval {interval}s"})


@app.post("/api/stop")
@require_auth
def stop():
    stop_event.set()
    audit.record("bot_stopped", user=session.get("user"))
    return jsonify({"ok": True, "message": "Bot stopped"})


@app.post("/api/run_once")
@require_auth
@require_legal
def run_once():
    global bot
    with state_lock:
        if bot_thread and bot_thread.is_alive():
            return jsonify({"error": "Bot loop is running - stop it first."}), 409
        try:
            capital, symbols, interval = _parse_params(request.get_json(silent=True) or {})
            if bot is None or bot.config.symbols != symbols:
                bot = _make_bot(capital, symbols, interval)
            result = bot.run_cycle()
        except (ValueError, EnvironmentError, RuntimeError) as e:
            return jsonify({"error": str(e)}), 400
        _record_cycle(result)
    return jsonify(result)


@app.get("/api/portfolio")
@require_auth
def portfolio():
    if bot is None:
        return jsonify({"cash": 0, "total_value": 0, "num_positions": 0, "positions": {},
                        "num_trades": 0, "pnl": 0, "pnl_pct": 0})
    return jsonify(bot.portfolio.portfolio_summary)


@app.get("/api/trades")
@require_auth
def trades():
    if bot is None:
        return jsonify([])
    return jsonify([{"symbol": t.symbol, "action": t.action, "shares": round(t.shares, 4),
                     "price": round(t.price, 2), "timestamp": t.timestamp.isoformat(),
                     "reason": t.reason, "pnl": round(t.pnl, 2)} for t in bot.portfolio.trades])


@app.get("/api/equity_history")
@require_auth
def get_equity_history():
    return jsonify(equity_history)


@app.get("/api/last_cycle")
@require_auth
def last_cycle():
    return jsonify(last_cycle_result)


# ─── Risk & audit ─────────────────────────────────────────────────────────────
@app.get("/api/risk")
@require_auth
def risk_status():
    if bot is None:
        return jsonify({"available": False})
    snap = bot.risk.snapshot(bot.portfolio.total_value, bot.portfolio.exposure())
    snap["available"] = True
    snap["limits"] = bot.risk.limits.to_dict()
    return jsonify(snap)


@app.post("/api/risk/kill")
@require_auth
def risk_kill():
    if bot is None:
        return jsonify({"error": "Bot not initialised"}), 400
    bot.risk.trip("Manual emergency stop", by=session.get("user", "?"))
    stop_event.set()
    return jsonify({"ok": True, "message": "Kill switch active; loop stopped."})


@app.post("/api/risk/reset")
@require_auth
def risk_reset():
    """Re-arming needs a fresh 2FA code and a written reason (audit trail)."""
    data = request.get_json(silent=True) or {}
    if bot is None:
        return jsonify({"error": "Bot not initialised"}), 400
    if not _verify_totp(session.get("user", ""), str(data.get("code", ""))):
        return jsonify({"error": "Invalid or already used 2FA code"}), 401
    if not bot.risk.reset(session.get("user", "?"), str(data.get("reason", ""))[:300]):
        return jsonify({"error": "A reason is required"}), 400
    return jsonify({"ok": True})


@app.get("/api/audit/verify")
@require_auth
def audit_verify():
    ok, n, msg = audit.verify()
    return jsonify({"ok": ok, "entries": n, "message": msg})


@app.get("/api/audit/tail")
@require_auth
def audit_tail():
    return jsonify(audit.tail(min(int(request.args.get("n", 50)), 500)))


@app.get("/api/audit/export")
@require_auth
def audit_export():
    with open(audit.path, "r", encoding="utf-8") as f:
        data = f.read()
    return Response(data, mimetype="application/x-ndjson",
                    headers={"Content-Disposition": "attachment; filename=quantpy_audit.jsonl"})


if __name__ == "__main__":
    setup_logging()
    if not os.environ.get("SECRET_KEY"):
        print("WARNING: SECRET_KEY not set - sessions reset on every restart.")
    host = os.environ.get("QUANTPY_HOST", "127.0.0.1")
    print("=" * 52, f"\n  QuantPy Control Panel -> http://{host}:5000\n", "=" * 52, sep="")
    app.run(host=host, port=5000, debug=False, use_reloader=False)
