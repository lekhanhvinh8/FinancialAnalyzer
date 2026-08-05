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
from analyze.strategies.buy import BuyMedian1000Strategy, BuyIntervalStrategy
from analyze.strategies.sell import SellMedian1000Strategy, SellStrategy
from analyze.strategies.reinvest import ReInvestMedian1000Strategy, ReinvestStrategy
from export.chart import save_backtest_chart
from analyze.median1000 import config

CHARTS_DIR = Path(__file__).parent / "charts"
SYMBOL     = sys.argv[1].upper() if len(sys.argv) > 1 else "VN30"


def _signal_map(symbol, df, window, col):
    """{row_index: signal value} for one trend-signal window."""
    date_to_idx = {pd.Timestamp(row["time"]): i for i, row in df.iterrows()}
    sig = db.load_trend_signals(symbol, window_days=window)
    out = {}
    if not sig.empty:
        for date, v in sig[col].items():
            idx = date_to_idx.get(pd.Timestamp(date))
            if idx is not None:
                out[idx] = float(v)
    return out


def make_strategies(signal3_map=None, signal1_map=None, reinvest_signal1_map=None, zdev_map=None):
    gate  = config.REINVEST_MIN_SIGNAL1 is not None
    zgate = config.SELL_MIN_ZDEV is not None
    return (
        BuyMedian1000Strategy(percentBuy=config.PERCENT_BUY,           use_pe=config.USE_PE),
        SellMedian1000Strategy(percentSell=config.PERCENT_SELL,         use_pe=config.USE_PE,
                               signal3_map=signal3_map or {}, min_signal3=config.MIN_SIGNAL3,
                               signal1_map=signal1_map or {}, min_signal1=config.SELL_MIN_SIGNAL1,
                               zdev_map=(zdev_map or {}) if zgate else {},
                               min_zdev=config.SELL_MIN_ZDEV or 0.0),
        ReInvestMedian1000Strategy(percentReinvest=config.PERCENT_REINVEST, use_pe=config.USE_PE,
                                   timeoutDays=config.REINVEST_TIMEOUT_DAYS,
                                   timeoutPercent=config.REINVEST_TIMEOUT_PERCENT,
                                   signal1_map=(reinvest_signal1_map or {}) if gate else {},
                                   min_signal1=config.REINVEST_MIN_SIGNAL1 or 0.0),
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

    s3 = _signal_map(SYMBOL, df, 1000, "signal3_sharpe")
    s1 = _signal_map(SYMBOL, df, config.SELL_SIGNAL1_WINDOW, "signal1_slope")
    ri_s1 = (s1 if config.REINVEST_SIGNAL1_WINDOW == config.SELL_SIGNAL1_WINDOW
             else _signal_map(SYMBOL, df, config.REINVEST_SIGNAL1_WINDOW, "signal1_slope"))

    zmap = {}
    if config.SELL_MIN_ZDEV is not None:
        _zd = db.load_zdev(SYMBOL, 1000, config.SELL_ZDEV_WINDOW)
        _d2i = {pd.Timestamp(r["time"]): i for i, r in df.iterrows()}
        if not _zd.empty:
            for date, z in _zd["z_dev"].items():
                idx = _d2i.get(pd.Timestamp(date))
                if idx is not None and z is not None:
                    zmap[idx] = float(z)

    buy, sell, reinvest = make_strategies(s3, s1, ri_s1, zmap)
    result = run_estimate(SYMBOL, df, config.INTERVAL_MONEY, buy, sell, reinvest,
                          cal_range_close)

    cmp_result = run_estimate(SYMBOL, df, config.INTERVAL_MONEY,
                              BuyIntervalStrategy(), SellStrategy(), ReinvestStrategy(),
                              cal_range_close)

    out = CHARTS_DIR / f"{SYMBOL.lower()}_backtest.html"
    save_backtest_chart(
        df,
        result["buyedInfos"], result["sellInfos"], result["reinvestInfos"],
        path=str(out),
        index=SYMBOL.lower(),
        buy_strategy=buy, sell_strategy=sell, reinvest_strategy=reinvest,
        cal_range_close=cal_range_close,
        result=result,
        compare_result=cmp_result,
    )
    print(f"\nChart -> {out}")
    os.startfile(out)
