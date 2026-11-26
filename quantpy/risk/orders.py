from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class OrderRequest:
    symbol: str
    side: str                      # "buy" | "sell"
    qty: float
    price: float                   # reference price (last bar / quote)
    reason: str = ""
    source: str = "ai"             # "ai" | "stop_loss" | "take_profit" | "kill_switch"
    is_exit: bool = False          # reduces an existing long position
    stop_price: Optional[float] = None
    quote_price: Optional[float] = None   # independent quote for sanity check
    data_time: Optional[datetime] = None  # timestamp of the last bar used
    avg_dollar_volume: Optional[float] = None

    @property
    def notional(self) -> float:
        return self.qty * self.price


@dataclass
class Decision:
    approved: bool
    qty: float = 0.0
    reasons: list = field(default_factory=list)     # why rejected / reduced
    checks: list = field(default_factory=list)      # passed checks (for audit)

    def to_dict(self) -> dict:
        return {"approved": self.approved, "qty": round(self.qty, 6),
                "reasons": self.reasons}
