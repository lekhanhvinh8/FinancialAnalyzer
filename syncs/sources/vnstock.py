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
