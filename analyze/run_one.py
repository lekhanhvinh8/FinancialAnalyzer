"""
Test a single strategy combination.

Usage:
    python analyze/run_one.py

Edit the strategy parameters in the EDIT HERE section, then run.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import os
import pandas as pd
import database as db
from analyze.range_calc import build_cal_range_close
from analyze.engine import estimate
from export.chart import save_backtest_chart
from analyze.strategies.buy import (
    BuyIntervalStrategy, BuyBottomStrategy, BuyMAStrategy,
    BuyUptrendStrategy, BuyPartialStrategy, BuyPartialMA, BuyMA1000Strategy,
    BuyMedian1000Strategy,
)
from analyze.strategies.sell import (
    SellTopStrategy, SellTopOfBottomStrategy, SellTopOfMA1000Strategy,
    SellPartialStrategy, SellMedian1000Strategy,
)
from analyze.strategies.reinvest import (
    ReInvestBottomStrategy, ReInvestBottomOfTopStrategy,
    ReInvestPartialStrategy, ReInvestUnderMA1000Strategy,
    ReInvestUnderMA1000OrMaxHoldTimeStrategy, ReInvestMedian1000Strategy,
)
from analyze.models import DeltaToActionMatrix

INTERVAL_MONEY = 8_000_000
INDEX_SYMBOL   = 'VN30'


def load_df():
    prices = db.load_daily_prices(INDEX_SYMBOL).reset_index().rename(columns={'date': 'time'})
    pe     = db.load_pe_ratios(INDEX_SYMBOL).reset_index().rename(columns={'date': 'time'})
    pe     = pe.dropna(subset=['pe_ratio'])[['time', 'pe_ratio']]
    df     = prices.merge(pe, on='time', how='left')
    df['pe_ratio'] = df['pe_ratio'].ffill()
    return df.reset_index(drop=True)


if __name__ == '__main__':
    db.init_db()
    df = load_df()
    firstClose = df['close'].iloc[0] * 1000
    firstPE    = df['pe_ratio'].dropna().iloc[0]
    firstDate  = pd.Timestamp(df['time'].iloc[0])

    print(f"Loaded {len(df)} rows | {df['time'].iloc[0].date()} -> {df['time'].iloc[-1].date()}")
    print("Loading cal_range_close from DB ...")
    cal_range_close = db.load_range_stats(INDEX_SYMBOL, df)
    # Only rebuild if not in DB or if you need use_pe=True (pe_avg is not stored):
    # cal_range_close = build_cal_range_close(df, range_days=list(range(50, 1001, 50)), max_workers=5)
    print("Done.\n")

    # ════════════════════════════════════════════════════════════════════════════
    # ── EDIT HERE ────────────────────────────────────────────────────────────
    buyIntervalStrategy = BuyIntervalStrategy()
    buyMedian1000Strategy = BuyMedian1000Strategy(
        percentBuy = 40,
        use_pe     = False,
    )
    sellMedian1000Strategy = SellMedian1000Strategy(
        percentSell = 60,  # sell when price is > 20% above 1000d median
        use_pe      = False,
    )
    reinvestMedian1000Strategy = ReInvestMedian1000Strategy(
        percentReinvest = -1,
        use_pe          = False,
    )


    buyStrategy = buyMedian1000Strategy
    sellStrategy = sellMedian1000Strategy
    reinvestStrategy = reinvestMedian1000Strategy

    # ════════════════════════════════════════════════════════════════════════════

    print("Running estimate ...")
    allTotalCapital, allTotalFinal, allRatioGrowth, buyedInfos, sellInfos, reinvestInfos = estimate(
        df, INTERVAL_MONEY, buyStrategy, sellStrategy, reinvestStrategy, cal_range_close, isPrint=True
    )

    out = Path(__file__).parent.parent / f"charts/backtest_{INDEX_SYMBOL.lower()}.html"
    save_backtest_chart(df, buyedInfos, sellInfos, reinvestInfos,
                        path=str(out), index=INDEX_SYMBOL.lower())
    os.startfile(out)
 
