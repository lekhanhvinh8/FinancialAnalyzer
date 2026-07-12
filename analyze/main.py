"""
Entry point for the VN30 investment strategy simulator.

Usage:
    python -m analyze.main
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import sqlite3
import pandas as pd
import numpy as np
import seaborn as sns
from matplotlib import pyplot as plt

import database as db
from .range_calc import build_cal_range_close
from .engine import estimate
from .strategies import (
    BuyIntervalStrategy, BuyMA1000Strategy,
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
        prices = db.load_index_prices(INDEX_SYMBOL).reset_index().rename(columns={'date': 'time'})
        con = sqlite3.connect(db.DB_PATH)
        pe = pd.read_sql_query(
            'SELECT date, pe_ratio FROM pe_vn30 WHERE pe_ratio IS NOT NULL ORDER BY date',
            con, parse_dates=['date']
        )
        con.close()
        pe = pe.rename(columns={'date': 'time'})
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
    cal_range_close = db.load_cal_range_close(INDEX_SYMBOL, df)
    if cal_range_close is None:
        print(f'  Not cached — building ({MAX_WORKERS} workers) ...')
        cal_range_close = build_cal_range_close(df, range_days=[1000], max_workers=MAX_WORKERS)
        db.save_cal_range_close(INDEX_SYMBOL, df, cal_range_close)
    else:
        print(f'  Loaded {len(cal_range_close)} entries from DB')

    firstClose = df['close'].iloc[0] * 1000

    buyStrategy      = BuyMA1000Strategy(increasedPercentNotBuy=45)
    sellStrategy     = SellTopOfMA1000Strategy(firstLocalBottom=firstClose, percentSell=45)
    reinvestStrategy = ReInvestUnderMA1000Strategy()

    print('\nRunning estimate ...')
    result = estimate(df, INTERVAL_MONEY, buyStrategy, sellStrategy, reinvestStrategy, cal_range_close, isPrint=True)
    allTotalCapital, allTotalFinal, allRatioGrowth, buyedInfos, sellInfos, reinvestInfos = result

    plot_results(df, buyedInfos, sellInfos, reinvestInfos)
