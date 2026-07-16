"""
Pre-compute rolling backward-window statistics for every row in df.

Result: dict[int, IndexCloses] keyed by row index.
Each IndexCloses holds rangeDayCloses (backward window),
storing top/avg/bottom for both price and pe_ratio.

Optimised: iterates over range_days (not rows), using pandas vectorised
rolling (C-level) instead of per-row Python slices.
Quantiles (p25/median/p75) are not used by any strategy and are omitted.
"""

import numpy as np
import pandas as pd
from .models import RangeDaysClose, IndexCloses


def build_cal_range_close(
    df: pd.DataFrame,
    range_days: list[int] | None = None,
    max_workers: int = 5,       # kept for API compatibility, unused
    batch_size: int = 200,      # kept for API compatibility, unused
    batch_callback=None,
    start_idx: int = 0,
) -> dict[int, IndexCloses]:
    """
    Build cal_range_close using vectorised pandas rolling.

    For each range_days value d, computes rolling(d).max/mean/min across
    all n rows in a single C-level pass, then reads out per-row values.

    Args:
        df          : DataFrame with 'close' column and optional 'pe_ratio'
        range_days  : list of window sizes; default [1000]
        start_idx   : only populate rows from this index onward
        batch_callback / batch_size: called with completed rows when provided
    """
    if range_days is None:
        range_days = [1000]

    n          = len(df)
    first_close = float(df['close'].iloc[0]) * 1000
    has_pe     = 'pe_ratio' in df.columns

    close_s = pd.Series((df['close'].to_numpy() * 1000), dtype=np.float64)
    pe_s    = pd.Series(df['pe_ratio'].to_numpy(), dtype=np.float64) if has_pe else None

    # Pre-initialise result dict
    cal: dict[int, IndexCloses] = {i: IndexCloses() for i in range(start_idx, n)}

    total = len(range_days)
    for rd_idx, rd in enumerate(range_days):
        roll       = close_s.rolling(window=rd, min_periods=1)
        top_arr    = roll.max().to_numpy()
        avg_arr    = roll.mean().to_numpy()
        bot_arr    = roll.min().to_numpy()
        p25_arr    = roll.quantile(0.25).to_numpy()
        med_arr    = roll.quantile(0.50).to_numpy()
        p75_arr    = roll.quantile(0.75).to_numpy()

        if has_pe:
            pe_roll    = pe_s.rolling(window=rd, min_periods=1)
            pe_top_arr = pe_roll.max().to_numpy()
            pe_avg_arr = pe_roll.mean().to_numpy()
            pe_bot_arr = pe_roll.min().to_numpy()
            pe_p25_arr = pe_roll.quantile(0.25).to_numpy()
            pe_med_arr = pe_roll.quantile(0.50).to_numpy()
            pe_p75_arr = pe_roll.quantile(0.75).to_numpy()
        else:
            pe_top_arr = pe_avg_arr = pe_bot_arr = None
            pe_p25_arr = pe_med_arr = pe_p75_arr = None

        for i in range(start_idx, n):
            cal[i].rangeDayCloses[rd] = RangeDaysClose(
                localTop    = float(top_arr[i]),
                localAvg    = float(avg_arr[i]),
                localBottom = float(bot_arr[i]),
                p25         = float(p25_arr[i]),
                median      = float(med_arr[i]),
                p75         = float(p75_arr[i]),
                pe_top    = float(pe_top_arr[i]) if has_pe else 0.0,
                pe_avg    = float(pe_avg_arr[i]) if has_pe else 0.0,
                pe_bottom = float(pe_bot_arr[i]) if has_pe else 0.0,
                pe_p25    = float(pe_p25_arr[i]) if has_pe else 0.0,
                pe_median = float(pe_med_arr[i]) if has_pe else 0.0,
                pe_p75    = float(pe_p75_arr[i]) if has_pe else 0.0,
            )

        if (rd_idx + 1) % 100 == 0 or rd_idx + 1 == total:
            print(f'  range_calc: {rd_idx + 1}/{total} range_days')

    if batch_callback is not None:
        # Deliver all rows in one shot (batch_callback interface preserved)
        for start in range(start_idx, n, batch_size):
            chunk = {i: cal[i] for i in range(start, min(start + batch_size, n))}
            batch_callback(chunk)

    return cal
