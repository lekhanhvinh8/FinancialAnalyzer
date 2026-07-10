"""
Sync all index data to today, then recalculate derived outputs.

Steps:
    1. Data sync   — fetch price tails, latest shares, latest profit
    2. Calculate   — recalculate aggregate P/E for all indices
    3. (future)    — regenerate charts, Excel exports, etc.

Usage:
    python sync.py              # sync all three indices
    python sync.py vn30         # sync one index only
"""

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from collectors.engine import sync
import calculate
import database as db

INDICES = ["vn30", "vndiamond", "vnfinlead"]

targets = sys.argv[1:] if len(sys.argv) > 1 else INDICES

# ── Step 1: Sync raw data ─────────────────────────────────────────────────────
for index in targets:
    sync(index)

# ── Step 2: Recalculate P/E ───────────────────────────────────────────────────
print(f"\n{'='*55}")
print("Recalculating P/E …")
db.init_db()
for index in targets:
    pe_df = calculate.calc_pe_history(index=index)
    valid = pe_df.dropna(subset=["pe_ratio"])
    if not valid.empty:
        print(f"  {index.upper()}: {len(valid)} dates, current {valid.iloc[-1]['pe_ratio']:.2f}x")
        calculate._PE_SAVERS[index](pe_df, override=True)

# ── Step 3: Regenerate outputs ───────────────────────────────────────────────
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
