"""
SQLite storage for Vietnam stock data.

Schema (7 tables):
    symbols                — symbol registry: 'stock' or 'index'
    daily_prices           — collected: daily close for stocks and indices
    quarterly_fundamentals — collected: quarterly shares + net profit per symbol
    index_members          — collected: historical index composition
    pe_ratios              — calculated: daily P/E (stock-level or index aggregate)
    range_stats            — aggregate calculated: rolling window statistics
    trend_signals          — calculated: rolling trend classification signals
"""

import sqlite3
from pathlib import Path
from contextlib import contextmanager
from collections import defaultdict

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
            CREATE TABLE IF NOT EXISTS symbols (
                symbol       TEXT  PRIMARY KEY,
                symbol_type  TEXT  NOT NULL        -- 'stock' or 'index'
            );

            CREATE TABLE IF NOT EXISTS daily_prices (
                symbol  TEXT  NOT NULL,
                date    TEXT  NOT NULL,            -- ISO date: YYYY-MM-DD
                close   REAL  NOT NULL,
                PRIMARY KEY (symbol, date)
            );

            CREATE TABLE IF NOT EXISTS quarterly_fundamentals (
                symbol   TEXT     NOT NULL,
                year     INTEGER  NOT NULL,
                quarter  INTEGER  NOT NULL,        -- 1-4
                shares   REAL,
                kqkd_14  REAL,
                kqkd_13  REAL,
                kqkd_10  REAL,
                PRIMARY KEY (symbol, year, quarter)
            );

            CREATE TABLE IF NOT EXISTS index_members (
                index_symbol   TEXT  NOT NULL,
                member_symbol  TEXT  NOT NULL,
                date_added     TEXT  NOT NULL,     -- ISO date
                date_removed   TEXT,               -- NULL = still active
                PRIMARY KEY (index_symbol, member_symbol, date_added)
            );

            CREATE TABLE IF NOT EXISTS pe_ratios (
                symbol            TEXT  NOT NULL,
                date              TEXT  NOT NULL,  -- ISO date
                pe_ratio          REAL,
                total_market_cap  REAL,            -- NULL for stock-level rows
                total_ttm_profit  REAL,            -- NULL for stock-level rows
                member_count      INTEGER,          -- NULL for stock-level rows
                PRIMARY KEY (symbol, date)
            );

            CREATE TABLE IF NOT EXISTS range_stats (
                symbol       TEXT     NOT NULL,
                date         TEXT     NOT NULL,
                range_days   INTEGER  NOT NULL,
                direction    TEXT     NOT NULL,    -- 'back' or 'fwd'
                local_top    REAL     NOT NULL,
                local_avg    REAL     NOT NULL,
                local_bottom REAL     NOT NULL,
                p25          REAL     NOT NULL,
                median       REAL     NOT NULL,
                p75          REAL     NOT NULL,
                pe_top       REAL,
                pe_avg       REAL,
                pe_bottom    REAL,
                pe_p25       REAL,
                pe_median    REAL,
                pe_p75       REAL,
                PRIMARY KEY (symbol, date, range_days, direction)
            );

            CREATE TABLE IF NOT EXISTS trend_signals (
                symbol          TEXT     NOT NULL,
                date            TEXT     NOT NULL,  -- ISO date: YYYY-MM-DD
                window_days     INTEGER  NOT NULL,  -- lookback window in trading days
                signal1_slope   REAL,               -- normalized lin-reg slope (%/day)
                signal2_return  REAL,               -- BuyInterval return % over window
                signal3_sharpe  REAL,               -- annualized return / vol (Sharpe-like)
                PRIMARY KEY (symbol, date, window_days)
            );

            -- ln(price / rolling median). Depends only on median_window, so it is
            -- stored once rather than duplicated across every stat-window config.
            CREATE TABLE IF NOT EXISTS valuation_dev (
                symbol          TEXT     NOT NULL,
                date            TEXT     NOT NULL,  -- ISO date: YYYY-MM-DD
                median_window   INTEGER  NOT NULL,  -- window for the price base M
                dev             REAL,               -- ln(price / M)
                PRIMARY KEY (symbol, date, median_window)
            );

            -- Relative valuation: how far price sits from its own long-term base,
            -- normalized by that symbol's own history. See analyze/zdev_calc.py.
            -- Windows are in the key so configurations coexist; join to
            -- valuation_dev on (symbol, date, median_window) for dev itself.
            CREATE TABLE IF NOT EXISTS valuation_zdev (
                symbol          TEXT     NOT NULL,
                date            TEXT     NOT NULL,  -- ISO date: YYYY-MM-DD
                median_window   INTEGER  NOT NULL,  -- window for the price base M
                stat_window     INTEGER  NOT NULL,  -- window for mu/sigma of dev
                min_periods     INTEGER  NOT NULL,  -- observations required for mu/sigma
                mu              REAL,               -- rolling mean of dev, shifted 1 bar
                sigma           REAL,               -- rolling std of dev, shifted 1 bar
                z_dev           REAL,               -- (dev - mu) / sigma
                PRIMARY KEY (symbol, date, median_window, stat_window, min_periods)
            );
        """)


# ── Daily prices ──────────────────────────────────────────────────────────────

def save_daily_prices(
    symbol: str,
    df: pd.DataFrame,
    symbol_type: str = 'stock',
) -> dict:
    """
    Save daily close prices for a stock or index symbol.
    df must have a DatetimeIndex and a 'close' column.
    Always INSERT OR REPLACE — caller decides what rows to pass.
    """
    rows = {str(d.date()): float(r["close"]) for d, r in df.iterrows()}
    if not rows:
        return {"saved": 0}
    with _conn() as con:
        con.execute(
            "INSERT OR IGNORE INTO symbols (symbol, symbol_type) VALUES (?, ?)",
            (symbol, symbol_type),
        )
        con.executemany(
            "INSERT OR REPLACE INTO daily_prices (symbol, date, close) VALUES (?, ?, ?)",
            [(symbol, d, v) for d, v in rows.items()],
        )
    label = "[index_prices]" if symbol_type == "index" else "[prices]    "
    print(f"  {label} {symbol}: saved {len(rows)}")
    return {"saved": len(rows)}


def load_daily_prices(symbol: str) -> pd.DataFrame:
    """Return DataFrame indexed by date with 'close' column."""
    with _conn() as con:
        df = pd.read_sql(
            "SELECT date, close FROM daily_prices WHERE symbol = ? ORDER BY date",
            con, params=(symbol,),
        )
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")


def load_latest_price_date(symbol: str) -> str | None:
    """Return most recent stored date for any symbol, or None."""
    with _conn() as con:
        row = con.execute(
            "SELECT MAX(date) FROM daily_prices WHERE symbol = ?", (symbol,)
        ).fetchone()
    return row[0] if row else None


# ── Quarterly fundamentals ────────────────────────────────────────────────────

def save_shares(symbol: str, df: pd.DataFrame) -> dict:
    """
    Save quarterly outstanding shares.
    df must have columns: year (int), quarter (int), shares (float).
    Always writes — caller decides what rows to pass.
    Only the 'shares' column is written; profit columns in the same row are preserved.
    """
    rows = [(int(r.year), int(r.quarter), float(r.shares)) for _, r in df.iterrows()]
    if not rows:
        return {"saved": 0}
    with _conn() as con:
        con.executemany(
            "INSERT OR IGNORE INTO quarterly_fundamentals (symbol, year, quarter) VALUES (?, ?, ?)",
            [(symbol, y, q) for y, q, _ in rows],
        )
        con.executemany(
            "UPDATE quarterly_fundamentals SET shares = ? WHERE symbol = ? AND year = ? AND quarter = ?",
            [(s, symbol, y, q) for y, q, s in rows],
        )
    print(f"  [shares]     {symbol}: saved {len(rows)}")
    return {"saved": len(rows)}


def load_shares(symbol: str) -> pd.DataFrame:
    """Return DataFrame with columns (year, quarter, shares)."""
    with _conn() as con:
        return pd.read_sql(
            "SELECT year, quarter, shares FROM quarterly_fundamentals WHERE symbol = ? AND shares IS NOT NULL ORDER BY year, quarter",
            con, params=(symbol,),
        )


def save_net_profit(symbol: str, df: pd.DataFrame) -> dict:
    """
    Save quarterly net profit figures.
    df must have columns: year, quarter, kqkd_14, kqkd_13, kqkd_10.
    Always writes — caller decides what rows/values to pass.
    Only the kqkd columns are written; shares in the same row are preserved.
    """
    rows = [
        (int(r.year), int(r.quarter),
         r.get("kqkd_14") if pd.notna(r.get("kqkd_14")) else None,
         r.get("kqkd_13") if pd.notna(r.get("kqkd_13")) else None,
         r.get("kqkd_10") if pd.notna(r.get("kqkd_10")) else None)
        for _, r in df.iterrows()
    ]
    if not rows:
        return {"saved": 0}
    with _conn() as con:
        con.executemany(
            "INSERT OR IGNORE INTO quarterly_fundamentals (symbol, year, quarter) VALUES (?, ?, ?)",
            [(symbol, y, q) for y, q, *_ in rows],
        )
        con.executemany(
            """UPDATE quarterly_fundamentals SET kqkd_14 = ?, kqkd_13 = ?, kqkd_10 = ?
               WHERE symbol = ? AND year = ? AND quarter = ?""",
            [(k14, k13, k10, symbol, y, q) for y, q, k14, k13, k10 in rows],
        )
    print(f"  [net_profit] {symbol}: saved {len(rows)}")
    return {"saved": len(rows)}


def load_net_profit(symbol: str) -> pd.DataFrame:
    """Return DataFrame with columns (year, quarter, kqkd_14, kqkd_13, kqkd_10)."""
    with _conn() as con:
        return pd.read_sql(
            """SELECT year, quarter, kqkd_14, kqkd_13, kqkd_10
               FROM quarterly_fundamentals WHERE symbol = ?
               ORDER BY year, quarter""",
            con, params=(symbol,),
        )


# ── Index members ─────────────────────────────────────────────────────────────

def save_index_members(
    index_symbol: str,
    rows: list[tuple[str, str, str | None]],
    override: bool = False,
) -> dict:
    """
    Save historical index membership.
    rows: list of (member_symbol, date_added, date_removed)
    """
    with _conn() as con:
        existing = {
            f"{r[0]}|{r[1]}"
            for r in con.execute(
                "SELECT member_symbol, date_added FROM index_members WHERE index_symbol = ?",
                (index_symbol,),
            ).fetchall()
        }
        to_save = rows if override else [r for r in rows if f"{r[0]}|{r[1]}" not in existing]
        skipped = len(rows) - len(to_save)
        if to_save:
            con.executemany(
                """INSERT OR REPLACE INTO index_members
                   (index_symbol, member_symbol, date_added, date_removed) VALUES (?, ?, ?, ?)""",
                [(index_symbol, sym, da, dr) for sym, da, dr in to_save],
            )
    print(f"  [{index_symbol}_members] saved {len(to_save)}, skipped {skipped}")
    return {"saved": len(to_save), "skipped": skipped}


def load_index_members(index_symbol: str, as_of: str | None = None) -> pd.DataFrame:
    """
    Load index members. Returns DataFrame with columns (symbol, date_added, date_removed).
    If as_of is given, returns only members active on that date.
    """
    with _conn() as con:
        if as_of:
            df = pd.read_sql(
                """SELECT member_symbol AS symbol, date_added, date_removed
                   FROM index_members
                   WHERE index_symbol = ?
                     AND date_added <= ?
                     AND (date_removed IS NULL OR date_removed > ?)
                   ORDER BY member_symbol""",
                con, params=(index_symbol, as_of, as_of),
            )
        else:
            df = pd.read_sql(
                """SELECT member_symbol AS symbol, date_added, date_removed
                   FROM index_members WHERE index_symbol = ?
                   ORDER BY date_added, member_symbol""",
                con, params=(index_symbol,),
            )
    return df


# ── P/E ratios ────────────────────────────────────────────────────────────────

def save_pe_ratios(symbol: str, df: pd.DataFrame) -> dict:
    """
    Save P/E ratios for a symbol (stock or index).
    df must have 'date' column. Optional: pe_ratio, total_market_cap, total_ttm_profit, member_count.
    For index aggregate P/E, include the optional columns.
    Always replaces all rows for the symbol — caller passes the full dataset.
    """
    has_agg = "total_market_cap" in df.columns

    rows = []
    for _, r in df.iterrows():
        rows.append((
            symbol,
            str(r["date"]) if not isinstance(r["date"], str) else r["date"],
            r.get("pe_ratio") if pd.notna(r.get("pe_ratio", None)) else None,
            float(r["total_market_cap"]) if has_agg and pd.notna(r.get("total_market_cap")) else None,
            float(r["total_ttm_profit"]) if has_agg and pd.notna(r.get("total_ttm_profit")) else None,
            int(r["member_count"]) if has_agg and pd.notna(r.get("member_count")) else None,
        ))

    with _conn() as con:
        if rows:
            con.executemany(
                """INSERT OR REPLACE INTO pe_ratios
                   (symbol, date, pe_ratio, total_market_cap, total_ttm_profit, member_count)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                rows,
            )
    print(f"  [pe_{symbol}] saved {len(rows)}")
    return {"saved": len(rows)}


def save_pe_ratios_bulk(records: list[dict]) -> dict:
    """
    Bulk save per-symbol P/E ratios. Always INSERT OR REPLACE.
    records: list of dicts with keys: symbol, date, pe_ratio,
             optionally total_market_cap, total_ttm_profit
    """
    rows = [
        (
            r["symbol"], r["date"], r.get("pe_ratio"),
            r.get("total_market_cap"), r.get("total_ttm_profit"),
        )
        for r in records
    ]
    with _conn() as con:
        con.executemany(
            """INSERT OR REPLACE INTO pe_ratios
               (symbol, date, pe_ratio, total_market_cap, total_ttm_profit)
               VALUES (?, ?, ?, ?, ?)""",
            rows,
        )
    print(f"  [pe_members] saved {len(rows)}")
    return {"saved": len(rows)}


def load_pe_ratios(
    symbol: str,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """
    Load P/E ratios for a symbol.
    Returns DataFrame indexed by date with columns:
        pe_ratio, total_market_cap, total_ttm_profit, member_count

    Index symbols are stored in pe_ratios as lowercase; this function
    resolves the correct key automatically from the symbols table.
    """
    with _conn() as con:
        row = con.execute(
            "SELECT symbol_type FROM symbols WHERE symbol = ?", (symbol,)
        ).fetchone()
    pe_key = symbol.lower() if (row and row[0] == "index") else symbol

    clauses = ["symbol = ?"]
    params: list = [pe_key]
    if start:
        clauses.append("date >= ?")
        params.append(start)
    if end:
        clauses.append("date <= ?")
        params.append(end)
    where = " AND ".join(clauses)
    with _conn() as con:
        df = pd.read_sql(
            f"SELECT date, pe_ratio, total_market_cap, total_ttm_profit, member_count "
            f"FROM pe_ratios WHERE {where} ORDER BY date",
            con, params=params,
        )
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
    return df


# ── Range stats (aggregate calculated) ───────────────────────────────────────

def save_range_stats(
    symbol: str,
    df: pd.DataFrame,
    cal_range_close: dict,
    override: bool = False,
    quiet: bool = False,
) -> dict:
    """
    Persist cal_range_close to range_stats table.
    df must have a 'time' column (or DatetimeIndex) so row positions map to dates.
    """
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
                symbol, date_str, rd, 'back',
                rdc.localTop, rdc.localAvg, rdc.localBottom,
                rdc.p25, rdc.median, rdc.p75,
                rdc.pe_top, rdc.pe_avg, rdc.pe_bottom,
                rdc.pe_p25, rdc.pe_median, rdc.pe_p75,
            ))

    verb = "INSERT OR REPLACE" if override else "INSERT OR IGNORE"
    with _conn() as con:
        con.executemany(
            f"""{verb} INTO range_stats
               (symbol, date, range_days, direction,
                local_top, local_avg, local_bottom, p25, median, p75,
                pe_top, pe_avg, pe_bottom, pe_p25, pe_median, pe_p75)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
        saved = con.total_changes
    if not quiet:
        if saved == 0:
            print(f"  [range_stats] {symbol}: up to date")
        else:
            print(f"  [range_stats] {symbol}: saved {saved} rows")
    return {"saved": saved}


def load_latest_range_stats_date(symbol: str) -> str | None:
    """Return the latest date in range_stats for symbol, or None."""
    with _conn() as con:
        row = con.execute(
            "SELECT MAX(date) FROM range_stats WHERE symbol = ?", (symbol,)
        ).fetchone()
    return row[0] if row and row[0] else None


def delete_range_stats(symbol: str) -> None:
    """Delete all range_stats rows for a symbol. Called by sync layer when override=True."""
    with _conn() as con:
        con.execute("DELETE FROM range_stats WHERE symbol = ?", (symbol,))


def load_range_stats(symbol: str, df: pd.DataFrame,
                     range_days: "int | None" = None) -> "dict | None":
    """
    Load cal_range_close from range_stats table.
    Returns dict[int, IndexCloses] or None if no cached data.
    df must have a 'time' column so dates map back to row positions.

    range_days restricts the load to a single window. The table holds ~1500
    windows per symbol and this is the slowest step in every pipeline that calls
    it, so a caller whose strategies only read one window should say so — the
    Median1000 family reads rangeDayCloses[1000] and nothing else. Left as None
    the behaviour is unchanged: every window is loaded, which is what callers
    using windowed strategies (localRangeDays, action.rangeDays) need.
    """
    from analyze.models import RangeDaysClose, IndexCloses

    sql = """SELECT date, range_days, direction,
                    local_top, local_avg, local_bottom, p25, median, p75,
                    pe_top, pe_avg, pe_bottom, pe_p25, pe_median, pe_p75
             FROM range_stats WHERE symbol = ?"""
    params: tuple = (symbol,)
    if range_days is not None:
        sql += " AND range_days = ?"
        params += (range_days,)

    with _conn() as con:
        rows = con.execute(sql, params).fetchall()

    if not rows:
        return None

    if hasattr(df.index, 'dtype') and pd.api.types.is_datetime64_any_dtype(df.index):
        date_to_idx = {str(df.index[i].date()): i for i in range(len(df))}
    else:
        date_to_idx = {str(pd.Timestamp(df['time'].iloc[i]).date()): i for i in range(len(df))}

    cal: dict = defaultdict(IndexCloses)
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


    return dict(cal)


# ── Trend signals ────────────────────────────────────────────────────────────

def save_trend_signals(
    symbol: str,
    rows: list[tuple],
    override: bool = False,
) -> dict:
    """
    Persist trend signals.
    rows: list of (symbol, date, window_days, signal1_slope, signal2_return, signal3_sharpe)
    """
    if not rows:
        return {"saved": 0}
    verb = "INSERT OR REPLACE" if override else "INSERT OR IGNORE"
    with _conn() as con:
        con.executemany(
            f"""{verb} INTO trend_signals
               (symbol, date, window_days, signal1_slope, signal2_return, signal3_sharpe)
               VALUES (?, ?, ?, ?, ?, ?)""",
            rows,
        )
        saved = con.total_changes
    return {"saved": saved}


def load_trend_signals(
    symbol: str,
    window_days: int,
) -> pd.DataFrame:
    """
    Load all stored trend signals for a symbol/window combination.
    Returns DataFrame indexed by date with columns: signal1_slope, signal2_return, signal3_sharpe.
    """
    with _conn() as con:
        df = pd.read_sql(
            """SELECT date, signal1_slope, signal2_return, signal3_sharpe
               FROM trend_signals WHERE symbol = ? AND window_days = ?
               ORDER BY date""",
            con, params=(symbol, window_days),
        )
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
    return df


def load_latest_trend_signals_date(symbol: str, window_days: int) -> str | None:
    """Return the most recent date in trend_signals for (symbol, window_days), or None."""
    with _conn() as con:
        row = con.execute(
            "SELECT MAX(date) FROM trend_signals WHERE symbol = ? AND window_days = ?",
            (symbol, window_days),
        ).fetchone()
    return row[0] if row and row[0] else None


def delete_trend_signals(symbol: str, window_days: int | None = None) -> None:
    """Delete trend_signals rows for a symbol, optionally filtered by window_days."""
    with _conn() as con:
        if window_days is not None:
            con.execute(
                "DELETE FROM trend_signals WHERE symbol = ? AND window_days = ?",
                (symbol, window_days),
            )
        else:
            con.execute("DELETE FROM trend_signals WHERE symbol = ?", (symbol,))


# ── Valuation z_dev ───────────────────────────────────────────────────────────

def save_dev(symbol: str, rows: list[tuple], override: bool = True) -> dict:
    """rows: (symbol, date, median_window, dev)"""
    if not rows:
        return {"saved": 0}
    verb = "INSERT OR REPLACE" if override else "INSERT OR IGNORE"
    with _conn() as con:
        con.executemany(
            f"""{verb} INTO valuation_dev (symbol, date, median_window, dev)
               VALUES (?, ?, ?, ?)""",
            rows,
        )
        saved = con.total_changes
    return {"saved": saved}


def load_dev(symbol: str, median_window: int = 1000) -> pd.DataFrame:
    """DataFrame indexed by date with a 'dev' column."""
    with _conn() as con:
        df = pd.read_sql(
            """SELECT date, dev FROM valuation_dev
               WHERE symbol = ? AND median_window = ? ORDER BY date""",
            con, params=(symbol, median_window),
        )
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
    return df


def save_zdev(symbol: str, rows: list[tuple], override: bool = True) -> dict:
    """
    Persist z_dev rows.
    rows: (symbol, date, median_window, stat_window, min_periods, mu, sigma, z_dev)

    override defaults to True, unlike the other sync tables: this is a derived
    metric that is always recomputed in full, so a revised price must be able to
    overwrite the value it produced.
    """
    if not rows:
        return {"saved": 0}
    verb = "INSERT OR REPLACE" if override else "INSERT OR IGNORE"
    with _conn() as con:
        con.executemany(
            f"""{verb} INTO valuation_zdev
               (symbol, date, median_window, stat_window, min_periods,
                mu, sigma, z_dev)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        saved = con.total_changes
    return {"saved": saved}


def load_zdev(
    symbol: str,
    median_window: int = 1000,
    stat_window:   int = 1000,
    min_periods:   int | None = None,   # None → stat_window, as the sweep writes it
) -> pd.DataFrame:
    """
    Load stored z_dev for one symbol/configuration, joined to dev.
    Returns DataFrame indexed by date with columns: dev, mu, sigma, z_dev.

    min_periods defaults to stat_window because that is the only relationship the
    sweep produces. Passing a mismatched pair returns an empty frame rather than
    an error — the row simply does not exist.
    """
    if min_periods is None:
        min_periods = stat_window
    with _conn() as con:
        df = pd.read_sql(
            """SELECT z.date, d.dev, z.mu, z.sigma, z.z_dev
               FROM valuation_zdev z
               LEFT JOIN valuation_dev d
                 ON d.symbol = z.symbol AND d.date = z.date
                AND d.median_window = z.median_window
               WHERE z.symbol = ? AND z.median_window = ? AND z.stat_window = ?
                 AND z.min_periods = ?
               ORDER BY z.date""",
            con, params=(symbol, median_window, stat_window, min_periods),
        )
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
    return df


def load_latest_zdev_date(
    symbol: str,
    median_window: int = 1000,
    stat_window:   int = 1000,
    min_periods:   int | None = None,   # None → stat_window, as the sweep writes it
) -> str | None:
    """Most recent date in valuation_zdev for this symbol/configuration, or None."""
    if min_periods is None:
        min_periods = stat_window
    with _conn() as con:
        row = con.execute(
            """SELECT MAX(date) FROM valuation_zdev
               WHERE symbol = ? AND median_window = ? AND stat_window = ?
                 AND min_periods = ?""",
            (symbol, median_window, stat_window, min_periods),
        ).fetchone()
    return row[0] if row and row[0] else None


def delete_zdev(symbol: str, median_window: int | None = None) -> None:
    """Delete z_dev rows for a symbol, optionally filtered by median_window."""
    with _conn() as con:
        if median_window is not None:
            con.execute(
                "DELETE FROM valuation_zdev WHERE symbol = ? AND median_window = ?",
                (symbol, median_window),
            )
        else:
            con.execute("DELETE FROM valuation_zdev WHERE symbol = ?", (symbol,))


# ── Orchestrator helpers ──────────────────────────────────────────────────────

def load_latest_shares_quarter(symbol: str) -> tuple[int, int] | None:
    """Return (year, quarter) of the most recent non-null shares entry, or None."""
    with _conn() as con:
        row = con.execute(
            """SELECT year, quarter FROM quarterly_fundamentals
               WHERE symbol = ? AND shares IS NOT NULL
               ORDER BY year DESC, quarter DESC LIMIT 1""",
            (symbol,),
        ).fetchone()
    return (row[0], row[1]) if row else None


def load_latest_profit_quarter(symbol: str) -> tuple[int, int] | None:
    """Return (year, quarter) of the most recent profit entry, or None."""
    with _conn() as con:
        row = con.execute(
            """SELECT year, quarter FROM quarterly_fundamentals
               WHERE symbol = ? AND (kqkd_14 IS NOT NULL OR kqkd_13 IS NOT NULL OR kqkd_10 IS NOT NULL)
               ORDER BY year DESC, quarter DESC LIMIT 1""",
            (symbol,),
        ).fetchone()
    return (row[0], row[1]) if row else None


def load_latest_pe_date(symbol: str) -> str | None:
    """Return the most recent date in pe_ratios for a symbol, or None."""
    with _conn() as con:
        row = con.execute(
            "SELECT MAX(date) FROM pe_ratios WHERE symbol = ?", (symbol,)
        ).fetchone()
    return row[0] if row and row[0] else None


# ── Utility ───────────────────────────────────────────────────────────────────

def list_symbols(symbol_type: str | None = None) -> list[str]:
    """Return symbols from the registry. Filter by 'stock' or 'index' if given."""
    with _conn() as con:
        if symbol_type:
            rows = con.execute(
                "SELECT symbol FROM symbols WHERE symbol_type = ? ORDER BY symbol",
                (symbol_type,),
            ).fetchall()
        else:
            rows = con.execute("SELECT symbol FROM symbols ORDER BY symbol").fetchall()
    return [r[0] for r in rows]


def summary() -> pd.DataFrame:
    """Show a summary of stored data per stock symbol."""
    with _conn() as con:
        df = pd.read_sql("""
            SELECT
                p.symbol,
                p.price_days,
                p.price_from,
                p.price_to,
                COALESCE(f.share_quarters, 0)  AS share_quarters,
                COALESCE(f.profit_quarters, 0) AS profit_quarters
            FROM (
                SELECT symbol, COUNT(*) AS price_days, MIN(date) AS price_from, MAX(date) AS price_to
                FROM daily_prices WHERE symbol IN (SELECT symbol FROM symbols WHERE symbol_type = 'stock')
                GROUP BY symbol
            ) p
            LEFT JOIN (
                SELECT symbol,
                       COUNT(CASE WHEN shares IS NOT NULL THEN 1 END) AS share_quarters,
                       COUNT(CASE WHEN kqkd_14 IS NOT NULL OR kqkd_13 IS NOT NULL OR kqkd_10 IS NOT NULL THEN 1 END) AS profit_quarters
                FROM quarterly_fundamentals GROUP BY symbol
            ) f ON f.symbol = p.symbol
            ORDER BY p.symbol
        """, con)
    return df


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at: {DB_PATH}")
    existing = list_symbols(symbol_type='stock')
    if existing:
        print(f"\nStored symbols: {existing}")
        print("\nSummary:")
        print(summary().to_string(index=False))
    else:
        print("No stock data stored yet.")
