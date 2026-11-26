.. _risk:

*********************
Risk and compliance
*********************

The trading bot never sends an order directly.  Every proposal passes the
``quantpy.risk.RiskEngine`` (sizing, exposure limits, kill switch) and the
``ComplianceGuard`` (no short selling, no leverage, restricted symbols,
order-rate limits, stale-data and fat-finger checks).  All decisions are written
to a hash-chained audit log.

See ``docs/RISK.md`` for the limits and their defaults, and ``docs/LEGAL_DE.md``
(German) for the regulatory background and the operator checklist.  Neither
document is legal advice.

.. automodule:: quantpy.risk
   :members:
