"""Sync (recalculate) P/E ratios for indices and individual stocks."""

import database as db
import calculate


def sync_pe(
    indices:   list[str] | None = None,
    symbols:   list[str] | None = None,
    from_date: str | None = None,
) -> None:
    """
    Recalculate and save P/E ratios.

    indices   : index names → aggregate index P/E (+ per-member P/E)
    symbols   : individual stock symbols → per-stock P/E only
    from_date : recalculate only from this date onward; None = full history

    If both are None, recalculates all three indices.
    """
    for index in (indices or ([] if symbols else ["vn30", "vndiamond", "vnfinlead"])):
        print(f"\n  Recalculating {index.upper()} P/E …")
        pe_df = calculate.calc_pe_history(
            index=index,
            start=from_date,
            emit_members=True,
        )

        valid = pe_df.dropna(subset=["pe_ratio"])
        if valid.empty:
            print(f"  [{index.upper()}] no valid P/E rows")
            continue

        print(
            f"  [{index.upper()}] {len(valid)} dates, "
            f"current {valid.iloc[-1]['pe_ratio']:.2f}x"
        )
        db.save_pe_ratios(index, pe_df)

    for sym in (symbols or []):
        print(f"\n  Recalculating {sym} P/E …")
        pe_df = calculate.calc_stock_pe(sym, start=from_date)

        if pe_df.empty:
            print(f"  [{sym}] no valid P/E rows")
            continue

        print(f"  [{sym}] {len(pe_df)} dates, current {pe_df.iloc[-1]['pe_ratio']:.2f}x")
        db.save_pe_ratios_bulk(pe_df.to_dict("records"))
