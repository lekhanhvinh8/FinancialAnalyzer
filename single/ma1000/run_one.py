"""
Entry point for the VN30 investment strategy simulator.

Usage:
    python -m single.ma1000.run_one
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np
import seaborn as sns
from matplotlib import pyplot as plt

import database as db
from core.range_calc import build_cal_range_close
from ..engine import estimate
from ..sweep import sweep_2d, plot_heatmap, plot_best
from ..strategies import (
    BuyIntervalStrategy, BuyMA1000Strategy, BuyMAStrategy,
    SellTopOfMA1000Strategy,
    ReInvestUnderMA1000Strategy, ReInvestUnderMA1000OrMaxHoldTimeStrategy,
)

# ── Config ────────────────────────────────────────────────────────────────────
DATA_SOURCE   = 'db'      # 'db' or 'vnstock'
INDEX_SYMBOL  = 'VN30'
INTERVAL_MONEY = 8_000_000
MAX_WORKERS   = 5


# ── Data loading ──────────────────────────────────────────────────────────────
def load_df(source: str) -> pd.DataFrame:
    if source == 'vnstock':
        from vnstock import Quote
        df = Quote(symbol=INDEX_SYMBOL, source='VCI').history(
            start='2012-01-01', end='2026-07-10', interval='1D'
        )
        df = df.reset_index(drop=True)
        df['time'] = pd.to_datetime(df['time'])
        return df

    if source == 'db':
        prices = db.load_daily_prices(INDEX_SYMBOL).reset_index().rename(columns={'date': 'time'})
        pe = db.load_pe_ratios(INDEX_SYMBOL).reset_index().rename(columns={'date': 'time'})
        pe = pe.dropna(subset=['pe_ratio'])[['time', 'pe_ratio']]
        df = prices.merge(pe, on='time', how='left')
        df['pe_ratio'] = df['pe_ratio'].ffill()
        return df.reset_index(drop=True)

    raise ValueError(f'Unknown source: {source}')


# ── Visualization ─────────────────────────────────────────────────────────────
def plot_results(df, buyedInfos, sellInfos, reinvestInfos):
    df['close'].plot(kind='line', figsize=(15, 10), title='VN30 close')
    plt.gca().spines[['top', 'right']].set_visible(False)

    df['ma1000'] = df['close'].rolling(window=1000).mean()
    plt.plot(df.index, df['ma1000'], label='MA1000', color='blue', linewidth=2)
    plt.legend()

    for t in buyedInfos:
        plt.scatter(t.index, df['close'][t.index], color='green', zorder=3)
    for t in sellInfos:
        plt.scatter(t.index, df['close'][t.index], color='red', zorder=3)
    for t in reinvestInfos:
        plt.scatter(t.index, df['close'][t.index], color='yellow', zorder=3)

    plt.show()


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    db.init_db()
    print(f'Loading data ({DATA_SOURCE}) ...')
    df = load_df(DATA_SOURCE)
    print(f'  {len(df)} rows | {df["time"].iloc[0].date()} -> {df["time"].iloc[-1].date()}')

    print(f'\nLoading cal_range_close from DB ...')
    cal_range_close = db.load_range_stats(INDEX_SYMBOL, df)
    if cal_range_close is None:
        print(f'  Not cached — building ({MAX_WORKERS} workers) ...')
        cal_range_close = build_cal_range_close(df, range_days=[1000], max_workers=MAX_WORKERS)
        db.save_range_stats(INDEX_SYMBOL, df, cal_range_close)
    else:
        print(f'  Loaded {len(cal_range_close)} entries from DB')

    firstClose = df['close'].iloc[0] * 1000

    sellStrategy     = SellTopOfMA1000Strategy(percentSell=45)
    reinvestStrategy = ReInvestUnderMA1000Strategy()

    # ── Single run ────────────────────────────────────────────────────────────
    # buyStrategy = BuyMA1000Strategy(increasedPercentNotBuy=45)
    # print('\nRunning estimate ...')
    # result = estimate(df, INTERVAL_MONEY, buyStrategy, sellStrategy, reinvestStrategy, cal_range_close, isPrint=True)
    # allTotalCapital, allTotalFinal, allRatioGrowth, buyedInfos, sellInfos, reinvestInfos = result
    # plot_results(df, buyedInfos, sellInfos, reinvestInfos)

    # ── 2D sweep ──────────────────────────────────────────────────────────────
    first_pe = df['pe_ratio'].dropna().iloc[0]

    def make_strategies(local_range_days, decrease_percent):
        return (
            BuyMAStrategy(localRangeDays=local_range_days,
                          decreasePercent=decrease_percent,
                          use_pe=True),
            sellStrategy,
            reinvestStrategy,
        )

    results = sweep_2d(
        df, INTERVAL_MONEY, cal_range_close,
        make_strategies=make_strategies,
        param1_name="localRangeDays",  param1_vals=list(range(1, 1501)),
        param2_name="decreasePercent", param2_vals=[1, 3, 5, 10, 15, 20, 30],
        max_workers=MAX_WORKERS,
    )
    plot_heatmap(results)
    plot_best(results, df, INTERVAL_MONEY, cal_range_close, make_strategies)
