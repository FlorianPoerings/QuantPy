import unittest
import numpy as np
import pandas as pd
from unittest.mock import patch
from quantpy.portfolio import Portfolio
 
 
def make_mock_df(prices, index=None):
    if index is None:
        index = pd.date_range('2020-01-01', periods=len(prices))
    return pd.DataFrame({'Adj Close': prices}, index=index)
 
 
MOCK_PRICES = {
    'AAPL': [100, 102, 101, 105, 107, 110, 108, 112, 115, 113],
    'MSFT': [200, 198, 203, 205, 207, 204, 210, 212, 208, 215],
    '^GSPC': [300, 302, 301, 305, 307, 310, 308, 312, 315, 313],
}
 
 
def mock_data_reader(symbol, *args, **kwargs):
    return make_mock_df(MOCK_PRICES[symbol])
 
 
class TestPortfolioInit(unittest.TestCase):
    @patch('quantpy.portfolio.web.DataReader', side_effect=mock_data_reader)
    def setUp(self, _):
        self.portfolio = Portfolio(['AAPL', 'MSFT'])
 
    def test_assets_loaded(self):
        self.assertIn('AAPL', self.portfolio.asset)
        self.assertIn('MSFT', self.portfolio.asset)
 
    def test_returns_calculated(self):
        self.assertIn('Return', self.portfolio.asset['AAPL'].columns)
        self.assertIn('Return', self.portfolio.asset['MSFT'].columns)
 
    def test_beta_is_scalar(self):
        beta = self.portfolio.asset['AAPL'].attrs['Beta']
        self.assertIsInstance(beta, float)
 
    def test_sharpe_is_scalar(self):
        sharpe = self.portfolio.asset['AAPL'].attrs['Sharpe']
        self.assertIsInstance(sharpe, float)
 
    def test_alpha_is_scalar(self):
        alpha = self.portfolio.asset['AAPL'].attrs['Alpha']
        self.assertIsInstance(alpha, float)
 
 
class TestPortfolioBetas(unittest.TestCase):
    @patch('quantpy.portfolio.web.DataReader', side_effect=mock_data_reader)
    def setUp(self, _):
        self.portfolio = Portfolio(['AAPL', 'MSFT'])
 
    def test_betas_returns_series(self):
        betas = self.portfolio.betas()
        self.assertIsInstance(betas, pd.Series)
 
    def test_betas_has_correct_index(self):
        betas = self.portfolio.betas()
        self.assertIn('AAPL', betas.index)
        self.assertIn('MSFT', betas.index)
 
    def test_betas_are_finite(self):
        for b in self.portfolio.betas():
            self.assertTrue(np.isfinite(b))
 
 
class TestPortfolioCov(unittest.TestCase):
    @patch('quantpy.portfolio.web.DataReader', side_effect=mock_data_reader)
    def setUp(self, _):
        self.portfolio = Portfolio(['AAPL', 'MSFT'])
 
    def test_cov_returns_dataframe(self):
        self.assertIsInstance(self.portfolio.cov(), pd.DataFrame)
 
    def test_cov_is_square(self):
        c = self.portfolio.cov()
        self.assertEqual(c.shape[0], c.shape[1])
 
    def test_cov_diagonal_positive(self):
        c = self.portfolio.cov()
        for i in range(len(c)):
            self.assertGreater(c.iloc[i, i], 0)
 
    def test_cov_is_symmetric(self):
        c = self.portfolio.cov()
        np.testing.assert_array_almost_equal(c.values, c.values.T)
 
 
class TestPortfolioWeights(unittest.TestCase):
    @patch('quantpy.portfolio.web.DataReader', side_effect=mock_data_reader)
    def setUp(self, _):
        self.portfolio = Portfolio(['AAPL', 'MSFT'])
 
    def test_get_w_sharpe_returns_series(self):
        w = self.portfolio.get_w(kind='sharpe')
        self.assertIsInstance(w, pd.Series)
 
    def test_get_w_characteristic_returns_series(self):
        w = self.portfolio.get_w(kind='characteristic')
        self.assertIsInstance(w, pd.Series)
 
    def test_get_w_invalid_kind_returns_none(self):
        result = self.portfolio.get_w(kind='invalid')
        self.assertIsNone(result)
 
    def test_weights_sum_to_one(self):
        w = self.portfolio.get_w(kind='sharpe')
        self.assertAlmostEqual(w.sum(), 1.0, places=5)
 
    def test_characteristic_weights_sum_to_one(self):
        w = self.portfolio.get_w(kind='characteristic')
        self.assertAlmostEqual(w.sum(), 1.0, places=5)
 
 
class TestPortfolioSharpes(unittest.TestCase):
    @patch('quantpy.portfolio.web.DataReader', side_effect=mock_data_reader)
    def setUp(self, _):
        self.portfolio = Portfolio(['AAPL', 'MSFT'])
 
    def test_sharpes_returns_series(self):
        self.assertIsInstance(self.portfolio.sharpes(), pd.Series)
 
    def test_sharpes_finite(self):
        for s in self.portfolio.sharpes():
            self.assertTrue(np.isfinite(s))
 
 
if __name__ == '__main__':
    unittest.main()
