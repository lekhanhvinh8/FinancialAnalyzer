"""Sync (recalculate) P/E ratios for indices and individual stocks."""

import database as db
import calculate
from ._helpers import resolve_symbols

_KNOWN_INDICES = {"vn30", "vndiamond", "vnfinlead"}


def sync_pe(
    index:     str | None = None,
    symbols:   list[str] | None = None,
    from_date: str | None = None,
    override:  bool = False,
) -> None:
    """
    Recalculate and save P/E ratios.

    index="vn30"     → aggregate VN30 P/E (+ per-member P/E as side effect)
    symbols=["VN30"] → individual P/E for each VN30 member stock
    symbols=["FPT"]  → individual FPT P/E
    both None        → aggregate P/E for all three indices

    from_date : recalculate only from this date onward; None = full history
    override  : True → ignore from_date, rebuild full history
    """
    start = None if override else from_date

    if index is not None:
        _sync_index_pe(index, start)
    elif symbols is not None:
        # resolve_symbols expands index symbols (e.g. "VN30") to member stocks
        for sym, _ in resolve_symbols(symbols, None):
            _sync_stock_pe(sym, start)
    else:
        for idx in _KNOWN_INDICES:
            _sync_index_pe(idx, start)


def _sync_index_pe(index: str, start: str | None) -> None:
    print(f"\n  Recalculating {index.upper()} P/E …")
    pe_df = calculate.calc_pe_history(index=index, start=start, emit_members=True)
    valid = pe_df.dropna(subset=["pe_ratio"])
    if valid.empty:
        print(f"  [{index.upper()}] no valid P/E rows")
        return
    print(f"  [{index.upper()}] {len(valid)} dates, current {valid.iloc[-1]['pe_ratio']:.2f}x")
    db.save_pe_ratios(index, pe_df)


def _sync_stock_pe(sym: str, start: str | None) -> None:
    print(f"\n  Recalculating {sym} P/E …")
    pe_df = calculate.calc_stock_pe(sym, start=start)
    if pe_df.empty:
        print(f"  [{sym}] no valid P/E rows")
        return
    print(f"  [{sym}] {len(pe_df)} dates, current {pe_df.iloc[-1]['pe_ratio']:.2f}x")
    db.save_pe_ratios_bulk(pe_df.to_dict("records"))
