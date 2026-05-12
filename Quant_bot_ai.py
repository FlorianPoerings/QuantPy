"""
AI-Powered Quantitative Trading Bot — Alpaca Edition
=====================================================
Data source:    Alpaca Markets API (live 1-min bars)
AI integration: Anthropic Claude API
Risk mgmt:      VaR, Sharpe Ratio, Stop-Loss, Take-Profit
Execution:      Alpaca Paper Trading (no real money)

.env additions needed:
  ALPACA_API_KEY=your_key
  ALPACA_SECRET_KEY=your_secret
  ALPACA_BASE_URL=https://paper-api.alpaca.markets   ← paper mode
  # ALPACA_BASE_URL=https://api.alpaca.markets       ← live mode (careful!)

Get free keys at: https://alpaca.markets
"""

import os
import json
import time
import logging
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd
import numpy as np
import anthropic
import requests
from dotenv import load_dotenv

load_dotenv()

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("quant_trader.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")


# ─── Configuration ────────────────────────────────────────────────────────────
@dataclass
class TradingConfig:
    symbols: list[str]          = field(default_factory=lambda: ["AAPL","MSFT","GOOGL","NVDA","TSLA","SPY"])
    initial_capital: float      = 10_000.0
    max_position_size: float    = 0.20      # max 20% per position
    max_portfolio_risk: float   = 0.10
    stop_loss_pct: float        = 0.03      # tighter for intraday
    take_profit_pct: float      = 0.06      # take profit at 6%
    lookback_bars: int          = 100       # number of 1-min bars for analysis
    var_confidence: float       = 0.95
    min_sharpe: float           = 0.5
    min_confidence: int         = 60        # min AI confidence to trade
    rebalance_interval: int     = 300       # check every 5 min (seconds)
    paper_trading: bool         = True
    # Intraday settings
    bar_timeframe: str          = "1Min"    # 1Min, 5Min, 15Min, 1Hour, 1Day
    market_open_only: bool      = True      # only trade during market hours


# ─── Alpaca Market Data + Execution ───────────────────────────────────────────
class AlpacaClient:
    """
    Handles both market data AND order execution via Alpaca REST API.
    No SDK dependency — pure requests.
    """

    DATA_URL   = "https://data.alpaca.markets"
    PAPER_URL  = "https://paper-api.alpaca.markets"
    LIVE_URL   = "https://api.alpaca.markets"

    def __init__(self, config: TradingConfig):
        self.config     = config
        self.api_key    = os.environ.get("ALPACA_API_KEY", "")
        self.secret_key = os.environ.get("ALPACA_SECRET_KEY", "")
        self.base_url   = os.environ.get("ALPACA_BASE_URL", self.PAPER_URL)

        if not self.api_key or not self.secret_key:
            raise EnvironmentError(
                "ALPACA_API_KEY and ALPACA_SECRET_KEY must be set in .env\n"
                "Get free keys at: https://alpaca.markets"
            )

        self.headers = {
            "APCA-API-KEY-ID":     self.api_key,
            "APCA-API-SECRET-KEY": self.secret_key,
            "Content-Type":        "application/json",
        }

    # ── Market Data ────────────────────────────────────────────────────────────

    def is_market_open(self) -> bool:
        try:
            r = requests.get(f"{self.base_url}/v2/clock", headers=self.headers, timeout=5)
            return r.json().get("is_open", False)
        except Exception as e:
            log.warning(f"Could not check market clock: {e}")
            return False

    def get_bars(self, symbol: str, timeframe: str = "1Min", limit: int = 100) -> pd.DataFrame:
        """Fetch recent OHLCV bars from Alpaca."""
        url = f"{self.DATA_URL}/v2/stocks/{symbol}/bars"
        params = {
            "timeframe": timeframe,
            "limit":     limit,
            "feed":      "iex",   # free feed; use "sip" with paid plan
        }
        for attempt in range(3):
            try:
                r = requests.get(url, headers=self.headers, params=params, timeout=10)
                if r.status_code == 429:
                    wait = 15 * (attempt + 1)
                    log.warning(f"{symbol}: Rate limit — waiting {wait}s")
                    time.sleep(wait)
                    continue
                if r.status_code != 200:
                    log.error(f"{symbol}: HTTP {r.status_code} — {r.text[:120]}")
                    return pd.DataFrame()

                bars = r.json().get("bars", [])
                if not bars:
                    log.warning(f"{symbol}: No bars returned")
                    return pd.DataFrame()

                df = pd.DataFrame(bars)
                df = df.rename(columns={"t":"timestamp","o":"Open","h":"High",
                                        "l":"Low","c":"Close","v":"Volume"})
                df["timestamp"] = pd.to_datetime(df["timestamp"])
                df = df.set_index("timestamp")[["Open","High","Low","Close","Volume"]]
                df.index = df.index.tz_convert(None)
                log.info(f"{symbol}: {len(df)} {timeframe} bars "
                         f"({df.index[0].strftime('%H:%M')} → {df.index[-1].strftime('%H:%M')})")
                return df

            except Exception as e:
                log.error(f"{symbol}: Failed to load bars — {e}")
                return pd.DataFrame()

        return pd.DataFrame()

    def get_latest_quote(self, symbol: str) -> float:
        """Get latest ask price for a symbol."""
        try:
            url = f"{self.DATA_URL}/v2/stocks/{symbol}/quotes/latest"
            r = requests.get(url, headers=self.headers, params={"feed":"iex"}, timeout=5)
            if r.status_code == 200:
                ask = r.json().get("quote", {}).get("ap", 0)
                if ask and ask > 0:
                    return float(ask)
        except Exception:
            pass
        return 0.0

    def get_multi_bars(self, symbols: list[str], timeframe: str, limit: int) -> dict:
        data = {}
        for sym in symbols:
            df = self.get_bars(sym, timeframe, limit)
            if not df.empty:
                data[sym] = df
            time.sleep(0.3)   # be polite with the API
        return data

    # ── Order Execution ────────────────────────────────────────────────────────

    def get_account(self) -> dict:
        try:
            r = requests.get(f"{self.base_url}/v2/account", headers=self.headers, timeout=5)
            return r.json()
        except Exception as e:
            log.error(f"Could not fetch account: {e}")
            return {}

    def place_market_order(self, symbol: str, qty: float, side: str) -> dict:
        """
        Place a market order.
        side: 'buy' or 'sell'
        qty:  number of shares (fractional supported)
        """
        if self.config.paper_trading:
            log.info(f"[PAPER] {side.upper()} {qty:.4f} {symbol} @ market")
        else:
            log.info(f"[LIVE]  {side.upper()} {qty:.4f} {symbol} @ market")

        payload = {
            "symbol":        symbol,
            "qty":           str(round(qty, 4)),
            "side":          side,
            "type":          "market",
            "time_in_force": "day",
        }
        try:
            r = requests.post(
                f"{self.base_url}/v2/orders",
                headers=self.headers,
                json=payload,
                timeout=10
            )
            result = r.json()
            if r.status_code in (200, 201):
                log.info(f"Order placed: {result.get('id')} | status: {result.get('status')}")
            else:
                log.error(f"Order failed: {result}")
            return result
        except Exception as e:
            log.error(f"Order exception: {e}")
            return {"error": str(e)}

    def get_positions(self) -> list[dict]:
        try:
            r = requests.get(f"{self.base_url}/v2/positions", headers=self.headers, timeout=5)
            return r.json() if r.status_code == 200 else []
        except Exception:
            return []

    def close_position(self, symbol: str) -> dict:
        try:
            r = requests.delete(
                f"{self.base_url}/v2/positions/{symbol}",
                headers=self.headers, timeout=10
            )
            return r.json()
        except Exception as e:
            return {"error": str(e)}


# ─── Technical Indicators ─────────────────────────────────────────────────────
class TechnicalAnalysis:

    @staticmethod
    def sma(series: pd.Series, window: int) -> pd.Series:
        return series.rolling(window).mean()

    @staticmethod
    def ema(series: pd.Series, span: int) -> pd.Series:
        return series.ewm(span=span, adjust=False).mean()

    @staticmethod
    def rsi(series: pd.Series, period: int = 14) -> pd.Series:
        delta = series.diff()
        gain  = delta.clip(lower=0).rolling(period).mean()
        loss  = (-delta.clip(upper=0)).rolling(period).mean()
        rs    = gain / loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))

    @staticmethod
    def macd(series: pd.Series, fast=12, slow=26, signal=9) -> pd.DataFrame:
        ema_fast   = series.ewm(span=fast,   adjust=False).mean()
        ema_slow   = series.ewm(span=slow,   adjust=False).mean()
        macd_line  = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        return pd.DataFrame({
            "macd":   macd_line,
            "signal": signal_line,
            "hist":   macd_line - signal_line,
        })

    @staticmethod
    def bollinger_bands(series: pd.Series, window=20, num_std=2) -> pd.DataFrame:
        mid = series.rolling(window).mean()
        std = series.rolling(window).std()
        return pd.DataFrame({
            "upper": mid + num_std * std,
            "mid":   mid,
            "lower": mid - num_std * std,
        })

    @staticmethod
    def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        high, low, close = df["High"], df["Low"], df["Close"]
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low  - close.shift()).abs(),
        ], axis=1).max(axis=1)
        return tr.rolling(period).mean()

    @staticmethod
    def vwap(df: pd.DataFrame) -> float:
        """Volume Weighted Average Price — key intraday indicator."""
        typical = (df["High"] + df["Low"] + df["Close"]) / 3
        return float((typical * df["Volume"]).sum() / df["Volume"].sum())

    def compute_all(self, df: pd.DataFrame) -> dict:
        close   = df["Close"]
        macd_df = self.macd(close)
        bb      = self.bollinger_bands(close)

        return {
            "price":            round(float(close.iloc[-1]), 4),
            "sma_20":           round(float(self.sma(close, 20).iloc[-1]),  4),
            "sma_50":           round(float(self.sma(close, 50).iloc[-1]),  4),
            "ema_12":           round(float(self.ema(close, 12).iloc[-1]),  4),
            "rsi_14":           round(float(self.rsi(close).iloc[-1]),      2),
            "macd":             round(float(macd_df["macd"].iloc[-1]),      4),
            "macd_signal":      round(float(macd_df["signal"].iloc[-1]),    4),
            "macd_hist":        round(float(macd_df["hist"].iloc[-1]),      4),
            "bb_upper":         round(float(bb["upper"].iloc[-1]),          4),
            "bb_lower":         round(float(bb["lower"].iloc[-1]),          4),
            "bb_pct":           round(float(
                (close.iloc[-1] - bb["lower"].iloc[-1]) /
                (bb["upper"].iloc[-1] - bb["lower"].iloc[-1] + 1e-9)), 4),
            "atr":              round(float(self.atr(df).iloc[-1]),         4),
            "vwap":             round(self.vwap(df),                        4),
            "price_change_1b":  round(float(close.pct_change(1).iloc[-1]  * 100), 2),
            "price_change_5b":  round(float(close.pct_change(5).iloc[-1]  * 100), 2),
            "price_change_20b": round(float(close.pct_change(20).iloc[-1] * 100), 2),
        }


# ─── Risk Management ──────────────────────────────────────────────────────────
@dataclass
class RiskMetrics:
    symbol:            str
    var_95:            float
    cvar_95:           float
    sharpe_ratio:      float
    max_drawdown:      float
    volatility_annual: float
    beta:              float
    recommended_size:  float
    risk_score:        str
    stop_loss_price:   float
    take_profit_price: float


class RiskEvaluator:

    def __init__(self, config: TradingConfig):
        self.config = config

    def value_at_risk(self, returns: pd.Series, confidence: float = 0.95) -> float:
        return float(np.percentile(returns.dropna(), (1 - confidence) * 100))

    def conditional_var(self, returns: pd.Series, confidence: float = 0.95) -> float:
        var = self.value_at_risk(returns, confidence)
        return float(returns[returns <= var].mean())

    def sharpe_ratio(self, returns: pd.Series, risk_free_rate: float = 0.05) -> float:
        daily_rf = risk_free_rate / 252
        excess   = returns - daily_rf
        if excess.std() == 0:
            return 0.0
        return float((excess.mean() / excess.std()) * np.sqrt(252))

    def max_drawdown(self, prices: pd.Series) -> float:
        cumulative  = (1 + prices.pct_change()).cumprod()
        rolling_max = cumulative.cummax()
        drawdown    = (cumulative - rolling_max) / rolling_max
        return float(drawdown.min())

    def beta(self, returns: pd.Series, market_returns: pd.Series) -> float:
        aligned = returns.align(market_returns, join="inner")
        cov     = np.cov(aligned[0].dropna(), aligned[1].dropna())
        if cov[1, 1] == 0:
            return 1.0
        return float(cov[0, 1] / cov[1, 1])

    def kelly_position_size(self, win_rate: float, avg_win: float, avg_loss: float) -> float:
        if avg_loss == 0:
            return 0.0
        b     = avg_win / abs(avg_loss)
        kelly = (b * win_rate - (1 - win_rate)) / b
        return max(0.0, min(kelly * 0.5, self.config.max_position_size))

    def evaluate(self, symbol: str, df: pd.DataFrame,
                 market_df: Optional[pd.DataFrame] = None) -> RiskMetrics:
        close   = df["Close"]
        returns = close.pct_change().dropna()

        var   = self.value_at_risk(returns, self.config.var_confidence)
        cvar  = self.conditional_var(returns, self.config.var_confidence)
        sharpe = self.sharpe_ratio(returns)
        mdd   = self.max_drawdown(close)
        vol_a = float(returns.std() * np.sqrt(252))

        beta_val = 1.0
        if market_df is not None and not market_df.empty:
            mkt_r    = market_df["Close"].pct_change().dropna()
            beta_val = self.beta(returns, mkt_r)

        risk_score = self._classify_risk(var, vol_a, mdd, sharpe)

        wins     = returns[returns > 0]
        losses   = returns[returns < 0]
        win_rate = len(wins) / len(returns) if len(returns) > 0 else 0.5
        avg_win  = float(wins.mean())   if len(wins)   > 0 else 0.01
        avg_loss = float(losses.mean()) if len(losses) > 0 else -0.01
        pos_size = self.kelly_position_size(win_rate, avg_win, avg_loss)

        if risk_score == "HIGH":    pos_size *= 0.5
        elif risk_score == "EXTREME": pos_size = 0.0

        price       = float(close.iloc[-1])
        stop_loss   = price * (1 - self.config.stop_loss_pct)
        take_profit = price * (1 + self.config.take_profit_pct)

        return RiskMetrics(
            symbol=symbol,
            var_95=round(var * 100, 3),
            cvar_95=round(cvar * 100, 3),
            sharpe_ratio=round(sharpe, 3),
            max_drawdown=round(mdd * 100, 2),
            volatility_annual=round(vol_a * 100, 2),
            beta=round(beta_val, 3),
            recommended_size=round(pos_size * 100, 2),
            risk_score=risk_score,
            stop_loss_price=round(stop_loss, 4),
            take_profit_price=round(take_profit, 4),
        )

    def _classify_risk(self, var: float, vol: float, mdd: float, sharpe: float) -> str:
        score = 0
        if var < -0.03:    score += 2
        elif var < -0.02:  score += 1
        if vol > 0.40:     score += 2
        elif vol > 0.25:   score += 1
        if mdd < -0.30:    score += 2
        elif mdd < -0.20:  score += 1
        if sharpe < 0:     score += 2
        elif sharpe < 0.5: score += 1
        if score >= 6: return "EXTREME"
        if score >= 4: return "HIGH"
        if score >= 2: return "MEDIUM"
        return "LOW"


# ─── Portfolio (tracks paper positions locally) ───────────────────────────────
@dataclass
class Position:
    symbol:      str
    shares:      float
    entry_price: float
    entry_time:  datetime
    stop_loss:   float
    take_profit: float


@dataclass
class Trade:
    symbol:    str
    action:    str
    shares:    float
    price:     float
    timestamp: datetime
    reason:    str
    pnl:       float = 0.0


class Portfolio:

    def __init__(self, config: TradingConfig):
        self.config    = config
        self.cash      = config.initial_capital
        self.positions: dict[str, Position] = {}
        self.trades:    list[Trade]          = []

    @property
    def total_value(self) -> float:
        return self.cash + sum(p.shares * p.entry_price for p in self.positions.values())

    @property
    def portfolio_summary(self) -> dict:
        return {
            "cash":          round(self.cash, 2),
            "total_value":   round(self.total_value, 2),
            "num_positions": len(self.positions),
            "positions": {
                sym: {
                    "shares":      p.shares,
                    "entry_price": p.entry_price,
                    "stop_loss":   p.stop_loss,
                    "take_profit": p.take_profit,
                }
                for sym, p in self.positions.items()
            },
            "num_trades": len(self.trades),
            "pnl":     round(self.total_value - self.config.initial_capital, 2),
            "pnl_pct": round((self.total_value / self.config.initial_capital - 1) * 100, 2),
        }

    def execute_buy(self, symbol: str, price: float, stop_loss: float,
                    take_profit: float, size_pct: float, reason: str) -> bool:
        if symbol in self.positions:
            return False
        budget = self.cash * min(size_pct / 100, self.config.max_position_size)
        shares = budget / price
        if shares * price > self.cash:
            log.warning(f"Insufficient capital for {symbol}")
            return False
        self.cash -= shares * price
        self.positions[symbol] = Position(
            symbol=symbol, shares=shares, entry_price=price,
            entry_time=datetime.now(), stop_loss=stop_loss, take_profit=take_profit
        )
        self.trades.append(Trade(symbol, "BUY", shares, price, datetime.now(), reason))
        log.info(f"BUY  {symbol}: {shares:.4f} @ ${price:.2f} | SL: ${stop_loss:.2f} | TP: ${take_profit:.2f}")
        return True

    def execute_sell(self, symbol: str, price: float, reason: str) -> bool:
        if symbol not in self.positions:
            return False
        pos      = self.positions.pop(symbol)
        proceeds = pos.shares * price
        pnl      = proceeds - pos.shares * pos.entry_price
        self.cash += proceeds
        self.trades.append(Trade(symbol, "SELL", pos.shares, price, datetime.now(), reason, pnl))
        log.info(f"SELL {symbol}: {pos.shares:.4f} @ ${price:.2f} | PnL: ${pnl:.2f}")
        return True

    def check_stop_loss_take_profit(self, prices: dict[str, float]) -> list[str]:
        sold = []
        for sym, pos in list(self.positions.items()):
            price = prices.get(sym)
            if price is None:
                continue
            if price <= pos.stop_loss:
                self.execute_sell(sym, price, f"Stop-loss @ ${price:.2f}")
                sold.append(sym)
            elif price >= pos.take_profit:
                self.execute_sell(sym, price, f"Take-profit @ ${price:.2f}")
                sold.append(sym)
        return sold


# ─── AI Analyst ───────────────────────────────────────────────────────────────
class AIAnalyst:

    MODEL = "claude-sonnet-4-6"

    def __init__(self):
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise EnvironmentError("ANTHROPIC_API_KEY not set in .env")
        self.client = anthropic.Anthropic(api_key=api_key)

    def analyze(self, symbol: str, indicators: dict, risk: RiskMetrics,
                portfolio: dict, market_open: bool) -> dict:
        prompt = f"""You are an intraday quantitative trader. Analyze the live 1-minute bar data and decide.

SYMBOL: {symbol}
MARKET OPEN: {market_open}

LIVE TECHNICAL INDICATORS (1-min bars):
{json.dumps(indicators, indent=2)}

RISK METRICS:
- VaR (95%):         {risk.var_95}%
- CVaR (95%):        {risk.cvar_95}%
- Sharpe Ratio:      {risk.sharpe_ratio}
- Max Drawdown:      {risk.max_drawdown}%
- Annual Volatility: {risk.volatility_annual}%
- Beta:              {risk.beta}
- Rec. Position:     {risk.recommended_size}%
- Risk Rating:       {risk.risk_score}

PORTFOLIO:
{json.dumps(portfolio, indent=2)}

Rules:
- If market is closed, always return HOLD
- Look for momentum: RSI, MACD crossover, price vs VWAP
- Only BUY if price > VWAP and RSI 40-65 and MACD hist > 0
- SELL existing position if RSI > 75 or MACD hist turning negative
- Prefer quick scalps (small gain, fast exit) over long holds

Reply ONLY with JSON (no markdown):
{{
  "action": "BUY" | "SELL" | "HOLD",
  "confidence": 0-100,
  "reasoning": "Brief justification",
  "key_signals": ["Signal 1", "Signal 2"],
  "risk_warning": "Risk note or null"
}}"""

        try:
            resp = self.client.messages.create(
                model=self.MODEL,
                max_tokens=400,
                messages=[{"role": "user", "content": prompt}]
            )
            text = resp.content[0].text.strip()
            if "```" in text:
                text = text.split("```")[1].replace("json", "").strip()
            decision = json.loads(text)
            if decision.get("action") not in ("BUY", "SELL", "HOLD"):
                raise ValueError(f"Unexpected action: {decision.get('action')}")
            log.info(f"{symbol} → {decision['action']} ({decision['confidence']}%) | {decision['reasoning'][:80]}")
            return decision
        except json.JSONDecodeError as e:
            log.error(f"Claude JSON error for {symbol}: {e}")
            return self._fallback(str(e))
        except Exception as e:
            log.error(f"AI failed for {symbol}: {e}")
            return self._fallback(str(e))

    @staticmethod
    def _fallback(reason: str) -> dict:
        return {
            "action":       "HOLD",
            "confidence":   0,
            "reasoning":    f"AI unavailable — HOLD. Reason: {reason}",
            "key_signals":  [],
            "risk_warning": "AI unavailable — manual review required",
        }


# ─── Trading Engine ───────────────────────────────────────────────────────────
class QuantTradingBot:

    def __init__(self, config: TradingConfig):
        self.config    = config
        self.alpaca    = AlpacaClient(config)
        self.ta        = TechnicalAnalysis()
        self.risk_eval = RiskEvaluator(config)
        self.ai        = AIAnalyst()
        self.portfolio = Portfolio(config)

    def run_cycle(self) -> dict:
        log.info("=" * 60)
        log.info(f"Trading cycle started: {datetime.now().isoformat()}")

        market_open = self.alpaca.is_market_open()
        if not market_open:
            log.info("Market is closed — analysis only, no new orders")

        # Fetch all bars
        all_data = self.alpaca.get_multi_bars(
            self.config.symbols,
            self.config.bar_timeframe,
            self.config.lookback_bars
        )

        market_df = all_data.get("SPY")

        # Get current prices and check SL/TP
        current_prices = {sym: float(df["Close"].iloc[-1]) for sym, df in all_data.items()}
        if market_open:
            self.portfolio.check_stop_loss_take_profit(current_prices)

        cycle_results = []

        for symbol in self.config.symbols:
            if symbol == "SPY":
                continue
            df = all_data.get(symbol)
            if df is None or len(df) < 30:
                log.warning(f"{symbol}: Not enough data ({len(df) if df is not None else 0} bars)")
                continue

            try:
                indicators = self.ta.compute_all(df)
                risk       = self.risk_eval.evaluate(symbol, df, market_df)
                decision   = self.ai.analyze(
                    symbol, indicators, risk,
                    self.portfolio.portfolio_summary, market_open
                )

                # Execute only if market open, risk not extreme, confidence high enough
                if (market_open
                        and risk.risk_score != "EXTREME"
                        and decision["confidence"] >= self.config.min_confidence):

                    price = indicators["price"]

                    if decision["action"] == "BUY" and symbol not in self.portfolio.positions:
                        bought = self.portfolio.execute_buy(
                            symbol, price,
                            risk.stop_loss_price,
                            risk.take_profit_price,
                            risk.recommended_size,
                            decision["reasoning"]
                        )
                        # Also place real Alpaca order (paper mode by default)
                        if bought:
                            pos = self.portfolio.positions[symbol]
                            self.alpaca.place_market_order(symbol, pos.shares, "buy")

                    elif decision["action"] == "SELL" and symbol in self.portfolio.positions:
                        self.portfolio.execute_sell(symbol, price, decision["reasoning"])
                        self.alpaca.place_market_order(symbol, 0, "sell")  # close_position
                        self.alpaca.close_position(symbol)

                cycle_results.append({
                    "symbol":   symbol,
                    "price":    indicators["price"],
                    "decision": decision,
                    "risk": {
                        "score":       risk.risk_score,
                        "sharpe":      risk.sharpe_ratio,
                        "var_95":      risk.var_95,
                        "max_drawdown": risk.max_drawdown,
                        "volatility":  risk.volatility_annual,
                    }
                })

            except Exception as e:
                log.error(f"Error processing {symbol}: {e}")

        summary = {
            "timestamp":   datetime.now().isoformat(),
            "market_open": market_open,
            "portfolio":   self.portfolio.portfolio_summary,
            "analyses":    cycle_results,
        }

        with open("last_cycle.json", "w") as f:
            json.dump(summary, f, indent=2, default=str)

        log.info(
            f"Portfolio: ${self.portfolio.total_value:,.2f} | "
            f"PnL: {self.portfolio.portfolio_summary['pnl_pct']}% | "
            f"Market: {'OPEN' if market_open else 'CLOSED'}"
        )
        return summary

    def run_continuous(self):
        log.info(f"Bot started | Capital: ${self.config.initial_capital:,.2f} | Paper: {self.config.paper_trading}")
        while True:
            try:
                self.run_cycle()
                log.info(f"Next cycle in {self.config.rebalance_interval}s...")
                time.sleep(self.config.rebalance_interval)
            except KeyboardInterrupt:
                log.info("Bot stopped by user")
                break
            except Exception as e:
                log.error(f"Critical error: {e}")
                time.sleep(60)


if __name__ == "__main__":
    config = QuantTradingBot(TradingConfig(
        symbols=["AAPL", "MSFT", "NVDA", "TSLA", "SPY"],
        initial_capital=10_000.0,
        paper_trading=True,
        rebalance_interval=300,
        bar_timeframe="1Min",
        lookback_bars=100,
    ))
    config.run_cycle()
