import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from quantpy.risk import (AuditLog, ComplianceGuard, OrderRequest, RiskEngine,
                          RiskLimits, metrics, live_trading_enabled, LIVE_ACK_PHRASE)

ET = ZoneInfo("America/New_York")
MIDDAY = datetime(2026, 11, 25, 12, 0, tzinfo=ET)   # a Wednesday, 12:00 ET


def make_engine(tmp, **limit_kw):
    limits = RiskLimits(**limit_kw)
    audit = AuditLog(os.path.join(tmp, "a.jsonl"))
    guard = ComplianceGuard(limits, restricted={"BAD"})
    return RiskEngine(limits, audit, guard, os.path.join(tmp, "state.json"))


def buy(sym="AAPL", qty=5, price=100.0, **kw):
    return OrderRequest(sym, "buy", qty, price, "t", stop_price=price * 0.98, **kw)


class TestAudit(unittest.TestCase):
    def test_chain_verifies_and_detects_tampering(self):
        with tempfile.TemporaryDirectory() as d:
            a = AuditLog(os.path.join(d, "x.jsonl"))
            for i in range(3):
                a.record("e", i=i)
            self.assertEqual(a.verify()[:2], (True, 3))
            lines = open(a.path).read().replace('"i": 1', '"i": 9')
            open(a.path, "w").write(lines)
            self.assertFalse(a.verify()[0])

    def test_chain_continues_after_restart(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.jsonl")
            AuditLog(p).record("a")
            b = AuditLog(p); b.record("b")
            self.assertTrue(b.verify()[0])


class TestLimits(unittest.TestCase):
    def test_leverage_and_short_rejected(self):
        with self.assertRaises(ValueError):
            RiskLimits(allow_short=True).validate()
        with self.assertRaises(ValueError):
            RiskLimits(allow_leverage=True).validate()

    def test_env_override(self):
        os.environ["RISK_MAX_POSITION_PCT"] = "0.05"
        try:
            self.assertEqual(RiskLimits.from_env().max_position_pct, 0.05)
        finally:
            del os.environ["RISK_MAX_POSITION_PCT"]


class TestEngine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.e = make_engine(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_sizing_respects_all_caps(self):
        q = self.e.size_entry(100, equity=10_000, cash=10_000, gross_exposure=0)
        self.assertLessEqual(q * 100, 10_000 * self.e.limits.max_position_pct + 1e-6)
        self.assertGreater(q, 0)

    def test_cash_reserve_blocks(self):
        q = self.e.size_entry(100, equity=10_000, cash=2_000, gross_exposure=0)
        self.assertEqual(q, 0.0)

    def test_approves_normal_buy_and_reduces_oversize(self):
        d = self.e.pre_trade(buy(qty=1000), 10_000, 10_000, {}, True, MIDDAY)
        self.assertTrue(d.approved)
        self.assertLess(d.qty, 1000)

    def test_blocks_closed_market_blocked_symbol_restricted(self):
        self.assertFalse(self.e.pre_trade(buy(), 10_000, 10_000, {}, False, MIDDAY).approved)
        self.assertFalse(self.e.pre_trade(buy("TQQQ"), 10_000, 10_000, {}, True, MIDDAY).approved)
        self.assertFalse(self.e.pre_trade(buy("BAD"), 10_000, 10_000, {}, True, MIDDAY).approved)

    def test_no_short_selling(self):
        o = OrderRequest("AAPL", "sell", 5, 100, "t", is_exit=False)
        d = self.e.pre_trade(o, 10_000, 10_000, {}, True, MIDDAY)
        self.assertFalse(d.approved)

    def test_exit_allowed_when_kill_switch_active(self):
        self.e.trip("test")
        pos = {"AAPL": {"qty": 5, "value": 500}}
        o = OrderRequest("AAPL", "sell", 5, 100, "x", "kill_switch", is_exit=True)
        self.assertTrue(self.e.pre_trade(o, 10_000, 9_500, pos, True, MIDDAY).approved)
        self.assertFalse(self.e.pre_trade(buy("MSFT"), 10_000, 9_500, pos, True, MIDDAY).approved)

    def test_opening_window_blocks_entries_not_exits(self):
        early = datetime(2026, 11, 25, 9, 35, tzinfo=ET)
        self.assertFalse(self.e.pre_trade(buy(), 10_000, 10_000, {}, True, early).approved)

    def test_daily_loss_trips_kill_switch_and_persists(self):
        self.e.update_equity(10_000)
        self.e.update_equity(9_600)
        self.assertTrue(self.e.kill_switch)
        e2 = RiskEngine(self.e.limits, self.e.audit, self.e.guard, self.e.state_path)
        self.assertTrue(e2.kill_switch)

    def test_reset_requires_reason(self):
        self.e.trip("x")
        self.assertFalse(self.e.reset("me", " "))
        self.assertTrue(self.e.reset("me", "reviewed"))
        self.assertFalse(self.e.kill_switch)

    def test_consecutive_losses_trip(self):
        for _ in range(self.e.limits.max_consecutive_losses):
            self.e.register_closed_trade(-1)
        self.assertTrue(self.e.kill_switch)

    def test_order_rate_limits_and_reentry_cooldown(self):
        e = make_engine(self.tmp.name + "/b", max_orders_per_hour=2)
        for s in ("A", "B"):
            e.guard.register(s, "buy", MIDDAY - timedelta(minutes=5))
        self.assertFalse(e.pre_trade(buy("C"), 10_000, 10_000, {}, True, MIDDAY).approved)
        e2 = make_engine(self.tmp.name + "/c")
        e2.guard.register("AAPL", "sell", MIDDAY - timedelta(minutes=20))
        self.assertFalse(e2.pre_trade(buy(), 10_000, 10_000, {}, True, MIDDAY).approved)

    def test_stale_data_and_fat_finger(self):
        old = (MIDDAY - timedelta(hours=2)).astimezone(timezone.utc).replace(tzinfo=None)
        self.assertFalse(self.e.pre_trade(buy(data_time=old), 10_000, 10_000, {}, True, MIDDAY).approved)
        self.assertFalse(self.e.pre_trade(buy(quote_price=110.0), 10_000, 10_000, {}, True, MIDDAY).approved)

    def test_penny_stock_and_illiquid(self):
        self.assertFalse(self.e.pre_trade(buy(price=2.0), 10_000, 10_000, {}, True, MIDDAY).approved)
        self.assertFalse(self.e.pre_trade(buy(avg_dollar_volume=1000), 10_000, 10_000, {}, True, MIDDAY).approved)

    def test_max_positions_and_no_pyramiding(self):
        pos = {f"S{i}": {"qty": 1, "value": 100} for i in range(5)}
        self.assertFalse(self.e.pre_trade(buy("NEW"), 10_000, 9_000, pos, True, MIDDAY).approved)
        self.assertFalse(self.e.pre_trade(buy("S1"), 10_000, 9_000, pos, True, MIDDAY).approved)


class TestLiveGate(unittest.TestCase):
    def test_live_needs_three_opt_ins(self):
        L = RiskLimits(allow_live_trading=True)
        for k in ("LEGAL_ACK", "QUANTPY_LIVE_CONFIRM"):
            os.environ.pop(k, None)
        self.assertFalse(live_trading_enabled(L)[0])
        os.environ["LEGAL_ACK"] = LIVE_ACK_PHRASE
        self.assertFalse(live_trading_enabled(L)[0])
        os.environ["QUANTPY_LIVE_CONFIRM"] = "YES_USE_REAL_MONEY"
        try:
            self.assertTrue(live_trading_enabled(L)[0])
            self.assertFalse(live_trading_enabled(RiskLimits())[0])
        finally:
            os.environ.pop("LEGAL_ACK"); os.environ.pop("QUANTPY_LIVE_CONFIRM")


class TestMetrics(unittest.TestCase):
    def test_annualisation_scales_with_timeframe(self):
        self.assertEqual(metrics.periods_per_year("1Day"), 252)
        self.assertEqual(metrics.periods_per_year("5Min"), 252 * 78)

    def test_var_negative_and_cvar_worse(self):
        np.random.seed(0)
        r = pd.Series(np.random.normal(0, 0.01, 500))
        v, c = metrics.var_hist(r), metrics.cvar_hist(r)
        self.assertLess(v, 0)
        self.assertLessEqual(c, v)

    def test_flat_series_is_safe(self):
        r = pd.Series([0.0] * 50)
        self.assertEqual(metrics.sharpe(r, "5Min"), 0.0)
        self.assertEqual(metrics.max_drawdown(pd.Series([100.0] * 10)), 0.0)

    def test_classify_extremes(self):
        self.assertEqual(metrics.classify(-0.01, 0.1, -0.01, 2), "LOW")
        self.assertEqual(metrics.classify(-0.08, 0.9, -0.2, -2), "EXTREME")
