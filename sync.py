"""
Sync index data to today, then recalculate derived outputs.

Usage:
    python sync.py                        # all steps, all indices
    python sync.py vn30                   # all steps, one index
    python sync.py vn30 --force           # all steps, overwrite all data
    python sync.py --prices               # prices only, all indices
    python sync.py vn30 --shares --profit # shares + profit only, one index
    python sync.py --pe --outputs         # PE + outputs only

Steps (flags):
    --prices      index series + member stock prices
    --shares      quarterly outstanding shares
    --profit      quarterly net profit (CafeF)
    --pe          recalculate aggregate P/E
    --range-stats rebuild rolling-range stats cache
    --outputs     regenerate charts + Excel exports
    --force       overwrite existing data (applies to prices/shares/profit)
"""

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import database as db
from syncs import sync_prices, sync_shares, sync_profit, sync_pe, sync_range_stats

INDICES   = ["vn30", "vndiamond", "vnfinlead"]
ALL_STEPS = {"prices", "shares", "profit", "pe", "range-stats", "outputs"}

args    = [a for a in sys.argv[1:] if not a.startswith("--")]
flags   = {a.lstrip("-") for a in sys.argv[1:] if a.startswith("--")}
targets = args or INDICES
force   = "force" in flags
steps   = flags - {"force"} or ALL_STEPS

db.init_db()

for index in targets:
    members   = db.load_index_members(index)["symbol"].unique().tolist()
    index_sym = index.upper()
    n         = len(members)

    print(f"\n{'='*55}")
    print(f"{'[FORCE] ' if force else ''}Syncing {index_sym} ({n} members) — {', '.join(sorted(steps))}")
    print(f"{'='*55}")

    # ── Prices ────────────────────────────────────────────────────────────────
    if "prices" in steps:
        print(f"\n── Index prices: {index_sym}")
        last_date = None if force else db.load_latest_price_date(index_sym)
        sync_prices(index=index, start=last_date, override=force)

        print(f"\n── Stock prices ({n} symbols)")
        for sym in members:
            last_date = None if force else db.load_latest_price_date(sym)
            sync_prices(symbols=[sym], start=last_date, override=force)

    # ── Shares ────────────────────────────────────────────────────────────────
    if "shares" in steps:
        print(f"\n── Shares ({n} symbols)")
        for sym in members:
            last_y, last_q = (None, None) if force else (
                db.load_latest_shares_quarter(sym) or (None, None)
            )
            sync_shares(symbols=[sym], from_year=last_y, from_quarter=last_q, override=force)

    # ── Profit ────────────────────────────────────────────────────────────────
    if "profit" in steps:
        print(f"\n── Profit ({n} symbols)")
        for sym in members:
            last_y, last_q = (None, None) if force else (
                db.load_latest_profit_quarter(sym) or (None, None)
            )
            sync_profit(symbols=[sym], from_year=last_y, from_quarter=last_q, override=force)

    # ── P/E ───────────────────────────────────────────────────────────────────
    if "pe" in steps:
        print(f"\n── P/E: {index_sym}")
        from_date = None if force else db.load_latest_pe_date(index)
        sync_pe(indices=[index], from_date=from_date)

    # ── Range stats ───────────────────────────────────────────────────────────
    if "range-stats" in steps:
        print(f"\n── Range stats: {index_sym}")
        sync_range_stats(index=index)

# ── Outputs ───────────────────────────────────────────────────────────────────
if "outputs" in steps:
    import os
    from export.chart import pe_chart, save_chart
    from export.excel import build_excel

    print(f"\n{'='*55}")
    print("Regenerating outputs …")

    os.makedirs("charts",  exist_ok=True)
    os.makedirs("exports", exist_ok=True)

    for index in targets:
        fig, pe_dates, pe_values, price_data = pe_chart(index=index)
        save_chart(fig, pe_dates, pe_values, price_data, f"charts/pe_{index}.html")
        build_excel(index)

print(f"\n{'='*55}")
print("Done.")
