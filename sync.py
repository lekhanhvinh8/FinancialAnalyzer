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

Progress is written to sync_progress.html (auto-refreshes every 3s).
"""

import sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import database as db
from syncs import sync_prices, sync_shares, sync_profit, sync_pe, sync_range_stats
from progress import SyncProgress

INDICES   = ["vn30", "vndiamond", "vnfinlead"]
ALL_STEPS = {"prices", "shares", "profit", "pe", "range-stats", "outputs"}


def main():
    args    = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags   = {a.lstrip("-") for a in sys.argv[1:] if a.startswith("--")}
    targets = args or INDICES
    force   = "force" in flags
    steps   = flags - {"force"} or ALL_STEPS

    db.init_db()

    # Split args into indices and stock symbols
    known_indices = set(INDICES)
    indices = [t for t in targets if t.lower() in known_indices]
    stocks  = [t.upper() for t in targets if t.lower() not in known_indices]

    # Pre-compute members for index targets
    all_members = {idx: db.load_index_members(idx)["symbol"].unique().tolist() for idx in indices}

    # outputs only makes sense for indices
    if not indices:
        steps -= {"outputs"}

    # Set up progress tracker
    p = SyncProgress(steps, targets, force)

    index_sym_count = sum(len(m) + 1 for m in all_members.values())
    stock_count     = len(stocks)
    if "prices"      in steps: p.set_totals("prices",      index_sym_count + stock_count)
    if "shares"      in steps: p.set_totals("shares",      sum(len(m) for m in all_members.values()) + stock_count)
    if "profit"      in steps: p.set_totals("profit",      sum(len(m) for m in all_members.values()) + stock_count)
    if "pe"          in steps: p.set_totals("pe",          len(indices) + stock_count)
    if "range-stats" in steps: p.set_totals("range-stats", len(indices) + stock_count)
    if "outputs"     in steps: p.set_totals("outputs",     len(indices))

    print("Progress: sync_progress.html")

    # ── Index runs ────────────────────────────────────────────────────────────
    for index in indices:
        members   = all_members[index]
        index_sym = index.upper()
        n         = len(members)

        print(f"\n{'='*55}")
        print(f"{'[FORCE] ' if force else ''}Syncing {index_sym} ({n} members) — {', '.join(sorted(steps))}")
        print(f"{'='*55}")

        # ── Prices ────────────────────────────────────────────────────────────
        if "prices" in steps:
            print(f"\n── Index prices: {index_sym}")
            t0 = time.time()
            p.begin("prices", index, index_sym)
            try:
                last_date = None if force else db.load_latest_price_date(index_sym)
                sync_prices(index=index, start=last_date, override=force)
                p.end("prices", index, index_sym, time.time() - t0)
            except Exception as e:
                p.end("prices", index, index_sym, time.time() - t0, status="error", note=str(e)[:100])

            print(f"\n── Stock prices ({n} symbols)")
            for sym in members:
                t0 = time.time()
                p.begin("prices", index, sym)
                try:
                    last_date = None if force else db.load_latest_price_date(sym)
                    sync_prices(symbols=[sym], start=last_date, override=force)
                    p.end("prices", index, sym, time.time() - t0)
                except Exception as e:
                    p.end("prices", index, sym, time.time() - t0, status="error", note=str(e)[:100])

        # ── Shares ────────────────────────────────────────────────────────────
        if "shares" in steps:
            print(f"\n── Shares ({n} symbols)")
            for sym in members:
                t0 = time.time()
                p.begin("shares", index, sym)
                try:
                    last_y, last_q = (None, None) if force else (
                        db.load_latest_shares_quarter(sym) or (None, None)
                    )
                    sync_shares(symbols=[sym], from_year=last_y, from_quarter=last_q, override=force)
                    p.end("shares", index, sym, time.time() - t0)
                except Exception as e:
                    p.end("shares", index, sym, time.time() - t0, status="error", note=str(e)[:100])

        # ── Profit ────────────────────────────────────────────────────────────
        if "profit" in steps:
            print(f"\n── Profit ({n} symbols)")
            for sym in members:
                t0 = time.time()
                p.begin("profit", index, sym)
                try:
                    last_y, last_q = (None, None) if force else (
                        db.load_latest_profit_quarter(sym) or (None, None)
                    )
                    sync_profit(symbols=[sym], from_year=last_y, from_quarter=last_q, override=force)
                    p.end("profit", index, sym, time.time() - t0)
                except Exception as e:
                    p.end("profit", index, sym, time.time() - t0, status="error", note=str(e)[:100])

        # ── P/E ───────────────────────────────────────────────────────────────
        if "pe" in steps:
            print(f"\n── P/E: {index_sym}")
            t0 = time.time()
            p.begin("pe", index, index_sym)
            try:
                from_date = None if force else db.load_latest_pe_date(index)
                sync_pe(indices=[index], from_date=from_date)
                p.end("pe", index, index_sym, time.time() - t0)
            except Exception as e:
                p.end("pe", index, index_sym, time.time() - t0, status="error", note=str(e)[:100])

        # ── Range stats ───────────────────────────────────────────────────────
        if "range-stats" in steps:
            print(f"\n── Range stats: {index_sym}")
            t0 = time.time()
            p.begin("range-stats", index, index_sym)
            try:
                sync_range_stats(index=index)
                p.end("range-stats", index, index_sym, time.time() - t0)
            except Exception as e:
                p.end("range-stats", index, index_sym, time.time() - t0, status="error", note=str(e)[:100])

    # ── Stock-only runs (symbols not belonging to any index) ─────────────────
    if stocks:
        print(f"\n{'='*55}")
        print(f"Stock symbols: {', '.join(stocks)}")
        print(f"{'='*55}")

    for sym in stocks:
        if "prices" in steps:
            t0 = time.time()
            p.begin("prices", sym, sym)
            try:
                last_date = None if force else db.load_latest_price_date(sym)
                sync_prices(symbols=[sym], start=last_date, override=force)
                p.end("prices", sym, sym, time.time() - t0)
            except Exception as e:
                p.end("prices", sym, sym, time.time() - t0, status="error", note=str(e)[:100])

        if "shares" in steps:
            t0 = time.time()
            p.begin("shares", sym, sym)
            try:
                last_y, last_q = (None, None) if force else (
                    db.load_latest_shares_quarter(sym) or (None, None)
                )
                sync_shares(symbols=[sym], from_year=last_y, from_quarter=last_q, override=force)
                p.end("shares", sym, sym, time.time() - t0)
            except Exception as e:
                p.end("shares", sym, sym, time.time() - t0, status="error", note=str(e)[:100])

        if "profit" in steps:
            t0 = time.time()
            p.begin("profit", sym, sym)
            try:
                last_y, last_q = (None, None) if force else (
                    db.load_latest_profit_quarter(sym) or (None, None)
                )
                sync_profit(symbols=[sym], from_year=last_y, from_quarter=last_q, override=force)
                p.end("profit", sym, sym, time.time() - t0)
            except Exception as e:
                p.end("profit", sym, sym, time.time() - t0, status="error", note=str(e)[:100])

        if "pe" in steps:
            t0 = time.time()
            p.begin("pe", sym, sym)
            try:
                from_date = None if force else db.load_latest_pe_date(sym)
                sync_pe(symbols=[sym], from_date=from_date)
                p.end("pe", sym, sym, time.time() - t0)
            except Exception as e:
                p.end("pe", sym, sym, time.time() - t0, status="error", note=str(e)[:100])

        if "range-stats" in steps:
            t0 = time.time()
            p.begin("range-stats", sym, sym)
            try:
                sync_range_stats(symbols=[sym])
                p.end("range-stats", sym, sym, time.time() - t0)
            except Exception as e:
                p.end("range-stats", sym, sym, time.time() - t0, status="error", note=str(e)[:100])

    # ── Outputs ───────────────────────────────────────────────────────────────
    if "outputs" in steps:
        import os
        from export.chart import pe_chart, save_chart
        from export.excel import build_excel

        print(f"\n{'='*55}")
        print("Regenerating outputs …")

        os.makedirs("charts",  exist_ok=True)
        os.makedirs("exports", exist_ok=True)

        for index in indices:
            t0 = time.time()
            p.begin("outputs", index, index.upper())
            try:
                fig, pe_dates, pe_values, price_data = pe_chart(index=index)
                save_chart(fig, pe_dates, pe_values, price_data, f"charts/pe_{index}.html")
                build_excel(index)
                p.end("outputs", index, index.upper(), time.time() - t0)
            except Exception as e:
                p.end("outputs", index, index.upper(), time.time() - t0, status="error", note=str(e)[:100])

    p.finish()

    print(f"\n{'='*55}")
    print("Done.")


if __name__ == "__main__":
    main()
