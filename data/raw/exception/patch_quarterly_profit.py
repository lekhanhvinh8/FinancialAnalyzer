"""
Patch missing quarterly profit (kqkd_14, kqkd_13) rows that CafeF does not provide.
Sources and confidence levels documented in quarterly_profit_patches.md.

Run from project root:
    python data/raw/exception/patch_quarterly_profit.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

import database as db

PATCHES = [
    # (symbol, year, quarter, kqkd_14, insert_if_missing)
    # NVL Q2 2025 — news: lỗ ~190 tỷ (low confidence)
    ("NVL", 2025, 2, -190_000_000_000, False),

    # PNJ Q2 2025 — calculated: H1(1119B) - Q1(677.7B) (medium confidence)
    ("PNJ", 2025, 2, 441_272_081_875, False),

    # TCB Q2 2025 — calculated: FY(25300B) - Q1 - Q3 - Q4 (medium confidence)
    ("TCB", 2025, 2, 6_257_134_000_000, False),

    # VHC Q3 2025 — directly stated: 433 tỷ (high confidence)
    ("VHC", 2025, 3, 433_000_000_000, False),

    # SBT 2025Q1 — INSERT: row missing; calculated 9M(680B) - Q1 - Q2 (medium confidence)
    ("SBT", 2025, 1, 259_921_621_781, True),

    # SBT 2025Q2 — calculated: FY(834B) - 9M(680B) (medium confidence)
    ("SBT", 2025, 2, 154_000_000_000, False),

    # SBT 2025Q3 — calculated: H1 fiscal 2025-2026(400B) - Q2 fiscal(192B) (medium confidence)
    ("SBT", 2025, 3, 208_000_000_000, False),

    # SBT 2025Q4 — directly stated: 192 tỷ (high confidence)
    ("SBT", 2025, 4, 192_000_000_000, False),

    # SBT 2026Q1 — directly stated: 245 tỷ (high confidence)
    ("SBT", 2026, 1, 245_000_000_000, False),
]


def apply_patches():
    db.init_db()
    with db._conn() as con:
        for sym, year, quarter, value, insert_if_missing in PATCHES:
            if insert_if_missing:
                con.execute(
                    "INSERT OR IGNORE INTO quarterly_fundamentals (symbol, year, quarter, kqkd_14, kqkd_13) VALUES (?,?,?,?,?)",
                    (sym, year, quarter, value, value),
                )
            con.execute(
                "UPDATE quarterly_fundamentals SET kqkd_14=?, kqkd_13=? WHERE symbol=? AND year=? AND quarter=?",
                (value, value, sym, year, quarter),
            )
            print(f"  patched {sym} {year}Q{quarter}: {value:,}")
        con.commit()
    print("Done.")


if __name__ == "__main__":
    apply_patches()
