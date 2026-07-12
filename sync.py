"""
Sync data to today, then recalculate derived outputs.

Usage:
    python sync.py                   # full sync: all indices + all member stocks
    python sync.py vn30              # index only: VN30 price series, P/E, range-stats
    python sync.py FPT               # stock only: prices, shares, profit, P/E, range-stats
    python sync.py vn30 FPT          # mix: VN30 index + FPT stock
    python sync.py vn30 --force      # force-rebuild VN30 index data
    python sync.py --prices          # prices only, full sync
    python sync.py --pe --outputs    # P/E + outputs only, full sync

Steps (flags):
    --prices      price series
    --shares      quarterly outstanding shares (stocks only)
    --profit      quarterly net profit (stocks only)
    --pe          recalculate P/E
    --range-stats rebuild rolling-range stats cache
    --outputs     regenerate charts + Excel exports (indices only)
    --force       overwrite existing data

Full sync (no args) includes member stock prices/shares/profit for each index.
Specifying an index (e.g. vn30) syncs only that index's own data, not its members.

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
    args  = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a.lstrip("-") for a in sys.argv[1:] if a.startswith("--")}
    force = "force" in flags
    steps = flags - {"force"} or ALL_STEPS

    db.init_db()

    known_indices = set(INDICES)
    full_sync     = not args                          # no args = full sync including members
    indices       = [t.lower() for t in (args or INDICES) if t.lower() in known_indices]
    stocks        = [t.upper() for t in args if t.lower() not in known_indices]

    # member stocks only sync on a full run
    members_by_index = {}
    if full_sync:
        members_by_index = {idx: db.load_index_members(idx)["symbol"].unique().tolist() for idx in indices}

    # outputs only makes sense for indices
    if not indices:
        steps -= {"outputs"}

    # shares/profit are member-only steps; skip for index-explicit runs with no stocks
    member_count = sum(len(m) for m in members_by_index.values()) + len(stocks)
    if member_count == 0:
        steps -= {"shares", "profit"}

    p = SyncProgress(steps, args or INDICES, force)

    prices_total = len(indices) + sum(len(m) for m in members_by_index.values()) + len(stocks)
    if "prices"      in steps: p.set_totals("prices",      prices_total)
    if "shares"      in steps: p.set_totals("shares",      member_count)
    if "profit"      in steps: p.set_totals("profit",      member_count)
    if "pe"          in steps: p.set_totals("pe",          len(indices) + len(stocks))
    if "range-stats" in steps: p.set_totals("range-stats", len(indices) + len(stocks))
    if "outputs"     in steps: p.set_totals("outputs",     len(indices))

    print("Progress: sync_progress.html")

    # ── Index runs ────────────────────────────────────────────────────────────
    for index in indices:
        members   = members_by_index.get(index, [])
        index_sym = index.upper()
        n         = len(members)

        print(f"\n{'='*55}")
        label = f"{index_sym} + {n} members" if n else index_sym
        print(f"{'[FORCE] ' if force else ''}Syncing {label} — {', '.join(sorted(steps))}")
        print(f"{'='*55}")

        # ── Index prices ──────────────────────────────────────────────────────
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

            if members:
                print(f"\n── Member prices ({n} symbols)")
                for sym in members:
                    t0 = time.time()
                    p.begin("prices", index, sym)
                    try:
                        last_date = None if force else db.load_latest_price_date(sym)
                        sync_prices(symbols=[sym], start=last_date, override=force)
                        p.end("prices", index, sym, time.time() - t0)
                    except Exception as e:
                        p.end("prices", index, sym, time.time() - t0, status="error", note=str(e)[:100])

        # ── Shares (members only) ─────────────────────────────────────────────
        if "shares" in steps and members:
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

        # ── Profit (members only) ─────────────────────────────────────────────
        if "profit" in steps and members:
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
                sync_pe(index=index, from_date=from_date, override=force)
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

    # ── Stock runs ────────────────────────────────────────────────────────────
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
                sync_pe(symbols=[sym], from_date=from_date, override=force)
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
