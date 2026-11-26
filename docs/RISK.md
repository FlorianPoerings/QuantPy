QuantPy risk system
Every order proposed by the AI (or by a stop/target rule) passes through
`RiskEngine.pre_trade()`. The model can propose; the engine decides.
```
AI / rules ──► OrderRequest ──► RiskEngine ──► ComplianceGuard ──► broker
                                   │                │
                                   └──── AuditLog (hash chain) ◄───┘
```
Layers
Sizing – risk-based: `equity × risk_per_trade_pct / (price × stop_distance)`,
then capped by position size, gross exposure, cash reserve and max order value.
Portfolio limits – max open positions, no pyramiding, cash reserve.
Loss limits (kill switch) – daily loss, drawdown from peak, consecutive
losses. When tripped: new entries are blocked, positions are closed
(`flatten_on_kill`), the state is persisted in `audit/risk_state.json` and
survives restarts. Re-arming needs a fresh 2FA code and a written reason.
Compliance guard – no short selling, no leverage, blocked leveraged/
inverse/volatility ETPs, operator restricted list, market-hours window
(no entries in the first/last 10 min), stale-data and fat-finger checks,
penny-stock and liquidity filters, order-rate limits, per-symbol spacing,
re-entry cool-down after a sell (wash-trade/churn guard).
Execution – marketable limit orders only (never market orders),
client order id `QPY-ALGO-…` flags algorithmic orders.
Audit – every proposal, decision, order, login and kill-switch action is
appended to `audit/audit_log.jsonl`; `verify()` detects edits and deletions.
Default limits (`quantpy/risk/limits.py`)
Limit	Default
Max position	10 % of equity
Max gross exposure	60 %
Cash reserve	20 %
Max open positions	5
Max order value	2,500
Risk per trade	0.5 % of equity
Stop-loss / take-profit	2 % / 4 %
Daily loss → kill switch	3 %
Drawdown → kill switch	10 %
Consecutive losses → kill switch	4
Orders per hour / day	12 / 40
Min. seconds between orders per symbol	900
Re-entry cool-down after sell	1,800 s
Min. price / liquidity	5.00 / 250k per bar
Override with environment variables `RISK_<NAME>` (e.g. `RISK_MAX_POSITION_PCT=0.05`).
`allow_short` and `allow_leverage` cannot be enabled. See also `docs/LEGAL_DE.md`.
Live trading gate
Live trading needs all three: `RISK_ALLOW_LIVE_TRADING=true`,
`QUANTPY_LIVE_CONFIRM=YES_USE_REAL_MONEY`, and `LEGAL_ACK=<phrase>` (see
`quantpy/risk/compliance.py`). The bot additionally refuses to start when
`paper_trading` and `ALPACA_BASE_URL` disagree.
Metrics
Sharpe, volatility and VaR/CVaR use the correct annualisation for the bar size
(`252 × bars per day`). Dashboard VaR is the 1-day figure (square-root-of-time
scaling – a rough estimate, not a guarantee).
Limitations
Historical VaR does not capture gaps, halts or regime changes; stops are not
guaranteed fills; the local book can differ from the broker until the next
reconciliation. Limits reduce, but do not remove, the risk of loss.
