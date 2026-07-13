"""Sync quarterly net profit from CafeF (stocks only)."""

import time

import database as db
from sources import cafef
from ._helpers import call_with_retry, resolve_stocks, fill_merge, is_profit_current

RAW_DIR   = "data/raw/cafef"
_KQKD_COLS = ["kqkd_14", "kqkd_13", "kqkd_10"]


def sync_profit(
    symbols:      list[str] | None = None,
    index:        str | None = None,
    from_year:    int | None = None,
    from_quarter: int | None = None,
    override:     bool = False,
) -> None:
    """
    Sync quarterly net profit for stocks via CafeF.

    symbols/index: which stocks to sync (index= resolves to its current members)
    from_year/from_quarter: only process quarters >= this point; None = all
    override: False → insert new rows; fill NULL kqkd columns in existing rows
              True  → overwrite all kqkd values with latest CafeF data
    """
    stocks = resolve_stocks(symbols, index)

    for sym in stocks:
        if not override and is_profit_current(sym):
            print(f"  [profit] {sym}: up to date")
            continue
        try:
            saved = _sync_one(sym, from_year, from_quarter, override)
        except Exception as e:
            print(f"  ERROR [profit] {sym}: {e}")
            saved = True  # assume API was called
        if saved:
            time.sleep(0.3)


def _sync_one(sym: str, from_year, from_quarter, override: bool) -> bool:
    df = call_with_retry(cafef.get_net_profit, sym, raw_dir=RAW_DIR, label=sym)

    if df is None or df.empty:
        print(f"  [profit] {sym}: no data returned")
        return True

    if from_year is not None:
        fq = from_quarter or 1
        df = df[
            (df["year"] > from_year) |
            ((df["year"] == from_year) & (df["quarter"] >= fq))
        ]

    if df.empty:
        print(f"  [profit] {sym}: nothing to update for given range")
        return False

    if not override:
        df = fill_merge(df, db.load_net_profit(sym), cols=_KQKD_COLS, key_cols=["year", "quarter"])

    if df.empty:
        print(f"  [profit] {sym}: up to date")
        return False

    db.save_net_profit(sym, df)
    return True
