"""
Sync all index data to today, then recalculate derived outputs.

Steps:
    0. Index prices — fetch VN30/VNINDEX/VNDIAMOND/VNFINLEAD price series
    1. Data sync    — fetch price tails, latest shares, latest profit for members
    2. Calculate    — recalculate aggregate P/E for all indices
    3. Cache        — rebuild cal_range_close DB cache (rolling stats for analyzer)
    4. Outputs      — regenerate charts and Excel exports

Usage:
    python sync.py              # sync all three indices
    python sync.py vn30         # sync one index only
"""

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import pandas as pd
from collectors.engine import sync, sync_indices
import calculate
import database as db
from analyze.range_calc import build_cal_range_close

INDICES = ["vn30", "vndiamond", "vnfinlead"]

targets = sys.argv[1:] if len(sys.argv) > 1 else INDICES

# ── Step 0: Sync index price series ──────────────────────────────────────────
sync_indices()

# ── Step 1: Sync member stock data ───────────────────────────────────────────
for index in targets:
    sync(index)

# ── Step 2: Recalculate P/E ───────────────────────────────────────────────────
print(f"\n{'='*55}")
print("Recalculating P/E …")
db.init_db()
for index in targets:
    pe_df = calculate.calc_pe_history(index=index, emit_members=True)
    valid = pe_df.dropna(subset=["pe_ratio"])
    if not valid.empty:
        print(f"  {index.upper()}: {len(valid)} dates, current {valid.iloc[-1]['pe_ratio']:.2f}x")
        calculate._PE_SAVERS[index](pe_df, override=True)

# ── Step 3: Rebuild cal_range_close cache ────────────────────────────────────
print(f"\n{'='*55}")
print("Rebuilding cal_range_close cache …")
for index in targets:
    symbol = index.upper()
    prices = db.load_daily_prices(symbol).reset_index().rename(columns={'date': 'time'})
    pe = db.load_pe_ratios(symbol).reset_index().rename(columns={'date': 'time'})
    pe = pe.dropna(subset=['pe_ratio'])[['time', 'pe_ratio']]
    df_idx = prices.merge(pe, on='time', how='left')
    df_idx['pe_ratio'] = df_idx['pe_ratio'].ffill()
    df_idx = df_idx.reset_index(drop=True)

    cal = build_cal_range_close(df_idx, range_days=[1000], max_workers=5)
    db.save_range_stats(symbol, df_idx, cal)

# ── Step 4: Regenerate outputs ───────────────────────────────────────────────
import os
from export.chart import pe_chart, save_chart
from export.excel import build_excel

os.makedirs("charts",  exist_ok=True)
os.makedirs("exports", exist_ok=True)

for index in targets:
    # HTML chart
    fig, pe_dates, pe_values, price_data = pe_chart(index=index)
    save_chart(fig, pe_dates, pe_values, price_data, f"charts/pe_{index}.html")

    # Excel snapshot
    build_excel(index)
