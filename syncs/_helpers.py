"""Shared helpers for sync functions."""

import time
import database as db

PRICE_START   = "2012-01-01"
_RETRY_WAIT   = 40
_RETRIES      = 3

_INDEX_SYMBOL_MAP = {
    "vn30":      "VN30",
    "vndiamond": "VNDIAMOND",
    "vnfinlead": "VNFINLEAD",
    "vnindex":   "VNINDEX",
}
_INDEX_SYMBOLS = set(_INDEX_SYMBOL_MAP.values())


def resolve_symbols(
    symbols: list[str] | None,
    index: str | None,
) -> list[tuple[str, str]]:
    """
    Resolve to [(symbol, symbol_type), ...].
    - index="vn30"   → the index series itself ("VN30", "index") — NOT member stocks
    - symbols=[...]  → each symbol with its type from DB (fallback: "stock")
    - both None      → all symbols registered in the DB
    """
    if index is not None:
        sym = _INDEX_SYMBOL_MAP.get(index.lower(), index.upper())
        return [(sym, "index")]

    if symbols is not None:
        registered = dict(_registered_types())
        return [(s, registered.get(s, "index" if s in _INDEX_SYMBOLS else "stock")) for s in symbols]

    return _registered_types()


def resolve_stocks(
    symbols: list[str] | None,
    index: str | None,
) -> list[str]:
    """
    Resolve to stock symbols only.
    - index="vn30"   → all current member stocks of vn30
    - symbols=[...]  → as-is, but raises ValueError for any index symbol
    - both None      → all stock symbols in DB
    """
    if index is not None:
        return db.load_index_members(index.lower())["symbol"].unique().tolist()

    if symbols is not None:
        for s in symbols:
            if s in _INDEX_SYMBOLS:
                raise ValueError(
                    f"'{s}' is an index symbol. Use index= to resolve its member stocks."
                )
        return symbols

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
