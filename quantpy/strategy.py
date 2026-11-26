from abc import ABC, abstractmethod

import numpy as np


class Strategy(ABC):

    def __init__(self):
        self.params = {}

    @abstractmethod
    def generate_signals(self, date, prices, portfolio):
        """Return a list of ``Event`` objects."""

    def __call__(self, date, prices, portfolio):
        return self.generate_signals(date, prices, portfolio)

    def set_params(self, **kwargs):
        self.params.update(kwargs)
        return self


class BuyAndHold(Strategy):
    def __init__(self, symbol, quantity=1):
        super().__init__()
        self.symbol = symbol
        self.quantity = quantity
        self._bought = False

    def generate_signals(self, date, prices, portfolio):
        from quantpy.backtester import Event
        if not self._bought and self.symbol in prices:
            self._bought = True
            return [Event(self.symbol, date, 'BUY', prices[self.symbol], self.quantity)]
        return []


class _SingleSymbol(Strategy):
    def __init__(self, symbol):
        super().__init__()
        self.symbol = symbol
        self._prices = []

    def _enter(self, date, price, portfolio):
        from quantpy.backtester import Event
        qty = int(portfolio.cash * 0.95 // price)
        return [Event(self.symbol, date, 'BUY', price, qty)] if qty > 0 else []

    def _exit(self, date, price, portfolio):
        from quantpy.backtester import Event
        pos = portfolio.positions.get(self.symbol)
        if pos and pos.quantity > 0:
            return [Event(self.symbol, date, 'SELL', price, pos.quantity)]
        return []

    def _holding(self, portfolio):
        pos = portfolio.positions.get(self.symbol)
        return bool(pos and pos.quantity > 0)


class SMACrossover(_SingleSymbol):
    def __init__(self, symbol, short_window=20, long_window=50):
        super().__init__(symbol)
        if short_window >= long_window:
            raise ValueError("short_window must be smaller than long_window")
        self.set_params(short_window=short_window, long_window=long_window)

    def generate_signals(self, date, prices, portfolio):
        if self.symbol not in prices:
            return []
        price = prices[self.symbol]
        self._prices.append(price)
        s, l = self.params['short_window'], self.params['long_window']
        if len(self._prices) < l:
            return []
        short_ma = np.mean(self._prices[-s:])
        long_ma = np.mean(self._prices[-l:])
        holding = self._holding(portfolio)
        if short_ma > long_ma and not holding:
            return self._enter(date, price, portfolio)
        if short_ma < long_ma and holding:
            return self._exit(date, price, portfolio)
        return []


class MeanReversion(_SingleSymbol):
    def __init__(self, symbol, window=20, z_threshold=1.5):
        super().__init__(symbol)
        self.set_params(window=window, z_threshold=z_threshold)

    def generate_signals(self, date, prices, portfolio):
        if self.symbol not in prices:
            return []
        price = prices[self.symbol]
        self._prices.append(price)
        w, thr = self.params['window'], self.params['z_threshold']
        if len(self._prices) < w:
            return []
        win = self._prices[-w:]
        std = np.std(win)
        if std == 0:
            return []
        z = (price - np.mean(win)) / std
        holding = self._holding(portfolio)
        if z < -thr and not holding:
            return self._enter(date, price, portfolio)
        if z > thr and holding:
            return self._exit(date, price, portfolio)
        return []
