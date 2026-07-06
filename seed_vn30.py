"""
Seed vn30_members table from historical snapshot data.

Source: C:\projects\Stock_Analyzer\PriceToEarn\src\index_definitions.py
        VN30_SNAPSHOTS — researched from HOSE announcements and ETF reports.

Each snapshot represents the VN30 composition effective from that date.
We derive (symbol, date_added, date_removed) by comparing consecutive snapshots:
  - stocks that appear in snapshot N but not N-1 → date_added = snapshot N date
  - stocks that disappear in snapshot N → date_removed = snapshot N date
  - stocks still active in the latest snapshot → date_removed = None
"""

from database import init_db, save_vn30_members, load_vn30_members

# ── Historical VN30 snapshots ─────────────────────────────────────────────────
# Copied from C:\projects\Stock_Analyzer\PriceToEarn\src\index_definitions.py
# Source: HOSE semi-annual review announcements, SSI/VNDIRECT ETF monitor reports

VN30_SNAPSHOTS: dict[str, list[str]] = {
    "2012-02-06": [
        "BVH","CTG","DPM","EIB","FPT","GAS","HAG","HPG","HT1","KDC",
        "MSN","MWG","PNJ","PPC","REE","SAB","SSI","STB","TCB","TRA",
        "VCB","VIC","VNM","VPB","VRE","BID","MBB","ACB","SHB","GMD",
    ],
    "2014-08-01": [
        "ACB","BID","BVH","CTG","DPM","EIB","FPT","GAS","GMD","HAG",
        "HPG","HT1","KDC","MBB","MSN","MWG","PNJ","REE","SAB","SSI",
        "STB","TCB","VCB","VIC","VNM","VPB","VRE","CII","SBT","NVL",
    ],
    "2017-03-01": [
        "ACB","BID","BVH","CTG","FPT","GAS","HDB","HPG","MBB","MSN",
        "MWG","NVL","PLX","PNJ","SAB","SSI","STB","TCB","TPB","VCB",
        "VHM","VIC","VJC","VNM","VPB","VRE","SHB","EIB","GVR","LPB",
    ],
    "2019-08-01": [
        "ACB","BID","BVH","CTG","FPT","GAS","GVR","HDB","HPG","LPB",
        "MBB","MSN","MWG","NVL","PLX","SAB","SHB","SSB","SSI","STB",
        "TCB","TPB","VCB","VHM","VIB","VIC","VJC","VNM","VPB","VRE",
    ],
    "2021-03-01": [
        "ACB","BID","BSR","CTG","FPT","GAS","GVR","HDB","HPG","LPB",
        "MBB","MSN","MWG","PLX","SAB","SHB","SSB","SSI","STB","TCB",
        "TPB","VCB","VHM","VIB","VIC","VJC","VNM","VPB","VPL","VRE",
    ],
    "2023-02-01": [
        "ACB","BID","BSR","CTG","FPT","GAS","GVR","HDB","HPG","LPB",
        "MBB","MSN","MWG","PLX","SAB","SHB","SSB","SSI","STB","TCB",
        "TPB","VCB","VHM","VIB","VIC","VJC","VNM","VPB","VPL","VRE",
    ],
    "2025-03-01": [
        "ACB","BID","BSR","CTG","FPT","GAS","GVR","HDB","HPG","LPB",
        "MBB","MSN","MWG","PLX","SAB","SHB","SSB","SSI","STB","TCB",
        "TPB","VCB","VHM","VIB","VIC","VJC","VNM","VPB","VPL","VRE",
    ],
}


def snapshots_to_membership(snapshots: dict[str, list[str]]) -> list[tuple[str, str, str | None]]:
    """
    Convert snapshot dict to (symbol, date_added, date_removed) rows.

    Logic:
    - For each consecutive pair of snapshots (prev, curr):
        - symbols in curr but not prev → added on curr date
        - symbols in prev but not curr → removed on curr date
    - First snapshot: all symbols added on that date
    - Last snapshot: active symbols have date_removed = None
    """
    sorted_dates = sorted(snapshots.keys())
    membership: dict[str, dict] = {}  # symbol -> {date_added, date_removed}

    rows = []

    for i, date_str in enumerate(sorted_dates):
        current = set(snapshots[date_str])
        previous = set(snapshots[sorted_dates[i - 1]]) if i > 0 else set()

        added   = current - previous if i > 0 else current
        removed = previous - current if i > 0 else set()

        for sym in added:
            if sym in membership:
                # Re-added after a removal — flush the completed period first
                rows.append((sym, membership[sym]["date_added"], membership[sym]["date_removed"]))
            membership[sym] = {"date_added": date_str, "date_removed": None}

        for sym in removed:
            if sym in membership:
                membership[sym]["date_removed"] = date_str
            else:
                # Stock was in previous snapshot but no earlier entry — use prev date
                rows.append((sym, sorted_dates[i - 1], date_str))

    # Flush remaining active and closed memberships
    for sym, info in membership.items():
        rows.append((sym, info["date_added"], info["date_removed"]))

    return sorted(rows, key=lambda r: (r[1], r[0]))


if __name__ == "__main__":
    init_db()

    rows = snapshots_to_membership(VN30_SNAPSHOTS)

    print(f"Derived {len(rows)} membership records from {len(VN30_SNAPSHOTS)} snapshots\n")
    print(f"{'Symbol':<8} {'Date Added':<14} {'Date Removed'}")
    print("-" * 40)
    for sym, added, removed in sorted(rows, key=lambda r: (r[1], r[0])):
        print(f"  {sym:<8} {added:<14} {removed or 'active'}")

    print()
    save_vn30_members(rows, override=True)

    print("\n--- Active members today ---")
    from datetime import date
    active = load_vn30_members(as_of=date.today().isoformat())
    print(f"  {len(active)} stocks: {', '.join(active['symbol'].tolist())}")

    print("\n--- Full history sample (first 10 rows) ---")
    history = load_vn30_members()
    print(history.head(10).to_string(index=False))
