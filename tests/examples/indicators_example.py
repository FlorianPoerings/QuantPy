import sys
sys.path.insert(0, '../..')
 
import pandas as pd
import matplotlib.pyplot as plt
import quantpy as qp
 
prices = pd.Series([
    100, 102, 101, 105, 107, 110, 108, 112,
    115, 113, 116, 120, 118, 122, 125, 123,
    127, 130, 128, 132, 135, 133, 137, 140
])
 
sma_10 = qp.sma(prices, 10)
sma_20 = qp.sma(prices, 20)
 
print("=== SMA(10) ===")
print(sma_10)
 
print("\n=== SMA(20) ===")
print(sma_20)
 
fig, ax = plt.subplots(figsize=(10, 5))
ax.plot(prices.values,  label='Price',   linewidth=2)
ax.plot(sma_10.values,  label='SMA(10)', linewidth=1.5, linestyle='--')
ax.plot(sma_20.values,  label='SMA(20)', linewidth=1.5, linestyle=':')
ax.set_title('Price vs Moving Averages')
ax.set_xlabel('Day')
ax.set_ylabel('Price')
ax.legend()
ax.grid(True, alpha=0.3)
plt.tight_layout()
plt.show()
 
