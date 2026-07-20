"""
Shared helper: load data for one symbol and run one estimate pass.
Used by run_one.py and run_all.py.
"""

import pandas as pd
import database as db
from .engine import estimate


def load_symbol_df(symbol: str) -> pd.DataFrame:
    prices = db.load_daily_prices(symbol).reset_index().rename(columns={"date": "time"})
    pe     = db.load_pe_ratios(symbol).reset_index().rename(columns={"date": "time"})
    pe     = pe.dropna(subset=["pe_ratio"])[["time", "pe_ratio"]]
    df     = prices.merge(pe, on="time", how="left")
    df["pe_ratio"] = df["pe_ratio"].ffill()
    return df.reset_index(drop=True)


def run_estimate(symbol: str, df: pd.DataFrame, interval_money: int,
                 buy_strategy, sell_strategy, reinvest_strategy,
                 cal_range_close: dict) -> dict:
    """
    Run one estimate pass and return a flat result dict.
    """
    (allTotalCapital, allTotalFinal, allRatioGrowth,
     buyedInfos, sellInfos, reinvestInfos,
     extra) = estimate(
        df, interval_money, buy_strategy, sell_strategy, reinvest_strategy,
        cal_range_close, isPrint=False,
    )
    return {
        "symbol":               symbol,
        "allTotalCapital":      allTotalCapital,
        "allTotalFinal":        allTotalFinal,
        "allRatioGrowth":       allRatioGrowth,
        "totalBuys":            len(buyedInfos),
        "totalSells":           len(sellInfos),
        "totalReinvest":        len(reinvestInfos),
        "buyedInfos":           buyedInfos,
        "sellInfos":            sellInfos,
        "reinvestInfos":        reinvestInfos,
        **extra,
    }
