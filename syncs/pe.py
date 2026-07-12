"""Sync (recalculate) P/E ratios for indices and individual stocks."""

import database as db
import calculate

_KNOWN_INDICES = {"vn30", "vndiamond", "vnfinlead"}


def sync_pe(
    index:     str | None = None,
    symbols:   list[str] | None = None,
    from_date: str | None = None,
    override:  bool = False,
) -> None:
    """
    Recalculate and save P/E ratios.

    index     : index name ("vn30") → aggregate index P/E (+ per-member P/E)
    symbols   : stock or index symbols → per-symbol P/E
                index symbols (VN30/VNDIAMOND/VNFINLEAD) are auto-detected
                and routed to aggregate index P/E calculation
    from_date : recalculate only from this date onward; None = full history
    override  : True → ignore from_date and rebuild full history

    If both index and symbols are None, recalculates all three indices.
    """
    start = None if override else from_date

    # Build index and stock target lists
    # symbols may contain index symbols (e.g. "VN30") — route them correctly
    indices_to_run = []
    stocks_to_run  = []

    if index is not None:
        indices_to_run = [index]
    elif symbols is not None:
        for sym in symbols:
            if sym.lower() in _KNOWN_INDICES:
                indices_to_run.append(sym.lower())
            else:
                stocks_to_run.append(sym)
    else:
        indices_to_run = list(_KNOWN_INDICES)

    for idx in indices_to_run:
        print(f"\n  Recalculating {idx.upper()} P/E …")
        pe_df = calculate.calc_pe_history(index=idx, start=start, emit_members=True)

        valid = pe_df.dropna(subset=["pe_ratio"])
        if valid.empty:
            print(f"  [{idx.upper()}] no valid P/E rows")
            continue

        print(f"  [{idx.upper()}] {len(valid)} dates, current {valid.iloc[-1]['pe_ratio']:.2f}x")
        db.save_pe_ratios(idx, pe_df)

    for sym in stocks_to_run:
        print(f"\n  Recalculating {sym} P/E …")
        pe_df = calculate.calc_stock_pe(sym, start=start)

        if pe_df.empty:
            print(f"  [{sym}] no valid P/E rows")
            continue

        print(f"  [{sym}] {len(pe_df)} dates, current {pe_df.iloc[-1]['pe_ratio']:.2f}x")
        db.save_pe_ratios_bulk(pe_df.to_dict("records"))
