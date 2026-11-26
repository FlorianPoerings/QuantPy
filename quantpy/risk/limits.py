"""Risk limits for the QuantPy trading bot.

All limits are *hard* limits enforced in code by :class:`quantpy.risk.RiskEngine`
and :class:`quantpy.risk.ComplianceGuard`.  The AI model can propose trades,
it can never override a limit.

Every value can be overridden through environment variables with the prefix
``RISK_`` (e.g. ``RISK_MAX_POSITION_PCT=0.05``).  Limits can only be *loosened*
deliberately, which is why they are logged to the audit trail at start-up.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, fields, asdict


# Leveraged / inverse exchange-traded products are blocked by default.
# They are complex products with daily reset (see docs/LEGAL_DE.md) and
# are not suitable for an unattended algorithm.
DEFAULT_BLOCKED_SYMBOLS = frozenset({
    "TQQQ", "SQQQ", "SOXL", "SOXS", "FNGU", "FNGD", "LABU", "LABD",
    "SPXL", "SPXS", "UPRO", "SPXU", "UDOW", "SDOW", "TNA", "TZA",
    "UVXY", "SVXY", "VXX", "VIXY",
})


@dataclass
class RiskLimits:
    # ── Position sizing / exposure ───────────────────────────────────────────
    max_position_pct: float = 0.10        # max. share of equity in one symbol
    max_gross_exposure_pct: float = 0.60  # max. share of equity invested overall
    max_open_positions: int = 5
    min_cash_reserve_pct: float = 0.20    # cash that is never invested
    max_order_notional: float = 2_500.0   # hard cap per single order (account currency)
    risk_per_trade_pct: float = 0.005     # equity risked per trade up to the stop-loss

    # ── Loss limits (kill switch) ────────────────────────────────────────────
    max_daily_loss_pct: float = 0.03      # trips kill switch
    max_drawdown_pct: float = 0.10        # from equity peak, trips kill switch
    max_consecutive_losses: int = 4       # trips kill switch
    flatten_on_kill: bool = True          # close all positions when tripped

    # ── Exits ────────────────────────────────────────────────────────────────
    stop_loss_pct: float = 0.02
    take_profit_pct: float = 0.04

    # ── Activity limits (anti-HFT / anti-churn, see docs/LEGAL_DE.md) ────────
    max_orders_per_hour: int = 12
    max_orders_per_day: int = 40
    min_seconds_between_orders_per_symbol: int = 900
    min_seconds_reentry_after_sell: int = 1800   # also avoids wash-trade patterns
    min_cycle_interval_seconds: int = 60

    # ── Market quality ───────────────────────────────────────────────────────
    min_price: float = 5.0                # no penny stocks
    min_avg_dollar_volume: float = 250_000.0   # avg. traded value per bar
    max_data_age_seconds: int = 900       # reject stale prices
    max_price_deviation_pct: float = 0.02 # "fat finger": quote vs. last bar
    no_trade_first_minutes: int = 10      # skip the opening auction chaos
    no_trade_last_minutes: int = 10
    limit_slippage_pct: float = 0.002     # marketable limit orders, never market

    # ── Hard compliance switches (see ComplianceGuard) ───────────────────────
    allow_short: bool = False
    allow_leverage: bool = False
    allow_live_trading: bool = False      # paper only unless explicitly enabled
    blocked_symbols: frozenset = field(default_factory=lambda: DEFAULT_BLOCKED_SYMBOLS)

    @classmethod
    def from_env(cls) -> "RiskLimits":
        base = cls()
        for f in fields(cls):
            raw = os.environ.get(f"RISK_{f.name.upper()}")
            if raw is None or raw == "":
                continue
            cur = getattr(base, f.name)
            if f.name == "blocked_symbols":
                extra = {s.strip().upper() for s in raw.split(",") if s.strip()}
                setattr(base, f.name, frozenset(DEFAULT_BLOCKED_SYMBOLS | extra))
            elif isinstance(cur, bool):
                setattr(base, f.name, raw.strip().lower() in ("1", "true", "yes"))
            elif isinstance(cur, int):
                setattr(base, f.name, int(raw))
            elif isinstance(cur, float):
                setattr(base, f.name, float(raw))
        base.validate()
        return base

    def validate(self) -> None:
        if not 0 < self.max_position_pct <= 0.5:
            raise ValueError("max_position_pct must be in (0, 0.5]")
        if not 0 < self.max_gross_exposure_pct <= 1.0:
            raise ValueError("max_gross_exposure_pct must be in (0, 1]")
        if self.min_cash_reserve_pct + self.max_gross_exposure_pct > 1.0 + 1e-9:
            raise ValueError("exposure + cash reserve must not exceed 100%")
        if not 0 < self.stop_loss_pct < 0.5:
            raise ValueError("stop_loss_pct must be in (0, 0.5)")
        if self.take_profit_pct <= 0:
            raise ValueError("take_profit_pct must be > 0")
        if self.allow_leverage:
            raise ValueError("Leverage is not supported by QuantPy.")
        if self.allow_short:
            raise ValueError("Short selling is not supported by QuantPy "
                             "(Short Selling Regulation, see docs/LEGAL_DE.md).")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["blocked_symbols"] = sorted(self.blocked_symbols)
        return d
