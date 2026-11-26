import os
import tempfile
import unittest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from Quant_bot_ai import (AIAnalyst, Portfolio, QuantTradingBot, TradingConfig,
                          TechnicalAnalysis)
from quantpy.risk import AuditLog, RiskEngine, RiskLimits

ET = ZoneInfo("America/New_York")
NOW = datetime(2026, 11, 25, 12, 0, tzinfo=ET)


def bars(last_close=None, n=120, seed=3):
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0.01, 0.05, n))
    if last_close:
        close[-1] = last_close
    idx = pd.date_range(end=NOW.astimezone(timezone.utc), periods=n, freq="5min")
    return pd.DataFrame({"Open": close, "High": close + .1, "Low": close - .1,
                         "Close": close, "Volume": 50_000}, index=idx)


class FakeAlpaca:
    is_paper = True

    def __init__(self, data, open_=True):
        self.data, self.open_, self.orders = data, open_, []

    def is_market_open(self): return self.open_
    def get_account(self): return {}
    def get_positions(self): return None
    def get_multi_bars(self, *a, **k): return self.data
    def get_latest_quote_mid(self, s): return 0.0

    def place_limit_order(self, symbol, qty, side, limit_price, client_order_id):
        self.orders.append((symbol, qty, side, limit_price, client_order_id))
        return {"id": f"id{len(self.orders)}"}


class FakeAI:
    def __init__(self, action="BUY", conf=90): self.a, self.c = action, conf
    def analyze(self, *a, **k):
        return {"action": self.a, "confidence": self.c, "reasoning": "test",
                "key_signals": [], "risk_warning": None}


class FakeTA:
    def compute_all(self, df):
        p = float(df["Close"].iloc[-1])
        return {"price": p, "vwap": p - 1, "rsi_14": 50.0, "macd_hist": 0.1, "atr": 0.1}


def make_bot(tmp, data, ai, open_=True):
    limits = RiskLimits(min_price=1.0)
    cfg = TradingConfig(symbols=["AAA", "SPY"], initial_capital=10_000, limits=limits,
                        paper_trading=True)
    audit = AuditLog(os.path.join(tmp, "a.jsonl"))
    risk = RiskEngine(limits, audit, state_path=os.path.join(tmp, "s.json"))
    risk.guard.restricted = set()
    broker = FakeAlpaca(data, open_)
    bot = QuantTradingBot(cfg, audit, broker, ai, risk, now_fn=lambda: NOW)
    bot.ta = FakeTA()
    return bot, broker


class TestBot(unittest.TestCase):
    def setUp(self):
        self._cwd = os.getcwd()
        self.tmp = tempfile.TemporaryDirectory()
        os.chdir(self.tmp.name)           # last_cycle.json lands here

    def tearDown(self):
        os.chdir(self._cwd)
        self.tmp.cleanup()

    def data(self, **kw):
        return {"AAA": bars(**kw), "SPY": bars(seed=9)}

    def test_buy_uses_limit_order_with_algo_flag_and_respects_limits(self):
        bot, broker = make_bot(self.tmp.name, self.data(), FakeAI())
        res = bot.run_cycle()
        self.assertEqual(len(broker.orders), 1)
        sym, qty, side, limit, coid = broker.orders[0]
        self.assertTrue(coid.startswith("QPY-ALGO-"))
        self.assertEqual(side, "buy")
        self.assertLessEqual(qty * limit, 10_000 * 0.10 * 1.01)
        self.assertIn("AAA", bot.portfolio.positions)
        self.assertTrue(res["analyses"][0]["execution"]["executed"])
        self.assertTrue(bot.audit.verify()[0])

    def test_no_order_when_market_closed_or_low_confidence(self):
        bot, broker = make_bot(self.tmp.name, self.data(), FakeAI(), open_=False)
        res = bot.run_cycle()
        self.assertEqual(broker.orders, [])
        self.assertFalse(res["analyses"][0]["execution"]["executed"])
        bot2, broker2 = make_bot(self.tmp.name, self.data(), FakeAI(conf=10))
        bot2.risk.state_path = os.path.join(self.tmp.name, "s2.json")
        bot2.run_cycle()
        self.assertEqual(broker2.orders, [])

    def test_stop_loss_closes_position(self):
        bot, broker = make_bot(self.tmp.name, self.data(), FakeAI())
        bot.run_cycle()
        entry = bot.portfolio.positions["AAA"].entry_price
        broker.data = self.data(last_close=entry * 0.95)
        bot.config.limits.min_seconds_between_orders_per_symbol = 0
        bot.run_cycle()
        self.assertNotIn("AAA", bot.portfolio.positions)
        self.assertEqual(broker.orders[-1][2], "sell")

    def test_kill_switch_blocks_entries(self):
        bot, broker = make_bot(self.tmp.name, self.data(), FakeAI())
        bot.risk.trip("test")
        bot.run_cycle()
        self.assertEqual(broker.orders, [])

    def test_mark_to_market_value(self):
        p = Portfolio(1000)
        p.buy("X", 10, 50, 45, 60, "t")
        p.mark({"X": 60})
        self.assertAlmostEqual(p.total_value, 500 + 600)
        self.assertAlmostEqual(p.sell("X", 60, "t"), 100)


class TestParsing(unittest.TestCase):
    def test_parse_variants(self):
        d = AIAnalyst._parse('```json\n{"action":"buy","confidence":150,"reasoning":"x"}\n```')
        self.assertEqual((d["action"], d["confidence"]), ("BUY", 100))
        with self.assertRaises(ValueError):
            AIAnalyst._parse("no json here")
        with self.assertRaises(ValueError):
            AIAnalyst._parse('{"action":"SHORT","confidence":5}')

    def test_indicators_finite(self):
        out = TechnicalAnalysis().compute_all(bars())
        self.assertTrue(all(np.isfinite(v) for v in out.values()))
        self.assertTrue(0 <= out["rsi_14"] <= 100)
