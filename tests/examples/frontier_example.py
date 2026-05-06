import sys
sys.path.insert(0, '../..')
 
from datetime import datetime
import quantpy as qp
 
start = datetime(2020, 1, 1)
end   = datetime(2023, 12, 31)
 
p = qp.Portfolio(['AAPL', 'MSFT', 'AMZN', 'GOOG'], start=start, end=end)
 
print("=== Min Variance Weights ===")
w_min = p.get_w(kind='characteristic')
print(w_min)
print(f"Expected return: {p.ret_for_w(w_min).sum():.4f}")
 
print("\n=== Max Sharpe Weights ===")
w_sharpe = p.get_w(kind='sharpe')
print(w_sharpe)
print(f"Expected return: {p.ret_for_w(w_sharpe).sum():.4f}")
 
p.efficient_frontier_plot(plabel='AAPL/MSFT/AMZN/GOOG')
