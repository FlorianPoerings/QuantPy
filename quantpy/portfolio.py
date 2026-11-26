import numpy as np
import pandas as pd
from pandas import Series, DataFrame


def _download(symbol, start=None, end=None):
    """Return a DataFrame with an 'Adj Close' column for `symbol`."""
    import yfinance as yf
    df = yf.download(symbol, start=start, end=end, auto_adjust=True,
                     progress=False, multi_level_index=False)
    if df is None or df.empty:
        raise ValueError(f"no data for {symbol}")
    df = df.copy()
    df['Adj Close'] = df['Close']      # auto_adjust=True: Close is adjusted
    return df


class Portfolio:
    def __init__(self, symbols, start=None, end=None, bench='^GSPC'):
        if not isinstance(symbols, (list, tuple)):
            symbols = [symbols]

        self.asset = {}
        for symbol in symbols:
            try:
                self.asset[symbol] = _download(symbol, start, end)
            except Exception as exc:
                print(f"Asset {symbol} not found! ({exc})")
        if not self.asset:
            raise ValueError("None of the requested assets could be loaded.")

        self.benchmark = _download(bench, start, end)
        self.benchmark['Return'] = self.benchmark['Adj Close'].pct_change()

        for symbol, df in self.asset.items():
            df['Return'] = df['Adj Close'].pct_change()
            ret = df['Return']
            bench_ret = self.benchmark['Return'].reindex(df.index)
            both = pd.concat([ret, bench_ret], axis=1).dropna()
            if len(both) > 2 and both.iloc[:, 1].var() > 0:
                beta = float(both.iloc[:, 0].cov(both.iloc[:, 1]) / both.iloc[:, 1].var())
                alpha = float(both.iloc[:, 0].mean() - beta * both.iloc[:, 1].mean())
            else:
                beta, alpha = 1.0, 0.0
            df.attrs['Beta'] = beta
            df.attrs['Alpha'] = alpha

            tmp = ret.dropna()
            sd = tmp.std()
            df.attrs['Sharpe'] = float(np.sqrt(252) * tmp.mean() / sd) if sd and sd > 0 else 0.0

    def nplot(self, symbol, color='b', nval=0):
        import matplotlib.pyplot as plt
        tmp = (self.benchmark if symbol == 'bench' else self.asset[symbol])['Adj Close']
        (tmp / tmp.iloc[nval]).plot(color=color, label=symbol)
        plt.legend(loc='best', shadow=True, fancybox=True)

    def betas(self):
        return Series([v.attrs['Beta'] for v in self.asset.values()], index=list(self.asset))

    def sharpes(self):
        return Series([v.attrs['Sharpe'] for v in self.asset.values()], index=list(self.asset))

    def returns(self):
        """DataFrame of daily returns, one column per asset."""
        return DataFrame({k: v['Return'] for k, v in self.asset.items()}).dropna()

    def cov(self):
        r = self.returns()
        return r.cov()

    def get_w(self, kind='sharpe'):
        iV = np.linalg.pinv(self.cov().values)
        r = self.returns()
        if kind == 'characteristic':
            e = np.ones(len(r.columns))
        elif kind == 'sharpe':
            e = r.sum().values
        else:
            print('\n  *Error: No weighting for kind ' + str(kind))
            return None
        # fully invested: normalise by 1' V^-1 e  (original code used e' V^-1 e,
        # whose weights did not sum to 1 for kind='sharpe')
        denom = float(np.ones(len(e)) @ iV @ e)
        if denom == 0:
            raise ValueError("degenerate covariance matrix")
        w = (iV @ e) / denom
        return Series(w, index=r.columns)

    def ret_for_w(self, w):
        """Daily portfolio return series for the weights `w`."""
        r = self.returns()
        return Series(r.values @ np.asarray(w, dtype=float), index=r.index)

    def min_var_w_ret(self, target_return):
        """Minimum-variance weights that reach `target_return` (sum of daily returns)."""
        wc, wq = self.get_w('characteristic'), self.get_w('sharpe')
        fc, fq = self.ret_for_w(wc).sum(), self.ret_for_w(wq).sum()
        if fq == fc:
            return wc
        return (fq - target_return) / (fq - fc) * wc + (target_return - fc) / (fq - fc) * wq

    def efficient_frontier_w(self, fp):
        return self.min_var_w_ret(fp)

    def efficient_frontier(self, xi=0.01, xf=4, npts=100):
        frontier = np.linspace(xi, xf, npts)
        rets, risks, sharpe = [], [], []
        for f in frontier:
            tmp = self.ret_for_w(self.efficient_frontier_w(f))
            sd = tmp.std()
            rets.append(tmp.sum())
            risks.append(sd * np.sqrt(len(tmp)))
            sharpe.append(tmp.sum() / (sd * np.sqrt(len(tmp))) if sd > 0 else np.nan)
        return Series(rets, index=risks), float(np.nanmax(sharpe))

    def efficient_frontier_plot(self, xi=0.01, xf=4, npts=100, col1='b', col2='r',
                                newfig=True, plabel='', show=True):
        import matplotlib.pyplot as plt
        eff, m = self.efficient_frontier(xi, xf, npts)
        if newfig:
            plt.figure()
        plt.plot(np.array(eff.index), np.array(eff), col1, linewidth=2,
                 label="Efficient Frontier " + plabel)
        plt.plot(np.hstack((0, np.array(eff.index))),
                 np.hstack((0, m * np.array(eff.index))), col2, linewidth=2,
                 label="Max Sharpe Ratio: %6.2g" % m)
        plt.legend(loc='best', shadow=True, fancybox=True)
        plt.xlabel('Risk %', fontsize=16)
        plt.ylabel('Return %', fontsize=16)
        if show:
            plt.show()
