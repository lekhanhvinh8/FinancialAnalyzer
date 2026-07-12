# PriceToEarn v2

Aggregate P/E calculator for Vietnamese stock indices (VN30, VN Diamond, VN Fin Lead).

**Formula:** `P/E = Σ(Price × Shares) / Σ(TTM Net Profit)` — market-cap weighted, point-in-time correct.

---

## Project Structure

```
database.py          SQLite storage layer (all reads/writes, no override logic)
calculate.py         Aggregate P/E calculation engine

sources/
  vnstock.py         Prices + shares (via vnstock library)
  cafef.py           Net profit (via CafeF API)

seeds/               Index membership history (static snapshots)
  vn30.py
  vndiamond.py
  vnfinlead.py

syncs/               One sync function per table
  prices.py          sync_prices   — daily close prices
  shares.py          sync_shares   — quarterly outstanding shares
  profit.py          sync_profit   — quarterly net profit (CafeF)
  pe.py              sync_pe       — aggregate P/E (recalculated from DB)
  range_stats.py     sync_range_stats — rolling range stats cache

collectors/          Legacy initial-collection scripts (still usable for first-time load)
  engine.py
  vn30.py / vndiamond.py / vnfinlead.py

export/
  chart.py           Plotly HTML charts
  excel.py           Excel snapshots

analyze/             Analyzer tool (interactive P/E range analysis)

sync.py              Orchestrator — syncs everything to today
```

---

## First-time Setup

```bash
# 1. Seed index membership into DB
python seeds/vn30.py
python seeds/vndiamond.py
python seeds/vnfinlead.py

# 2. Collect all historical data (slow — ~15s per symbol via vnstock)
python collectors/vn30.py
python collectors/vndiamond.py
python collectors/vnfinlead.py
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
python calculate.py                       # recalculate P/E only
```

Charts → `charts/pe_<index>.html` (git-ignored)
Excel  → `exports/<index>_pe_<date>.xlsx` (git-ignored)

---

## Update Index Membership

When HOSE announces a rebalancing, add a new snapshot to the relevant seed file:

```python
# seeds/vn30.py — add at the bottom of VN30_SNAPSHOTS
"2026-08-01": [
    "ACB", "BID", ...  # full list of 30 stocks after rebalance
],
```

Then re-run the seed and sync:

```bash
python seeds/vn30.py
python sync.py vn30
```

---

## Data Sources

| Data | Source | Notes |
|------|--------|-------|
| Prices (daily) | vnstock (VCI) | Free tier |
| Shares outstanding | vnstock (VCI) | Latest 4 quarters only — older dates backfilled |
| Net profit (quarterly) | CafeF API | `apiweb.cafef.vn` — no login required |
| Index membership | Manual (HOSE announcements) | Stored in `seeds/` |

Raw CafeF JSON responses are cached in `data/raw/cafef/` for auditing.

See [DATA_ISSUES.md](DATA_ISSUES.md) for known data quality limitations.
