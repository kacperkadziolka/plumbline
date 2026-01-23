## 1. What Plumbline is

Plumbline is a **self-hosted, local-first** web dashboard that helps you:

1. define an **investment policy** (target weights, constraints, drift thresholds),
2. answer: **“I have X EUR/USD/PLN — what should I buy?”** via a transparent **contribution allocator**,
3. run **reproducible policy backtests** (daily simulation of contributions + rebalancing rules + costs),
4. understand **currency exposure** and **FX attribution** (how much P&L is FX vs asset movement).

Plumbline is designed to be **auditable**: every proposal and backtest run stores inputs, config hash, and outputs.

## 2. Target user

* Investor using **IBKR** (initially via CSV export) + optional manual assets.
* Trades **infrequently**; wants a consistent process, not news-driven trading.
* Wants private/local storage (no SaaS) and a simple self-hosted dashboard.

## 3. Non-goals (MVP)

* No automatic order placement (no live trading) in MVP.
* No price data scraping in MVP by default (start with CSV import; online providers can be V2).
* No advanced HFT features, no tick-level data.
* No “AI picks stocks” system.

## 4. MVP deliverables

* Web UI: Dashboard, Import, Holdings, Policy editor, Propose (allocator), Backtests, Run details.
* SQLite storage for holdings, prices, FX, policies, proposals, backtest results.
* Decision report (HTML) and backtest report (HTML + PNG charts).
* Deterministic backtest engine and a basic cost model.

## 5. Glossary

* **Base currency:** reporting currency (e.g., EUR). All values normalized here.
* **Target weights:** desired portfolio weights per bucket/ticker.
* **Drift:** difference between current weight and target.
* **Contribution allocator:** splits new cash into buy amounts to reduce drift while respecting constraints.
* **Policy backtest:** simulation of applying the policy rules over historical daily prices.
