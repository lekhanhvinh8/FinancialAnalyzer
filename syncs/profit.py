"""Sync quarterly net profit from CafeF (stocks only)."""

import time
from datetime import date
from pathlib import Path

import pandas as pd

import database as db
from syncs.calculate import _quarter_end
from syncs.sources import cafef
from ._helpers import call_with_retry, resolve_stocks, is_profit_current

RAW_DIR   = "data/raw/cafef"
# Every quarter derived from a full-year figure, so the DB can be rebuilt
# without the API (audit_data.py --offline --fix) — CafeF may have changed by then.
DERIVED_CSV = Path(__file__).resolve().parent.parent / "data/raw/exception/derived_quarterly_profit.csv"
# Hand-sourced quarters (data/raw/exception/quarterly_profit_patches.md) beat a
# derived one: the subtraction inherits any error in the other three quarters.
PATCH_SCRIPT = DERIVED_CSV.parent / "patch_quarterly_profit.py"
_KQKD_COLS = ["kqkd_14", "kqkd_13", "kqkd_10"]

# Two figures this close apart are the same figure.
_AGREE_TOL = 0.001


def sync_profit(
    symbols:      list[str] | None = None,
    index:        str | None = None,
    from_year:    int | None = None,
    from_quarter: int | None = None,
    override:     bool = False,
) -> dict[str, str]:
    """
    Sync quarterly net profit for stocks via CafeF.

    symbols/index: which stocks to sync (index= resolves to its current members)
    from_year/from_quarter: with override, only overwrite quarters >= this point
    override: False → add new quarters, fill empty kqkd values (see merge_profit),
                      and derive a year's single missing quarter from the
                      full-year figure (see derive_from_annual)
              True  → overwrite all kqkd values with latest CafeF data

    Returns {symbol: date} — the quarter-end of the earliest quarter written.
    P/E has to be recomputed from there: a quarter that arrives a month after
    it ended changes TTM on dates P/E has already been computed for.
    """
    stocks  = resolve_stocks(symbols, index)
    changed = {}

    for sym in stocks:
        if not override and is_profit_current(sym) and not lone_gaps(db.load_net_profit(sym)):
            print(f"  [profit] {sym}: up to date")
            continue
        try:
            saved, since = _sync_one(sym, from_year, from_quarter, override)
            if since:
                changed[sym] = since
        except Exception as e:
            print(f"  ERROR [profit] {sym}: {e}")
            saved = True  # assume API was called
        if saved:
            time.sleep(0.3)

    return changed


def _sync_one(sym: str, from_year, from_quarter, override: bool) -> tuple[bool, str | None]:
    """Returns (api_called, earliest quarter-end written)."""
    df = call_with_retry(cafef.get_net_profit, sym, raw_dir=RAW_DIR, label=sym)

    if df is None or df.empty:
        print(f"  [profit] {sym}: no data returned")
        return True, None

    if override:
        if from_year is not None:
            fq = from_quarter or 1
            df = df[(df["year"] > from_year) |
                    ((df["year"] == from_year) & (df["quarter"] >= fq))]
    else:
        # The whole response, not just quarters after the latest stored one:
        # CafeF fills in old quarters late, and only a full merge picks them up.
        df, skipped = merge_profit(df, db.load_net_profit(sym))
        for (y, q), why in skipped:
            print(f"  [profit] {sym} {y}Q{q}: not filled — {why}")

    since = save(sym, df)
    if override:
        return True, since

    stored = db.load_net_profit(sym)
    if lone_gaps(stored):
        annual  = call_with_retry(cafef.get_annual_net_profit, sym, raw_dir=RAW_DIR, label=sym)
        derived = derive_from_annual(sym, stored, annual)
        for r in derived.itertuples():
            print(f"  [profit] {sym} {r.year}Q{r.quarter}: derived from the full year")
        d = save(sym, derived)
        record_derived(sym, derived)
        since = min(filter(None, (since, d)), default=None)
    return True, since


def lone_gaps(stored: pd.DataFrame) -> list[tuple[int, int]]:
    """Quarters missing from a finished year that has the other three."""
    have = {(int(r.year), int(r.quarter)) for r in stored.itertuples()
            if any(_val(getattr(r, c)) is not None for c in _KQKD_COLS)}
    out = []
    for y in {y for y, _ in have if y < date.today().year}:
        missing = [(y, q) for q in range(1, 5) if (y, q) not in have]
        if len(missing) == 1:
            out.append(missing[0])
    return sorted(out)


def derive_from_annual(sym: str, stored: pd.DataFrame, annual: pd.DataFrame) -> pd.DataFrame:
    """
    Each lone missing quarter as the full year minus the other three, column
    by column. A column is derived only when the year and all three quarters
    have it — the same way the manual patches in data/raw/exception were made.
    A quarter that has a manual patch is left to it.
    """
    if annual is None or annual.empty:
        return pd.DataFrame(columns=["year", "quarter", *_KQKD_COLS])
    q = {(int(r.year), int(r.quarter)): r for r in stored.itertuples()}
    fy = {int(r.year): r for r in annual.itertuples()}
    out = []
    patched = _patched_quarters()
    for y, gap in lone_gaps(stored):
        if y not in fy or (sym, y, gap) in patched:
            continue
        row = {"year": y, "quarter": gap}
        for c in _KQKD_COLS:
            parts = [_val(getattr(q[(y, k)], c)) for k in range(1, 5) if k != gap]
            total = _val(getattr(fy[y], c))
            row[c] = (_val(total - sum(parts))
                      if total is not None and all(v is not None for v in parts) else None)
        if any(row[c] is not None for c in _KQKD_COLS):
            out.append(row)
    return pd.DataFrame(out, columns=["year", "quarter", *_KQKD_COLS])


def _patched_quarters() -> set[tuple[str, int, int]]:
    """(symbol, year, quarter) of every manual patch."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("patch_quarterly_profit", PATCH_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return {(s, y, q) for s, y, q, *_ in mod.PATCHES}


def merge_profit(new: pd.DataFrame, existing: pd.DataFrame):
    """
    Rows of `new` worth writing over `existing`, and the quarters refused.

    - Quarter not stored  → written as is
    - Stored value empty  → filled. Zero counts as empty: CafeF served 0 for
      banks' KQKD_14 for years before it had the real figure.
    - Stored value set    → kept

    A stored quarter is filled only when every value both sides have agrees.
    When they disagree the source row itself is suspect — CafeF has served a
    bank's cumulative half-year as its Q2 — so it is refused rather than mixed
    into a row that is right.

    Returns (rows_to_write, [((year, quarter), reason), ...]).
    """
    have = {(int(r.year), int(r.quarter)): r for r in existing.itertuples()}
    out, skipped = [], []
    for r in new.itertuples():
        key = (int(r.year), int(r.quarter))
        row = {"year": key[0], "quarter": key[1], **{c: _val(getattr(r, c)) for c in _KQKD_COLS}}
        old = have.get(key)
        if old is None:
            if any(row[c] is not None for c in _KQKD_COLS):
                out.append(row)
            continue

        stored = {c: _val(getattr(old, c)) for c in _KQKD_COLS}
        clash = [c for c in _KQKD_COLS if stored[c] is not None and row[c] is not None
                 and abs(stored[c] - row[c]) > _AGREE_TOL * abs(stored[c])]
        fill = [c for c in _KQKD_COLS if stored[c] is None and row[c] is not None]
        if not fill:
            continue
        if clash:
            skipped.append((key, "source disagrees on " + ", ".join(clash)))
            continue
        out.append({**row, **{c: stored[c] for c in _KQKD_COLS if stored[c] is not None}})

    return pd.DataFrame(out, columns=["year", "quarter", *_KQKD_COLS]), skipped


def _val(v):
    """A usable figure, or None for null / NaN / zero."""
    return None if v is None or v != v or v == 0 else float(v)


def record_derived(sym: str, df: pd.DataFrame) -> None:
    """Add derived quarters to DERIVED_CSV, replacing any earlier row for the same quarter."""
    if df.empty:
        return
    new = df.assign(symbol=sym, derived_on=date.today().isoformat(),
                    method="full year minus the other three quarters")
    old = load_derived()
    keys = set(zip(new.symbol, new.year, new.quarter))
    old = old[[k not in keys for k in zip(old.symbol, old.year, old.quarter)]]
    out = (pd.concat([old, new], ignore_index=True)
           .sort_values(["symbol", "year", "quarter"])
           [["symbol", "year", "quarter", *_KQKD_COLS, "method", "derived_on"]])
    DERIVED_CSV.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(DERIVED_CSV, index=False, float_format="%.0f")


def load_derived(sym: str | None = None) -> pd.DataFrame:
    """DERIVED_CSV, optionally for one symbol; empty frame when there is none."""
    if not DERIVED_CSV.exists():
        return pd.DataFrame(columns=["symbol", "year", "quarter", *_KQKD_COLS, "method", "derived_on"])
    df = pd.read_csv(DERIVED_CSV)
    return df[df.symbol == sym].reset_index(drop=True) if sym else df


def save(sym: str, df: pd.DataFrame) -> str | None:
    """Write the rows; return the quarter-end of the earliest one, or None."""
    if df.empty:
        print(f"  [profit] {sym}: up to date")
        return None
    db.save_net_profit(sym, df)
    first = df.sort_values(["year", "quarter"]).iloc[0]
    return _quarter_end(int(first.year), int(first.quarter)).date().isoformat()
