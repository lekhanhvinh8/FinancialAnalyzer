"""Shared helpers for sync functions."""

import sys, io, time
from datetime import date, timedelta
import database as db

# Ensure stdout handles Vietnamese/Unicode output from vnstock on Windows
if hasattr(sys.stdout, "buffer") and getattr(sys.stdout, "encoding", "").lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PRICE_START   = "2012-01-01"
_RETRY_WAIT   = 40
_RETRIES      = 3


def last_trading_day() -> str:
    """Return the most recent trading day (Mon–Fri) as YYYY-MM-DD string."""
    today = date.today()
    offset = max(0, today.weekday() - 4)  # Sat→1, Sun→2, weekdays→0
    return (today - timedelta(days=offset)).isoformat()


def is_price_current(symbol: str) -> bool:
    """Return True if symbol has a non-null close price for the last trading day."""
    latest = db.load_latest_price_date(symbol)
    return latest is not None and latest >= last_trading_day()


def is_shares_current(symbol: str) -> bool:
    """Return True if symbol has a non-null shares value for the current quarter."""
    result = db.load_latest_shares_quarter(symbol)
    if result is None:
        return False
    year, quarter = result
    today = date.today()
    cur_q = (today.month - 1) // 3 + 1
    # current quarter data won't be released yet — consider previous quarter as "current"
    exp_y, exp_q = (today.year, cur_q - 1) if cur_q > 1 else (today.year - 1, 4)
    return (year, quarter) >= (exp_y, exp_q)


def is_range_stats_current(symbol: str) -> bool:
    """Return True if symbol has range_stats up to the last trading day."""
    latest = db.load_latest_range_stats_date(symbol)
    return latest is not None and latest >= last_trading_day()


def is_profit_current(symbol: str) -> bool:
    """Return True if symbol has non-null profit for the current quarter."""
    result = db.load_latest_profit_quarter(symbol)
    if result is None:
        return False
    year, quarter = result
    today = date.today()
    cur_q = (today.month - 1) // 3 + 1
    exp_y, exp_q = (today.year, cur_q - 1) if cur_q > 1 else (today.year - 1, 4)
    return (year, quarter) >= (exp_y, exp_q)

_INDEX_SYMBOL_MAP = {
    "vn30":      "VN30",
    "vndiamond": "VNDIAMOND",
    "vnfinlead": "VNFINLEAD",
    "vnindex":   "VNINDEX",
}
_INDEX_SYMBOLS    = set(_INDEX_SYMBOL_MAP.values())
_SYMBOL_INDEX_MAP = {v: k for k, v in _INDEX_SYMBOL_MAP.items()}  # "VN30" → "vn30"


def _members(index_name: str) -> list[str]:
    return db.load_index_members(index_name)["symbol"].unique().tolist()


def resolve_symbols(
    symbols: list[str] | None,
    index: str | None,
) -> list[tuple[str, str]]:
    """
    Resolve to [(symbol, symbol_type), ...].

    index="vn30"    → the index series itself: [("VN30", "index")]
    symbols=["VN30"] → all member stocks of VN30: [("ACB", "stock"), ...]
    symbols=["FPT"]  → [("FPT", "stock")]
    both None        → all symbols registered in the DB
    """
    if index is not None:
        sym = _INDEX_SYMBOL_MAP.get(index.lower(), index.upper())
        return [(sym, "index")]

    if symbols is not None:
        registered = dict(_registered_types())
        result = []
        for s in symbols:
            if s in _INDEX_SYMBOLS:
                result.extend([(m, "stock") for m in _members(_SYMBOL_INDEX_MAP[s])])
            else:
                result.append((s, registered.get(s, "stock")))
        return result

    return _registered_types()


def resolve_stocks(
    symbols: list[str] | None,
    index: str | None,
) -> list[str]:
    """
    Resolve to stock symbols only (shares/profit — no index series).

    index="vn30"     → raises ValueError (index has no shares/profit)
    symbols=["VN30"] → all member stocks of VN30
    symbols=["FPT"]  → ["FPT"]
    both None        → all stock symbols in DB
    """
    if index is not None:
        raise ValueError(
            f"index= is not valid here — the index series has no shares/profit. "
            f"Use symbols=['{index.upper()}'] to sync its member stocks."
        )

    if symbols is not None:
        result = []
        for s in symbols:
            if s in _INDEX_SYMBOLS:
                result.extend(_members(_SYMBOL_INDEX_MAP[s]))
            else:
                result.append(s)
        return result

    return db.list_symbols(symbol_type="stock")


def call_with_retry(fn, *args, label: str = "", **kwargs):
    for attempt in range(1, _RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except (Exception, SystemExit) as e:
            msg = str(e)
            is_rate = any(k in msg.lower() for k in ("rate", "limit", "20/", "exceeded"))
            is_exit = isinstance(e, SystemExit) or "process terminated" in msg.lower()
            if is_rate or is_exit:
                print(f"  Rate limited [{label}] — waiting {_RETRY_WAIT}s (attempt {attempt}/{_RETRIES})")
                time.sleep(_RETRY_WAIT)
            else:
                raise
    raise RuntimeError(f"Still rate-limited after {_RETRIES} retries for {label}")


def fill_merge(
    new_df,
    existing,
    cols: list[str],
    key_cols: list[str],
):
    """
    Merge new_df with existing for override=False semantics.

    For each row keyed by key_cols:
    - Row not in existing          → keep new row as-is
    - Row in existing, col IS NULL → use new value (fill the null)
    - Row in existing, col NOT NULL → keep existing value (protect non-null)

    Returns only rows that have something to write (new rows or rows with nulls filled).
    """
    import pandas as pd

    if existing is None or existing.empty:
        return new_df

    existing_map = {
        tuple(int(r[k]) if str(r[k]).isdigit() else r[k] for k in key_cols): r
        for _, r in existing.iterrows()
    }

    result = []
    for _, new_row in new_df.iterrows():
        key = tuple(int(new_row[k]) if str(new_row[k]).isdigit() else new_row[k] for k in key_cols)
        ex = existing_map.get(key)

        if ex is None:
            result.append(new_row)
            continue

        merged = new_row.copy()
        needs_write = False
        for col in cols:
            ex_val = ex.get(col)
            if ex_val is not None and not (isinstance(ex_val, float) and ex_val != ex_val):
                merged[col] = ex_val  # protect existing non-null
            else:
                needs_write = True    # DB has null — this column needs filling

        if needs_write:
            result.append(merged)

    return pd.DataFrame(result, columns=new_df.columns) if result else pd.DataFrame()


def _registered_types() -> list[tuple[str, str]]:
    return (
        [(s, "stock") for s in db.list_symbols("stock")] +
        [(s, "index") for s in db.list_symbols("index")]
    )
