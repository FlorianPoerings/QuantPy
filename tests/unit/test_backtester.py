import unittest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from quantpy.backtester import Event, Position, Portfolio, Backtester
 
 
def make_data(n=100, start_price=100.0, seed=42):
    np.random.seed(seed)
    dates = [datetime(2020, 1, 1) + timedelta(days=i) for i in range(n)]
    prices = start_price * np.exp(np.cumsum(np.random.normal(0.001, 0.01, n)))
    return pd.DataFrame({'Close': prices}, index=dates)
 
 
class TestEvent(unittest.TestCase):
    def test_repr_contains_action(self):
        date = datetime(2020, 1, 1)
        e = Event('AAPL', date, 'BUY', 150.0, 10)
        self.assertIn('BUY', repr(e))
        self.assertIn('AAPL', repr(e))
 
    def test_event_stores_fields(self):
        date = datetime(2020, 1, 1)
        e = Event('MSFT', date, 'SELL', 200.0, 5)
        self.assertEqual(e.symbol, 'MSFT')
        self.assertEqual(e.action, 'SELL')
        self.assertEqual(e.price, 200.0)
        self.assertEqual(e.quantity, 5)
 
 
class TestPosition(unittest.TestCase):
    def setUp(self):
        self.pos = Position('AAPL')
 
    def test_initial_state(self):
        self.assertEqual(self.pos.quantity, 0)
        self.assertEqual(self.pos.avg_cost, 0.0)
        self.assertEqual(self.pos.realized_pnl, 0.0)
 
    def test_buy_updates_quantity(self):
        self.pos.buy(100.0, 10)
        self.assertEqual(self.pos.quantity, 10)
        self.assertAlmostEqual(self.pos.avg_cost, 100.0)
 
    def test_buy_twice_updates_avg_cost(self):
        self.pos.buy(100.0, 10)
        self.pos.buy(200.0, 10)
        self.assertAlmostEqual(self.pos.avg_cost, 150.0)
        self.assertEqual(self.pos.quantity, 20)
 
    def test_sell_reduces_quantity(self):
        self.pos.buy(100.0, 10)
        self.pos.sell(120.0, 5)
        self.assertEqual(self.pos.quantity, 5)
 
    def test_sell_calculates_realized_pnl(self):
        self.pos.buy(100.0, 10)
        self.pos.sell(120.0, 10)
        self.assertAlmostEqual(self.pos.realized_pnl, 200.0)
 
    def test_sell_cannot_exceed_quantity(self):
        self.pos.buy(100.0, 5)
        self.pos.sell(120.0, 100)
        self.assertEqual(self.pos.quantity, 0)
 
    def test_unrealized_pnl(self):
        self.pos.buy(100.0, 10)
        self.assertAlmostEqual(self.pos.unrealized_pnl(110.0), 100.0)
 
    def test_market_value(self):
        self.pos.buy(100.0, 10)
        self.assertAlmostEqual(self.pos.market_value(150.0), 1500.0)
 
 
class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.portfolio = Portfolio(initial_cash=10_000)
 
    def test_initial_cash(self):
        self.assertEqual(self.portfolio.cash, 10_000)
 
    def test_buy_reduces_cash(self):
        date = datetime(2020, 1, 1)
        event = Event('AAPL', date, 'BUY', 100.0, 10)
        self.portfolio.execute(event, {'AAPL': 100.0})
        self.assertAlmostEqual(self.portfolio.cash, 9_000.0)
 
    def test_sell_increases_cash(self):
        date = datetime(2020, 1, 1)
        self.portfolio.execute(Event('AAPL', date, 'BUY', 100.0, 10), {'AAPL': 100.0})
        self.portfolio.execute(Event('AAPL', date, 'SELL', 120.0, 10), {'AAPL': 120.0})
        self.assertAlmostEqual(self.portfolio.cash, 10_200.0)
 
    def test_buy_capped_by_cash(self):
        date = datetime(2020, 1, 1)
        event = Event('AAPL', date, 'BUY', 100.0, 99999)
        self.portfolio.execute(event, {'AAPL': 100.0})
        self.assertGreaterEqual(self.portfolio.cash, 0)
 
    def test_total_value_includes_positions(self):
        date = datetime(2020, 1, 1)
        self.portfolio.execute(Event('AAPL', date, 'BUY', 100.0, 50), {'AAPL': 100.0})
        value = self.portfolio.total_value({'AAPL': 110.0})
        self.assertAlmostEqual(value, 5_000 + 50 * 110.0)
 
    def test_history_logged(self):
        date = datetime(2020, 1, 1)
        self.portfolio.execute(Event('AAPL', date, 'BUY', 100.0, 10), {'AAPL': 100.0})
        self.assertEqual(len(self.portfolio.history), 1)
 
 
class TestBacktester(unittest.TestCase):
    def setUp(self):
        self.data = {'SYNTH': make_data(n=100)}
 
    def _buy_and_hold(self, date, prices, portfolio):
        if not hasattr(self, '_bought'):
            self._bought = True
            return [Event('SYNTH', date, 'BUY', prices['SYNTH'], 10)]
        return []
 
    def test_run_returns_self(self):
        bt = Backtester(self.data, self._buy_and_hold, initial_cash=10_000)
        result = bt.run()
        self.assertIs(result, bt)
 
    def test_equity_curve_length(self):
        bt = Backtester(self.data, self._buy_and_hold, initial_cash=10_000)
        bt.run()
        self.assertEqual(len(bt.equity_curve), 100)
 
    def test_results_keys(self):
        bt = Backtester(self.data, self._buy_and_hold, initial_cash=10_000)
        bt.run()
        r = bt.results()
        for key in ['total_return', 'annual_return', 'sharpe_ratio', 'max_drawdown', 'n_trades']:
            self.assertIn(key, r)
 
    def test_max_drawdown_non_positive(self):
        bt = Backtester(self.data, self._buy_and_hold, initial_cash=10_000)
        bt.run()
        self.assertLessEqual(bt.results()['max_drawdown'], 0)
 
    def test_no_strategy_keeps_cash(self):
        bt = Backtester(self.data, lambda d, p, pf: [], initial_cash=10_000)
        bt.run()
        self.assertAlmostEqual(bt.portfolio.cash, 10_000)
 
    def test_events_logged(self):
        bt = Backtester(self.data, self._buy_and_hold, initial_cash=10_000)
        bt.run()
        self.assertEqual(bt.results()['n_trades'], 1)
 
 
if __name__ == '__main__':
    unittest.main()
 
