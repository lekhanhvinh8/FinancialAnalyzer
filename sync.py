"""
Sync data to today, then recalculate derived outputs.

Usage:
    python sync.py                   # all stocks (deduplicated) then all indices
    python sync.py vnindex           # all member stocks only, no index series
    python sync.py vn30              # VN30 index series only (prices, P/E, range-stats)
    python sync.py VN30              # all member stocks of VN30
    python sync.py FPT               # FPT stock only
    python sync.py vn30 FPT          # VN30 index + FPT stock
    python sync.py vn30 --force      # force-rebuild VN30 index data
    python sync.py --prices          # prices only, full sync
    python sync.py --pe --outputs    # P/E + outputs only, full sync

Steps (flags):
    --prices         price series
    --shares         quarterly outstanding shares (stocks only)
    --profit         quarterly net profit (stocks only)
    --pe             recalculate P/E
    --range-stats    rebuild rolling-range stats cache
    --trend-signals  rebuild trend classification signals
    --zdev           rebuild relative-valuation z_dev (swept stat windows)
    --outputs        regenerate charts + Excel exports (indices only)
    --force          overwrite existing data

Trend-signals tuning (optional, defaults shown):
    --trend-window=500       rolling lookback window in trading days
    --trend-step=10          compute a point every N trading days
    --trend-lookback=1500    how far back (trading days) to go

Progress is written to sync_progress.html (auto-refreshes every 3s).
"""

import sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import database as db
from syncs import (sync_prices, sync_shares, sync_profit, sync_pe, sync_range_stats,
                   sync_trend_signals, sync_zdev)
from syncs.trend_signals import WINDOW_STEP as _TW, STEP_DAYS as _TS, MAX_LOOKBACK as _TL
from progress import SyncProgress

INDICES   = ["vn30", "vndiamond", "vnfinlead"]
ALL_STEPS = {"prices", "shares", "profit", "pe", "range-stats", "trend-signals", "zdev", "outputs"}


def _all_members() -> list[str]:
    """All member stocks across all indices, deduplicated, preserving first-seen order."""
    seen, result = set(), []
    for idx in INDICES:
        for sym in db.load_index_members(idx)["symbol"].unique():
            if sym not in seen:
                seen.add(sym)
                result.append(sym)
    return result


def main():
    args      = [a for a in sys.argv[1:] if not a.startswith("--")]
    raw_flags = [a.lstrip("-") for a in sys.argv[1:] if a.startswith("--")]
    bool_flags = {f for f in raw_flags if "=" not in f}
    kv_flags   = {f.split("=", 1)[0]: f.split("=", 1)[1] for f in raw_flags if "=" in f}
    flags      = bool_flags

    force = "force" in flags

    def _kv_int(key: str, default: int | None) -> int | None:
        try: return int(kv_flags[key])
        except (KeyError, ValueError): return default

    workers        = _kv_int("workers",         None)
    trend_window   = _kv_int("trend-window",    _TW)   # window_days increment
    trend_step     = _kv_int("trend-step",      _TS)   # date offset increment
    trend_lookback = _kv_int("trend-lookback",  _TL)

    steps = (flags - {"force"}) or ALL_STEPS

    db.init_db()

    # Auto-seed index members on a fresh DB
    import sqlite3 as _sq
    with _sq.connect(db.DB_PATH) as _c:
        if _c.execute("SELECT COUNT(*) FROM index_members").fetchone()[0] == 0:
            print("Fresh DB — seeding index members...")
            from syncs.seeds.vn30 import seed as _s1
            from syncs.seeds.vndiamond import seed as _s2
            from syncs.seeds.vnfinlead import seed as _s3
            _s1(); _s2(); _s3()
            print("Seeding done.\n")

    known_indices = set(INDICES)
    index_symbols = {"VN30", "VNDIAMOND", "VNFINLEAD"}  # uppercase = member-expand mode

    stocks_only = "vnindex" in args          # vnindex → all stocks, no index series
    full_sync   = not args                   # no args  → all stocks + all indices

    # lowercase vn30 = index series; uppercase VN30 = expand to members
    indices        = [] if stocks_only else [t.lower() for t in (args or INDICES) if t.lower() in known_indices and t not in index_symbols]
    member_targets = [t for t in args if t in index_symbols]
    explicit_stocks = [t.upper() for t in args if t.lower() not in known_indices and t != "vnindex"]

    # build deduplicated stocks list
    seen   = set(explicit_stocks)
    stocks = list(explicit_stocks)

    if full_sync or stocks_only:
        for sym in _all_members():
            if sym not in seen:
                seen.add(sym)
                stocks.append(sym)
    else:
        for t in member_targets:
            for sym in db.load_index_members(t.lower())["symbol"].unique():
                if sym not in seen:
                    seen.add(sym)
                    stocks.append(sym)

    if not indices and not stocks:
        steps -= {"outputs"}
    if not stocks:
        steps -= {"shares", "profit"}

    p = SyncProgress(steps, args or ["all"], force)

    if "prices"         in steps: p.set_totals("prices",         len(stocks) + len(indices))
    if "shares"         in steps: p.set_totals("shares",         len(stocks))
    if "profit"         in steps: p.set_totals("profit",         len(stocks))
    if "pe"             in steps: p.set_totals("pe",             len(stocks) + len(indices))
    if "range-stats"    in steps: p.set_totals("range-stats",    len(stocks) + len(indices))
    if "trend-signals"  in steps: p.set_totals("trend-signals",  len(stocks) + len(indices))
    if "zdev"           in steps: p.set_totals("zdev",           len(stocks) + len(indices))
    if "outputs"        in steps: p.set_totals("outputs",        len(indices) + len(stocks))

    print("Progress: sync_progress.html")

    # ── Stock runs (all stocks, deduplicated) ─────────────────────────────────
    if stocks:
        print(f"\n{'='*55}")
        print(f"{'[FORCE] ' if force else ''}Stocks ({len(stocks)}) — {', '.join(sorted(steps - {'outputs'}))}")
        print(f"{'='*55}")

    # Symbols whose price history the source re-adjusted under us. Their
    # price-derived caches cannot resume from a stored date — the dates they
    # already hold are on the old scale — so those steps run as if forced.
    readjusted: set[str] = set()

    # Symbols whose newly arrived quarter restates a share count that P/E has
    # already been computed on, mapped to the quarter-end it goes stale from.
    # Unlike a price re-adjustment this spoils only the tail of the series, so
    # these steps resume from that date instead of rebuilding everything.
    restated: dict[str, str] = {}

    for sym in stocks:
        if "prices" in steps:
            t0 = time.time()
            p.begin("prices", sym, sym)
            try:
                last_date = None if force else db.load_latest_price_date(sym)
                readjusted.update(sync_prices(symbols=[sym], start=last_date, override=force))
                note = "re-adjusted — rebuilding derived data" if sym in readjusted else ""
                p.end("prices", sym, sym, time.time() - t0, note=note)
            except Exception as e:
                p.end("prices", sym, sym, time.time() - t0, status="error", note=str(e)[:100])

        sym_force = force or sym in readjusted

        if "shares" in steps:
            t0 = time.time()
            p.begin("shares", sym, sym)
            try:
                last_y, last_q = (None, None) if force else (
                    db.load_latest_shares_quarter(sym) or (None, None)
                )
                restated.update(sync_shares(symbols=[sym], from_year=last_y,
                                            from_quarter=last_q, override=force))
                note = (f"share count restated — P/E stale from {restated[sym]}"
                        if sym in restated else "")
                p.end("shares", sym, sym, time.time() - t0, note=note)
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
                from_date = (None if sym_force else
                             restated.get(sym) or db.load_latest_pe_date(sym))
                sync_pe(symbols=[sym], from_date=from_date, override=sym_force)
                p.end("pe", sym, sym, time.time() - t0)
            except Exception as e:
                p.end("pe", sym, sym, time.time() - t0, status="error", note=str(e)[:100])

        if "range-stats" in steps:
            t0 = time.time()
            p.begin("range-stats", sym, sym)
            try:
                # A restated quarter rewrites P/E from its quarter-end on, so
                # the rows range_stats built over those dates have to go too.
                range_start = (None if sym_force else
                               restated.get(sym) or db.load_latest_range_stats_date(sym))
                sync_range_stats(symbols=[sym], start=range_start,
                                 override=sym_force or sym in restated, max_workers=workers)
                p.end("range-stats", sym, sym, time.time() - t0)
            except Exception as e:
                p.end("range-stats", sym, sym, time.time() - t0, status="error", note=str(e)[:100])

        if "trend-signals" in steps:
            t0 = time.time()
            p.begin("trend-signals", sym, sym)
            try:
                ts_start = None if sym_force else db.load_latest_trend_signals_date(sym, trend_window)
                sync_trend_signals(
                    symbols=[sym],
                    start=ts_start,
                    window_step=trend_window,
                    step_days=trend_step,
                    max_lookback=trend_lookback,
                    override=sym_force,
                )
                p.end("trend-signals", sym, sym, time.time() - t0)
            except Exception as e:
                p.end("trend-signals", sym, sym, time.time() - t0, status="error", note=str(e)[:100])

        if "zdev" in steps:
            t0 = time.time()
            p.begin("zdev", sym, sym)
            try:
                # No flag to pass: zdev fingerprints the close series itself and
                # picks its own path — skip when nothing moved, resume from the
                # last synced date when dates were only appended, rebuild when
                # history was revised. sym_force would be redundant, since the
                # revision it reacts to is what the fingerprint already sees.
                sync_zdev(symbols=[sym])
                p.end("zdev", sym, sym, time.time() - t0)
            except Exception as e:
                p.end("zdev", sym, sym, time.time() - t0, status="error", note=str(e)[:100])

    # ── Index runs (index series only, no members) ────────────────────────────
    for index in indices:
        index_sym = index.upper()

        print(f"\n{'='*55}")
        print(f"{'[FORCE] ' if force else ''}Index {index_sym} — {', '.join(sorted(steps))}")
        print(f"{'='*55}")

        if "prices" in steps:
            t0 = time.time()
            p.begin("prices", index, index_sym)
            try:
                last_date = None if force else db.load_latest_price_date(index_sym)
                readjusted.update(sync_prices(index=index, start=last_date, override=force))
                note = "re-adjusted — rebuilding derived data" if index_sym in readjusted else ""
                p.end("prices", index, index_sym, time.time() - t0, note=note)
            except Exception as e:
                p.end("prices", index, index_sym, time.time() - t0, status="error", note=str(e)[:100])

        # An index P/E is Σ(member price × member shares) / Σ(member profit), so
        # a member that was repaired above drags the index with it — its own
        # price series being untouched says nothing.
        members    = set(db.load_index_members(index)["symbol"].unique())
        idx_force  = force or index_sym in readjusted or bool(members & readjusted)
        idx_since  = None if idx_force else min(
            (d for s, d in restated.items() if s in members), default=None)

        if "pe" in steps:
            t0 = time.time()
            p.begin("pe", index, index_sym)
            try:
                # index_sym, not index: pe_ratios stores the uppercase symbol.
                # Passing the lowercase id returns None and silently forces a
                # full recompute on every sync.
                from_date = (None if idx_force else
                             idx_since or db.load_latest_pe_date(index_sym))
                sync_pe(index=index, from_date=from_date, override=idx_force)
                p.end("pe", index, index_sym, time.time() - t0)
            except Exception as e:
                p.end("pe", index, index_sym, time.time() - t0, status="error", note=str(e)[:100])

        if "range-stats" in steps:
            t0 = time.time()
            p.begin("range-stats", index, index_sym)
            try:
                range_start = (None if idx_force else
                               idx_since or db.load_latest_range_stats_date(index.upper()))
                sync_range_stats(index=index, start=range_start,
                                 override=idx_force or idx_since is not None, max_workers=workers)
                p.end("range-stats", index, index_sym, time.time() - t0)
            except Exception as e:
                p.end("range-stats", index, index_sym, time.time() - t0, status="error", note=str(e)[:100])

        if "trend-signals" in steps:
            t0 = time.time()
            p.begin("trend-signals", index, index_sym)
            try:
                ts_start = None if idx_force else db.load_latest_trend_signals_date(index_sym, trend_window)
                sync_trend_signals(
                    index=index,
                    start=ts_start,
                    window_step=trend_window,
                    step_days=trend_step,
                    max_lookback=trend_lookback,
                    override=idx_force,
                )
                p.end("trend-signals", index, index_sym, time.time() - t0)
            except Exception as e:
                p.end("trend-signals", index, index_sym, time.time() - t0, status="error", note=str(e)[:100])

        if "zdev" in steps:
            t0 = time.time()
            p.begin("zdev", index, index_sym)
            try:
                sync_zdev(index=index)
                p.end("zdev", index, index_sym, time.time() - t0)
            except Exception as e:
                p.end("zdev", index, index_sym, time.time() - t0, status="error", note=str(e)[:100])

    # ── Outputs ───────────────────────────────────────────────────────────────
    if "outputs" in steps:
        import os
        from export.chart import pe_chart, save_chart, save_stock_chart, save_index_chart
        from export.excel import build_excel

        print(f"\n{'='*55}")
        print("Regenerating outputs …")

        os.makedirs("charts",  exist_ok=True)
        os.makedirs("exports", exist_ok=True)

        for index in indices:
            t0 = time.time()
            p.begin("outputs", index, index.upper())
            try:
                save_index_chart(index, f"charts/{index}_valuation.html")
                build_excel(index)
                p.end("outputs", index, index.upper(), time.time() - t0)
            except Exception as e:
                p.end("outputs", index, index.upper(), time.time() - t0, status="error", note=str(e)[:100])

        for sym in stocks:
            t0 = time.time()
            p.begin("outputs", sym, sym)
            try:
                save_stock_chart(sym, f"charts/{sym.lower()}_valuation.html")
                p.end("outputs", sym, sym, time.time() - t0)
            except Exception as e:
                p.end("outputs", sym, sym, time.time() - t0, status="error", note=str(e)[:100])

    p.finish()

    print(f"\n{'='*55}")
    print("Done.")


if __name__ == "__main__":
    main()
