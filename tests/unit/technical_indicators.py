import matplotlib.pyplot as plt
from pandas_datareader import data as web
import yfinance as pd
import numpy as np
import pandas as pd
from pandas import Series, DataFrame
 
 
class Portfolio:
    def __init__(self, symbols, start=None, end=None, bench='^GSPC'):
 
        if type(symbols) != list:
            symbols = [symbols]
 
        self.asset = {}
 
        for symbol in symbols:
            try:
                self.asset[symbol] = web.DataReader(
                    symbol, "yahoo", start=start, end=end)
            except Exception:
                print("Asset " + str(symbol) + " not found!")
 
        self.benchmark = web.DataReader(bench, "yahoo", start=start, end=end)
        self.benchmark['Return'] = self.benchmark['Adj Close'].pct_change()
 
        for symbol in symbols:
            self.asset[symbol]['Return'] = \
                self.asset[symbol]['Adj Close'].pct_change()
 
            A = self.asset[symbol]['Return'].fillna(0)
            B = self.benchmark['Return'].fillna(0)
            cov_matrix = np.cov(A, B)
            self.asset[symbol].attrs['Beta'] = cov_matrix[0, 1] / cov_matrix[1, 1]
            self.asset[symbol].attrs['Alpha'] = (
                A.mean() - self.asset[symbol].attrs['Beta'] * B.mean()
            )
 
            tmp = self.asset[symbol]['Return'].dropna()
            self.asset[symbol].attrs['Sharpe'] = (
                np.sqrt(252) * tmp.mean() / tmp.std()
            )
 
    def nplot(self, symbol, color='b', nval=0):
        tmp = (self.benchmark if symbol == 'bench'
               else self.asset[symbol])['Adj Close']
        tmp = tmp / tmp.iloc[nval]
        tmp.plot(color=color, label=symbol)
        plt.legend(loc='best', shadow=True, fancybox=True)
 
    def betas(self):
        betas = [v.attrs['Beta'] for v in self.asset.values()]
        return Series(betas, index=self.asset.keys())
 
    def sharpes(self):
        sharpes = [v.attrs['Sharpe'] for v in self.asset.values()]
        return Series(sharpes, index=self.asset.keys())
 
    def returns(self):
        returns = [v['Return'].dropna() for v in self.asset.values()]
        return Series(returns, index=self.asset.keys())
 
    def cov(self):
        keys = list(self.asset.keys())
        ret_matrix = np.array([
            self.asset[k]['Return'].fillna(0).values for k in keys
        ])
        return DataFrame(np.cov(ret_matrix), index=keys, columns=keys)
 
    def get_w(self, kind='sharpe'):
        V = self.cov()
        iV = np.matrix(np.linalg.inv(V))
 
        if kind == 'characteristic':
            e = np.matrix(np.ones(len(self.asset))).T
        elif kind == 'sharpe':
            suml = [self.returns()[s].sum() for s in self.asset.keys()]
            e = np.matrix(suml).T
        else:
            print('\n  *Error: No weighting for kind ' + kind)
            return
 
        num = iV * e
        denom = e.T * iV * e
        w = np.array(num / denom).flatten()
        return Series(w, index=self.asset.keys())
 
    def ret_for_w(self, w):
        tmp = self.returns()
        tmpl = [v * wi for v, wi in zip(tmp.values, w)]
        return sum(tmpl)
 
    def efficient_frontier_w(self, fp):
        wc = self.get_w(kind='characteristic')
        wq = self.get_w(kind='sharpe')
 
        fc = self.ret_for_w(wc).sum()
        fq = self.ret_for_w(wq).sum()
 
        denom = fq - fc
        w = (fq - fp) * wc + (fp - fc) * wq
        return Series(w / denom, index=self.asset.keys())
 
    def efficient_frontier(self, xi=0.01, xf=4, npts=100):
        frontier = np.linspace(xi, xf, npts)
 
        rets = np.zeros(len(frontier))
        sharpe = np.zeros(len(frontier))
        for i, f in enumerate(frontier):
            w = self.efficient_frontier_w(f)
            tmp = self.ret_for_w(w)
            rets[i] = tmp.sum()
            sharpe[i] = tmp.mean() / tmp.std() * np.sqrt(len(tmp))
 
        risk = rets / sharpe
        return Series(rets, index=risk), sharpe.max()
 
    def efficient_frontier_plot(self, xi=0.01, xf=4, npts=100,
                                col1='b', col2='r', newfig=True, plabel=''):
        eff, m = self.efficient_frontier(xi, xf, npts)
 
        if newfig:
            plt.figure()
 
        plt.plot(np.array(eff.index), np.array(eff), col1,
                 linewidth=2, label="Efficient Frontier " + plabel)
        plt.plot(
            np.hstack((0, np.array(eff.index))),
            np.hstack((0, m * np.array(eff.index))),
            col2, linewidth=2, label="Max Sharpe Ratio: %6.2g" % m
        )
        plt.legend(loc='best', shadow=True, fancybox=True)
        plt.xlabel('Risk %', fontsize=16)
        plt.ylabel('Return %', fontsize=16)
        plt.show()
