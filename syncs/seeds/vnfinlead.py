import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from database import init_db, save_index_members, load_index_members
from syncs.seeds.vn30 import snapshots_to_membership

# Source: SSIAM VNFIN LEAD ETF factsheets, BSC rebalancing reports, HOSE announcements.
# VN Fin Lead launched 2019-11-18; reviewed quarterly by HOSE.
# 23 stocks as of 2025 (all financial sector: banks, securities, insurance).

VNFINLEAD_SNAPSHOTS: dict[str, list[str]] = {
    "2019-11-18": [
        "VCB", "BID", "CTG", "MBB", "ACB", "TCB", "VPB", "STB", "HDB", "SSI",
    ],
    "2020-05-01": [
        "VCB", "BID", "CTG", "MBB", "ACB", "TCB", "VPB", "STB", "HDB", "SSI",
        "VIB", "LPB", "SHB",
    ],
    "2021-02-01": [
        "VCB", "BID", "CTG", "MBB", "ACB", "TCB", "VPB", "STB", "HDB", "SSI",
        "VIB", "LPB", "SHB", "TPB", "EIB",
    ],
    "2022-02-01": [
        "VCB", "BID", "CTG", "MBB", "ACB", "TCB", "VPB", "STB", "HDB", "SSI",
        "VIB", "LPB", "SHB", "TPB", "EIB", "MSB", "OCB",
    ],
    "2023-02-01": [
        "VCB", "BID", "CTG", "MBB", "ACB", "TCB", "VPB", "STB", "HDB", "SSI",
        "VIB", "LPB", "SHB", "TPB", "EIB", "MSB", "OCB", "SSB", "VCI", "HCM",
    ],
    "2024-02-01": [
        "VCB", "BID", "CTG", "MBB", "ACB", "TCB", "VPB", "STB", "HDB", "SSI",
        "VIB", "LPB", "SHB", "TPB", "EIB", "MSB", "OCB", "SSB", "VCI", "HCM",
        "VIX", "VND", "NAB",
    ],
    "2025-02-01": [
        "ACB", "BID", "CTG", "EIB", "HCM", "HDB", "LPB", "MBB", "MSB", "NAB",
        "OCB", "SHB", "SSB", "SSI", "STB", "TCB", "TPB", "VCB", "VCI", "VIB",
        "VIX", "VND", "VPB",
    ],
}


def seed():
    rows = snapshots_to_membership(VNFINLEAD_SNAPSHOTS)
    save_index_members('vnfinlead', rows, override=True)


if __name__ == "__main__":
    init_db()

    rows = snapshots_to_membership(VNFINLEAD_SNAPSHOTS)
    print(f"Derived {len(rows)} membership records from {len(VNFINLEAD_SNAPSHOTS)} snapshots\n")
    print(f"{'Symbol':<8} {'Date Added':<14} {'Date Removed'}")
    print("-" * 40)
    for sym, added, removed in rows:
        print(f"  {sym:<8} {added:<14} {removed or 'active'}")

    print()
    save_index_members('vnfinlead', rows, override=True)

    print("\n--- Active members today ---")
    from datetime import date
    active = load_index_members('vnfinlead', as_of=date.today().isoformat())
    print(f"  {len(active)} stocks: {', '.join(active['symbol'].tolist())}")
