"""
AI-Powered Quantitative Trading Bot
====================================
Data source: yfinance
AI integration: Anthropic Claude API
Risk management: Value at Risk, Sharpe Ratio, Max Drawdown
"""

import os
import json
import time
import logging
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional

import yfinance as yf
import pandas as pd
import numpy as np
import anthropic

# ─── Logging Setup ───────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("quant_trader.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)


# ─── Configuration ───────────────────────────────────────────────────────────
@dataclass
class TradingConfig:
    symbols: list[str] = field(default_factory=lambda: ["AAPL", "MSFT", "GOOGL", "NVDA", "SPY"])
    initial_capital: float = 100_000.0        # Starting capital in USD
    max_position_size: float = 0.20           # Max 20% per position
    max_portfolio_risk: float = 0.10          # Max 10% total portfolio risk
    stop_loss_pct: float = 0.05               # 5% stop-loss
    take_profit_pct: float = 0.15             # 15% take-profit
    lookback_days: int = 60                   # Analysis window
    var_confidence: float = 0.95             # VaR confidence level
    min_sharpe: float = 0.5                  # Minimum Sharpe ratio to trade
    rebalance_interval: int = 3600           # Seconds between cycles
    paper_trading: bool = True               # True = no real money!


# ─── Market Data via yfinance ─────────────────────────────────────────────────
class MarketDataFeed:
    """
    Fetches and processes market data from Yahoo Finance via yfinance.

    Breaking changes in yfinance >= 0.2.x handled here:
    (1) auto_adjust=True is now the default in download() — set explicitly
    (2) download() returns MultiIndex columns even for a single symbol — must flatten
    (3) history() index carries timezone info — tz_localize(None) removes it
    (4) On rate limiting: catch YfRateLimitError and retry with backoff
    """

    def __init__(self, config: TradingConfig):
        self.config = config

    @staticmethod
    def _clean_df(df: pd.DataFrame) -> pd.DataFrame:
        """
        Normalizes the DataFrame regardless of whether yfinance returns
        a flat or MultiIndex column structure.
        FIX (1): Flatten MultiIndex columns, e.g. ('Close', 'AAPL') -> 'Close'.
        FIX (2): Remove timezone from DatetimeIndex (tz-aware -> tz-naive).
        """
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
        df = df[cols].copy()

        if hasattr(df.index, "tz") and df.index.tz is not None:
            df.index = df.index.tz_localize(None)

        df.index = pd.to_datetime(df.index)
        return df.dropna()

    def get_ohlcv(self, symbol: str, period: str = None) -> pd.DataFrame:
        """
        Fetches OHLCV data for a symbol via Ticker.history().
        FIX (3): Set auto_adjust=True explicitly (default changed in recent versions).
        FIX (4): Exponential backoff on rate-limit errors.
        """
        for attempt in range(3):
            try:
                ticker = yf.Ticker(symbol)
                if period is not None:
                    df = ticker.history(period=period, auto_adjust=True)
                else:
                    end = datetime.today()
                    start = end - timedelta(days=self.config.lookback_days)
                    df = ticker.history(
                        start=start.strftime("%Y-%m-%d"),
                        end=end.strftime("%Y-%m-%d"),
                        auto_adjust=True,
                    )

                if df is None or df.empty:
                    log.warning(f"{symbol}: No data returned (possible delisting or rate limit)")
                    return pd.DataFrame()

                df = self._clean_df(df)
                log.info(
                    f"{symbol}: {len(df)} data points "
                    f"({df.index[0].date()} -> {df.index[-1].date()})"
                )
                return df

            except Exception as e:
                err = str(e).lower()
                if "ratelimit" in err or "rate limit" in err or "429" in err:
                    wait = 15 * (attempt + 1)
                    log.warning(f"{symbol}: Rate limit — waiting {wait}s (attempt {attempt+1}/3)")
                    time.sleep(wait)
                else:
                    log.error(f"{symbol}: Failed to load — {e}")
                    return pd.DataFrame()

        log.error(f"{symbol}: All 3 attempts failed")
        return pd.DataFrame()

    def get_fundamentals(self, symbol: str) -> dict:
        """
        Fetches fundamental metrics.
        FIX (5): ticker.info may raise KeyError in newer yfinance versions
                 — use .get() with None fallback throughout.
        """
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
        except Exception as e:
            log.warning(f"{symbol}: Fundamentals unavailable — {e}")
            info = {}

        return {
            "pe_ratio":       info.get("trailingPE"),
            "market_cap":     info.get("marketCap"),
            "revenue_growth": info.get("revenueGrowth"),
            "profit_margins": info.get("profitMargins"),
            "debt_to_equity": info.get("debtToEquity"),
            "beta":           info.get("beta"),
            "52w_high":       info.get("fiftyTwoWeekHigh"),
            "52w_low":        info.get("fiftyTwoWeekLow"),
            "sector":         info.get("sector"),
            "industry":       info.get("industry"),
        }

    def get_multi_symbol_data(self) -> dict[str, pd.DataFrame]:
        """
        Loads data for all configured symbols sequentially.
        FIX (6): yfinance.download() with threads=True is NOT thread-safe
                 (race condition on global _DFS dict, issue #2557).
                 -> Use Ticker.history() in a loop instead of download().
        """
        data = {}
        for sym in self.config.symbols:
            df = self.get_ohlcv(sym)
            if not df.empty:
                data[sym] = df
            time.sleep(0.5)
        return data


# ─── Technical Indicators ─────────────────────────────────────────────────────
class TechnicalAnalysis:
    """Calculates technical indicators."""

    @staticmethod
    def sma(series: pd.Series, window: int) -> pd.Series:
        return series.rolling(window).mean()

    @staticmethod
    def ema(series: pd.Series, span: int) -> pd.Series:
        return series.ewm(span=span, adjust=False).mean()

    @staticmethod
    def rsi(series: pd.Series, period: int = 14) -> pd.Series:
        delta = series.diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean()
        rs = gain / loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))

    @staticmethod
    def macd(series: pd.Series, fast=12, slow=26, signal=9) -> pd.DataFrame:
        ema_fast = series.ewm(span=fast, adjust=False).mean()
        ema_slow = series.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line
        return pd.DataFrame({"macd": macd_line, "signal": signal_line, "hist": histogram})

    @staticmethod
    def bollinger_bands(series: pd.Series, window=20, num_std=2) -> pd.DataFrame:
        mid = series.rolling(window).mean()
        std = series.rolling(window).std()
        return pd.DataFrame({
            "upper": mid + num_std * std,
            "mid": mid,
            "lower": mid - num_std * std
        })

    @staticmethod
    def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        high, low, close = df["High"], df["Low"], df["Close"]
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs()
        ], axis=1).max(axis=1)
        return tr.rolling(period).mean()

    @staticmethod
    def volume_trend(df: pd.DataFrame, window=20) -> pd.Series:
        return df["Volume"] / df["Volume"].rolling(window).mean()

    def compute_all(self, df: pd.DataFrame) -> dict:
        """Calculates all indicators and returns current values."""
        close = df["Close"]
        macd_df = self.macd(close)
        bb = self.bollinger_bands(close)

        return {
            "price":            round(close.iloc[-1], 4),
            "sma_20":           round(self.sma(close, 20).iloc[-1], 4),
            "sma_50":           round(self.sma(close, 50).iloc[-1], 4),
            "ema_12":           round(self.ema(close, 12).iloc[-1], 4),
            "rsi_14":           round(self.rsi(close).iloc[-1], 2),
            "macd":             round(macd_df["macd"].iloc[-1], 4),
            "macd_signal":      round(macd_df["signal"].iloc[-1], 4),
            "macd_hist":        round(macd_df["hist"].iloc[-1], 4),
            "bb_upper":         round(bb["upper"].iloc[-1], 4),
            "bb_lower":         round(bb["lower"].iloc[-1], 4),
            "bb_pct":           round((close.iloc[-1] - bb["lower"].iloc[-1]) /
                                      (bb["upper"].iloc[-1] - bb["lower"].iloc[-1] + 1e-9), 4),
            "atr":              round(self.atr(df).iloc[-1], 4),
            "vol_trend":        round(self.volume_trend(df).iloc[-1], 2),
            "price_change_1d":  round(close.pct_change(1).iloc[-1] * 100, 2),
            "price_change_5d":  round(close.pct_change(5).iloc[-1] * 100, 2),
            "price_change_20d": round(close.pct_change(20).iloc[-1] * 100, 2),
        }


# ─── Risk Management ──────────────────────────────────────────────────────────
@dataclass
class RiskMetrics:
    symbol: str
    var_95: float
    cvar_95: float
    sharpe_ratio: float
    max_drawdown: float
    volatility_annual: float
    beta: float
    recommended_size: float
    risk_score: str        # LOW / MEDIUM / HIGH / EXTREME
    stop_loss_price: float
    take_profit_price: float


class RiskEvaluator:
    """Calculates comprehensive risk metrics."""

    def __init__(self, config: TradingConfig):
        self.config = config

    def value_at_risk(self, returns: pd.Series, confidence: float = 0.95) -> float:
        """Historical Value at Risk."""
        return float(np.percentile(returns.dropna(), (1 - confidence) * 100))

    def conditional_var(self, returns: pd.Series, confidence: float = 0.95) -> float:
        """Conditional VaR (Expected Shortfall)."""
        var = self.value_at_risk(returns, confidence)
        return float(returns[returns <= var].mean())

    def sharpe_ratio(self, returns: pd.Series, risk_free_rate: float = 0.05) -> float:
        """Annualized Sharpe Ratio."""
        daily_rf = risk_free_rate / 252
        excess = returns - daily_rf
        if excess.std() == 0:
            return 0.0
        return float((excess.mean() / excess.std()) * np.sqrt(252))

    def max_drawdown(self, prices: pd.Series) -> float:
        """Maximum Drawdown."""
        cumulative = (1 + prices.pct_change()).cumprod()
        rolling_max = cumulative.cummax()
        drawdown = (cumulative - rolling_max) / rolling_max
        return float(drawdown.min())

    def beta(self, returns: pd.Series, market_returns: pd.Series) -> float:
        """Beta relative to the market."""
        aligned = returns.align(market_returns, join="inner")
        cov = np.cov(aligned[0].dropna(), aligned[1].dropna())
        if cov[1, 1] == 0:
            return 1.0
        return float(cov[0, 1] / cov[1, 1])

    def kelly_position_size(self, win_rate: float, avg_win: float, avg_loss: float) -> float:
        """Kelly Criterion for optimal position sizing."""
        if avg_loss == 0:
            return 0.0
        b = avg_win / abs(avg_loss)
        kelly = (b * win_rate - (1 - win_rate)) / b
        return max(0.0, min(kelly * 0.5, self.config.max_position_size))  # Half-Kelly

    def evaluate(self, symbol: str, df: pd.DataFrame,
                 market_df: Optional[pd.DataFrame] = None) -> RiskMetrics:
        """Calculates all risk metrics for a symbol."""
        close = df["Close"]
        returns = close.pct_change().dropna()

        var = self.value_at_risk(returns, self.config.var_confidence)
        cvar = self.conditional_var(returns, self.config.var_confidence)
        sharpe = self.sharpe_ratio(returns)
        mdd = self.max_drawdown(close)
        vol_annual = float(returns.std() * np.sqrt(252))

        beta_val = 1.0
        if market_df is not None and not market_df.empty:
            mkt_returns = market_df["Close"].pct_change().dropna()
            beta_val = self.beta(returns, mkt_returns)

        risk_score = self._classify_risk(var, vol_annual, mdd, sharpe)

        wins = returns[returns > 0]
        losses = returns[returns < 0]
        win_rate = len(wins) / len(returns) if len(returns) > 0 else 0.5
        avg_win = float(wins.mean()) if len(wins) > 0 else 0.01
        avg_loss = float(losses.mean()) if len(losses) > 0 else -0.01
        pos_size = self.kelly_position_size(win_rate, avg_win, avg_loss)

        if risk_score == "HIGH":
            pos_size *= 0.5
        elif risk_score == "EXTREME":
            pos_size = 0.0

        current_price = float(close.iloc[-1])
        stop_loss = current_price * (1 - self.config.stop_loss_pct)
        take_profit = current_price * (1 + self.config.take_profit_pct)

        return RiskMetrics(
            symbol=symbol,
            var_95=round(var * 100, 3),
            cvar_95=round(cvar * 100, 3),
            sharpe_ratio=round(sharpe, 3),
            max_drawdown=round(mdd * 100, 2),
            volatility_annual=round(vol_annual * 100, 2),
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


# ─── Portfolio ────────────────────────────────────────────────────────────────
@dataclass
class Position:
    symbol: str
    shares: float
    entry_price: float
    entry_time: datetime
    stop_loss: float
    take_profit: float

    @property
    def current_value(self) -> float:
        return self.shares * self.entry_price


@dataclass
class Trade:
    symbol: str
    action: str      # BUY / SELL / HOLD
    shares: float
    price: float
    timestamp: datetime
    reason: str
    pnl: float = 0.0


class Portfolio:
    """Manages positions and capital."""

    def __init__(self, config: TradingConfig):
        self.config = config
        self.cash = config.initial_capital
        self.positions: dict[str, Position] = {}
        self.trades: list[Trade] = []

    @property
    def total_value(self) -> float:
        pos_value = sum(p.shares * p.entry_price for p in self.positions.values())
        return self.cash + pos_value

    @property
    def portfolio_summary(self) -> dict:
        return {
            "cash": round(self.cash, 2),
            "total_value": round(self.total_value, 2),
            "num_positions": len(self.positions),
            "positions": {
                sym: {"shares": p.shares, "entry_price": p.entry_price,
                      "stop_loss": p.stop_loss, "take_profit": p.take_profit}
                for sym, p in self.positions.items()
            },
            "num_trades": len(self.trades),
            "pnl": round(self.total_value - self.config.initial_capital, 2),
            "pnl_pct": round((self.total_value / self.config.initial_capital - 1) * 100, 2),
        }

    def execute_buy(self, symbol: str, price: float, stop_loss: float,
                    take_profit: float, size_pct: float, reason: str) -> bool:
        if symbol in self.positions:
            log.info(f"Already invested in {symbol} — skipping duplicate buy")
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
        trade = Trade(symbol, "BUY", shares, price, datetime.now(), reason)
        self.trades.append(trade)
        log.info(f"BUY {symbol}: {shares:.4f} @ ${price:.2f} | Reason: {reason}")
        return True

    def execute_sell(self, symbol: str, price: float, reason: str) -> bool:
        if symbol not in self.positions:
            return False

        pos = self.positions.pop(symbol)
        proceeds = pos.shares * price
        pnl = proceeds - pos.shares * pos.entry_price
        self.cash += proceeds

        trade = Trade(symbol, "SELL", pos.shares, price, datetime.now(), reason, pnl)
        self.trades.append(trade)
        log.info(f"SELL {symbol}: {pos.shares:.4f} @ ${price:.2f} | PnL: ${pnl:.2f}")
        return True

    def check_stop_loss_take_profit(self, prices: dict[str, float]) -> list[str]:
        """Checks stop-loss and take-profit for all open positions."""
        to_sell = []
        for sym, pos in list(self.positions.items()):
            price = prices.get(sym)
            if price is None:
                continue
            if price <= pos.stop_loss:
                self.execute_sell(sym, price, f"Stop-loss triggered @ ${price:.2f}")
                to_sell.append(sym)
            elif price >= pos.take_profit:
                self.execute_sell(sym, price, f"Take-profit reached @ ${price:.2f}")
                to_sell.append(sym)
        return to_sell


# ─── AI Analysis via Claude ───────────────────────────────────────────────────
class AIAnalyst:
    """Uses Claude to analyze markets and make trading decisions."""

    def __init__(self):
        self.client = anthropic.Anthropic()  # API key from ANTHROPIC_API_KEY env var

    def analyze(self, symbol: str, indicators: dict, risk: RiskMetrics,
                fundamentals: dict, portfolio: dict) -> dict:
        """Lets Claude make a trading decision based on all available data."""

        prompt = f"""You are an experienced quantitative analyst. Analyze the following data and make a trading decision.

SYMBOL: {symbol}

TECHNICAL INDICATORS:
{json.dumps(indicators, indent=2)}

RISK METRICS:
- VaR (95%): {risk.var_95}%
- CVaR (95%): {risk.cvar_95}%
- Sharpe Ratio: {risk.sharpe_ratio}
- Max Drawdown: {risk.max_drawdown}%
- Annual Volatility: {risk.volatility_annual}%
- Beta: {risk.beta}
- Recommended Position Size: {risk.recommended_size}%
- Risk Rating: {risk.risk_score}

FUNDAMENTAL DATA:
{json.dumps(fundamentals, indent=2)}

PORTFOLIO STATUS:
{json.dumps(portfolio, indent=2)}

Reply ONLY with a JSON object (no markdown):
{{
  "action": "BUY" | "SELL" | "HOLD",
  "confidence": 0-100,
  "reasoning": "Brief justification in English",
  "key_signals": ["Signal 1", "Signal 2"],
  "risk_warning": "Most important risk note or null"
}}"""

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}]
            )
            text = response.content[0].text.strip()
            if "```" in text:
                text = text.split("```")[1].replace("json", "").strip()
            return json.loads(text)
        except Exception as e:
            log.error(f"AI analysis failed for {symbol}: {e}")
            return {"action": "HOLD", "confidence": 0, "reasoning": f"Error: {e}",
                    "key_signals": [], "risk_warning": "AI unavailable"}


# ─── Trading Engine ───────────────────────────────────────────────────────────
class QuantTradingBot:
    """Main class: coordinates all components."""

    def __init__(self, config: TradingConfig):
        self.config = config
        self.data_feed = MarketDataFeed(config)
        self.ta = TechnicalAnalysis()
        self.risk_eval = RiskEvaluator(config)
        self.ai = AIAnalyst()
        self.portfolio = Portfolio(config)

    def run_cycle(self) -> dict:
        """Runs a complete analysis-and-trade cycle."""
        log.info("=" * 60)
        log.info(f"Trading cycle started: {datetime.now().isoformat()}")

        all_data = self.data_feed.get_multi_symbol_data()
        market_df = all_data.get("SPY")
        cycle_results = []

        current_prices = {sym: float(df["Close"].iloc[-1]) for sym, df in all_data.items()}
        self.portfolio.check_stop_loss_take_profit(current_prices)

        for symbol in self.config.symbols:
            if symbol == "SPY":
                continue
            df = all_data.get(symbol)
            if df is None or len(df) < 50:
                continue

            try:
                indicators = self.ta.compute_all(df)
                risk = self.risk_eval.evaluate(symbol, df, market_df)
                fundamentals = self.data_feed.get_fundamentals(symbol)
                decision = self.ai.analyze(
                    symbol, indicators, risk, fundamentals,
                    self.portfolio.portfolio_summary
                )

                log.info(f"{symbol}: {decision['action']} (confidence: {decision['confidence']}%) | {decision['reasoning'][:80]}")

                if risk.risk_score != "EXTREME" and decision["confidence"] >= 60:
                    price = indicators["price"]
                    if decision["action"] == "BUY" and symbol not in self.portfolio.positions:
                        self.portfolio.execute_buy(
                            symbol, price, risk.stop_loss_price,
                            risk.take_profit_price, risk.recommended_size,
                            decision["reasoning"]
                        )
                    elif decision["action"] == "SELL" and symbol in self.portfolio.positions:
                        self.portfolio.execute_sell(symbol, price, decision["reasoning"])

                cycle_results.append({
                    "symbol": symbol,
                    "price": indicators["price"],
                    "decision": decision,
                    "risk": {
                        "score": risk.risk_score,
                        "sharpe": risk.sharpe_ratio,
                        "var_95": risk.var_95,
                        "max_drawdown": risk.max_drawdown,
                        "volatility": risk.volatility_annual,
                    }
                })

            except Exception as e:
                log.error(f"Error processing {symbol}: {e}")

        summary = {
            "timestamp": datetime.now().isoformat(),
            "portfolio": self.portfolio.portfolio_summary,
            "analyses": cycle_results,
        }

        with open("last_cycle.json", "w") as f:
            json.dump(summary, f, indent=2, default=str)

        log.info(f"Portfolio: ${self.portfolio.total_value:,.2f} | PnL: {self.portfolio.portfolio_summary['pnl_pct']}%")
        return summary

    def run_continuous(self):
        """Runs in an infinite loop (paper trading)."""
        log.info(f"Bot started | Capital: ${self.config.initial_capital:,.2f} | Paper: {self.config.paper_trading}")
        while True:
            try:
                self.run_cycle()
                log.info(f"Next cycle in {self.config.rebalance_interval}s...")
                time.sleep(self.config.rebalance_interval)
            except KeyboardInterrupt:
                log.info("Bot stopped")
                break
            except Exception as e:
                log.error(f"Critical error: {e}")
                time.sleep(60)

if __name__ == "__main__":
    config = TradingConfig(
        symbols=["AAPL", "MSFT", "GOOGL", "NVDA", "TSLA", "SPY"],
        initial_capital=100_000.0,
        paper_trading=True,          # Always test with paper trading first!
        rebalance_interval=3600,     # Hourly
    )

    bot = QuantTradingBot(config)

    # Single cycle (for testing)
    results = bot.run_cycle()
    print(json.dumps(results, indent=2, default=str))

    # Uncomment for continuous production mode:
    # bot.run_continuous()
