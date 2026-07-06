"""
Data collection orchestration — source-agnostic.

Functions here accept a `source` module that must expose:
    source.get_prices(symbol, start, end) -> DataFrame
    source.get_shares(symbol)             -> DataFrame
    source.get_net_profit(symbol)         -> DataFrame

Default source: sources.vnstock
"""

import importlib

import database as db


def _load_source(source):
    if isinstance(source, str):
        return importlib.import_module(f"sources.{source}")
    return source  # already a module


def collect_prices(symbol: str, start: str, end: str, source=None, override: bool = False):
    """
    Fetch daily prices and save to database.

    Args:
        symbol   : stock ticker, e.g. 'VNM'
        start    : ISO date string 'YYYY-MM-DD'
        end      : ISO date string 'YYYY-MM-DD'
        source   : source module or name string (default: 'vnstock')
        override : overwrite existing rows if True
    """
    src = _load_source(source or "vnstock")
    db.init_db()

    print(f"  [{src.__name__.split('.')[-1]}] Fetching prices for {symbol} ({start} → {end})")
    prices = src.get_prices(symbol, start, end)
    db.save_prices(symbol, prices, override=override)
    return prices


def collect_fundamentals(symbol: str, source=None, override: bool = False):
    """
    Fetch latest quarterly shares + net profit and save to database.

    Args:
        symbol   : stock ticker, e.g. 'VNM'
        source   : source module or name string (default: 'vnstock')
        override : overwrite existing rows if True
    """
    src = _load_source(source or "vnstock")
    db.init_db()

    print(f"  [{src.__name__.split('.')[-1]}] Fetching shares for {symbol}")
    shares = src.get_shares(symbol)
    db.save_shares(symbol, shares, override=override)

    print(f"  [{src.__name__.split('.')[-1]}] Fetching net profit for {symbol}")
    profit = src.get_net_profit(symbol)
    db.save_net_profit(symbol, profit, override=override)

    return shares, profit


if __name__ == "__main__":
    SYMBOL = "VNM"
    START  = "2024-01-01"
    END    = "2025-01-01"

    print(f"\n{'='*55}")
    print(f"  Collecting: {SYMBOL}")
    print(f"{'='*55}\n")

    collect_prices(SYMBOL, START, END)
    collect_fundamentals(SYMBOL)

    print(f"\n--- Run again (should skip all) ---")
    collect_prices(SYMBOL, START, END)
    collect_fundamentals(SYMBOL)

    print(f"\n--- Database summary ---")
    print(db.summary().to_string(index=False))
    print(f"\nShares:")
    print(db.load_shares(SYMBOL).to_string(index=False))
    print(f"\nNet Profit:")
    print(db.load_net_profit(SYMBOL).to_string(index=False))
