## 1. Core workflows (user stories)

### FR-1: Setup and onboarding

* As a user, I can start Plumbline locally and see an empty dashboard.
* As a user, I can import holdings (manual CSV) and see them in Holdings view.
* As a user, I can import prices (CSV) and see portfolio valuation in base currency.

### FR-2: Import holdings

* As a user, I can upload a **manual holdings CSV** (ticker, qty, currency, asset_type) and store a snapshot.
* As a user, I can upload an **IBKR CSV** (MVP supports at least a holdings snapshot export). The system maps it into canonical assets/positions.
* After import, the UI shows: number of tickers imported, any rows skipped, and detected currencies.

### FR-3: Import market data

* As a user, I can upload **daily prices CSV** (date, ticker, close, currency).
* As a user, I can upload **FX rates CSV** (date, pair, rate) for needed currency pairs.
* The system validates that required tickers exist and dates are parseable.
* The system stores prices/FX in SQLite and can compute valuations.

### FR-4: Dashboard analytics

* As a user, I can see:

  * portfolio total value (base currency),
  * top holdings by weight,
  * concentration metrics (e.g., top 5 weights),
  * currency exposure (e.g., % in USD/EUR/PLN),
  * last data update timestamps.

### FR-5: Policy management

* As a user, I can create/edit a **policy YAML** in the UI.
* As a user, I can save versions of a policy (versioned by hash/time).
* A policy contains:

  * base_currency,
  * buckets: `core` and optional `satellite` with target weights,
  * constraints (min trade value, max weight, no_sell),
  * rebalancing thresholds (soft/hard),
  * costs (commission, FX spread),
  * contribution defaults.

### FR-6: Propose contribution (“What to buy?”)

* As a user, I can enter:

  * contribution amount,
  * contribution currency,
  * toggle: **core-only** vs include satellite,
  * optional: minimum trade value override.
* The system returns a **buy plan**:

  * list of tickers to buy + amounts (in base and contribution currency),
  * explanation per ticker (current weight, target, gap, post-trade expected weight),
  * note if constraints filtered any tickers.
* The user can export the plan as CSV.
* Each proposal is saved to DB (inputs + policy hash + results).

### FR-7: FX attribution and currency insights

* As a user, I can view currency exposure.
* As a user, I can view a simple attribution:

  * estimated portfolio change from asset returns,
  * estimated portfolio change from FX movement.
* MVP attribution can be “good enough” (transparent assumptions documented).

### FR-8: Policy backtest

* As a user, I can select:

  * policy version,
  * backtest date range,
  * contribution schedule:

    * monthly fixed amount, OR
    * contributions CSV (date, amount, currency).
* The system runs a **daily simulation** and saves:

  * equity curve (equity, cash, drawdown, turnover),
  * summary metrics: CAGR, vol, max drawdown, turnover, total costs.
* The system produces a backtest report (HTML) with charts.

### FR-9: Backtest run browsing

* As a user, I can list previous runs.
* As a user, I can open a run detail page with:

  * metrics,
  * charts,
  * configuration hash + policy text.

## 2. UI pages (MVP)

* `/` Dashboard
* `/import` Import holdings/prices/fx
* `/holdings` Holdings table + weights + filters
* `/policy` Policy editor + version list
* `/propose` Contribution allocator form + output table + export
* `/backtests` Run backtest form + list of runs
* `/backtests/{id}` Run detail + report link

## 3. Validation & error handling

* Inputs must be validated (dates, numeric values, tickers).
* Missing price/FX data must surface a clear error: which ticker/pair and which dates are missing.
* If policy targets do not sum to 1.0 for a bucket, system warns and can auto-normalize (documented behavior).

## 4. Security / safety (functional)

* No brokerage credentials in MVP.
* Uploaded files stored under `data/uploads`.
* Basic CSRF protections or limited attack surface (local-first); document recommended deployment behind auth if exposed.
