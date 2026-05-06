import numpy as np
import pandas as pd
from pandas import Series, DataFrame
import matplotlib.pyplot as plt
 
 
class Event:
    def __init__(self, symbol, date, action, price, quantity):
        self.symbol = symbol
        self.date = date
        self.action = action      # 'BUY' or 'SELL'
        self.price = price
        self.quantity = quantity
 
    def __repr__(self):
        return f"Event({self.action} {self.quantity}x {self.symbol} @ {self.price:.2f} on {self.date.date()})"
 
 
class Position:
    def __init__(self, symbol):
        self.symbol = symbol
        self.quantity = 0
        self.avg_cost = 0.0
        self.realized_pnl = 0.0
 
    def buy(self, price, quantity):
        total_cost = self.avg_cost * self.quantity + price * quantity
        self.quantity += quantity
        self.avg_cost = total_cost / self.quantity if self.quantity > 0 else 0
 
    def sell(self, price, quantity):
        quantity = min(quantity, self.quantity)
        self.realized_pnl += (price - self.avg_cost) * quantity
        self.quantity -= quantity
 
    def unrealized_pnl(self, current_price):
        return (current_price - self.avg_cost) * self.quantity
 
    def market_value(self, current_price):
        return current_price * self.quantity
 
 
class Portfolio:
    def __init__(self, initial_cash):
        self.cash = initial_cash
        self.initial_cash = initial_cash
        self.positions = {}
        self.history = []
 
    def _get_or_create(self, symbol):
        if symbol not in self.positions:
            self.positions[symbol] = Position(symbol)
        return self.positions[symbol]
 
    def execute(self, event, prices):
        pos = self._get_or_create(event.symbol)
        current_price = prices.get(event.symbol, event.price)
 
        if event.action == 'BUY':
            cost = event.price * event.quantity
            if cost > self.cash:
                event.quantity = int(self.cash // event.price)
                cost = event.price * event.quantity
            if event.quantity > 0:
                self.cash -= cost
                pos.buy(event.price, event.quantity)
 
        elif event.action == 'SELL':
            if pos.quantity > 0:
                event.quantity = min(event.quantity, pos.quantity)
                self.cash += event.price * event.quantity
                pos.sell(event.price, event.quantity)
 
        total_value = self.total_value(prices)
        self.history.append({
            'date': event.date,
            'cash': self.cash,
            'total_value': total_value,
            'event': repr(event)
        })
 
    def total_value(self, prices):
        market_val = sum(
            pos.market_value(prices.get(sym, 0))
            for sym, pos in self.positions.items()
        )
        return self.cash + market_val
 
    def unrealized_pnl(self, prices):
        return sum(
            pos.unrealized_pnl(prices.get(sym, 0))
            for sym, pos in self.positions.items()
        )
 
    def realized_pnl(self):
        return sum(pos.realized_pnl for pos in self.positions.values())
 
 
class Backtester:
    def __init__(self, data, strategy, initial_cash=100_000):
        self.data = data          # dict of {symbol: DataFrame with 'Close'}
        self.strategy = strategy  # callable: (date, prices, portfolio) -> list[Event]
        self.portfolio = Portfolio(initial_cash)
        self.equity_curve = []
        self.events_log = []
 
    def run(self):
        all_dates = sorted(set(
            date for df in self.data.values() for date in df.index
        ))
 
        for date in all_dates:
            prices = {
                sym: df.loc[date, 'Close']
                for sym, df in self.data.items()
                if date in df.index
            }
 
            events = self.strategy(date, prices, self.portfolio)
 
            for event in (events or []):
                self.portfolio.execute(event, prices)
                self.events_log.append(event)
 
            self.equity_curve.append({
                'date': date,
                'value': self.portfolio.total_value(prices),
                'cash': self.portfolio.cash
            })
 
        return self
 
    def results(self):
        curve = DataFrame(self.equity_curve).set_index('date')
        curve['returns'] = curve['value'].pct_change()
 
        total_return = (curve['value'].iloc[-1] / self.portfolio.initial_cash) - 1
        n_days = len(curve)
        annual_return = (1 + total_return) ** (252 / n_days) - 1
        sharpe = (curve['returns'].mean() / curve['returns'].std()) * np.sqrt(252)
        rolling_max = curve['value'].cummax()
        drawdown = (curve['value'] - rolling_max) / rolling_max
        max_drawdown = drawdown.min()
 
        return {
            'total_return': total_return,
            'annual_return': annual_return,
            'sharpe_ratio': sharpe,
            'max_drawdown': max_drawdown,
            'n_trades': len(self.events_log),
            'final_value': curve['value'].iloc[-1],
            'equity_curve': curve
        }
 
    def plot(self):
        res = self.results()
        curve = res['equity_curve']
 
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
 
        ax1.plot(curve.index, curve['value'], color='#2563eb', linewidth=1.8)
        ax1.set_ylabel('Portfolio Value ($)')
        ax1.set_title('Backtest Results')
        ax1.grid(True, alpha=0.3)
 
        rolling_max = curve['value'].cummax()
        drawdown = (curve['value'] - rolling_max) / rolling_max
        ax2.fill_between(curve.index, drawdown, 0, color='#dc2626', alpha=0.5)
        ax2.set_ylabel('Drawdown')
        ax2.set_xlabel('Date')
        ax2.grid(True, alpha=0.3)
 
        plt.tight_layout()
        plt.show()
 
        print(f"\n--- Backtest Summary ---")
        print(f"Total Return:    {res['total_return']:.2%}")
        print(f"Annual Return:   {res['annual_return']:.2%}")
        print(f"Sharpe Ratio:    {res['sharpe_ratio']:.2f}")
        print(f"Max Drawdown:    {res['max_drawdown']:.2%}")
        print(f"Total Trades:    {res['n_trades']}")
        print(f"Final Value:     ${res['final_value']:,.2f}")
 
