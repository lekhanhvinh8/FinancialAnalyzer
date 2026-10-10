"""
The market's trend, read from the index, aligned to one symbol's rows.

The classic trend filter (Faber 2007 on moving averages, Jegadeesh-Titman /
Moskowitz on 12-1 momentum): be invested while the market trends up, step
aside while it trends down. Both are among the few timing rules with a long
out-of-sample record across markets, which is the reason to test them here --
everything else in this package was found on this one history.

Two readings of the same index, both in percent so one threshold convention
serves both:

  ma200     close / its 200-bar moving average - 1        > 0: above the MA
  mom12_1   close 21 bars ago / close 252 bars ago - 1     > 0: up over the
                                                           year, skipping the
                                                           last month

Computed from closes up to and including the bar, so on the day it is read it
uses that day's close -- the same convention as every other signal here.

A missing reading (index warmup, a date the index did not trade) is absent from
the map, and every gate reading it treats absence as "do not act", the way the
breadth gates do.
"""

from functools import lru_cache

import pandas as pd

import database as db

SIGNALS = ("ma200", "mom12_1")


def compute(close: pd.Series) -> pd.DataFrame:
    """Both readings for a close series indexed by date. NaN during warmup."""
    ma = close.rolling(200, min_periods=200).mean()
    return pd.DataFrame({
        "ma200": (close / ma - 1) * 100,
        "mom12_1": (close.shift(21) / close.shift(252) - 1) * 100,
    }, index=close.index)


@lru_cache(maxsize=8)
def _index_signals(index: str) -> pd.DataFrame:
    close = db.load_daily_prices(index)["close"].astype(float)
    close.index = pd.to_datetime(close.index)
    return compute(close)


def build_trend_map(df, signal: str, index: str) -> dict:
    """{row_index: value} for the rows of `df` (needs a `time` column)."""
    if signal not in SIGNALS:
        raise ValueError(f"TREND_SIGNAL must be one of {SIGNALS}, not {signal!r}")
    s = _index_signals(index)[signal].dropna()
    by_date = dict(zip(s.index, s.to_numpy()))
    out = {}
    for i, t in enumerate(df["time"]):
        v = by_date.get(pd.Timestamp(t))
        if v is not None:
            out[i] = float(v)
    return out
