"""
vnstock data source adapter.

All public functions return data in the project standard format:

    get_prices(symbol, start, end) -> DataFrame
        index : DatetimeIndex (trading days)
        close : float  (VND)

    get_shares(symbol) -> DataFrame
        year    : int
        quarter : int  (1-4)
        shares  : float

    get_net_profit(symbol) -> DataFrame
        year       : int
        quarter    : int  (1-4)
        net_profit : float  (VND)

Note: free tier returns only the latest 4 quarters for fundamentals.
"""

import warnings
import os

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
warnings.filterwarnings("ignore")

import pandas as pd
from vnstock import Vnstock

_PAR_VALUE    = 10_000  # Standard Vietnam stock par value (VND)
_SOURCE       = "VCI"
_INDEX_SOURCE = "VCI"   # VCI supports both stock and index symbols


def _parse_quarter_col(q: str) -> tuple[int, int, pd.Timestamp]:
    """
    '2025-Q3'  ->  (year=2025, quarter=3, period_end_date=2025-09-30)
    """
    year_str, q_label = q.split("-")
    year    = int(year_str)
    quarter = int(q_label[1])
    end_month = quarter * 3
    end_date  = pd.Timestamp(year=year, month=end_month, day=1) + pd.offsets.MonthEnd(0)
    return year, quarter, end_date


def _quarter_cols(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if "Q" in str(c)]


def _stock(symbol: str):
    return Vnstock().stock(symbol=symbol, source=_SOURCE)


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def get_index_prices(symbol: str, start: str, end: str) -> pd.DataFrame:
    """
    Fetch daily closing prices for an index (VN30, VNINDEX, VNDIAMOND, VNFINLEAD).
    Returns DataFrame with DatetimeIndex and 'close' column in index points (not VND).
    """
    stock = Vnstock().stock(symbol=symbol, source=_INDEX_SOURCE)
    df = stock.quote.history(start=start, end=end, interval="1D")
    if df is None or df.empty:
        raise ValueError(f"[vnstock] No index price data for {symbol} ({start} → {end})")

    df["time"] = pd.to_datetime(df["time"])
    df = df.set_index("time")[["close"]].sort_index()
    # Index values are already in points — no scaling needed
    return df


def get_prices(symbol: str, start: str, end: str) -> pd.DataFrame:
    """
    Fetch daily closing prices.
    Returns DataFrame with DatetimeIndex and 'close' column in VND.
    """
    df = _stock(symbol).quote.history(start=start, end=end, interval="1D")
    if df is None or df.empty:
        raise ValueError(f"[vnstock] No price data for {symbol} ({start} → {end})")

    df["time"] = pd.to_datetime(df["time"])
    df = df.set_index("time")[["close"]].sort_index()
    # vnstock returns prices in thousands VND
    df["close"] = df["close"] * 1000
    return df


def get_shares(symbol: str) -> pd.DataFrame:
    """
    Fetch quarterly outstanding shares from balance sheet (Paid-in capital / par value).
    Returns DataFrame with columns: year, quarter, shares.
    """
    bs = _stock(symbol).finance.balance_sheet(period="quarter", lang="en")

    # Non-banks: "Paid-in capital"; Banks: "Charter capital"
    paid_in_row = bs[bs["item_en"].str.contains("Paid-in capital|Charter capital", case=False, na=False)]
    if paid_in_row.empty:
        raise ValueError(f"[vnstock] No paid-in/charter capital row found for {symbol}. Rows: {bs['item_en'].tolist()}")

    records = []
    for q in _quarter_cols(bs):
        year, quarter, _ = _parse_quarter_col(q)
        paid_in = float(paid_in_row[q].iloc[0])
        records.append({"year": year, "quarter": quarter, "shares": paid_in / _PAR_VALUE})

    return pd.DataFrame(records).sort_values(["year", "quarter"]).reset_index(drop=True)


def get_current_shares(symbol: str) -> float:
    """
    Shares in issue today, from the company overview rather than a balance sheet.

    Two overviews carry five counts between them, and each lags a bonus issue
    differently, in October 2026:

        FPT  KBS charter capital 1,885.7M   KBS listed / VCI issue  1,714.3M
        VPB  KBS listed         10,000.0M   KBS charter             7,933.9M
        HDB  VCI issue           6,506.9M   every KBS count         5,005.3M
        MBB  VCI issue          10,068.7M   every KBS count         9,263.2M

    The left column is what smoney.com.vn and 24hmoney.vn report. The adjusted
    price history is on the post-issue basis from the ex-date, so the largest
    count is the one that matches it. The cost of taking the largest is treasury
    or not-yet-listed shares, a few percent where they exist (MSN, VPL ≈ 4–5%);
    a missed bonus is 10–100%.
    """
    from vnstock.api.company import Company
    kbs = Company(symbol=symbol, source="KBS").overview().iloc[0]
    vci = Company(symbol=symbol, source="VCI").overview()

    def num(v, scale=1.0):
        return float(v) * scale if v is not None and v == v and float(v) > 0 else None

    exact = [num(kbs.get("outstanding_shares"))]
    # VCI's overview repeats issue_share across several columns, with
    # different values — the post-issue count is among them.
    if "issue_share" in vci.columns:
        exact += [num(v) for v in vci.loc[:, vci.columns == "issue_share"].iloc[0].tolist()]
    rounded = [num(kbs.get("charter_capital"), 1e9 / _PAR_VALUE),   # billion VND
               num(kbs.get("listed_volume"), 1e6)]                   # million shares
    exact   = [c for c in exact if c]
    counts  = exact + [c for c in rounded if c]
    if not counts:
        raise ValueError(f"[vnstock] no share count in the overviews for {symbol}")
    best = max(counts)
    # The rounded two are to 0.1M and 1M shares; prefer an exact count when it
    # is the same figure.
    match = [c for c in exact if abs(c / best - 1) < 0.001]
    return max(match) if match else best


def get_net_profit(symbol: str) -> pd.DataFrame:
    """
    Fetch quarterly net profit (after tax) from income statement.
    Returns DataFrame with columns: year, quarter, net_profit.
    """
    inc = _stock(symbol).finance.income_statement(period="quarter", lang="en")

    profit_row = inc[inc["item_en"].str.contains("after tax", case=False, na=False)]
    if profit_row.empty:
        raise ValueError(f"[vnstock] 'Net profit after tax' row not found for {symbol}")

    records = []
    for q in _quarter_cols(inc):
        year, quarter, _ = _parse_quarter_col(q)
        profit = float(profit_row[q].iloc[0])
        records.append({"year": year, "quarter": quarter, "net_profit": profit})

    return pd.DataFrame(records).sort_values(["year", "quarter"]).reset_index(drop=True)
