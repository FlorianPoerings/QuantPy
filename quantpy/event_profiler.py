import numpy as np


def event_profiler(asset, truth, periods=5):
    """Collect price windows (+/- `periods`) around every event.

    Returns an array of shape (n_events, 2 * periods), each row normalised by
    the price on the event day.
    """
    asset = np.asarray(asset, dtype=float)
    truth = np.asarray(truth)
    cut = []
    for i in range(periods, len(asset) - periods):
        if truth[i] == 1 and asset[i] > 0:
            cut.append(asset[i - periods:i + periods] / asset[i])
    return np.array(cut)


def plot_event_profile(events, name='', show=True):
    import matplotlib.pyplot as plt
    if len(events) == 0:
        raise ValueError("no events to plot")
    mn = events.mean(axis=0) - 1.0
    st = events.std(axis=0)
    plt.errorbar(np.arange(len(mn)), mn, st, label=name)
    plt.xlabel('Periods', fontsize=16)
    plt.ylabel('Price Change %', fontsize=16)
    if len(name) > 1:
        plt.legend(loc='best', shadow=True, fancybox=True)
    if show:
        plt.show()
