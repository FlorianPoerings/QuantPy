import math


def peg(pe_ratio, earnings_growth_pct):
    if pe_ratio is None or earnings_growth_pct is None:
        return math.nan
    if earnings_growth_pct <= 0:
        return math.nan
    return float(pe_ratio) / float(earnings_growth_pct)
