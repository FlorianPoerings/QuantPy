"""Pre-trade risk engine with persistent kill switch."""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from typing import Optional

from .audit import AuditLog
from .compliance import ComplianceGuard, ET
from .limits import RiskLimits
from .orders import Decision, OrderRequest


class RiskEngine:
    def __init__(self, limits: Optional[RiskLimits] = None,
                 audit: Optional[AuditLog] = None,
                 guard: Optional[ComplianceGuard] = None,
                 state_path: str = "audit/risk_state.json"):
        self.limits = limits or RiskLimits.from_env()
        self.limits.validate()
        self.audit = audit or AuditLog()
        self.guard = guard or ComplianceGuard(self.limits)
        self.state_path = state_path
        self._lock = threading.RLock()
        self.peak_equity = 0.0
        self.day = None
        self.day_start_equity = 0.0
        self.consecutive_losses = 0
        self.kill_switch = False
        self.kill_reason = ""
        self.recent_blocks: list = []
        self._load_state()
        self.audit.record("risk_engine_started", limits=self.limits.to_dict(),
                          kill_switch=self.kill_switch)

    # ── persistence (kill switch survives restarts) ──────────────────────────
    def _load_state(self) -> None:
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                s = json.load(f)
            self.kill_switch = bool(s.get("kill_switch"))
            self.kill_reason = s.get("kill_reason", "")
            self.peak_equity = float(s.get("peak_equity", 0.0))
            self.consecutive_losses = int(s.get("consecutive_losses", 0))
        except (OSError, ValueError):
            pass

    def _save_state(self) -> None:
        os.makedirs(os.path.dirname(self.state_path) or ".", exist_ok=True)
        tmp = self.state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"kill_switch": self.kill_switch, "kill_reason": self.kill_reason,
                       "peak_equity": self.peak_equity,
                       "consecutive_losses": self.consecutive_losses}, f)
        os.replace(tmp, self.state_path)

    # ── kill switch ──────────────────────────────────────────────────────────
    def trip(self, reason: str, by: str = "engine") -> None:
        with self._lock:
            if not self.kill_switch:
                self.kill_switch, self.kill_reason = True, reason
                self._save_state()
                self.audit.record("kill_switch_tripped", reason=reason, by=by)

    def reset(self, by: str, reason: str) -> bool:
        with self._lock:
            if not reason.strip():
                return False
            self.kill_switch, self.kill_reason = False, ""
            self.consecutive_losses = 0
            self.peak_equity = self.day_start_equity or self.peak_equity
            self._save_state()
            self.audit.record("kill_switch_reset", by=by, reason=reason)
            return True

    # ── equity tracking ──────────────────────────────────────────────────────
    def update_equity(self, equity: float) -> None:
        with self._lock:
            today = datetime.now(ET).date()
            if self.day != today:
                self.day, self.day_start_equity = today, equity
            self.peak_equity = max(self.peak_equity, equity)
            if self.day_start_equity > 0:
                dl = equity / self.day_start_equity - 1
                if dl <= -self.limits.max_daily_loss_pct:
                    self.trip(f"daily loss {dl:.2%} exceeds limit {self.limits.max_daily_loss_pct:.2%}")
            if self.peak_equity > 0:
                dd = equity / self.peak_equity - 1
                if dd <= -self.limits.max_drawdown_pct:
                    self.trip(f"drawdown {dd:.2%} exceeds limit {self.limits.max_drawdown_pct:.2%}")
            self._save_state()

    def register_closed_trade(self, pnl: float) -> None:
        with self._lock:
            self.consecutive_losses = self.consecutive_losses + 1 if pnl < 0 else 0
            if self.consecutive_losses >= self.limits.max_consecutive_losses:
                self.trip(f"{self.consecutive_losses} consecutive losing trades")
            self._save_state()

    # ── sizing ───────────────────────────────────────────────────────────────
    def size_entry(self, price: float, equity: float, cash: float,
                   gross_exposure: float, stop_pct: Optional[float] = None) -> float:
        """Shares to buy: risk-based, then capped by every exposure limit."""
        L = self.limits
        stop = stop_pct or L.stop_loss_pct
        if price <= 0 or equity <= 0:
            return 0.0
        by_risk = equity * L.risk_per_trade_pct / (price * stop)
        caps = [
            by_risk,
            equity * L.max_position_pct / price,
            max(0.0, equity * L.max_gross_exposure_pct - gross_exposure) / price,
            max(0.0, cash - equity * L.min_cash_reserve_pct) / price,
            L.max_order_notional / price,
        ]
        return max(0.0, round(min(caps), 4))

    # ── the gate ─────────────────────────────────────────────────────────────
    def pre_trade(self, o: OrderRequest, equity: float, cash: float,
                  positions: dict, market_open: bool,
                  now: Optional[datetime] = None) -> Decision:
        """positions: {symbol: {"qty": float, "value": float}}"""
        L = self.limits
        with self._lock:
            held = positions.get(o.symbol, {}).get("qty", 0.0)
            gross = sum(p["value"] for p in positions.values())
            reasons: list = []
            qty = o.qty

            if o.side == "buy":
                if self.kill_switch:
                    reasons.append(f"kill switch active: {self.kill_reason}")
                if o.symbol in positions:
                    reasons.append("position already open (no pyramiding)")
                if len(positions) >= L.max_open_positions:
                    reasons.append(f"max open positions ({L.max_open_positions}) reached")
                cap = self.size_entry(o.price, equity, cash, gross,
                                      stop_pct=(1 - o.stop_price / o.price) if o.stop_price else None)
                if cap <= 0:
                    reasons.append("no capacity left under exposure/cash limits")
                qty = min(qty, cap) if cap > 0 else 0.0
            else:
                qty = min(qty, held) if o.is_exit else qty

            reasons += self.guard.check(
                OrderRequest(**{**o.__dict__, "qty": qty}), held, market_open, now)

            ok = not reasons and qty > 0
            d = Decision(approved=ok, qty=qty if ok else 0.0, reasons=reasons)
            self.audit.record("pre_trade_decision", symbol=o.symbol, side=o.side,
                              requested_qty=o.qty, source=o.source,
                              reason=o.reason[:200], **d.to_dict())
            if not ok:
                self.recent_blocks.append({"time": datetime.now(timezone.utc).isoformat(),
                                           "symbol": o.symbol, "side": o.side,
                                           "reasons": reasons})
                self.recent_blocks = self.recent_blocks[-30:]
            return d

    def post_trade(self, o: OrderRequest, qty: float, price: float, order_id: str = "",
                   when: Optional[datetime] = None) -> None:
        self.guard.register(o.symbol, o.side, when)
        self.audit.record("order_submitted", symbol=o.symbol, side=o.side, qty=qty,
                          price=price, order_id=order_id, source=o.source)

    # ── status for the dashboard ─────────────────────────────────────────────
    def snapshot(self, equity: float = 0.0, positions: Optional[dict] = None) -> dict:
        L, positions = self.limits, positions or {}
        gross = sum(p["value"] for p in positions.values())
        now = datetime.now(ET)
        dl = (equity / self.day_start_equity - 1) if self.day_start_equity and equity else 0.0
        dd = (equity / self.peak_equity - 1) if self.peak_equity and equity else 0.0
        return {
            "kill_switch": self.kill_switch, "kill_reason": self.kill_reason,
            "daily_pnl_pct": round(dl * 100, 2), "daily_loss_limit_pct": L.max_daily_loss_pct * 100,
            "drawdown_pct": round(dd * 100, 2), "drawdown_limit_pct": L.max_drawdown_pct * 100,
            "gross_exposure_pct": round(gross / equity * 100, 2) if equity else 0.0,
            "gross_exposure_limit_pct": L.max_gross_exposure_pct * 100,
            "open_positions": len(positions), "max_open_positions": L.max_open_positions,
            "orders_last_hour": self.guard.orders_since(3600, now),
            "orders_hour_limit": L.max_orders_per_hour,
            "orders_today": self.guard.orders_today(now), "orders_day_limit": L.max_orders_per_day,
            "consecutive_losses": self.consecutive_losses,
            "consecutive_loss_limit": L.max_consecutive_losses,
            "recent_blocks": self.recent_blocks[-10:],
        }
