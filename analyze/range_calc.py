"""
Pre-compute rolling backward-window statistics for every row in df.

Result: dict[int, IndexCloses] keyed by row index.
Each IndexCloses holds rangeDayCloses (backward window),
storing top/avg/bottom/p25/median/p75 for both price and pe_ratio.

Uses ProcessPoolExecutor for true parallelism (bypasses GIL).
"""

import pandas as pd
from concurrent.futures import ProcessPoolExecutor, as_completed
from .models import RangeDaysClose, IndexCloses

# Module-level references used by worker processes (must be picklable)
_df: pd.DataFrame = None
_first_close: float = 0.0
_range_days_list: list[int] = []


def _init_worker(df_records, columns, first_close, range_days_list):
    global _df, _first_close, _range_days_list
    _df = pd.DataFrame(df_records, columns=columns)
    _first_close = first_close
    _range_days_list = range_days_list


def _compute_stats(closes: pd.Series, pe_vals: pd.Series, fallback: float) -> dict:
    if closes.empty:
        return dict(
            localTop=fallback, localAvg=fallback, localBottom=fallback,
            p25=fallback, median=fallback, p75=fallback,
            pe_top=0.0, pe_avg=0.0, pe_bottom=0.0,
            pe_p25=0.0, pe_median=0.0, pe_p75=0.0,
        )
    has_pe = not pe_vals.empty
    return dict(
        localTop    = closes.max(),
        localAvg    = closes.mean(),
        localBottom = closes.min(),
        p25         = closes.quantile(0.25),
        median      = closes.quantile(0.50),
        p75         = closes.quantile(0.75),
        pe_top      = pe_vals.max()           if has_pe else 0.0,
        pe_avg      = pe_vals.mean()          if has_pe else 0.0,
        pe_bottom   = pe_vals.min()           if has_pe else 0.0,
        pe_p25      = pe_vals.quantile(0.25)  if has_pe else 0.0,
        pe_median   = pe_vals.quantile(0.50)  if has_pe else 0.0,
        pe_p75      = pe_vals.quantile(0.75)  if has_pe else 0.0,
    )


def _process_index(index: int) -> tuple[int, IndexCloses]:
    df = _df
    first_close = _first_close
    n = len(df)
    has_pe = 'pe_ratio' in df.columns
    indexCloses = IndexCloses()

    for rangeDays in _range_days_list:
        # ── Backward ─────────────────────────────────────────────────────────
        back = df.iloc[max(0, index - rangeDays):index]
        closes  = back['close'] * 1000
        pe_vals = back['pe_ratio'].dropna() if has_pe else pd.Series(dtype=float)
        indexCloses.rangeDayCloses[rangeDays] = RangeDaysClose(
            **_compute_stats(closes, pe_vals, first_close)
        )


    return index, indexCloses


def build_cal_range_close(
    df: pd.DataFrame,
    range_days: list[int] | None = None,
    max_workers: int = 5,
    batch_size: int = 200,
    batch_callback=None,
) -> dict[int, IndexCloses]:
    """
    Build cal_range_close for all rows in df using up to max_workers processes.

    Args:
        df             : DataFrame with 'close' column and optional 'pe_ratio'
        range_days     : list of window sizes, default [1000]
        max_workers    : number of parallel processes
        batch_size     : call batch_callback every N completed rows
        batch_callback : callable(batch: dict[int, IndexCloses]) — called with
                         each completed batch so callers can save incrementally

    Returns:
        dict mapping row index -> IndexCloses
    """
    if range_days is None:
        range_days = [1000]

    first_close = df['close'].iloc[0] * 1000
    records = df.to_dict('records')
    columns = list(df.columns)
    n = len(df)

    cal_range_close: dict[int, IndexCloses] = {}
    batch: dict[int, IndexCloses] = {}

    with ProcessPoolExecutor(
        max_workers=max_workers,
        initializer=_init_worker,
        initargs=(records, columns, first_close, range_days),
    ) as executor:
        futures = {executor.submit(_process_index, i): i for i in range(n)}
        done = 0
        for future in as_completed(futures):
            idx, closes = future.result()
            cal_range_close[idx] = closes
            if batch_callback is not None:
                batch[idx] = closes
                if len(batch) >= batch_size:
                    batch_callback(batch)
                    batch = {}
            done += 1
            if done % 500 == 0 or done == n:
                print(f'  range_calc: {done}/{n}')

    if batch_callback is not None and batch:
        batch_callback(batch)

    return cal_range_close
