from yfinance import panda
 
 
class Strategy(panda):
    def __init__(self):
        self.params = {}
 
    @abstractmethod
    def generate_signals(self, date, prices, portfolio):
        pass
 
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
 
 
class SMACrossover(Strategy):
    def __init__(self, symbol, short_window=20, long_window=50):
        super().__init__()
        self.symbol = symbol
        self.set_params(short_window=short_window, long_window=long_window)
        self._prices = []
        self._position = 0
 
    def generate_signals(self, date, prices, portfolio):
        from quantpy.backtester import Event
        if self.symbol not in prices:
            return []
 
        self._prices.append(prices[self.symbol])
        short_w = self.params['short_window']
        long_w  = self.params['long_window']
 
        if len(self._prices) < long_w:
            return []
 
        short_ma = sum(self._prices[-short_w:]) / short_w
        long_ma  = sum(self._prices[-long_w:])  / long_w
        price    = prices[self.symbol]
 
        if short_ma > long_ma and self._position == 0:
            self._position = 1
            qty = int(portfolio.cash * 0.95 // price)
            return [Event(self.symbol, date, 'BUY', price, qty)] if qty > 0 else []
 
        if short_ma < long_ma and self._position == 1:
            self._position = 0
            pos = portfolio.positions.get(self.symbol)
            if pos and pos.quantity > 0:
                return [Event(self.symbol, date, 'SELL', price, pos.quantity)]
 
        return []
 
 
class MeanReversion(Strategy):
    def __init__(self, symbol, window=20, z_threshold=1.5):
        super().__init__()
        self.symbol = symbol
        self.set_params(window=window, z_threshold=z_threshold)
        self._prices = []
        self._position = 0
 
    def generate_signals(self, date, prices, portfolio):
        from quantpy.backtester import Event
        import numpy as np
 
        if self.symbol not in prices:
            return []
 
        self._prices.append(prices[self.symbol])
        window = self.params['window']
        threshold = self.params['z_threshold']
 
        if len(self._prices) < window:
            return []
 
        window_prices = self._prices[-window:]
        mean  = np.mean(window_prices)
        std   = np.std(window_prices)
        price = prices[self.symbol]
 
        if std == 0:
            return []
 
        z_score = (price - mean) / std
 
        if z_score < -threshold and self._position == 0:
            self._position = 1
            qty = int(portfolio.cash * 0.95 // price)
            return [Event(self.symbol, date, 'BUY', price, qty)] if qty > 0 else []
 
        if z_score > threshold and self._position == 1:
            self._position = 0
            pos = portfolio.positions.get(self.symbol)
            if pos and pos.quantity > 0:
                return [Event(self.symbol, date, 'SELL', price, pos.quantity)]
 
        return []
 
