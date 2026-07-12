"""
SQLite storage for Vietnam stock data.

Tables:
    prices           (symbol, date, close)
    shares           (symbol, year, quarter, shares)
    net_profit       (symbol, year, quarter, net_profit)

quarter is an integer 1-4.
Save functions skip existing rows by default; pass override=True to overwrite.
"""

import sqlite3
from pathlib import Path
from contextlib import contextmanager

import pandas as pd

DB_PATH = Path(__file__).parent / "stock_data.db"


@contextmanager
def _conn():
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA journal_mode=WAL")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_db():
    """Create tables if they don't exist."""
    with _conn() as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS prices (
                symbol  TEXT     NOT NULL,
                date    TEXT     NOT NULL,   -- ISO date: YYYY-MM-DD
                close   REAL     NOT NULL,   -- VND
                PRIMARY KEY (symbol, date)
            );

            CREATE TABLE IF NOT EXISTS shares (
                symbol   TEXT     NOT NULL,
                year     INTEGER  NOT NULL,
                quarter  INTEGER  NOT NULL,  -- 1, 2, 3, or 4
                shares   REAL     NOT NULL,
                PRIMARY KEY (symbol, year, quarter)
            );

            CREATE TABLE IF NOT EXISTS net_profit (
                symbol   TEXT     NOT NULL,
                year     INTEGER  NOT NULL,
                quarter  INTEGER  NOT NULL,  -- 1, 2, 3, or 4
                kqkd_14  REAL,               -- profit attr. to parent shareholders (primary for P/E)
                kqkd_13  REAL,               -- total consolidated profit after tax
                kqkd_10  REAL,               -- securities broker template (SSI, VCI, etc.)
                PRIMARY KEY (symbol, year, quarter)
            );

            CREATE TABLE IF NOT EXISTS index_prices (
                symbol  TEXT  NOT NULL,
                date    TEXT  NOT NULL,   -- ISO date: YYYY-MM-DD
                close   REAL  NOT NULL,   -- index points (not VND)
                PRIMARY KEY (symbol, date)
            );

            CREATE TABLE IF NOT EXISTS pe_vn30 (
                date             TEXT  PRIMARY KEY,  -- ISO date: YYYY-MM-DD
                pe_ratio         REAL,               -- aggregate P/E, NULL if incalculable
                total_market_cap REAL,               -- Σ(price × shares) in VND
                total_ttm_profit REAL,               -- Σ(TTM net profit) in VND
                member_count     INTEGER             -- number of stocks included
            );

            CREATE TABLE IF NOT EXISTS vn30_members (
                symbol        TEXT  NOT NULL,
                date_added    TEXT  NOT NULL,  -- ISO date: first effective trading day
                date_removed  TEXT,            -- ISO date: first day no longer in index, NULL = still active
                PRIMARY KEY (symbol, date_added)
            );

            CREATE TABLE IF NOT EXISTS vndiamond_members (
                symbol        TEXT  NOT NULL,
                date_added    TEXT  NOT NULL,
                date_removed  TEXT,
                PRIMARY KEY (symbol, date_added)
            );

            CREATE TABLE IF NOT EXISTS pe_vndiamond (
                date             TEXT  PRIMARY KEY,
                pe_ratio         REAL,
                total_market_cap REAL,
                total_ttm_profit REAL,
                member_count     INTEGER
            );

            CREATE TABLE IF NOT EXISTS vnfinlead_members (
                symbol        TEXT  NOT NULL,
                date_added    TEXT  NOT NULL,
                date_removed  TEXT,
                PRIMARY KEY (symbol, date_added)
            );

            CREATE TABLE IF NOT EXISTS pe_vnfinlead (
                date             TEXT  PRIMARY KEY,
                pe_ratio         REAL,
                total_market_cap REAL,
                total_ttm_profit REAL,
                member_count     INTEGER
            );

            CREATE TABLE IF NOT EXISTS pe_members (
                symbol    TEXT  NOT NULL,
                date      TEXT  NOT NULL,   -- ISO date: YYYY-MM-DD
                pe_ratio  REAL,             -- individual stock P/E, NULL if incalculable
                PRIMARY KEY (symbol, date)
            );

            CREATE TABLE IF NOT EXISTS cal_range_stats (
                index_symbol  TEXT     NOT NULL,
                date          TEXT     NOT NULL,   -- ISO date: YYYY-MM-DD
                range_days    INTEGER  NOT NULL,
                direction     TEXT     NOT NULL,   -- 'back' or 'fwd'
                local_top     REAL     NOT NULL,
                local_avg     REAL     NOT NULL,
                local_bottom  REAL     NOT NULL,
                p25           REAL     NOT NULL,
                median        REAL     NOT NULL,
                p75           REAL     NOT NULL,
                pe_top        REAL     NOT NULL,
                pe_avg        REAL     NOT NULL,
                pe_bottom     REAL     NOT NULL,
                pe_p25        REAL     NOT NULL,
                pe_median     REAL     NOT NULL,
                pe_p75        REAL     NOT NULL,
                PRIMARY KEY (index_symbol, date, range_days, direction)
            );
        """)


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def save_prices(symbol: str, df: pd.DataFrame, override: bool = False) -> dict:
    """
    Save daily prices for a symbol.
    df must have a DatetimeIndex and a 'close' column.

    override=False : skip rows that already exist  (default)
    override=True  : overwrite existing rows
    """
    rows = {
        str(date.date()): float(row["close"])
        for date, row in df.iterrows()
    }

    with _conn() as con:
        existing = {
            r[0] for r in con.execute(
                f"SELECT date FROM prices WHERE symbol = ? AND date IN ({','.join('?'*len(rows))})",
                (symbol, *rows.keys())
            ).fetchall()
        }

        to_save = rows if override else {d: v for d, v in rows.items() if d not in existing}
        skipped = len(rows) - len(to_save)

        if to_save:
            con.executemany(
                "INSERT OR REPLACE INTO prices (symbol, date, close) VALUES (?, ?, ?)",
                [(symbol, d, v) for d, v in to_save.items()],
            )

    print(f"  [prices]     {symbol}: saved {len(to_save)}, skipped {skipped}")
    return {"saved": len(to_save), "skipped": skipped}


def save_shares(symbol: str, df: pd.DataFrame, override: bool = False) -> dict:
    """
    Save quarterly outstanding shares for a symbol.
    df must have columns: year (int), quarter (int), shares (float).

    override=False : skip rows that already exist  (default)
    override=True  : overwrite existing rows
    """
    rows = {
        (int(row["year"]), int(row["quarter"])): float(row["shares"])
        for _, row in df.iterrows()
    }

    with _conn() as con:
        existing = set()
        for (y, q) in rows:
            r = con.execute(
                "SELECT 1 FROM shares WHERE symbol=? AND year=? AND quarter=?", (symbol, y, q)
            ).fetchone()
            if r:
                existing.add((y, q))

        to_save = rows if override else {k: v for k, v in rows.items() if k not in existing}
        skipped = len(rows) - len(to_save)

        if to_save:
            con.executemany(
                "INSERT OR REPLACE INTO shares (symbol, year, quarter, shares) VALUES (?, ?, ?, ?)",
                [(symbol, y, q, v) for (y, q), v in to_save.items()],
            )

    print(f"  [shares]     {symbol}: saved {len(to_save)}, skipped {skipped}")
    return {"saved": len(to_save), "skipped": skipped}


def save_net_profit(symbol: str, df: pd.DataFrame, override: bool = False) -> dict:
    """
    Save quarterly net profit for a symbol.
    df must have columns: year (int), quarter (int), kqkd_14, kqkd_13, kqkd_10 (float or None).

    override=False : skip rows that already exist  (default)
    override=True  : overwrite existing rows
    """
    def _f(v):
        return float(v) if v is not None and str(v) != "nan" else None

    rows = {
        (int(row["year"]), int(row["quarter"])): (
            _f(row.get("kqkd_14")), _f(row.get("kqkd_13")), _f(row.get("kqkd_10"))
        )
        for _, row in df.iterrows()
    }

    with _conn() as con:
        if override:
            existing = set()
        else:
            existing = {
                (r[0], r[1]) for r in con.execute(
                    f"SELECT year, quarter FROM net_profit WHERE symbol=?", (symbol,)
                ).fetchall()
            }

        to_save = {k: v for k, v in rows.items() if k not in existing}
        skipped = len(rows) - len(to_save)

        if to_save:
            con.executemany(
                "INSERT OR REPLACE INTO net_profit "
                "(symbol, year, quarter, kqkd_14, kqkd_13, kqkd_10) VALUES (?, ?, ?, ?, ?, ?)",
                [(symbol, y, q, v14, v13, v10) for (y, q), (v14, v13, v10) in to_save.items()],
            )

    print(f"  [net_profit] {symbol}: saved {len(to_save)}, skipped {skipped}")
    return {"saved": len(to_save), "skipped": skipped}


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def load_prices(symbol: str) -> pd.DataFrame:
    """Load all daily prices for a symbol. Returns DataFrame indexed by date."""
    with _conn() as con:
        df = pd.read_sql(
            "SELECT date, close FROM prices WHERE symbol = ? ORDER BY date",
            con, params=(symbol,)
        )
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")


def load_shares(symbol: str) -> pd.DataFrame:
    """Load all quarterly shares for a symbol. Returns DataFrame with year, quarter, shares."""
    with _conn() as con:
        df = pd.read_sql(
            "SELECT year, quarter, shares FROM shares WHERE symbol = ? ORDER BY year, quarter",
            con, params=(symbol,)
        )
    return df


def load_net_profit(symbol: str) -> pd.DataFrame:
    """Load all quarterly net profit for a symbol.
    Returns DataFrame with columns: year, quarter, kqkd_14, kqkd_13, kqkd_10."""
    with _conn() as con:
        df = pd.read_sql(
            "SELECT year, quarter, kqkd_14, kqkd_13, kqkd_10 "
            "FROM net_profit WHERE symbol = ? ORDER BY year, quarter",
            con, params=(symbol,)
        )
    return df


def save_vn30_members(rows: list[tuple[str, str, str | None]], override: bool = False) -> dict:
    """
    Save VN30 membership rows.
    Each row is (symbol, date_added, date_removed) — date_removed may be None.

    override=False : skip rows with existing (symbol, date_added)
    override=True  : overwrite existing rows
    """
    with _conn() as con:
        existing = {
            r[0] for r in con.execute("SELECT symbol || '|' || date_added FROM vn30_members").fetchall()
        }
        to_save = rows if override else [r for r in rows if f"{r[0]}|{r[1]}" not in existing]
        skipped = len(rows) - len(to_save)

        if to_save:
            con.executemany(
                "INSERT OR REPLACE INTO vn30_members (symbol, date_added, date_removed) VALUES (?, ?, ?)",
                to_save,
            )

    print(f"  [vn30_members] saved {len(to_save)}, skipped {skipped}")
    return {"saved": len(to_save), "skipped": skipped}


def load_vn30_members(as_of: str | None = None) -> pd.DataFrame:
    """
    Load VN30 membership records.
    If as_of (ISO date string) is given, return only symbols active on that date.
    Otherwise return the full membership history.
    """
    with _conn() as con:
        if as_of:
            df = pd.read_sql("""
                SELECT symbol, date_added, date_removed
                FROM vn30_members
                WHERE date_added <= ?
                  AND (date_removed IS NULL OR date_removed > ?)
                ORDER BY symbol
            """, con, params=(as_of, as_of))
        else:
            df = pd.read_sql(
                "SELECT symbol, date_added, date_removed FROM vn30_members ORDER BY date_added, symbol",
                con
            )
    return df


def save_vndiamond_members(rows: list[tuple[str, str, str | None]], override: bool = False) -> dict:
    with _conn() as con:
        existing = {
            r[0] for r in con.execute("SELECT symbol || '|' || date_added FROM vndiamond_members").fetchall()
        }
        to_save = rows if override else [r for r in rows if f"{r[0]}|{r[1]}" not in existing]
        skipped = len(rows) - len(to_save)

        if to_save:
            con.executemany(
                "INSERT OR REPLACE INTO vndiamond_members (symbol, date_added, date_removed) VALUES (?, ?, ?)",
                to_save,
            )

    print(f"  [vndiamond_members] saved {len(to_save)}, skipped {skipped}")
    return {"saved": len(to_save), "skipped": skipped}


def load_vndiamond_members(as_of: str | None = None) -> pd.DataFrame:
    with _conn() as con:
        if as_of:
            df = pd.read_sql("""
                SELECT symbol, date_added, date_removed
                FROM vndiamond_members
                WHERE date_added <= ?
                  AND (date_removed IS NULL OR date_removed > ?)
                ORDER BY symbol
            """, con, params=(as_of, as_of))
        else:
            df = pd.read_sql(
                "SELECT symbol, date_added, date_removed FROM vndiamond_members ORDER BY date_added, symbol",
                con
            )
    return df


def save_pe_vndiamond(df: pd.DataFrame, override: bool = False) -> dict:
    return _save_pe_table("pe_vndiamond", df, override)


def load_pe_vndiamond(start: str | None = None, end: str | None = None) -> pd.DataFrame:
    return _load_pe_table("pe_vndiamond", start, end)


def _save_pe_table(table: str, df: pd.DataFrame, override: bool) -> dict:
    with _conn() as con:
        existing = {r[0] for r in con.execute(f"SELECT date FROM {table}").fetchall()}
        rows = df.to_dict("records")
        to_save = rows if override else [r for r in rows if r["date"] not in existing]
        skipped = len(rows) - len(to_save)
        if to_save:
            con.executemany(
                f"""INSERT OR REPLACE INTO {table}
                   (date, pe_ratio, total_market_cap, total_ttm_profit, member_count)
                   VALUES (:date, :pe_ratio, :total_market_cap, :total_ttm_profit, :member_count)""",
                to_save,
            )
    print(f"  [{table}] saved {len(to_save)}, skipped {skipped}")
    return {"saved": len(to_save), "skipped": skipped}


def _load_pe_table(table: str, start: str | None, end: str | None) -> pd.DataFrame:
    where, params = [], []
    if start:
        where.append("date >= ?")
        params.append(start)
    if end:
        where.append("date <= ?")
        params.append(end)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    with _conn() as con:
        df = pd.read_sql(
            f"SELECT date, pe_ratio, total_market_cap, total_ttm_profit, member_count "
            f"FROM {table} {clause} ORDER BY date",
            con, params=params
        )
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
    return df


def save_pe_vn30(df: pd.DataFrame, override: bool = False) -> dict:
    return _save_pe_table("pe_vn30", df, override)


def load_pe_vn30(start: str | None = None, end: str | None = None) -> pd.DataFrame:
    return _load_pe_table("pe_vn30", start, end)


def save_vnfinlead_members(rows: list[tuple[str, str, str | None]], override: bool = False) -> dict:
    with _conn() as con:
        existing = {
            r[0] for r in con.execute("SELECT symbol || '|' || date_added FROM vnfinlead_members").fetchall()
        }
        to_save = rows if override else [r for r in rows if f"{r[0]}|{r[1]}" not in existing]
        skipped = len(rows) - len(to_save)
        if to_save:
            con.executemany(
                "INSERT OR REPLACE INTO vnfinlead_members (symbol, date_added, date_removed) VALUES (?, ?, ?)",
                to_save,
            )
    print(f"  [vnfinlead_members] saved {len(to_save)}, skipped {skipped}")
    return {"saved": len(to_save), "skipped": skipped}


def load_vnfinlead_members(as_of: str | None = None) -> pd.DataFrame:
    with _conn() as con:
        if as_of:
            df = pd.read_sql("""
                SELECT symbol, date_added, date_removed
                FROM vnfinlead_members
                WHERE date_added <= ?
                  AND (date_removed IS NULL OR date_removed > ?)
                ORDER BY symbol
            """, con, params=(as_of, as_of))
        else:
            df = pd.read_sql(
                "SELECT symbol, date_added, date_removed FROM vnfinlead_members ORDER BY date_added, symbol",
                con
            )
    return df


def save_pe_vnfinlead(df: pd.DataFrame, override: bool = False) -> dict:
    return _save_pe_table("pe_vnfinlead", df, override)


def load_pe_vnfinlead(start: str | None = None, end: str | None = None) -> pd.DataFrame:
    return _load_pe_table("pe_vnfinlead", start, end)


def save_pe_members(df: pd.DataFrame, override: bool = False) -> dict:
    """
    Save per-member daily P/E ratios.
    df must have columns: symbol, date (str), pe_ratio (float or None).
    """
    rows = [(r["symbol"], r["date"], r["pe_ratio"]) for _, r in df.iterrows()]
    with _conn() as con:
        existing = {
            f"{r[0]}|{r[1]}"
            for r in con.execute("SELECT symbol, date FROM pe_members").fetchall()
        }
        to_save = rows if override else [r for r in rows if f"{r[0]}|{r[1]}" not in existing]
        skipped = len(rows) - len(to_save)
        if to_save:
            con.executemany(
                "INSERT OR REPLACE INTO pe_members (symbol, date, pe_ratio) VALUES (?, ?, ?)",
                to_save,
            )
    print(f"  [pe_members] saved {len(to_save)}, skipped {skipped}")
    return {"saved": len(to_save), "skipped": skipped}


def load_pe_members(
    symbol: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """
    Load per-member P/E ratios. Optionally filter by symbol and/or date range.
    Returns DataFrame with columns: symbol, date, pe_ratio.
    """
    clauses, params = [], []
    if symbol:
        clauses.append("symbol = ?")
        params.append(symbol)
    if start:
        clauses.append("date >= ?")
        params.append(start)
    if end:
        clauses.append("date <= ?")
        params.append(end)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    with _conn() as con:
        df = pd.read_sql(
            f"SELECT symbol, date, pe_ratio FROM pe_members {where} ORDER BY symbol, date",
            con, params=params, parse_dates=["date"],
        )
    return df


def save_cal_range_close(
    index_symbol: str,
    df: pd.DataFrame,
    cal_range_close: dict,
    override: bool = True,
) -> dict:
    """
    Persist cal_range_close to DB.
    df must have a 'time' column (DatetimeIndex or column) so row positions map to dates.
    cal_range_close: dict[int, IndexCloses] as returned by build_cal_range_close.
    """
    from analyze.models import IndexCloses

    # Build date lookup: row_index -> ISO date string
    if hasattr(df.index, 'dtype') and pd.api.types.is_datetime64_any_dtype(df.index):
        dates = {i: str(df.index[i].date()) for i in range(len(df))}
    else:
        dates = {i: str(pd.Timestamp(df['time'].iloc[i]).date()) for i in range(len(df))}

    rows = []
    for row_idx, ic in cal_range_close.items():
        date_str = dates.get(row_idx)
        if date_str is None:
            continue
        for rd, rdc in ic.rangeDayCloses.items():
            rows.append((
                index_symbol, date_str, rd, 'back',
                rdc.localTop, rdc.localAvg, rdc.localBottom,
                rdc.p25, rdc.median, rdc.p75,
                rdc.pe_top, rdc.pe_avg, rdc.pe_bottom,
                rdc.pe_p25, rdc.pe_median, rdc.pe_p75,
            ))
        for rd, rdc in ic.rangeDayClosesPos.items():
            rows.append((
                index_symbol, date_str, rd, 'fwd',
                rdc.localTop, rdc.localAvg, rdc.localBottom,
                rdc.p25, rdc.median, rdc.p75,
                rdc.pe_top, rdc.pe_avg, rdc.pe_bottom,
                rdc.pe_p25, rdc.pe_median, rdc.pe_p75,
            ))

    with _conn() as con:
        if override:
            con.execute(
                "DELETE FROM cal_range_stats WHERE index_symbol = ?", (index_symbol,)
            )
        con.executemany(
            """INSERT OR REPLACE INTO cal_range_stats
               (index_symbol, date, range_days, direction,
                local_top, local_avg, local_bottom, p25, median, p75,
                pe_top, pe_avg, pe_bottom, pe_p25, pe_median, pe_p75)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
    print(f"  [cal_range_stats] {index_symbol}: saved {len(rows)} rows")
    return {"saved": len(rows)}


def load_cal_range_close(
    index_symbol: str,
    df: pd.DataFrame,
) -> "dict | None":
    """
    Load cal_range_close from DB for the given index and df row layout.
    Returns dict[int, IndexCloses] or None if no cached data exists.
    df must have a 'time' column so dates map back to row positions.
    """
    from analyze.models import RangeDaysClose, IndexCloses

    with _conn() as con:
        rows = con.execute(
            """SELECT date, range_days, direction,
                      local_top, local_avg, local_bottom, p25, median, p75,
                      pe_top, pe_avg, pe_bottom, pe_p25, pe_median, pe_p75
               FROM cal_range_stats WHERE index_symbol = ?""",
            (index_symbol,),
        ).fetchall()

    if not rows:
        return None

    # Map ISO date -> row index using df
    if hasattr(df.index, 'dtype') and pd.api.types.is_datetime64_any_dtype(df.index):
        date_to_idx = {str(df.index[i].date()): i for i in range(len(df))}
    else:
        date_to_idx = {str(pd.Timestamp(df['time'].iloc[i]).date()): i for i in range(len(df))}

    from collections import defaultdict
    cal: dict[int, IndexCloses] = defaultdict(IndexCloses)

    for (date, rd, direction,
         lt, la, lb, p25, med, p75,
         pe_top, pe_avg, pe_bot, pe_p25, pe_med, pe_p75) in rows:
        row_idx = date_to_idx.get(date)
        if row_idx is None:
            continue
        rdc = RangeDaysClose(
            localTop=lt, localAvg=la, localBottom=lb,
            p25=p25, median=med, p75=p75,
            pe_top=pe_top, pe_avg=pe_avg, pe_bottom=pe_bot,
            pe_p25=pe_p25, pe_median=pe_med, pe_p75=pe_p75,
        )
        if direction == 'back':
            cal[row_idx].rangeDayCloses[rd] = rdc
        else:
            cal[row_idx].rangeDayClosesPos[rd] = rdc

    return dict(cal)


def list_symbols() -> list[str]:
    """Return all symbols that have price data."""
    with _conn() as con:
        rows = con.execute("SELECT DISTINCT symbol FROM prices ORDER BY symbol").fetchall()
    return [r[0] for r in rows]


def save_index_prices(symbol: str, df: pd.DataFrame, override: bool = False) -> dict:
    """
    Save daily index prices (index points, not VND).
    df must have a DatetimeIndex and a 'close' column.
    """
    rows = {
        str(date.date()): float(row["close"])
        for date, row in df.iterrows()
    }

    with _conn() as con:
        existing = {
            r[0] for r in con.execute(
                f"SELECT date FROM index_prices WHERE symbol = ? AND date IN ({','.join('?'*len(rows))})",
                (symbol, *rows.keys())
            ).fetchall()
        } if rows else set()

        to_save = rows if override else {d: v for d, v in rows.items() if d not in existing}
        skipped = len(rows) - len(to_save)

        if to_save:
            con.executemany(
                "INSERT OR REPLACE INTO index_prices (symbol, date, close) VALUES (?, ?, ?)",
                [(symbol, d, v) for d, v in to_save.items()],
            )

    print(f"  [index_prices] {symbol}: saved {len(to_save)}, skipped {skipped}")
    return {"saved": len(to_save), "skipped": skipped}


def load_index_prices(symbol: str) -> pd.DataFrame:
    """Load all daily prices for an index. Returns DataFrame indexed by date with 'close' column."""
    with _conn() as con:
        df = pd.read_sql(
            "SELECT date, close FROM index_prices WHERE symbol = ? ORDER BY date",
            con, params=(symbol,)
        )
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")


def load_latest_index_price_date(symbol: str) -> str | None:
    """Return the most recent stored date for an index symbol, or None if no data."""
    with _conn() as con:
        row = con.execute(
            "SELECT MAX(date) FROM index_prices WHERE symbol = ?", (symbol,)
        ).fetchone()
    return row[0] if row else None


def load_latest_price_date(symbol: str) -> str | None:
    """Return the most recent stored price date for a symbol, or None if no data."""
    with _conn() as con:
        row = con.execute(
            "SELECT MAX(date) FROM prices WHERE symbol = ?", (symbol,)
        ).fetchone()
    return row[0] if row else None


def summary() -> pd.DataFrame:
    """Show a summary of stored data per symbol."""
    with _conn() as con:
        df = pd.read_sql("""
            SELECT
                p.symbol,
                p.price_days,
                p.price_from,
                p.price_to,
                COALESCE(s.share_quarters, 0)  AS share_quarters,
                COALESCE(n.profit_quarters, 0) AS profit_quarters
            FROM (
                SELECT symbol, COUNT(*) AS price_days, MIN(date) AS price_from, MAX(date) AS price_to
                FROM prices GROUP BY symbol
            ) p
            LEFT JOIN (
                SELECT symbol, COUNT(*) AS share_quarters FROM shares GROUP BY symbol
            ) s ON s.symbol = p.symbol
            LEFT JOIN (
                SELECT symbol, COUNT(*) AS profit_quarters FROM net_profit GROUP BY symbol
            ) n ON n.symbol = p.symbol
            ORDER BY p.symbol
        """, con)
    return df


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at: {DB_PATH}")

    existing = list_symbols()
    if existing:
        print(f"\nStored symbols: {existing}")
        print("\nSummary:")
        print(summary().to_string(index=False))
        print("\nShares (VNM):")
        print(load_shares("VNM").to_string(index=False))
        print("\nNet Profit (VNM):")
        print(load_net_profit("VNM").to_string(index=False))
    else:
        print("No data stored yet.")
