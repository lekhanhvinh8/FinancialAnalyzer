"""
Sync all index data to today, then recalculate derived outputs.

Steps:
    1. Prices      — index series + member stock prices (tail from last stored date)
    2. Shares      — latest quarters (fill NULLs / overwrite with --force)
    3. Profit      — all quarters via CafeF (fill NULLs / overwrite with --force)
    4. P/E         — recalculate aggregate P/E + per-stock P/E for all indices
    5. Range stats — rebuild cal_range_close DB cache
    6. Outputs     — regenerate charts and Excel exports

Usage:
    python sync.py                  # sync all three indices
    python sync.py vn30             # sync one index only
    python sync.py vn30 --force     # re-sync all data from the beginning
"""

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import database as db
from syncs import sync_prices, sync_shares, sync_profit, sync_pe, sync_range_stats

INDICES = ["vn30", "vndiamond", "vnfinlead"]

args    = [a for a in sys.argv[1:] if not a.startswith("--")]
flags   = {a for a in sys.argv[1:] if a.startswith("--")}
targets = args or INDICES
force   = "--force" in flags

db.init_db()

for index in targets:
    members    = db.load_index_members(index)["symbol"].unique().tolist()
    index_sym  = index.upper()
    n          = len(members)

    print(f"\n{'='*55}")
    print(f"{'[FORCE] ' if force else ''}Syncing {index_sym} ({n} members)")
    print(f"{'='*55}")

    # ── 1a. Prices: index series ──────────────────────────────────────────────
    print(f"\n── Index prices: {index_sym}")
    last_date = None if force else db.load_latest_price_date(index_sym)
    sync_prices(index=index, start=last_date, override=force)

    # ── 1b. Prices: member stocks ─────────────────────────────────────────────
    print(f"\n── Stock prices ({n} symbols)")
    for sym in members:
        last_date = None if force else db.load_latest_price_date(sym)
        sync_prices(symbols=[sym], start=last_date, override=force)

    # ── 2. Shares ─────────────────────────────────────────────────────────────
    print(f"\n── Shares ({n} symbols)")
    for sym in members:
        if force:
            last_y, last_q = None, None
        else:
            last = db.load_latest_shares_quarter(sym)
            last_y, last_q = last if last else (None, None)
        sync_shares(symbols=[sym], from_year=last_y, from_quarter=last_q, override=force)

    # ── 3. Profit ─────────────────────────────────────────────────────────────
    print(f"\n── Profit ({n} symbols)")
    for sym in members:
        if force:
            last_y, last_q = None, None
        else:
            last = db.load_latest_profit_quarter(sym)
            last_y, last_q = last if last else (None, None)
        sync_profit(symbols=[sym], from_year=last_y, from_quarter=last_q, override=force)

    # ── 4. P/E ────────────────────────────────────────────────────────────────
    print(f"\n── P/E: {index_sym}")
    from_date = None if force else db.load_latest_pe_date(index)
    sync_pe(indices=[index], from_date=from_date, override=True)

    # ── 5. Range stats ────────────────────────────────────────────────────────
    print(f"\n── Range stats: {index_sym}")
    sync_range_stats(index=index)

# ── 6. Regenerate outputs ─────────────────────────────────────────────────────
print(f"\n{'='*55}")
print("Regenerating outputs …")

import os
from export.chart import pe_chart, save_chart
from export.excel import build_excel

os.makedirs("charts",  exist_ok=True)
os.makedirs("exports", exist_ok=True)

for index in targets:
    fig, pe_dates, pe_values, price_data = pe_chart(index=index)
    save_chart(fig, pe_dates, pe_values, price_data, f"charts/pe_{index}.html")
    build_excel(index)

print(f"\n{'='*55}")
print("Done.")
