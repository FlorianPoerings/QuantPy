QuantPy
A small Python framework for quantitative finance, plus an AI-assisted paper-trading
bot with a built-in risk and compliance layer and a secured web dashboard.
> **Research software – not investment advice.** Paper trading is the default.
> There is no performance promise; trading can lead to total loss. Read
> [`docs/LEGAL_DE.md`](docs/LEGAL_DE.md) (German) before connecting any real account.
Version 0.6.0 – alpha. APIs may change.
What's inside
Area	Description
`quantpy.Portfolio`	Load prices (Yahoo via `yfinance`), betas, Sharpe ratios, covariance, optimal weights, efficient frontier
`quantpy.Backtester`	Event-driven backtester with commission support, equity curve, Sharpe, drawdown
`quantpy.strategy`	`BuyAndHold`, `SMACrossover`, `MeanReversion` (callable, plug into the backtester)
`quantpy.technical_indicators`	SMA, EMA, rolling/exp. std, MACD, full stochastic
`quantpy.event_profiler`	Event studies around price events
`quantpy.risk`	Risk engine, compliance guard, kill switch, tamper-evident audit log → `docs/RISK.md`
`Quant_bot_ai.py`	Alpaca data/execution + Claude as advisory analyst; every order goes through the risk engine
`server.py` + `dashboard.html`	Flask control panel: password + TOTP 2FA, risk panel, kill switch, audit verification
Quick start (backtesting library)
```bash
git clone https://github.com/FlorianPoerings/QuantPy.git && cd QuantPy
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e .            # core
pip install -e ".[dev]"     # + pytest
```
```python
import quantpy as qp
p = qp.Portfolio(["AAPL", "MSFT", "GOOG"], start="2022-01-01")
print(p.betas(), p.sharpes(), p.get_w(kind="sharpe"), sep="\n")
```
Trading bot & dashboard
```bash
pip install -e ".[bot]"                       # flask, pyotp, anthropic, ...
cp .env.example .env                          # then edit it
python -c "import secrets; print(secrets.token_hex(32))"   # -> SECRET_KEY
python setup_2fa.py                           # scan the QR code (once)
python server.py                              # http://127.0.0.1:5000
```
Log in with password + 6-digit TOTP code (2FA is mandatory).
Accept the risk & legal notice (stored in the audit log).
Run Once for a single analysis or Start Bot for the server-side loop.
The server binds to `127.0.0.1`. Do not expose it to the internet without TLS and a
reverse proxy (`QUANTPY_HTTPS=1` then marks cookies `Secure`).
Required environment variables (`.env.example`)
`ANTHROPIC_API_KEY`, `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`,
`ALPACA_BASE_URL=https://paper-api.alpaca.markets`, `SECRET_KEY`, `QUANT_USER`,
and `QUANT_PASSWORD` or `QUANT_PASSWORD_HASH` (bcrypt, recommended).
Optional: `QUANTPY_MODEL`, `RISK_*` limit overrides.
> **Never commit `.env`.** If a key ever leaves your machine, rotate it immediately.
Risk system in one minute
Risk-based position sizing capped by position, exposure, cash-reserve and order-size limits
Kill switch on daily loss / drawdown / consecutive losses (persistent, re-arm needs 2FA + reason)
No short selling, no leverage, leveraged/inverse ETPs blocked, restricted-symbol list
Anti-churn / wash-trade / order-rate limits, stale-data and fat-finger checks
Marketable limit orders only, algorithmic orders flagged (`QPY-ALGO-…`)
Hash-chained audit log of every AI proposal, risk decision, order and login
Live trading disabled unless three independent opt-ins are set
Details and defaults: `docs/RISK.md`. Legal mapping and operator
checklist (German): `docs/LEGAL_DE.md`. This is orientation, not legal advice.
Tests
```bash
pip install -e ".[dev,bot]"
pytest
```
The suite runs offline (broker, AI and market data are mocked).
Project layout
```
QuantPy/
├── quantpy/              # library (portfolio, backtester, strategy, indicators, risk/)
├── Quant_bot_ai.py       # trading bot
├── server.py             # Flask backend
├── dashboard.html        # web UI
├── setup_2fa.py          # one-time TOTP setup
├── docs/                 # Sphinx docs, RISK.md, LEGAL_DE.md
├── examples/, tests/
└── audit/                # created at runtime (audit log, kill-switch state) - back it up
```
`quantpy/gui` is a legacy GTK prototype that needs data files which are not part of
this repository; it is unmaintained.
Known limitations
Alpha software; no guarantee of correctness, uptime or fills
The free Alpaca IEX feed covers only part of market volume
The local book is reconciled with the broker each cycle; open limit orders may lag
Historical VaR cannot predict gaps or regime changes
Contributing
Issues and pull requests are welcome: https://github.com/FlorianPoerings/QuantPy/issues.
Please include tests. Do not commit secrets or broker/market data you may not redistribute.
License & attribution
BSD 3-Clause (see LICENSE). The project builds on an earlier open-source
"QuantPy"; keep upstream copyright notices when redistributing. The event profiler is
conceptually inspired by QSTK (no source used).
