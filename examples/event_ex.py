import quantpy as qp
from numpy import *

def truth_function(asset):
    truth = zeros(len(asset))
    for i in range(1,len(asset)):
       if  asset[i] - asset[i-1] > 1.0:
           truth[i] = 1
    return truth
    
P = qp.Portfolio(['GOOG','IBM','INTC'])
asset = P.asset['IBM']['Adj Close']
truth = truth_function(asset)
profiles = qp.event_profiler(asset,truth)
qp.plot_event_profile(profiles,name='When price increases $1.')
