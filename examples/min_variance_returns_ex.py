from pylab import *
import quantpy as qp

syms = ['IBM','GOOG','MSFT','AAPL','INTC']
cols = ['b','r','g','k','m','y']
o
P = qp.Portfolio(syms)

for sym,col in zip(syms,cols):
    P.nplot(sym,col)
show()
