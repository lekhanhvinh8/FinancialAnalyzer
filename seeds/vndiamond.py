import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import init_db, save_index_members, load_index_members
from seeds.vn30 import snapshots_to_membership

# Source: HOSE announcements, cafef.vn review articles, VNDirect ETF monitor,
#         FUEVFVND ETF portfolio (Investing.com UK, ~Jun 2026)
# VN Diamond launched 2019-11-18; reviewed quarterly by HOSE.
# 19 stocks: ≤10 banking stocks (combined weight capped at 40%) + non-banking.

VNDIAMOND_SNAPSHOTS: dict[str, list[str]] = {
    "2019-11-18": [
        "FPT", "MWG", "REE", "VNM", "PNJ", "NLG",
    ],
    "2020-02-01": [
        "FPT", "MWG", "REE", "VNM", "PNJ", "NLG",
        "VPB", "MBB", "TCB", "ACB",
    ],
    "2021-02-01": [
        "FPT", "MWG", "REE", "VNM", "PNJ", "NLG", "KDH",
        "VPB", "MBB", "TCB", "ACB", "HDB", "EIB", "MSB",
    ],
    "2022-05-01": [
        "FPT", "MWG", "REE", "VNM", "PNJ", "NLG", "KDH", "VHM", "VIC",
        "VPB", "MBB", "TCB", "ACB", "HDB", "EIB", "MSB", "LPB", "STB", "VIB",
    ],
    "2023-02-01": [
        "FPT", "MWG", "REE", "VNM", "PNJ", "NLG", "KDH", "VHM", "VIC", "MSN",
        "VPB", "MBB", "TCB", "ACB", "HDB", "EIB", "MSB", "LPB", "VIB",
    ],
    "2024-05-01": [
        "FPT", "MWG", "PNJ", "GMD", "KDH", "REE", "NLG", "VHC", "VCS",
        "TCB", "ACB", "VPB", "MBB", "HDB", "EIB", "MSB", "LPB", "VIB", "STB",
    ],
    "2025-04-28": [
        "FPT", "MWG", "PNJ", "GMD", "KDH", "REE", "CTD", "NLG", "VCS",
        "TCB", "ACB", "VPB", "MBB", "HDB", "EIB", "MSB", "LPB", "VIB", "STB",
    ],
    "2025-11-03": [
        "FPT", "MWG", "PNJ", "GMD", "KDH", "REE", "CTD", "NLG", "VCS",
        "TCB", "ACB", "VPB", "MBB", "HDB", "EIB", "MSB", "LPB", "STB", "MSN",
    ],
}


if __name__ == "__main__":
    init_db()

    rows = snapshots_to_membership(VNDIAMOND_SNAPSHOTS)
    print(f"Derived {len(rows)} membership records from {len(VNDIAMOND_SNAPSHOTS)} snapshots\n")
    print(f"{'Symbol':<8} {'Date Added':<14} {'Date Removed'}")
    print("-" * 40)
    for sym, added, removed in rows:
        print(f"  {sym:<8} {added:<14} {removed or 'active'}")

    print()
    save_index_members('vndiamond', rows, override=True)

    print("\n--- Active members today ---")
    from datetime import date
    active = load_index_members('vndiamond', as_of=date.today().isoformat())
    print(f"  {len(active)} stocks: {', '.join(active['symbol'].tolist())}")
