import sys
sys.path.insert(0, '../..')
 
from datetime import datetime
import quantpy as qp
 
start = datetime(2020, 1, 1)
end   = datetime(2023, 12, 31)
 
p = qp.Portfolio(['AAPL', 'MSFT', 'GOOG'], start=start, end=end)
 
print("=== Betas ===")
print(p.betas())
 
print("\n=== Sharpe Ratios ===")
print(p.sharpes())
 
print("\n=== Optimal Weights (Sharpe) ===")
print(p.get_w(kind='sharpe'))
 
print("\n=== Covariance Matrix ===")
print(p.cov())
 
p.efficient_frontier_plot()
