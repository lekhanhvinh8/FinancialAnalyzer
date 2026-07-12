"""
One-time migration: copy data from old DB schema (12 tables) to new schema (6 tables).

Run once after updating code:
    python migrate.py

Safe to run multiple times — uses INSERT OR IGNORE so existing rows are skipped.
Old tables are left intact and can be dropped manually once verified.
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "stock_data.db"


def migrate():
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA journal_mode=WAL")

    # ── Create new tables ─────────────────────────────────────────────────────
    import database as db
    db.init_db()

    print("Migrating data from old schema to new schema...")

    # ── 1. symbols: register stocks from prices table ─────────────────────────
    n = con.execute("""
        INSERT OR IGNORE INTO symbols (symbol, symbol_type)
        SELECT DISTINCT symbol, 'stock' FROM prices
    """).rowcount
    print(f"  symbols (stock):  {n} inserted")

    # ── 2. symbols: register indices from index_prices table ──────────────────
    try:
        n = con.execute("""
            INSERT OR IGNORE INTO symbols (symbol, symbol_type)
            SELECT DISTINCT symbol, 'index' FROM index_prices
        """).rowcount
        print(f"  symbols (index):  {n} inserted")
    except sqlite3.OperationalError:
        print("  symbols (index):  skipped (index_prices table not found)")

    # ── 3. daily_prices: from prices ─────────────────────────────────────────
    try:
        n = con.execute("""
            INSERT OR IGNORE INTO daily_prices (symbol, date, close)
            SELECT symbol, date, close FROM prices
        """).rowcount
        print(f"  daily_prices (stocks):  {n} inserted")
    except sqlite3.OperationalError:
        print("  daily_prices (stocks):  skipped")

    # ── 4. daily_prices: from index_prices ───────────────────────────────────
    try:
        n = con.execute("""
            INSERT OR IGNORE INTO daily_prices (symbol, date, close)
            SELECT symbol, date, close FROM index_prices
        """).rowcount
        print(f"  daily_prices (indices): {n} inserted")
    except sqlite3.OperationalError:
        print("  daily_prices (indices): skipped")

    # ── 5. quarterly_fundamentals: from shares ────────────────────────────────
    try:
        n = con.execute("""
            INSERT OR IGNORE INTO quarterly_fundamentals (symbol, year, quarter, shares)
            SELECT symbol, year, quarter, shares FROM shares
        """).rowcount
        print(f"  quarterly_fundamentals (shares):     {n} inserted")
    except sqlite3.OperationalError:
        print("  quarterly_fundamentals (shares):     skipped")

    # ── 6. quarterly_fundamentals: from net_profit ────────────────────────────
    try:
        con.execute("""
            INSERT OR IGNORE INTO quarterly_fundamentals (symbol, year, quarter)
            SELECT symbol, year, quarter FROM net_profit
        """)
        cur = con.execute("""
            UPDATE quarterly_fundamentals SET
                kqkd_14 = (SELECT kqkd_14 FROM net_profit np WHERE np.symbol = quarterly_fundamentals.symbol AND np.year = quarterly_fundamentals.year AND np.quarter = quarterly_fundamentals.quarter),
                kqkd_13 = (SELECT kqkd_13 FROM net_profit np WHERE np.symbol = quarterly_fundamentals.symbol AND np.year = quarterly_fundamentals.year AND np.quarter = quarterly_fundamentals.quarter),
                kqkd_10 = (SELECT kqkd_10 FROM net_profit np WHERE np.symbol = quarterly_fundamentals.symbol AND np.year = quarterly_fundamentals.year AND np.quarter = quarterly_fundamentals.quarter)
            WHERE EXISTS (SELECT 1 FROM net_profit np WHERE np.symbol = quarterly_fundamentals.symbol AND np.year = quarterly_fundamentals.year AND np.quarter = quarterly_fundamentals.quarter)
        """)
        print(f"  quarterly_fundamentals (net_profit): {cur.rowcount} updated")
    except sqlite3.OperationalError as e:
        print(f"  quarterly_fundamentals (net_profit): skipped ({e})")

    # ── 7. index_members: from vn30_members ──────────────────────────────────
    for idx in ("vn30", "vndiamond", "vnfinlead"):
        try:
            n = con.execute(f"""
                INSERT OR IGNORE INTO index_members (index_symbol, member_symbol, date_added, date_removed)
                SELECT '{idx}', symbol, date_added, date_removed FROM {idx}_members
            """).rowcount
            print(f"  index_members ({idx}): {n} inserted")
        except sqlite3.OperationalError:
            print(f"  index_members ({idx}): skipped")

    # ── 8. pe_ratios: from pe_vn30, pe_vndiamond, pe_vnfinlead ──────────────
    for idx in ("vn30", "vndiamond", "vnfinlead"):
        try:
            n = con.execute(f"""
                INSERT OR IGNORE INTO pe_ratios
                    (symbol, date, pe_ratio, total_market_cap, total_ttm_profit, member_count)
                SELECT '{idx}', date, pe_ratio, total_market_cap, total_ttm_profit, member_count
                FROM pe_{idx}
            """).rowcount
            print(f"  pe_ratios ({idx}): {n} inserted")
        except sqlite3.OperationalError:
            print(f"  pe_ratios ({idx}): skipped")

    # ── 9. pe_ratios: from pe_members (stock-level) ───────────────────────────
    try:
        n = con.execute("""
            INSERT OR IGNORE INTO pe_ratios (symbol, date, pe_ratio)
            SELECT symbol, date, pe_ratio FROM pe_members
        """).rowcount
        print(f"  pe_ratios (members): {n} inserted")
    except sqlite3.OperationalError:
        print("  pe_ratios (members): skipped")

    # ── 10. range_stats: from cal_range_stats ────────────────────────────────
    try:
        n = con.execute("""
            INSERT OR IGNORE INTO range_stats
                (symbol, date, range_days, direction,
                 local_top, local_avg, local_bottom, p25, median, p75,
                 pe_top, pe_avg, pe_bottom, pe_p25, pe_median, pe_p75)
            SELECT
                index_symbol, date, range_days, direction,
                local_top, local_avg, local_bottom, p25, median, p75,
                pe_top, pe_avg, pe_bottom, pe_p25, pe_median, pe_p75
            FROM cal_range_stats
        """).rowcount
        print(f"  range_stats: {n} inserted")
    except sqlite3.OperationalError:
        print("  range_stats: skipped (cal_range_stats not found)")

    con.commit()
    con.close()
    print("\nMigration complete. Old tables are preserved — drop them manually once verified.")
    print("Old tables: prices, index_prices, shares, net_profit,")
    print("            vn30_members, vndiamond_members, vnfinlead_members,")
    print("            pe_vn30, pe_vndiamond, pe_vnfinlead, pe_members, cal_range_stats")


if __name__ == "__main__":
    migrate()
