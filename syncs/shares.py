"""Sync share counts (stocks only, via vnstock): today's count, and the quarterly history."""

import time
from datetime import date

import database as db
from syncs.calculate import _quarter_end  # same convention P/E gans shares by — see _restated_from
from syncs.sources import vnstock
from ._helpers import call_with_retry, resolve_stocks, fill_merge, is_shares_current

_SHARES_COLS = ["shares"]

# Two share counts this close apart are the same count — paid-in capital
# divided by par value does not land on an exact integer.
_SHARES_EPS = 0.0001

# Returned as the restated date when today's share count moves. P/E multiplies
# that one count into every date, so nothing earlier is left unaffected.
ALL_DATES = "1900-01-01"


def sync_shares(
    symbols:      list[str] | None = None,
    index:        str | None = None,
    from_year:    int | None = None,
    from_quarter: int | None = None,
    override:     bool = False,
) -> dict[str, str]:
    """
    Sync share counts for stocks: today's count (share_snapshots, the one P/E
    uses) on every run, and the quarterly balance-sheet history.

    symbols/index: which stocks to sync (index= resolves to its current members)
    from_year/from_quarter: only process quarters >= this point; None = all
    override: False → insert new rows; fill NULL shares in existing rows
              True  → overwrite all shares values

    Returns {symbol: date} for symbols whose newly arrived quarter restates the
    share count over dates that already have a P/E. A balance sheet lands about
    a month after the quarter it covers, so by the time a bonus issue or a
    capital raise shows up here, P/E has already been computed across that
    quarter on the old count. Those rows are wrong and an incremental sync will
    never revisit them — it resumes from the last date it wrote. The caller has
    to recompute P/E, and range_stats with it, from the returned date.

    Today's count moving returns ALL_DATES for that symbol: P/E reads it on every
    date. Once a symbol has today's count, a restated quarter no longer moves its
    P/E and is not reported.
    """
    stocks   = resolve_stocks(symbols, index)
    restated = {}

    for sym in stocks:
        try:
            if _sync_current(sym):
                restated[sym] = ALL_DATES
        except Exception as e:
            print(f"  ERROR [shares] {sym} today's count: {e}")
        time.sleep(6)   # two overview calls; the guest tier allows 20 a minute

        if not override and is_shares_current(sym):
            print(f"  [shares] {sym}: up to date")
            continue
        try:
            saved, since = _sync_one(sym, from_year, from_quarter, override)
            if since and db.load_current_shares(sym) is None:
                restated[sym] = since
        except Exception as e:
            print(f"  ERROR [shares] {sym}: {e}")
            saved = True  # assume API was called
        if saved:
            time.sleep(5)

    return restated


def _sync_current(sym: str) -> bool:
    """Store today's count; True when it moved and P/E has already been computed."""
    new = call_with_retry(vnstock.get_current_shares, sym, label=sym)
    old = db.load_current_shares(sym)
    db.save_share_snapshot(sym, new, date.today().isoformat())
    if old is not None and abs(new / old - 1) <= _SHARES_EPS:
        return False
    print(f"  [shares] {sym}: today's count {new:,.0f}"
          + (f" (was {old:,.0f}) — P/E stale on every date" if old else ""))
    return db.load_latest_pe_date(sym) is not None


def _sync_one(sym: str, from_year, from_quarter, override: bool) -> tuple[bool, str | None]:
    """Returns (api_called, restated_from) — see sync_shares for restated_from."""
    df = call_with_retry(vnstock.get_shares, sym, label=sym)

    if df is None or df.empty:
        print(f"  [shares] {sym}: no data returned")
        return True, None

    if from_year is not None:
        fq = from_quarter or 1
        df = df[
            (df["year"] > from_year) |
            ((df["year"] == from_year) & (df["quarter"] >= fq))
        ]

    if df.empty:
        print(f"  [shares] {sym}: nothing to update for given range")
        return False, None

    existing = db.load_shares(sym)

    if not override:
        df = fill_merge(df, existing, cols=_SHARES_COLS, key_cols=["year", "quarter"])

    if df.empty:
        print(f"  [shares] {sym}: up to date")
        return False, None

    since = _restated_from(sym, df, existing)
    db.save_shares(sym, df)

    if since:
        print(f"  [shares] {sym}: share count restated — P/E stale from {since}")

    return True, since


def _restated_from(sym: str, incoming, existing) -> str | None:
    """
    The earliest date whose P/E was computed on a share count we are now
    replacing, or None.

    P/E reads shares as a step function: a date takes the newest quarter whose
    quarter-end it has passed. So a quarter only invalidates dates from its own
    quarter-end onward, and only when it actually moves the count — most
    quarters repeat the previous one and change nothing.
    """
    import pandas as pd

    merged = pd.concat([existing, incoming])[["year", "quarter", "shares"]] if not existing.empty else incoming
    merged = merged.dropna(subset=["shares"])
    # Later rows win: incoming is concatenated second, so it overwrites a
    # quarter the DB already held.
    merged = merged.drop_duplicates(subset=["year", "quarter"], keep="last")
    merged = merged.sort_values(["year", "quarter"]).reset_index(drop=True)
    if len(merged) < 2:
        return None

    arriving = {(int(r.year), int(r.quarter)) for _, r in incoming.iterrows()}
    latest_pe = db.load_latest_pe_date(sym)
    if latest_pe is None:
        return None  # nothing computed yet — the first run will get it right

    for i in range(1, len(merged)):
        row  = merged.iloc[i]
        key  = (int(row.year), int(row.quarter))
        if key not in arriving:
            continue
        prev = float(merged.iloc[i - 1]["shares"])
        if prev <= 0 or abs(float(row.shares) / prev - 1) <= _SHARES_EPS:
            continue
        q_end = _quarter_end(key[0], key[1]).date().isoformat()
        if q_end <= latest_pe:
            return q_end

    return None
