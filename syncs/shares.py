"""Sync quarterly outstanding shares (stocks only, via vnstock)."""

import time

import database as db
from sources import vnstock
from ._helpers import call_with_retry, resolve_stocks


def sync_shares(
    symbols:      list[str] | None = None,
    index:        str | None = None,
    from_year:    int | None = None,
    from_quarter: int | None = None,
    override:     bool = False,
) -> None:
    """
    Sync quarterly outstanding shares for stocks.

    symbols/index: which stocks to sync (index= resolves to its current members)
    from_year/from_quarter: only process quarters >= this point; None = all
    override: False → skip quarters already stored with non-null shares
              True  → overwrite all quarters received from vnstock
    """
    stocks = resolve_stocks(symbols, index)

    for sym in stocks:
        try:
            _sync_one(sym, from_year, from_quarter, override)
        except Exception as e:
            print(f"  ERROR [shares] {sym}: {e}")
        time.sleep(5)


def _sync_one(sym: str, from_year, from_quarter, override: bool) -> None:
    df = call_with_retry(vnstock.get_shares, sym, label=sym)

    if df is None or df.empty:
        print(f"  [shares] {sym}: no data returned")
        return

    # Apply quarter filter
    if from_year is not None:
        fq = from_quarter or 1
        df = df[
            (df["year"] > from_year) |
            ((df["year"] == from_year) & (df["quarter"] >= fq))
        ]

    if df.empty:
        print(f"  [shares] {sym}: nothing to update for given range")
        return

    if not override:
        # Only write quarters where DB does not yet have a non-null shares value
        existing_non_null = set(
            (int(r[0]), int(r[1]))
            for r in _query_existing_non_null_shares(sym)
        )
        df = df[~df.apply(lambda r: (int(r.year), int(r.quarter)) in existing_non_null, axis=1)]

    if df.empty:
        print(f"  [shares] {sym}: up to date")
        return

    db.save_shares(sym, df)


def _query_existing_non_null_shares(sym: str) -> set[tuple[int, int]]:
    existing = db.load_shares(sym)
    if existing.empty:
        return set()
    return set(zip(existing["year"].astype(int), existing["quarter"].astype(int)))
