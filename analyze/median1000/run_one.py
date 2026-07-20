"""
Test the Median1000 strategy on a single symbol.

Usage:
    python analyze/median1000/run_one.py
    python analyze/median1000/run_one.py HPG

Edit config.py to tune strategy parameters.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import os
import pandas as pd
import database as db
from analyze.runner import load_symbol_df, run_estimate
from analyze.strategies.buy import BuyMedian1000Strategy
from analyze.strategies.sell import SellMedian1000Strategy
from analyze.strategies.reinvest import ReInvestMedian1000Strategy
from export.chart import save_backtest_chart
from analyze.median1000 import config

CHARTS_DIR = Path(__file__).parent / "charts"
SYMBOL     = sys.argv[1].upper() if len(sys.argv) > 1 else "VN30"


def make_strategies():
    return (
        BuyMedian1000Strategy(percentBuy=config.PERCENT_BUY,           use_pe=config.USE_PE),
        SellMedian1000Strategy(percentSell=config.PERCENT_SELL,         use_pe=config.USE_PE),
        ReInvestMedian1000Strategy(percentReinvest=config.PERCENT_REINVEST, use_pe=config.USE_PE),
    )


if __name__ == "__main__":
    db.init_db()
    CHARTS_DIR.mkdir(exist_ok=True)

    df = load_symbol_df(SYMBOL)
    print(f"Loaded {len(df)} rows | {df['time'].iloc[0].date()} -> {df['time'].iloc[-1].date()}")

    cal_range_close = db.load_range_stats(SYMBOL, df)
    if cal_range_close is None:
        print("ERROR: no range_stats in DB for", SYMBOL)
        sys.exit(1)

    buy, sell, reinvest = make_strategies()
    result = run_estimate(SYMBOL, df, config.INTERVAL_MONEY, buy, sell, reinvest,
                          cal_range_close)

    out = CHARTS_DIR / f"backtest_{SYMBOL.lower()}.html"
    save_backtest_chart(
        df,
        result["buyedInfos"], result["sellInfos"], result["reinvestInfos"],
        path=str(out),
        index=SYMBOL.lower(),
        buy_strategy=buy, sell_strategy=sell, reinvest_strategy=reinvest,
        cal_range_close=cal_range_close,
        result=result,
    )
    print(f"\nChart -> {out}")
    os.startfile(out)
