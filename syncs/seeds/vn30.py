import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from database import init_db, save_index_members, load_index_members

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

    - symbols appearing in snapshot N but not N-1 → added on N
    - symbols disappearing in snapshot N → removed on N
    - active in latest snapshot → date_removed = None
    """
    sorted_dates = sorted(snapshots.keys())
    membership: dict[str, dict] = {}
    rows = []

    for i, date_str in enumerate(sorted_dates):
        current  = set(snapshots[date_str])
        previous = set(snapshots[sorted_dates[i - 1]]) if i > 0 else set()

        added   = current - previous if i > 0 else current
        removed = previous - current if i > 0 else set()

        for sym in added:
            if sym in membership:
                rows.append((sym, membership[sym]["date_added"], membership[sym]["date_removed"]))
            membership[sym] = {"date_added": date_str, "date_removed": None}

        for sym in removed:
            if sym in membership:
                membership[sym]["date_removed"] = date_str
            else:
                rows.append((sym, sorted_dates[i - 1], date_str))

    for sym, info in membership.items():
        rows.append((sym, info["date_added"], info["date_removed"]))

    return sorted(rows, key=lambda r: (r[1], r[0]))


def seed():
    rows = snapshots_to_membership(VN30_SNAPSHOTS)
    save_index_members('vn30', rows, override=True)


if __name__ == "__main__":
    init_db()

    rows = snapshots_to_membership(VN30_SNAPSHOTS)
    print(f"Derived {len(rows)} membership records from {len(VN30_SNAPSHOTS)} snapshots\n")
    print(f"{'Symbol':<8} {'Date Added':<14} {'Date Removed'}")
    print("-" * 40)
    for sym, added, removed in rows:
        print(f"  {sym:<8} {added:<14} {removed or 'active'}")

    print()
    save_index_members('vn30', rows, override=True)

    print("\n--- Active members today ---")
    from datetime import date
    active = load_index_members('vn30', as_of=date.today().isoformat())
    print(f"  {len(active)} stocks: {', '.join(active['symbol'].tolist())}")

    print("\n--- Full history sample (first 10 rows) ---")
    history = load_index_members('vn30')
    print(history.head(10).to_string(index=False))
