"""Sync (recalculate) aggregate P/E ratios for indices."""

import database as db
import calculate


def sync_pe(
    indices:   list[str] | None = None,
    from_date: str | None = None,
) -> None:
    """
    Recalculate and save aggregate P/E for each index.

    indices   : ["vn30", "vndiamond", "vnfinlead"] or None (= all three)
    from_date : recalculate only from this date onward; None = full history
    """
    targets = indices or ["vn30", "vndiamond", "vnfinlead"]

    for index in targets:
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
