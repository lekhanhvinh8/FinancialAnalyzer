"""
Aggregate P/E calculation for VN30 and VN Diamond.

Formula:
    P/E(date) = Σ(price_i × shares_i) / Σ(TTM_profit_i)

    summed over all active index members on that date that have
    both price and at least 4 quarters of net profit available.

TTM (Trailing Twelve Months) for a stock on date D:
    sum of the 4 most recent quarterly profits whose quarter-end ≤ D.

Shares on date D:
    most recent quarterly shares whose quarter-end ≤ D.
    Backfilled from oldest known value for dates before first quarter.

Note: the free vnstock tier provides only the latest 4 quarters of
balance-sheet data. Shares are bfill-approximated for earlier dates.
"""

import sys
from pathlib import Path

# Was a root-level script; from inside syncs/ the project root is no longer
# on sys.path when this is run directly, and `import database` needs it.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import database as db

import functools

_MEMBER_LOADERS = {
    "vn30":      functools.partial(db.load_index_members, "vn30"),
    "vndiamond": functools.partial(db.load_index_members, "vndiamond"),
    "vnfinlead": functools.partial(db.load_index_members, "vnfinlead"),
}

# The dict KEY is the internal index id, lowercase like index_members.index_symbol.
# The bound argument is the SYMBOL as stored, which is uppercase — pe_ratios holds
# stocks and indices in one column and every other table (daily_prices, symbols,
# trend_signals, range_stats) spells that column uppercase. Indices used to be
# written lowercase here, which made pe_ratios the only table where the same
# entity had two spellings, and silently dropped all three from any query that
# joined on symbol without normalising.
_PE_SAVERS = {
    "vn30":      functools.partial(db.save_pe_ratios, "VN30"),
    "vndiamond": functools.partial(db.save_pe_ratios, "VNDIAMOND"),
    "vnfinlead": functools.partial(db.save_pe_ratios, "VNFINLEAD"),
}

_PE_LOADERS = {
    "vn30":      functools.partial(db.load_pe_ratios, "VN30"),
    "vndiamond": functools.partial(db.load_pe_ratios, "VNDIAMOND"),
    "vnfinlead": functools.partial(db.load_pe_ratios, "VNFINLEAD"),
}


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

    # ── Shares: one value per quarter-end, bfill + ffill ─────────────────────
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
    # Coalesce: kqkd_14 -> kqkd_13 -> kqkd_10
    # CafeF stores 0.0 (not NaN) in kqkd_14 for banks — treat zero as missing too
    def _coalesce(row):
        for col in ("kqkd_14", "kqkd_13", "kqkd_10"):
            v = row[col]
            if v is not None and not (isinstance(v, float) and (v != v)) and v != 0.0:
                return v
        return None
    profit_df["net_profit"] = profit_df.apply(_coalesce, axis=1)
    profit_df["ttm"] = profit_df["net_profit"].rolling(4).sum()
    profit_ts = (
        profit_df.dropna(subset=["ttm"])
        .set_index("quarter_end")["ttm"]
    )

    # ── Reindex to daily, bfill+ffill shares, ffill TTM (no look-ahead) ──────
    full_index = dates.union(shares_ts.index).union(profit_ts.index)
    daily_shares = shares_ts.reindex(full_index).ffill().bfill().reindex(dates)
    daily_ttm    = profit_ts.reindex(full_index).ffill().reindex(dates)

    result = pd.DataFrame({"shares": daily_shares, "ttm_profit": daily_ttm})
    return result.dropna()


def calc_stock_pe(
    symbol: str,
    start: str | None = None,
) -> pd.DataFrame:
    """
    Calculate daily P/E for a single stock.

    Returns a DataFrame with columns:
        date (str), pe_ratio, total_market_cap, total_ttm_profit
    """
    prices = db.load_daily_prices(symbol)["close"]
    if start:
        prices = prices[prices.index >= start]
    if prices.empty:
        return pd.DataFrame()

    fd = _build_fundamental_daily(symbol, prices.index)
    if fd is None or fd.empty:
        return pd.DataFrame()

    records = []
    for date in fd.index:
        if date not in prices.index:
            continue
        price  = prices[date]
        shares = fd.loc[date, "shares"]
        ttm    = fd.loc[date, "ttm_profit"]
        if ttm <= 0:
            continue
        mcap = price * shares
        records.append({
            "symbol":           symbol,
            "date":             date.date().isoformat(),
            "pe_ratio":         mcap / ttm,
            "total_market_cap": mcap,
            "total_ttm_profit": ttm,
        })

    return pd.DataFrame(records)


def calc_pe_history(
    index: str = "vn30",
    start: str | None = None,
    end: str | None = None,
    emit_members: bool = False,
) -> pd.DataFrame:
    """
    Calculate daily aggregate P/E for `index` over [start, end].

    index        : "vn30", "vndiamond", or "vnfinlead"
    emit_members : if True, also save per-member daily P/E to pe_members table

    Returns a DataFrame with columns:
        date (str), pe_ratio, total_market_cap, total_ttm_profit, member_count
    """
    index = index.lower()
    if index not in _MEMBER_LOADERS:
        raise ValueError(f"Unknown index '{index}'. Choose from: {list(_MEMBER_LOADERS)}")

    load_members = _MEMBER_LOADERS[index]

    # ── Gather all price data ────────────────────────────────────────────────
    symbols = db.list_symbols(symbol_type='stock')
    prices: dict[str, pd.Series] = {}
    for sym in symbols:
        p = db.load_daily_prices(sym)["close"]
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
    member_records = []  # for emit_members

    for date in all_dates:
        date_str = date.date().isoformat()

        members = set(load_members(as_of=date_str)["symbol"].tolist())

        total_mcap   = 0.0
        total_profit = 0.0
        count        = 0

        for sym in members:
            if sym not in prices or date not in prices[sym].index:
                continue
            if sym not in fundamentals or date not in fundamentals[sym].index:
                continue

            price  = prices[sym][date]
            shares = fundamentals[sym].loc[date, "shares"]
            ttm    = fundamentals[sym].loc[date, "ttm_profit"]

            if ttm <= 0:
                continue

            mcap = price * shares
            total_mcap   += mcap
            total_profit += ttm
            count        += 1

            if emit_members:
                member_records.append({
                    "symbol":            sym,
                    "date":              date_str,
                    "pe_ratio":          mcap / ttm,
                    "total_market_cap":  mcap,
                    "total_ttm_profit":  ttm,
                })

        # all_dates is the union over members, so a sync that left some symbols
        # a few days ahead of the rest produces dates only they can answer for.
        # An aggregate over that handful is not the index: repairing nine
        # symbols once put VN30 at 6.03x off 8 of its 30 members. Genuine
        # coverage gaps are nowhere near that thin — the sparsest honest date on
        # record is 17 of 30, back in 2012 — so half the membership is a floor
        # no real date reaches.
        enough = count > 0 and count * 2 >= len(members)

        if not enough or total_profit == 0:
            pe = None
        else:
            pe = total_mcap / total_profit

        records.append({
            "date":             date_str,
            "pe_ratio":         pe,
            "total_market_cap": total_mcap if enough else None,
            "total_ttm_profit": total_profit if enough else None,
            "member_count":     count,
        })

    if emit_members and member_records:
        db.save_pe_ratios_bulk(member_records)

    return pd.DataFrame(records)


if __name__ == "__main__":
    db.init_db()

    for idx in ["vn30", "vndiamond", "vnfinlead"]:
        print(f"\n{'='*55}")
        print(f"Calculating {idx.upper()} aggregate P/E …")
        pe_df = calc_pe_history(index=idx)
        valid = pe_df.dropna(subset=["pe_ratio"])
        print(f"  {len(pe_df)} dates, {len(valid)} with valid P/E")
        if not valid.empty:
            print(f"  Range: {valid.iloc[0]['date']} → {valid.iloc[-1]['date']}")
            print(f"  P/E range: {valid['pe_ratio'].min():.2f}x – {valid['pe_ratio'].max():.2f}x")
            print(f"  Current:   {valid.iloc[-1]['pe_ratio']:.2f}x")
            _PE_SAVERS[idx](pe_df)
