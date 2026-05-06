import sys
sys.path.insert(0, '../..')
 
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from quantpy.backtester import Backtester
from quantpy.strategy import BuyAndHold, SMACrossover, MeanReversion
 
 
def make_synthetic_data(n_days=500, start_price=100, drift=0.0003, vol=0.015, seed=42):
    np.random.seed(seed)
    dates  = [datetime(2020, 1, 1) + timedelta(days=i) for i in range(n_days)]
    log_returns = np.random.normal(drift, vol, n_days)
    prices = start_price * np.exp(np.cumsum(log_returns))
    df = pd.DataFrame({'Close': prices}, index=dates)
    return df
 
 
data = {'SYNTH': make_synthetic_data()}
 
print("=" * 50)
print("Strategy 1: Buy and Hold")
print("=" * 50)
 
strategy_bah = BuyAndHold(symbol='SYNTH', quantity=100)
bt_bah = Backtester(data, strategy_bah.generate_signals, initial_cash=10_000)
bt_bah.run()
bt_bah.plot()
 
print("\n" + "=" * 50)
print("Strategy 2: SMA Crossover (20 / 50)")
print("=" * 50)
 
strategy_sma = SMACrossover(symbol='SYNTH', short_window=20, long_window=50)
bt_sma = Backtester(data, strategy_sma.generate_signals, initial_cash=10_000)
bt_sma.run()
bt_sma.plot()
 
print("\n" + "=" * 50)
print("Strategy 3: Mean Reversion (window=20, z=1.5)")
print("=" * 50)
 
strategy_mr = MeanReversion(symbol='SYNTH', window=20, z_threshold=1.5)
bt_mr = Backtester(data, strategy_mr.generate_signals, initial_cash=10_000)
bt_mr.run()
bt_mr.plot()
 
print("\n" + "=" * 50)
print("Comparison")
print("=" * 50)
 
results = {
    'Buy & Hold':     bt_bah.results(),
    'SMA Crossover':  bt_sma.results(),
    'Mean Reversion': bt_mr.results(),
}
 
print(f"\n{'Strategy':<20} {'Total Return':>14} {'Annual Return':>14} {'Sharpe':>8} {'Max DD':>10}")
print("-" * 68)
for name, r in results.items():
    print(
        f"{name:<20}"
        f"{r['total_return']:>13.2%} "
        f"{r['annual_return']:>13.2%} "
        f"{r['sharpe_ratio']:>7.2f} "
        f"{r['max_drawdown']:>9.2%}"
    )
