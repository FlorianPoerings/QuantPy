"""Technical compliance controls.

These checks encode regulatory *design constraints* as code.  They do not make
a deployment compliant by themselves - see ``docs/LEGAL_DE.md`` for what you
still have to do as the operator.  QuantPy is a research / paper-trading tool.
"""
from __future__ import annotations

import os
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Deque, Optional, Tuple
from zoneinfo import ZoneInfo

from .limits import RiskLimits
from .orders import OrderRequest

ET = ZoneInfo("America/New_York")

# Exact phrase the operator must put into LEGAL_ACK to enable *live* trading.
# Changing the docs version forces a fresh acknowledgement.
LEGAL_DOC_VERSION = "2026-11"
LIVE_ACK_PHRASE = f"I_HAVE_READ_LEGAL_DE_{LEGAL_DOC_VERSION}_AND_ACCEPT_ALL_RISK"

RESTRICTED_FILE = os.environ.get("QUANTPY_RESTRICTED_FILE", "restricted_symbols.txt")


def load_restricted_symbols(path: str = RESTRICTED_FILE) -> set:
    """Symbols the operator must not trade (inside information, employer
    restrictions, conflicts of interest).  One ticker per line, '#' = comment."""
    out = set()
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.split("#", 1)[0].strip().upper()
                if s:
                    out.add(s)
    return out


def live_trading_enabled(limits: RiskLimits) -> Tuple[bool, str]:
    """Live trading needs three independent opt-ins."""
    if not limits.allow_live_trading:
        return False, "RISK_ALLOW_LIVE_TRADING is not set"
    if os.environ.get("LEGAL_ACK", "") != LIVE_ACK_PHRASE:
        return False, "LEGAL_ACK does not contain the acknowledgement phrase"
    if os.environ.get("QUANTPY_LIVE_CONFIRM", "") != "YES_USE_REAL_MONEY":
        return False, "QUANTPY_LIVE_CONFIRM is not set"
    return True, "ok"


class ComplianceGuard:
    def __init__(self, limits: RiskLimits, restricted: Optional[set] = None):
        self.limits = limits
        self.restricted = restricted if restricted is not None else load_restricted_symbols()
        self._orders: Deque[Tuple[datetime, str, str]] = deque(maxlen=2000)

    # ── bookkeeping ──────────────────────────────────────────────────────────
    def register(self, symbol: str, side: str, when: Optional[datetime] = None) -> None:
        self._orders.append((when or datetime.now(ET), symbol, side))

    def orders_since(self, seconds: int, now: datetime) -> int:
        cut = now - timedelta(seconds=seconds)
        return sum(1 for t, _, _ in self._orders if t >= cut)

    def orders_today(self, now: datetime) -> int:
        return sum(1 for t, _, _ in self._orders if t.astimezone(ET).date() == now.astimezone(ET).date())

    def _last(self, symbol: str, side: Optional[str] = None):
        for t, s, sd in reversed(self._orders):
            if s == symbol and (side is None or sd == side):
                return t
        return None

    # ── checks ───────────────────────────────────────────────────────────────
    def check(self, o: OrderRequest, held_qty: float, market_open: bool,
              now: Optional[datetime] = None) -> list:
        """Return a list of violation strings (empty list = compliant)."""
        L, v = self.limits, []
        now = now or datetime.now(ET)

        if o.side not in ("buy", "sell"):
            v.append(f"unknown side '{o.side}'")
            return v
        if o.qty <= 0 or o.price <= 0:
            v.append("quantity and price must be positive")

        sym = o.symbol.upper()
        if sym in L.blocked_symbols:
            v.append(f"{sym}: leveraged/inverse/volatility product is blocked")
        if sym in self.restricted and not o.is_exit:
            v.append(f"{sym}: on the operator's restricted list (conflict / inside information)")

        # No short selling, no naked sells (Short Selling Regulation, EU 236/2012)
        if o.side == "sell" and o.qty > held_qty + 1e-9:
            v.append(f"sell {o.qty:g} exceeds long position {held_qty:g} (short selling not allowed)")

        if not market_open:
            v.append("market is closed (no orders outside regular session)")
        else:
            t = now.astimezone(ET)
            open_t = t.replace(hour=9, minute=30, second=0, microsecond=0)
            close_t = t.replace(hour=16, minute=0, second=0, microsecond=0)
            if not o.is_exit:
                if t < open_t + timedelta(minutes=L.no_trade_first_minutes):
                    v.append("opening-auction window: no new entries")
                if t > close_t - timedelta(minutes=L.no_trade_last_minutes):
                    v.append("closing window: no new entries")

        # Stale data / fat finger (price manipulation & erroneous orders)
        if o.data_time is not None and not o.is_exit:
            ref = o.data_time
            ref_utc = ref.replace(tzinfo=timezone.utc) if ref.tzinfo is None \
                else ref.astimezone(timezone.utc)
            age = (now.astimezone(timezone.utc) - ref_utc).total_seconds()
            if age > L.max_data_age_seconds:
                v.append(f"market data is {int(age)}s old")
        if o.quote_price and o.price:
            dev = abs(o.quote_price - o.price) / o.price
            if dev > L.max_price_deviation_pct:
                v.append(f"quote deviates {dev:.1%} from last bar (fat-finger guard)")

        if not o.is_exit and o.side == "buy":
            if o.price < L.min_price:
                v.append(f"price {o.price:.2f} below minimum {L.min_price:.2f}")
            if o.avg_dollar_volume is not None and o.avg_dollar_volume < L.min_avg_dollar_volume:
                v.append("insufficient liquidity (avg traded value per bar too low)")

        # Anti-churn / anti-HFT / wash-trade patterns (MAR Art. 12, WpHG)
        if o.source not in ("stop_loss", "kill_switch"):
            if self.orders_since(3600, now) >= L.max_orders_per_hour:
                v.append("hourly order limit reached")
            if self.orders_today(now) >= L.max_orders_per_day:
                v.append("daily order limit reached")
            last = self._last(sym)
            if last and (now - last).total_seconds() < L.min_seconds_between_orders_per_symbol:
                v.append("minimum time between orders in this symbol not reached")
            if o.side == "buy":
                ls = self._last(sym, "sell")
                if ls and (now - ls).total_seconds() < L.min_seconds_reentry_after_sell:
                    v.append("re-entry cool-down after sell (wash-trade / churn guard)")
        return v
