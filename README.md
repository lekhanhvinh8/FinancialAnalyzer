# PriceToEarn v2

Aggregate P/E calculator for Vietnamese stock indices (VN30, VN Diamond, VN Fin Lead).

**Formula:** `P/E = Σ(Price × Shares) / Σ(TTM Net Profit)` — market-cap weighted, point-in-time correct.

---

## Project Structure

```
database.py          SQLite storage layer (all reads/writes)
calculate.py         P/E calculation engine

sources/
  vnstock.py         Prices + shares (via vnstock library)
  cafef.py           Net profit (via CafeF API)

seeds/               Index membership history (static snapshots)
  vn30.py
  vndiamond.py
  vnfinlead.py

collectors/          Data collection scripts
  engine.py          Shared logic (retry, loops, summary)
  vn30.py            Initial collect for VN30
  vndiamond.py
  vnfinlead.py

export/
  chart.py           Plotly HTML charts

scripts/             Debug / one-off tools
  probe_cafef.py
  probe_vndiamond.py

sync.py              Single command to sync all data to today
```

---

## First-time Setup

Run once to seed membership history and collect all historical data:

```bash
# 1. Seed index membership into DB
python seeds/vn30.py
python seeds/vndiamond.py
python seeds/vnfinlead.py

# 2. Collect all historical prices + profit (slow — ~15s per symbol)
python collectors/vn30.py
python collectors/vndiamond.py
python collectors/vnfinlead.py
```

---

## Ongoing: Sync to Today

After initial setup, just run:

```bash
python sync.py
```

This runs in sequence:
1. **Data sync** — price tail per symbol, latest shares + profit (upsert, never deletes)
2. **P/E recalculation** — saves updated `pe_vn30`, `pe_vndiamond`, `pe_vnfinlead` to DB
3. *(future)* — charts, Excel exports, …

To sync a single index only:

```bash
python sync.py vn30
```

---

## Reproduce Outputs

```bash
# Sync data + recalculate P/E (run this first)
python sync.py

# Generate HTML charts from updated P/E
python export/chart.py vn30
python export/chart.py vndiamond
python export/chart.py vnfinlead
```

`calculate.py` can still be run standalone if you only want to recalculate P/E
without re-fetching any data (e.g. after a formula change).

Charts are saved to `charts/` — ignored by git (generated output).
Excel exports will go to `exports/` — also ignored by git.

---

## Update Index Membership

When HOSE announces a rebalancing, add a new snapshot to the relevant seed file:

```python
# seeds/vn30.py — add at the bottom of VN30_SNAPSHOTS
"2026-08-01": [
    "ACB", "BID", ...  # full list of 30 stocks after rebalance
],
```

Then re-run the seed and collect any newly added symbols:

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
