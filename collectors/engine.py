"""
Shared collection engine — used by collectors/vn30.py, vndiamond.py, vnfinlead.py.
Not meant to be run directly.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import sqlite3
import time

import database as db
from sources import vnstock, cafef

RAW_DIR     = "data/raw/cafef"
_RETRY_WAIT = 40
_RETRIES    = 3

_MEMBER_LOADERS = {
    "vn30":      lambda **kw: db.load_index_members("vn30",      **kw),
    "vndiamond": lambda **kw: db.load_index_members("vndiamond", **kw),
    "vnfinlead": lambda **kw: db.load_index_members("vnfinlead", **kw),
}

_LABELS = {
    "vn30":      "VN30",
    "vndiamond": "VN Diamond",
    "vnfinlead": "VN Fin Lead",
}


def _call_with_retry(fn, *args, label="", **kwargs):
    for attempt in range(1, _RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except (Exception, SystemExit) as e:
            msg = str(e)
            if any(k in msg.lower() for k in ("rate", "limit", "20/", "exceeded", "process terminated")):
                print(f"  Rate limited -- waiting {_RETRY_WAIT}s (attempt {attempt}/{_RETRIES})")
                time.sleep(_RETRY_WAIT)
            elif isinstance(e, SystemExit):
                print(f"  vnstock exited unexpectedly -- waiting {_RETRY_WAIT}s (attempt {attempt}/{_RETRIES})")
                time.sleep(_RETRY_WAIT)
            else:
                raise
    raise RuntimeError(f"Still rate-limited after {_RETRIES} retries for {label}")


def _missing(all_members):
    """Return (need_prices, need_profit) for symbols not yet in DB."""
    have_prices = set(db.list_symbols(symbol_type='stock'))
    con = sqlite3.connect(db.DB_PATH)
    have_profit = {
        r[0] for r in con.execute(
            """SELECT DISTINCT symbol FROM quarterly_fundamentals
               WHERE kqkd_14 IS NOT NULL OR kqkd_13 IS NOT NULL OR kqkd_10 IS NOT NULL"""
        ).fetchall()
    }
    con.close()
    return (
        [s for s in all_members if s not in have_prices],
        [s for s in all_members if s not in have_profit],
    )


INDEX_SYMBOLS = ["VN30", "VNINDEX", "VNDIAMOND", "VNFINLEAD"]
INDEX_START   = "2012-01-01"


def sync_indices(symbols: list[str] | None = None):
    """
    Incrementally sync index price series (VN30, VNINDEX, etc.) into index_prices table.
    Fetches only the tail from the latest stored date to today.
    """
    from datetime import date
    today   = date.today().isoformat()
    targets = symbols or INDEX_SYMBOLS

    print(f"\n{'='*55}")
    print(f"Syncing index prices: {targets}")
    print(f"{'='*55}")

    db.init_db()
    for symbol in targets:
        latest = db.load_latest_price_date(symbol)
        if latest is None:
            start = INDEX_START
            print(f"\n[{symbol}] no data — full fetch from {start}")
        elif latest >= today:
            print(f"\n[{symbol}] up to date ({latest})")
            continue
        else:
            start = latest
            print(f"\n[{symbol}] tail from {start}")

        try:
            prices = _call_with_retry(vnstock.get_index_prices, symbol, start, today, label=symbol)
            db.save_daily_prices(symbol, prices, symbol_type='index')
        except Exception as e:
            print(f"  ERROR {symbol}: {e}")
        time.sleep(5)


def sync(index: str):
    """
    Incrementally update data for all members of an index.

    - Prices : fetch from each symbol's latest stored date to today (tail only)
    - Shares : re-fetch latest quarters and upsert (shares change each quarter)
    - Profit : re-fetch all quarters and upsert (CafeF may restate figures)

    Never deletes existing data. Safe to run repeatedly.
    """
    from datetime import date
    today = date.today().isoformat()

    db.init_db()

    if index not in _MEMBER_LOADERS:
        raise ValueError(f"Unknown index '{index}'. Choose from: {list(_MEMBER_LOADERS)}")

    index_label = _LABELS[index]
    all_members = sorted(_MEMBER_LOADERS[index]()["symbol"].unique())

    print(f"\n{'='*55}")
    print(f"Syncing {index_label} ({len(all_members)} symbols) …")
    print(f"{'='*55}")

    errors = []

    for i, symbol in enumerate(all_members, 1):
        print(f"\n[{i:02d}/{len(all_members)}] {symbol}")

        # ── Prices: fetch tail from latest stored date ────────────────────────
        try:
            latest = db.load_latest_price_date(symbol)
            if latest is None:
                print(f"  prices: no existing data — use collect() for initial load")
            elif latest >= today:
                print(f"  prices: up to date ({latest})")
            else:
                prices = _call_with_retry(vnstock.get_prices, symbol, latest, today, label=symbol)
                db.save_daily_prices(symbol, prices, symbol_type='stock')
        except Exception as e:
            print(f"  ERROR prices: {e}")
            errors.append((symbol, "prices", str(e)))
        time.sleep(5)

        # ── Shares: re-fetch and upsert ───────────────────────────────────────
        try:
            shares = _call_with_retry(vnstock.get_shares, symbol, label=symbol)
            db.save_shares(symbol, shares)
        except Exception as e:
            print(f"  ERROR shares: {e}")
            errors.append((symbol, "shares", str(e)))
        time.sleep(5)

        # ── Profit: re-fetch and upsert ───────────────────────────────────────
        try:
            profit = cafef.get_net_profit(symbol, raw_dir=RAW_DIR)
            db.save_net_profit(symbol, profit)
        except Exception as e:
            print(f"  ERROR profit: {e}")
            errors.append((symbol, "net_profit", str(e)))

    print(f"\n{'='*55}")
    if errors:
        print(f"Sync complete with {len(errors)} error(s):")
        for sym, kind, msg in errors:
            print(f"  {sym} [{kind}]: {msg}")
    else:
        print(f"Sync complete — all {len(all_members)} symbols updated.")


def collect(index: str, start: str):
    """
    Collect prices + shares (vnstock) and net profit (CafeF) for all
    symbols ever in an index, skipping those already in the DB.

    index : "vn30", "vndiamond", or "vnfinlead"
    start : earliest price date to fetch, e.g. "2012-01-01"
    """
    from datetime import date
    end = date.today().isoformat()

    db.init_db()

    if index not in _MEMBER_LOADERS:
        raise ValueError(f"Unknown index '{index}'. Choose from: {list(_MEMBER_LOADERS)}")

    index_label  = _LABELS[index]
    all_members  = sorted(_MEMBER_LOADERS[index]()["symbol"].unique())
    need_prices, need_profit = _missing(all_members)

    print(f"{index_label} unique members ever: {len(all_members)}")
    print(f"Need prices : {need_prices or 'none'}")
    print(f"Need profit : {need_profit or 'none'}")
    print()

    errors = []

    # ── Prices + shares via vnstock ───────────────────────────────────────────
    for i, symbol in enumerate(need_prices, 1):
        print(f"[{i:02d}/{len(need_prices)}] {symbol} -- prices + shares")
        try:
            prices = _call_with_retry(vnstock.get_prices, symbol, start, end, label=symbol)
            db.save_daily_prices(symbol, prices, symbol_type='stock')
        except Exception as e:
            print(f"  ERROR prices: {e}")
            errors.append((symbol, "prices", str(e)))

        try:
            shares = _call_with_retry(vnstock.get_shares, symbol, label=symbol)
            db.save_shares(symbol, shares)
        except Exception as e:
            print(f"  ERROR shares: {e}")
            errors.append((symbol, "shares", str(e)))

        time.sleep(15)

    # ── Net profit via CafeF ──────────────────────────────────────────────────
    print()
    for i, symbol in enumerate(need_profit, 1):
        print(f"[{i:02d}/{len(need_profit)}] {symbol} -- net profit (CafeF)")
        try:
            profit = cafef.get_net_profit(symbol, raw_dir=RAW_DIR)
            db.save_net_profit(symbol, profit)
            n14 = profit["kqkd_14"].notna().sum()
            n10 = profit["kqkd_10"].notna().sum()
            tag = "broker(kqkd_10)" if n10 > 0 and n14 == 0 else "kqkd_14"
            print(f"  net_profit: {len(profit)} quarters [{tag}]")
        except Exception as e:
            print(f"  ERROR profit: {e}")
            errors.append((symbol, "net_profit", str(e)))
        time.sleep(0.3)

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 55)
    print(db.summary().to_string(index=False))

    if errors:
        print(f"\nErrors ({len(errors)}):")
        for sym, kind, msg in errors:
            print(f"  {sym} [{kind}]: {msg}")
    else:
        print("\nAll collected successfully.")
