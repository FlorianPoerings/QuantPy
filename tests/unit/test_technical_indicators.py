import unittest
import numpy as np
import pandas as pd
import quantpy as qp


class TestIndicators(unittest.TestCase):
    def setUp(self):
        np.random.seed(1)
        self.s = pd.Series(100 + np.cumsum(np.random.normal(0, 1, 120)))

    def test_sma_matches_manual(self):
        r = qp.sma(self.s, 5)
        self.assertAlmostEqual(r.iloc[10], self.s.iloc[6:11].mean())
        self.assertTrue(np.isnan(r.iloc[3]))

    def test_smstd_nonnegative(self):
        self.assertTrue((qp.smstd(self.s, 10).dropna() >= 0).all())

    def test_ema_and_emstd_run(self):
        self.assertEqual(len(qp.ema(self.s, 10)), len(self.s))
        self.assertEqual(len(qp.emstd(self.s, 10)), len(self.s))

    def test_macd_histogram_identity(self):
        m, sig, hist = qp.macd(self.s)
        np.testing.assert_allclose(hist, m - sig)

    def test_stochastic_in_range(self):
        df = pd.DataFrame({'High': self.s + 1, 'Low': self.s - 1, 'Close': self.s})
        _, _, k = qp.full_stochastic(df)
        self.assertTrue(((k.dropna() >= 0) & (k.dropna() <= 100)).all())

    def test_invalid_window(self):
        with self.assertRaises(ValueError):
            qp.sma(self.s, 0)
        with self.assertRaises(ValueError):
            qp.sma([1, 2, 3], 2)

    def test_peg(self):
        self.assertAlmostEqual(qp.peg(20, 10), 2.0)
        self.assertTrue(np.isnan(qp.peg(20, -3)))

    def test_event_profiler(self):
        asset = np.arange(1, 40, dtype=float)
        truth = np.zeros(39); truth[20] = 1
        ev = qp.event_profiler(asset, truth, periods=5)
        self.assertEqual(ev.shape, (1, 10))


class TestStrategies(unittest.TestCase):
    def test_sma_crossover_trades_on_trend(self):
        dates = pd.date_range('2020-01-01', periods=200)
        prices = np.concatenate([np.linspace(100, 60, 100), np.linspace(60, 140, 100)])
        data = {'X': pd.DataFrame({'Close': prices}, index=dates)}
        bt = qp.Backtester(data, qp.SMACrossover('X', 5, 20), initial_cash=10_000).run()
        self.assertGreaterEqual(bt.results()['n_trades'], 1)

    def test_invalid_windows(self):
        with self.assertRaises(ValueError):
            qp.SMACrossover('X', 50, 20)
