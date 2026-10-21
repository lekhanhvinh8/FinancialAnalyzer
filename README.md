<div align="center">

# FinancialAnalyzer

### Valuation, market breadth and backtesting for Vietnamese stocks

[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)](#requirements)
[![Market](https://img.shields.io/badge/market-HOSE-444444?style=flat-square)](#data-sources)

</div>

---

## Capabilities

Collects prices, share counts and quarterly net profit for HOSE stocks into a SQLite
database, computes valuation and market indicators from it, and backtests buy/sell
strategies on those indicators.

| Area | What it does | Code |
|---|---|---|
| **Data collection** | Daily prices and share counts (vnstock), quarterly net profit (CafeF) | `syncs/` |
| **Index P/E** | Aggregate P/E of VN30, VN Diamond and VN Fin Lead: `Σ(Price × Shares) / Σ(TTM Net Profit)` | `syncs/pe.py` |
| **z_dev** | Each stock's log-distance from its own rolling median, standardized | `core/zdev_calc.py` |
| **Market breadth** | Daily statistics across the basket: share of stocks below their median, distribution of premiums | `core/breadth_calc.py` |
| **Trend signals** | Rolling slope, periodic-buy return, Sharpe-like ratio | `syncs/trend_signals.py` |
| **Data audit** | Checks stored data against its sources and against itself; `--fix` repairs | `syncs/audit_data.py` |
| **Backtesting** | Three methods: per stock, one portfolio across the basket, VN30 timed by breadth | `single/` `portfolio/` `breadth/` |
| **Reports** | Plotly charts, Excel snapshots, HTML backtest reports | `export/` and each method's report module |

Known data limitations are listed in [DATA_ISSUES.md](DATA_ISSUES.md).

## Contents

- [Capabilities](#capabilities)
- [Project Structure](#project-structure)
- [Requirements](#requirements)
- [First-time Setup](#first-time-setup)
- [Ongoing: Sync to Today](#ongoing-sync-to-today)
- [Sync Functions](#sync-functions)
- [Reproduce Outputs](#reproduce-outputs)
- [Update Index Membership](#update-index-membership)
- [Data Sources](#data-sources)
- [Tests](#tests)

---

## Project Structure

Three concerns, three places. The split is the important thing about this layout:
the three INVESTMENT METHODS below are independent of each other, and all three read
the same data rather than each keeping its own idea of what a price was.

<details>
<summary><strong>Full module layout</strong> (click to expand)</summary>

```
database.py          SQLite storage layer — the one definition of market facts
progress.py          live HTML progress renderers (used by sync and by single/)
export/              Plotly charts and Excel snapshots
sync.py              orchestrator — syncs everything to today

syncs/               DATA PIPELINE — fills and checks the database
  prices.py          daily close prices
  shares.py          quarterly outstanding shares
  profit.py          quarterly net profit (CafeF)
  pe.py              aggregate P/E, recalculated from the DB
  range_stats.py     rolling window statistics cache
  trend_signals.py   rolling trend classification
  zdev.py            valuation z-scores
  breadth.py         the whole basket as one row per day (cross-sectional)
  calculate.py       aggregate P/E calculation engine
  migrate.py         schema migrations
  audit_data.py      checks stored data against the source, repairs with --fix
  sources/           vnstock (prices, shares), cafef (net profit)
  seeds/             index membership history (static snapshots)
  collectors/        first-time bulk collection
  probes/            one-off source investigation scripts

core/                SHARED — reading the market and moving the money
  data.py            the database into one shape every method reads
  market.py          one calendar across many symbols
  ledger.py          execute_buy / execute_sell / execute_reinvest, written once
  breadth_calc.py    the basket reduced to one number a day (used by syncs/breadth.py)
  range_calc.py      rolling statistics builder (used by syncs/range_stats.py)
  zdev_calc.py       z_dev builder (used by syncs/zdev.py)
  rules.py           who is eligible today (used by portfolio/)
  scoring.py         in what order they deserve the money
  models.py          window_stats.py  universe.py  progress.py

single/              METHOD 1 — one wallet per symbol
  engine.py          the per-symbol backtest loop
  models.py          InvestmentTracker and friends
  strategies/        buy / sell / reinvest conditions
  runner.py sweep.py shared by the methods below
  multi_signal/      the tuned configuration and its runners
                     sweep_runner.py + sweep_specs.py — every parameter sweep
                     SWEEPS.md — what each sweep found
                     CONCLUSIONS.md — which profile won, and what it is not
  ma1000/            the plain moving-average variant

breadth/             METHOD 3 — trade VN30 on what the whole basket is doing
  strategy.py        the three arms as breadth conditions
  engine.py          the daily loop (money from core.ledger)

portfolio/           METHOD 2 — one wallet, the whole basket
  allocator.py       how much each eligible symbol gets
  strategy.py        Plan — the three arms plus the allocator
  engine.py          the daily loop over a shared calendar
  report.py          report_html.py  symbol_chart.py  overlay_chart.py
  run.py             CLI
  CONCLUSIONS.md     where this strand stopped, and why
```

</details>

### How the three methods relate

`single/` asks "does this rule beat buy-and-hold on FPT", once per symbol, with a
separate wallet each time. `portfolio/` asks "given one monthly contribution and
the whole basket to choose from, where should it go" — which is not a loop over
the first question, because the money is shared and the symbols compete for it.
`breadth/` asks a third: reduce the whole basket to one number per day and trade
VN30 on it.

No method imports another. The one deliberate exception is named in
`test_layout.py`: `single/multi_signal/` reads the stored breadth signal, and
borrows `breadth.chart.add_signal_line` to draw it. Everything shared lives in
`core/` — reading the market, and the three functions that move money.

`test_layout.py` asserts that shape rather than describing it, because layout
rules rot silently: a module in the wrong package still imports and still runs.

### Which configuration won

`single/multi_signal/CONCLUSIONS.md`. Short version, 52 symbols against DCA: the
basket profile beats the per-symbol price profile, +92.33 against +46.75 on
average and +12.78 on the paired median (32/52, p = 0.063). That document also
records what the advantage is *not*, which took more work than finding it.

### Running a backtest

```bash
python -m single.multi_signal.run_one FPT              # one symbol, one wallet
python -m single.multi_signal.run_all --all           # every symbol, price profile
python -m single.multi_signal.run_all --all --profile=breadth   # the winner
python -m breadth.run                                 # VN30 on the basket signal
python -m portfolio.run                               # one wallet, whole basket
python -m portfolio.run --top-k=5
```

---

## Requirements

Python 3.10+. Third-party dependencies:

```bash
pip install -r requirements.txt
```

`vnstock` provides prices and shares outstanding; `requests` talks to the CafeF API
directly for net profit. No API keys — both sources are free-tier, no login.

---

## First-time Setup

```bash
# 1. Seed index membership into DB
python syncs/seeds/vn30.py
python syncs/seeds/vndiamond.py
python syncs/seeds/vnfinlead.py

# 2. Collect all historical data (slow — ~15s per symbol via vnstock)
python syncs/collectors/vn30.py
python syncs/collectors/vndiamond.py
python syncs/collectors/vnfinlead.py
```

After first-time setup, use `sync.py` for all future updates.

---

## Ongoing: Sync to Today

```bash
python sync.py              # sync all three indices
python sync.py vn30         # sync one index only
python sync.py vn30 --force # re-fetch and overwrite all data from the beginning
```

Sync runs in order per index:

1. **Index prices** — fetch tail from last stored date
2. **Stock prices** — tail per member symbol
3. **Shares** — latest quarters (fill NULLs only, unless `--force`)
4. **Profit** — all quarters via CafeF (fill NULLs only, unless `--force`)
5. **P/E** — full recalculate from DB data; always replaces stored P/E
6. **Range stats** — rebuild rolling-range cache from DB data
7. **Outputs** — regenerate HTML charts + Excel exports

### Override semantics

| Flag | Behavior |
|------|----------|
| *(default)* | Incremental: only fetch from last stored date; existing non-null values are never overwritten |
| `--force` | Full resync: fetch all history; overwrite existing values |

P/E and range stats always fully replace on every run (they are derived from DB data, not fetched from external sources).

---

## Sync Functions

The `syncs/` package exposes individual sync functions that can be called programmatically:

```python
from syncs import sync_prices, sync_shares, sync_profit, sync_pe, sync_range_stats

# Sync only VN30 index price series (not member stocks)
sync_prices(index="vn30", start="2026-01-01", override=False)

# Sync prices for specific stocks
sync_prices(symbols=["VCB", "CTG"], start="2026-06-01", override=False)

# Sync shares for all VN30 member stocks
sync_shares(index="vn30", from_year=2026, from_quarter=1, override=False)

# Sync profit for specific stocks, overwriting existing values
sync_profit(symbols=["VCB"], override=True)

# Recalculate P/E for all indices
sync_pe()

# Rebuild range stats cache
sync_range_stats(index="vn30")
```

**`sync_prices`**
- `index="vn30"` → syncs the VN30 index series itself (not member stocks)
- `symbols=[...]` → specific symbols (stock or index)
- `override=False` → skip dates already in DB; `True` → overwrite

**`sync_shares` / `sync_profit`**
- `index="vn30"` → resolves to all current VN30 member stocks
- `symbols=[...]` → specific stock symbols (passing an index symbol raises `ValueError`)
- `from_year` / `from_quarter` → only process quarters ≥ this point (`None` = all history)
- `override=False` → preserve existing non-null values; `True` → overwrite all

**`sync_pe`**
- Always `override=True` — P/E is fully recalculated and replaced every run
- `from_date` → recalculate only from this date onward (passed by orchestrator)

**`sync_range_stats`**
- Always full rebuild — no network fetch, purely derived from DB

---

## Reproduce Outputs

```bash
python sync.py
```

To generate outputs individually (without re-syncing data):

```bash
python export/chart.py vn30
python export/excel.py vn30
python export/excel.py vn30 2026-07-01   # specific as-of date
python syncs/calculate.py                       # recalculate P/E only
```

Charts → `charts/<index>_valuation.html` (git-ignored)
Excel  → `exports/<index>_pe_<date>.xlsx` (git-ignored)

---

## Update Index Membership

When HOSE announces a rebalancing, add a new snapshot to the relevant seed file:

```python
# syncs/seeds/vn30.py — add at the bottom of VN30_SNAPSHOTS
"2026-08-01": [
    "ACB", "BID", ...  # full list of 30 stocks after rebalance
],
```

Then re-run the seed and sync:

```bash
python syncs/seeds/vn30.py
python sync.py vn30
```

---

## Data Sources

| Data | Source | Notes |
|------|--------|-------|
| Prices (daily) | vnstock (VCI) | Free tier |
| Shares outstanding | vnstock (VCI) | Latest 4 quarters only — older dates backfilled |
| Net profit (quarterly) | CafeF API | `apiweb.cafef.vn` — no login required |
| Index membership | Manual (HOSE announcements) | Stored in `syncs/seeds/` |

Raw CafeF JSON responses are cached in `data/raw/cafef/` for auditing.

See [DATA_ISSUES.md](DATA_ISSUES.md) for known data quality limitations.

---

## Tests

No test runner — each file runs as a script and returns a non-zero exit code on
failure, same as the sync and backtest entry points above.

```bash
python -m test_layout                      # package-shape rules (test_layout.py)
python -m core.test_rules
python -m core.test_breadth_calc
python -m breadth.test_engine
python -m portfolio.test_position_cap
python -m single.multi_signal.test_profiles
python -m single.multi_signal.test_sweeps
python -m single.multi_signal.test_trend
python -m syncs.test_breadth
python -m syncs.test_listings
```
