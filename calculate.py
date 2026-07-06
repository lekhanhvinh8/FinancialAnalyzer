"""
Aggregate P/E calculation for VN30.

Formula:
    P/E(date) = Σ(price_i × shares_i) / Σ(TTM_profit_i)

    summed over all VN30 members active on that date that have
    both price and at least 4 quarters of net profit available.

TTM (Trailing Twelve Months) for a stock on date D:
    sum of the 4 most recent quarterly profits whose quarter-end ≤ D.

Shares on date D:
    most recent quarterly shares whose quarter-end ≤ D.

Note: the free vnstock tier provides only the latest 4 quarters of
fundamentals. Historical P/E coverage depends on how far back the
oldest available quarter falls.
"""

import pandas as pd
import database as db


def _quarter_end(year: int, quarter: int) -> pd.Timestamp:
    month = quarter * 3
    return pd.Timestamp(year=year, month=month, day=1) + pd.offsets.MonthEnd(0)


def _build_fundamental_daily(symbol: str, dates: pd.DatetimeIndex) -> pd.DataFrame | None:
    """
    Return a DataFrame indexed by `dates` with columns [shares, ttm_profit]
    using point-in-time correct values (no look-ahead).

    Returns None if the symbol has fewer than 4 profit quarters.
    """
    shares_df = db.load_shares(symbol)
    profit_df = db.load_net_profit(symbol)

    if len(profit_df) < 4 or shares_df.empty:
        return None

    # ── Shares: one value per quarter-end, then ffill ────────────────────────
    shares_ts = pd.Series(
        shares_df["shares"].values,
        index=[_quarter_end(int(r.year), int(r.quarter)) for _, r in shares_df.iterrows()],
        name="shares",
    ).sort_index()

    # ── TTM profit: rolling 4-quarter sum, one value per quarter-end ─────────
    profit_df = profit_df.sort_values(["year", "quarter"]).reset_index(drop=True)
    profit_df["quarter_end"] = profit_df.apply(
        lambda r: _quarter_end(int(r.year), int(r.quarter)), axis=1
    )
    profit_df["ttm"] = profit_df["net_profit"].rolling(4).sum()
    profit_ts = (
        profit_df.dropna(subset=["ttm"])
        .set_index("quarter_end")["ttm"]
    )

    # ── Reindex to daily, forward-fill only (no look-ahead) ──────────────────
    full_index = dates.union(shares_ts.index).union(profit_ts.index)
    daily_shares = shares_ts.reindex(full_index).ffill().reindex(dates)
    daily_ttm    = profit_ts.reindex(full_index).ffill().reindex(dates)

    result = pd.DataFrame({"shares": daily_shares, "ttm_profit": daily_ttm})
    return result.dropna()  # dates where either is still unknown → excluded


def calc_pe_history(start: str | None = None, end: str | None = None) -> pd.DataFrame:
    """
    Calculate daily aggregate P/E for VN30 over [start, end].

    Defaults to the full date range covered by price data.

    Returns a DataFrame with columns:
        date (str), pe_ratio, total_market_cap, total_ttm_profit, member_count
    """
    # ── Gather all price data ────────────────────────────────────────────────
    symbols = db.list_symbols()
    prices: dict[str, pd.Series] = {}
    for sym in symbols:
        p = db.load_prices(sym)["close"]
        if start:
            p = p[p.index >= start]
        if end:
            p = p[p.index <= end]
        if not p.empty:
            prices[sym] = p

    if not prices:
        return pd.DataFrame()

    all_dates = sorted(set().union(*[p.index for p in prices.values()]))
    all_dates = pd.DatetimeIndex(all_dates)

    # ── Build daily fundamentals per symbol ──────────────────────────────────
    fundamentals: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        fd = _build_fundamental_daily(sym, all_dates)
        if fd is not None:
            fundamentals[sym] = fd

    # ── Calculate aggregate P/E per date ─────────────────────────────────────
    records = []
    for date in all_dates:
        date_str = date.date().isoformat()

        # Active VN30 members on this date
        members = set(db.load_vn30_members(as_of=date_str)["symbol"].tolist())

        total_mcap   = 0.0
        total_profit = 0.0
        count        = 0

        for sym in members:
            if sym not in prices:
                continue
            price_series = prices[sym]
            if date not in price_series.index:
                continue
            if sym not in fundamentals:
                continue
            fd = fundamentals[sym]
            if date not in fd.index:
                continue

            price  = price_series[date]
            shares = fd.loc[date, "shares"]
            ttm    = fd.loc[date, "ttm_profit"]

            if ttm <= 0:  # skip loss-making or zero-profit stocks from denominator
                continue

            total_mcap   += price * shares
            total_profit += ttm
            count        += 1

        if count == 0 or total_profit == 0:
            pe = None
        else:
            pe = total_mcap / total_profit

        records.append({
            "date":             date_str,
            "pe_ratio":         pe,
            "total_market_cap": total_mcap if count > 0 else None,
            "total_ttm_profit": total_profit if count > 0 else None,
            "member_count":     count,
        })

    return pd.DataFrame(records)


if __name__ == "__main__":
    db.init_db()

    print("Calculating aggregate P/E history …")
    pe_df = calc_pe_history()

    valid = pe_df.dropna(subset=["pe_ratio"])
    print(f"\nCalculated {len(pe_df)} dates, {len(valid)} with valid P/E\n")

    if not valid.empty:
        print(valid.tail(10).to_string(index=False))

        db.save_pe_history(pe_df)

        print("\nRecent P/E from database:")
        stored = db.load_pe_history()
        print(stored.dropna().tail(10).to_string())
