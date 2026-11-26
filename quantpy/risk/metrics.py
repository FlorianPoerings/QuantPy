"""Risk metrics with correct annualisation for intraday bars."""
from __future__ import annotations

import numpy as np
import pandas as pd

# Regular US session: 390 one-minute bars, 252 trading days.
BARS_PER_DAY = {"1Min": 390, "5Min": 78, "15Min": 26, "30Min": 13,
                "1Hour": 7, "1Day": 1}


def bars_per_day(timeframe: str) -> int:
    return BARS_PER_DAY.get(timeframe, 1)


def periods_per_year(timeframe: str) -> int:
    return 252 * bars_per_day(timeframe)


def var_hist(returns: pd.Series, confidence: float = 0.95) -> float:
    r = returns.dropna()
    if len(r) < 10:
        return 0.0
    return float(np.percentile(r, (1 - confidence) * 100))


def cvar_hist(returns: pd.Series, confidence: float = 0.95) -> float:
    r = returns.dropna()
    if len(r) < 10:
        return 0.0
    v = var_hist(r, confidence)
    tail = r[r <= v]
    return float(tail.mean()) if len(tail) else v


def scale_to_horizon(x: float, bars: int) -> float:
    """Square-root-of-time scaling (rough; assumes i.i.d. returns)."""
    return float(x * np.sqrt(max(bars, 1)))


def sharpe(returns: pd.Series, timeframe: str, risk_free_annual: float = 0.0) -> float:
    r = returns.dropna()
    if len(r) < 10:
        return 0.0
    ppy = periods_per_year(timeframe)
    excess = r - risk_free_annual / ppy
    sd = excess.std()
    if not np.isfinite(sd) or sd == 0:
        return 0.0
    return float(excess.mean() / sd * np.sqrt(ppy))


def max_drawdown(prices: pd.Series) -> float:
    p = prices.dropna()
    if len(p) < 2:
        return 0.0
    dd = p / p.cummax() - 1.0
    return float(dd.min())


def annual_vol(returns: pd.Series, timeframe: str) -> float:
    r = returns.dropna()
    if len(r) < 2:
        return 0.0
    return float(r.std() * np.sqrt(periods_per_year(timeframe)))


def beta(returns: pd.Series, market: pd.Series) -> float:
    df = pd.concat([returns, market], axis=1, join="inner").dropna()
    if len(df) < 10:
        return 1.0
    var_m = df.iloc[:, 1].var()
    if not np.isfinite(var_m) or var_m == 0:
        return 1.0
    return float(df.iloc[:, 0].cov(df.iloc[:, 1]) / var_m)


def classify(var_1d: float, vol: float, mdd: float, sh: float) -> str:
    score = 0
    score += 2 if var_1d < -0.05 else 1 if var_1d < -0.03 else 0
    score += 2 if vol > 0.60 else 1 if vol > 0.35 else 0
    score += 2 if mdd < -0.10 else 1 if mdd < -0.05 else 0
    score += 2 if sh < -1 else 1 if sh < 0 else 0
    return "EXTREME" if score >= 6 else "HIGH" if score >= 4 else \
           "MEDIUM" if score >= 2 else "LOW"
