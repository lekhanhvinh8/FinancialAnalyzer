"""
Collect daily price, outstanding shares, and quarterly net profit for Vietnam stocks.
Uses vnstock (VCI source).

Data structure from vnstock:
- company.overview()  -> current_price, issue_share (outstanding shares)
- finance.income_statement(period='quarter', lang='en')
    -> rows indexed by item_en, columns are quarter labels like '2025-Q4'
    -> "Net profit/(loss) after tax" row = net profit
"""

import warnings
import os

# Suppress vnstock noise
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
warnings.filterwarnings("ignore")

import pandas as pd
from vnstock import Vnstock


def get_stock_data(symbol: str) -> dict:
    """
    Fetch price, outstanding shares, and TTM net profit for a single stock.

    Returns:
        {
            "symbol": str,
            "price": float,           # latest price in VND
            "shares": float,          # total outstanding shares
            "market_cap": float,      # price * shares
            "ttm_net_profit": float,  # sum of last 4 quarters net profit
            "pe": float | None,       # market_cap / ttm_net_profit
            "quarters": dict,         # individual quarter profits
        }
    """
    stock = Vnstock().stock(symbol=symbol, source="VCI")

    # --- 1. Price and outstanding shares ---
    overview = stock.company.overview()
    price = float(overview["current_price"].iloc[0])
    shares = float(overview["issue_share"].iloc[0])
    market_cap = price * shares

    # --- 2. Quarterly net profit (last 4 quarters = TTM) ---
    inc = stock.finance.income_statement(period="quarter", lang="en")

    # Rows are items; find the after-tax net profit row
    net_profit_row = inc[inc["item_en"].str.contains("after tax", case=False, na=False)]
    if net_profit_row.empty:
        raise ValueError(f"Could not find net profit row for {symbol}")

    # Quarter columns look like '2025-Q4', '2025-Q3', etc.
    quarter_cols = [c for c in inc.columns if "Q" in str(c)]
    quarter_profits = net_profit_row[quarter_cols].iloc[0].to_dict()

    # TTM = sum of available quarters (up to 4)
    ttm_quarters = list(quarter_profits.items())[:4]
    ttm_net_profit = sum(v for _, v in ttm_quarters)

    pe = (market_cap / ttm_net_profit) if ttm_net_profit > 0 else None

    return {
        "symbol": symbol,
        "price": price,
        "shares": shares,
        "market_cap": market_cap,
        "ttm_net_profit": ttm_net_profit,
        "pe": pe,
        "quarters": dict(ttm_quarters),
    }


def format_vnd(value: float) -> str:
    """Format large VND numbers readably (billions)."""
    return f"{value / 1e9:,.1f} tỷ"


if __name__ == "__main__":
    SYMBOL = "VNM"  # Vinamilk

    print(f"{'='*50}")
    print(f"  Stock P/E Analysis: {SYMBOL}")
    print(f"{'='*50}\n")

    data = get_stock_data(SYMBOL)

    print(f"  Price (latest)     : {data['price']:>15,.0f} VND")
    print(f"  Outstanding Shares : {data['shares']:>15,.0f}")
    print(f"  Market Cap         : {format_vnd(data['market_cap']):>20}")
    print()
    print(f"  TTM Net Profit breakdown:")
    for quarter, profit in data["quarters"].items():
        print(f"    {quarter}: {format_vnd(profit)}")
    print(f"  TTM Net Profit     : {format_vnd(data['ttm_net_profit']):>20}")
    print()
    if data["pe"] is not None:
        print(f"  P/E Ratio          : {data['pe']:>15.2f}x")
    else:
        print(f"  P/E Ratio          : N/A (negative earnings)")
