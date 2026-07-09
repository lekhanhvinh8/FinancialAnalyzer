"""
Seed vnfinlead_members table from historical snapshot data.

Source: C:\projects\Stock_Analyzer\PriceToEarn\src\index_definitions.py
        VNFINLEAD_SNAPSHOTS — researched from SSIAM VNFIN LEAD ETF factsheets,
        BSC rebalancing reports, and HOSE announcements.

VN Fin Lead launched 2019-11-18; reviewed quarterly by HOSE.
23 stocks as of 2025 (all financial sector: banks, securities, insurance).
"""

from database import init_db, save_vnfinlead_members, load_vnfinlead_members
from seed_vn30 import snapshots_to_membership

VNFINLEAD_SNAPSHOTS: dict[str, list[str]] = {
    # Launch (Nov 2019) — initial 10 leading financial stocks
    "2019-11-18": [
        "VCB", "BID", "CTG", "MBB", "ACB", "TCB", "VPB", "STB", "HDB", "SSI",
    ],
    # 2020 — VIB, LPB, SHB added
    "2020-05-01": [
        "VCB", "BID", "CTG", "MBB", "ACB", "TCB", "VPB", "STB", "HDB", "SSI",
        "VIB", "LPB", "SHB",
    ],
    # 2021 — TPB, EIB added
    "2021-02-01": [
        "VCB", "BID", "CTG", "MBB", "ACB", "TCB", "VPB", "STB", "HDB", "SSI",
        "VIB", "LPB", "SHB", "TPB", "EIB",
    ],
    # 2022 — MSB, OCB added
    "2022-02-01": [
        "VCB", "BID", "CTG", "MBB", "ACB", "TCB", "VPB", "STB", "HDB", "SSI",
        "VIB", "LPB", "SHB", "TPB", "EIB", "MSB", "OCB",
    ],
    # 2023 — SSB, VCI, HCM added
    "2023-02-01": [
        "VCB", "BID", "CTG", "MBB", "ACB", "TCB", "VPB", "STB", "HDB", "SSI",
        "VIB", "LPB", "SHB", "TPB", "EIB", "MSB", "OCB", "SSB", "VCI", "HCM",
    ],
    # 2024 — VIX, VND, NAB added
    "2024-02-01": [
        "VCB", "BID", "CTG", "MBB", "ACB", "TCB", "VPB", "STB", "HDB", "SSI",
        "VIB", "LPB", "SHB", "TPB", "EIB", "MSB", "OCB", "SSB", "VCI", "HCM",
        "VIX", "VND", "NAB",
    ],
    # 2025-current — confirmed from SSIAM VNFIN LEAD ETF factsheet 31/05/2026
    # BSC report: no composition change in Q2 2025 rebalancing
    "2025-02-01": [
        "ACB", "BID", "CTG", "EIB", "HCM", "HDB", "LPB", "MBB", "MSB", "NAB",
        "OCB", "SHB", "SSB", "SSI", "STB", "TCB", "TPB", "VCB", "VCI", "VIB",
        "VIX", "VND", "VPB",
    ],
}


if __name__ == "__main__":
    init_db()

    rows = snapshots_to_membership(VNFINLEAD_SNAPSHOTS)

    print(f"Derived {len(rows)} membership records from {len(VNFINLEAD_SNAPSHOTS)} snapshots\n")
    print(f"{'Symbol':<8} {'Date Added':<14} {'Date Removed'}")
    print("-" * 40)
    for sym, added, removed in rows:
        print(f"  {sym:<8} {added:<14} {removed or 'active'}")

    print()
    save_vnfinlead_members(rows, override=True)

    print("\n--- Active members today ---")
    from datetime import date
    active = load_vnfinlead_members(as_of=date.today().isoformat())
    print(f"  {len(active)} stocks: {', '.join(active['symbol'].tolist())}")
