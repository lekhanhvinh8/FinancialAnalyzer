# PriceToEarn v2

Aggregate P/E calculator for Vietnamese stock indices (VN30, VN Diamond, VN Fin Lead).

**Formula:** `P/E = Σ(Price × Shares) / Σ(TTM Net Profit)` — market-cap weighted, point-in-time correct.

---

## Project Structure

Three concerns, three places. The split is the important thing about this layout:
the two INVESTMENT METHODS are independent of each other, and both read the same
data rather than each keeping its own idea of what a price was.

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
  calculate.py       aggregate P/E calculation engine
  migrate.py         schema migrations
  audit_data.py      checks stored data against the source, repairs with --fix
  sources/           vnstock (prices, shares), cafef (net profit)
  seeds/             index membership history (static snapshots)
  collectors/        first-time bulk collection
  probes/            one-off source investigation scripts

single/              METHOD 1 — one wallet per symbol
  engine.py          the per-symbol backtest loop
  models.py          InvestmentTracker and friends
  strategies/        buy / sell / reinvest conditions
  median1000/        the tuned configuration, its runners and ~20 sweeps
  range_calc.py      rolling statistics builder (used by syncs/range_stats.py)
  zdev_calc.py       z_dev builder (used by syncs/zdev.py)

portfolio/           METHOD 2 — one wallet, the whole basket
  rules.py           who is eligible today
  scoring.py         in what order they deserve the money
  allocator.py       how much each one gets
  strategy.py        Plan — the three arms plus the allocator
  engine.py          the daily loop over a shared calendar
  market.py          one calendar across many symbols
  data.py            reads the database into this package's own shapes
  run.py             CLI
```

### How the two methods relate

`single/` asks "does this rule beat buy-and-hold on FPT", once per symbol, with a
separate wallet each time. `portfolio/` asks "given one monthly contribution and
the whole basket to choose from, where should it go" — which is not a loop over
the first question, because the money is shared and the symbols compete for it.

They share the database and nothing else. `portfolio/` imports nothing from
`single/`, so an experiment in one cannot move a result in the other.

One coupling runs the other way and is worth knowing about: `syncs/range_stats.py`
and `syncs/zdev.py` import their maths from `single/range_calc.py` and
`single/zdev_calc.py`. Those two modules are data computation rather than
strategy and belong in `syncs/`; `range_calc.py` cannot move yet because it
returns objects defined in `single/models.py`.

### Running a backtest

```bash
python single/median1000/run_one.py FPT      # one symbol, one wallet
python single/median1000/run_all.py          # every symbol, a wallet each
python -m portfolio.run                      # one wallet, the whole basket
python -m portfolio.run --top-k=5
```

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
