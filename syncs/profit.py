"""Sync quarterly net profit from CafeF (stocks only)."""

import time

import pandas as pd
import database as db
from sources import cafef
from ._helpers import call_with_retry, resolve_stocks

RAW_DIR = "data/raw/cafef"
_KQKD_COLS = ("kqkd_14", "kqkd_13", "kqkd_10")


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
    override: False → preserve existing non-null kqkd values; only fill NULLs
              True  → overwrite all kqkd values with latest CafeF data
    """
    stocks = resolve_stocks(symbols, index)

    for sym in stocks:
        try:
            _sync_one(sym, from_year, from_quarter, override)
        except Exception as e:
            print(f"  ERROR [profit] {sym}: {e}")
        time.sleep(0.3)


def _sync_one(sym: str, from_year, from_quarter, override: bool) -> None:
    new_df = call_with_retry(cafef.get_net_profit, sym, raw_dir=RAW_DIR, label=sym)

    if new_df is None or new_df.empty:
        print(f"  [profit] {sym}: no data returned")
        return

    # Apply quarter filter
    if from_year is not None:
        fq = from_quarter or 1
        new_df = new_df[
            (new_df["year"] > from_year) |
            ((new_df["year"] == from_year) & (new_df["quarter"] >= fq))
        ]

    if new_df.empty:
        print(f"  [profit] {sym}: nothing to update for given range")
        return

    if not override:
        # Pre-merge: replace new values with existing DB values where DB is non-null
        new_df = _merge_preserve_existing(sym, new_df)

    if new_df.empty:
        return

    db.save_net_profit(sym, new_df)


def _merge_preserve_existing(sym: str, new_df: pd.DataFrame) -> pd.DataFrame:
    """
    For each row in new_df, replace kqkd columns with DB values where DB is non-null.
    This implements override=False semantics at the column level.
    """
    existing = db.load_net_profit(sym)
    if existing.empty:
        return new_df

    existing_map = {
        (int(r.year), int(r.quarter)): r
        for _, r in existing.iterrows()
    }

    merged = new_df.copy()
    for idx, row in merged.iterrows():
        key = (int(row.year), int(row.quarter))
        ex = existing_map.get(key)
        if ex is None:
            continue
        for col in _KQKD_COLS:
            ex_val = ex.get(col)
            if ex_val is not None and not (isinstance(ex_val, float) and ex_val != ex_val):
                merged.at[idx, col] = ex_val

    return merged
