"""
Which stored price series are still on a pre-adjustment scale?

sync_prices only grew the fix that catches this on 2026-08-18. Every corporate
action before that left the stored history on the old scale, with the newer
rows stacked on top at the new one — and once those newer rows exist the sync
can no longer see the break, because the date it compares is past the ex-date
and agrees.

This asks the source directly: fetch each full series, compare it against the
DB on the oldest dates they share, and report the factor. Read-only — it
writes nothing, it only tells you which symbols need a --force.

    python scripts/audit_price_scale.py              # every stock in the DB
    python scripts/audit_price_scale.py VHM MBB ACB  # just these
"""

import sys, os, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database as db
from sources import vnstock
from syncs._helpers import PRICE_START, call_with_retry
from syncs.prices import detect_adjustment, _ADJ_TOLERANCE

_SLEEP = 5  # same courtesy gap the sync uses between calls


def main():
    args   = [a.upper() for a in sys.argv[1:] if not a.startswith("--")]
    today  = __import__("datetime").date.today().isoformat()
    stocks = args or db.list_symbols(symbol_type="stock")

    print(f"Auditing {len(stocks)} symbols against the source "
          f"(tolerance {_ADJ_TOLERANCE:.0%}, ~{_SLEEP}s apart) …\n")

    stale, clean, failed = [], [], []

    for i, sym in enumerate(stocks, 1):
        existing = db.load_daily_prices(sym)
        if existing.empty:
            print(f"  [{i:2d}/{len(stocks)}] {sym:5s} no stored prices — skipped")
            continue
        try:
            fresh = call_with_retry(vnstock.get_prices, sym, PRICE_START, today, label=sym)
        except Exception as e:
            print(f"  [{i:2d}/{len(stocks)}] {sym:5s} FETCH FAILED — {e}")
            failed.append(sym)
            continue

        factor = detect_adjustment(fresh, existing)
        if factor is None:
            print(f"  [{i:2d}/{len(stocks)}] {sym:5s} ok")
            clean.append(sym)
        else:
            # Where the two series stop disagreeing is the ex-date.
            joined = existing.join(fresh, how="inner", lsuffix="_db", rsuffix="_api").sort_index()
            ratio  = joined["close_db"] / joined["close_api"]
            agreed = ratio[(ratio - 1).abs() <= _ADJ_TOLERANCE]
            since  = agreed.index.min().date() if not agreed.empty else None
            print(f"  [{i:2d}/{len(stocks)}] {sym:5s} STALE — stored is {factor:.4g}x the source"
                  + (f", broken from {since}" if since else ""))
            stale.append((sym, factor, since))

        if i < len(stocks):
            time.sleep(_SLEEP)

    print(f"\n{'='*60}")
    print(f"clean {len(clean)}   stale {len(stale)}   failed {len(failed)}")

    if failed:
        print(f"\nCould not check: {' '.join(failed)} — rerun for these.")

    if not stale:
        print("\nNothing to repair.")
        return

    syms = " ".join(s for s, _, _ in stale)
    print(f"\nStale: {syms}")
    print("\nTo repair (prices first, then P/E, then the caches that read it):")
    print(f"\n  python sync.py {syms} --prices --force")
    print(f"  python sync.py {syms} --pe --force")
    print(f"  python sync.py {syms} --range-stats --trend-signals --zdev --force")


if __name__ == "__main__":
    main()
