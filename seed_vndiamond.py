"""
Seed vndiamond_members table from historical snapshot data.

Source: C:\projects\Stock_Analyzer\PriceToEarn\src\index_definitions.py
        VNDIAMOND_SNAPSHOTS — researched from HOSE announcements,
        cafef.vn review articles, VNDirect ETF monitor, and
        FUEVFVND ETF portfolio (DCVFM VN Diamond ETF).

VN Diamond launched 2019-11-18; reviewed quarterly by HOSE.
19 stocks: ≤10 banking stocks (combined weight capped at 40%) + non-banking.
Stocks qualify when their foreign ownership room is near exhausted.
"""

from database import init_db, save_vndiamond_members, load_vndiamond_members
from seed_vn30 import snapshots_to_membership

# ── Historical VN Diamond snapshots ──────────────────────────────────────────
# Source: HOSE announcements, cafef.vn review articles, VNDirect ETF monitor,
#         FUEVFVND ETF portfolio (Investing.com UK, ~Jun 2026)

VNDIAMOND_SNAPSHOTS: dict[str, list[str]] = {
    # Launch (Nov 2019) — initial non-bank FOL stocks
    "2019-11-18": [
        "FPT", "MWG", "REE", "VNM", "PNJ", "NLG",
    ],
    # Q1 2020 — bank FOL stocks (VPB, MBB, TCB, ACB near 30% bank limit) join
    "2020-02-01": [
        "FPT", "MWG", "REE", "VNM", "PNJ", "NLG",
        "VPB", "MBB", "TCB", "ACB",
    ],
    # 2021 — more FOL banks added
    "2021-02-01": [
        "FPT", "MWG", "REE", "VNM", "PNJ", "NLG", "KDH",
        "VPB", "MBB", "TCB", "ACB", "HDB", "EIB", "MSB",
    ],
    # 2022 — further expansion
    "2022-05-01": [
        "FPT", "MWG", "REE", "VNM", "PNJ", "NLG", "KDH", "VHM", "VIC",
        "VPB", "MBB", "TCB", "ACB", "HDB", "EIB", "MSB", "LPB", "STB", "VIB",
    ],
    # 2023 — 19 stocks; VNM weight increases; MSN added
    "2023-02-01": [
        "FPT", "MWG", "REE", "VNM", "PNJ", "NLG", "KDH", "VHM", "VIC", "MSN",
        "VPB", "MBB", "TCB", "ACB", "HDB", "EIB", "MSB", "LPB", "VIB",
    ],
    # Q2 2024 — VNM removed as FOL eased; GMD, VHC, VCS enter
    "2024-05-01": [
        "FPT", "MWG", "PNJ", "GMD", "KDH", "REE", "NLG", "VHC", "VCS",
        "TCB", "ACB", "VPB", "MBB", "HDB", "EIB", "MSB", "LPB", "VIB", "STB",
    ],
    # Q2 2025 (eff. Apr 28 2025) — CTD added, VRE removed
    # Source: HOSE Apr 2025 announcement; FUEVFVND ETF (Investing.com UK ~Jun 2026)
    "2025-04-28": [
        "FPT", "MWG", "PNJ", "GMD", "KDH", "REE", "CTD", "NLG", "VCS",
        "TCB", "ACB", "VPB", "MBB", "HDB", "EIB", "MSB", "LPB", "VIB", "STB",
    ],
    # Q4 2025 (eff. Nov 3 2025) — VIB removed, MSN re-enters
    # Source: HOSE Oct 20 2025 announcement
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
    save_vndiamond_members(rows, override=True)

    print("\n--- Active members today ---")
    from datetime import date
    active = load_vndiamond_members(as_of=date.today().isoformat())
    print(f"  {len(active)} stocks: {', '.join(active['symbol'].tolist())}")
