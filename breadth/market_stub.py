"""
Just enough Market to run the backtest from a cached breadth series.

WHY THIS IS NOT core.Market

  core.Market loads rolling statistics for every symbol, which is the eight
  minutes. This method needs those statistics only to COMPUTE breadth, and once
  breadth is cached the statistics are not needed again -- the backtest itself
  touches exactly one thing, the traded instrument's daily close.

  So this reads one symbol's prices and nothing else, and exposes the two
  methods the engine calls: days() and __getitem__. It is a stub in the precise
  sense that it is complete for the one caller it has, not that it is a
  placeholder for something better.

  It is deliberately NOT a subclass. Inheriting would let a future caller reach
  a method that quietly returns nothing useful; a separate class means the
  failure is an AttributeError at the first attempt rather than a wrong number
  at the end.
"""

import sqlite3

import numpy as np
import pandas as pd

from database import DB_PATH


class _Bar:
    __slots__ = ("symbol", "index", "price")

    def __init__(self, symbol, index, price):
        self.symbol, self.index, self.price = symbol, index, price


class _Day:
    __slots__ = ("date", "bars")

    def __init__(self, date, bars):
        self.date, self.bars = date, bars


class _Series:
    """Closes only. Anything else a Rule might ask for is absent on purpose."""

    def __init__(self, symbol, closes, dates, is_index=True):
        self.symbol = symbol
        self.closes = np.asarray(closes, dtype=float)
        self.dates = dates
        self.is_index = is_index
        self.warmup = 0
        self.row_of = {d: i for i, d in enumerate(dates)}

    def __len__(self) -> int:
        return len(self.closes)

    def close(self, i: int) -> float:
        return float(self.closes[i])


class PriceMarket:
    """One instrument, its calendar restricted to the days breadth covers."""

    def __init__(self, symbol, dates, closes, tradable=None):
        """
        `dates` is the WHOLE calendar; `tradable` marks the days the instrument
        can actually be bought on.

        THE UNTRADABLE DAYS HAVE TO STAY. The engine accrues the monthly
        contribution before it looks for a bar, so a day dropped from the
        calendar is a month of savings that never arrives. Dropping them gave
        127 months against the full loader's 137 -- identical trades, 80m less
        capital, and a growth figure that looked better for it.
        """
        self.symbol = symbol
        self._series = _Series(symbol, closes, dates)
        self._days = []
        for i, (d, c) in enumerate(zip(dates, closes)):
            ok = True if tradable is None else tradable[i]
            self._days.append(
                _Day(d, {symbol: _Bar(symbol, i, float(c))} if ok else {}))

    @classmethod
    def for_symbol(cls, symbol: str, dates, warmup: int = 0) -> "PriceMarket":
        """
        Prices for `symbol` on exactly `dates`, past its own warmup.

        WARMUP IS NOT OPTIONAL HERE, and leaving it out was a real bug. core's
        Market yields a bar only once a symbol is `warmup` rows into ITS OWN
        history, so the instrument is untradable for the first stretch of the
        calendar. A stub that ignored that gave 137 buys where the full load
        gave 127 -- the same config, two answers, decided by which path the
        caller happened to take.

        The count is rows of the symbol's own price series, exactly as in
        core.data: max(windows) - 1, because the rolling statistics are built
        with min_periods=1 and exist, meaninglessly, from row zero.

        Days the instrument did not trade are DROPPED rather than
        forward-filled. A forward fill would let the engine buy at yesterday's
        price on a day the market was shut, which is a fill that never existed;
        dropping them means the contribution waits for the next real bar, which
        is what actually happens.
        """
        with sqlite3.connect(DB_PATH) as con:
            rows = con.execute(
                "SELECT date, close FROM daily_prices WHERE symbol = ? "
                "ORDER BY date", (symbol.upper(),)).fetchall()
        if not rows:
            raise ValueError(f"no prices for {symbol}")
        # Row number in the symbol's own series, which is what warmup counts.
        have = {pd.Timestamp(d): (i, float(c)) for i, (d, c) in enumerate(rows)}

        keep_d, keep_c, ok = [], [], []
        last = 0.0
        for d in dates:
            got = have.get(pd.Timestamp(d))
            row, close = got if got is not None else (-1, 0.0)
            tradable = got is not None and row >= warmup and close > 0
            keep_d.append(d)
            # A price is carried forward only to keep the arrays aligned; the
            # day is marked untradable, so nothing can ever be bought at it.
            keep_c.append(close if close > 0 else last)
            last = keep_c[-1]
            ok.append(tradable)
        if not any(ok):
            raise ValueError(f"{symbol} has no tradable price on any breadth date")
        return cls(symbol.upper(), keep_d, keep_c, ok)

    def days(self):
        return iter(self._days)

    def __getitem__(self, symbol: str):
        if symbol.upper() != self.symbol:
            raise KeyError(
                f"PriceMarket holds only {self.symbol}; asked for {symbol}. "
                "Computing breadth needs the full core.Market -- run --fresh.")
        return self._series

    @property
    def symbols(self) -> list:
        return [self.symbol]

    def summary(self) -> str:
        return (f"{self.symbol} | {len(self._days)} trading days | "
                f"{str(self._days[0].date)[:10]} -> {str(self._days[-1].date)[:10]}")
