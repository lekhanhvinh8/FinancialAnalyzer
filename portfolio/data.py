"""
Reading one symbol out of the database, in the shape this package wants.

WHAT IS SHARED WITH THE REST OF THE PROJECT, AND WHAT IS NOT

  The only thing borrowed is the DATABASE — the same tables sync.py fills and
  syncs/audit_data.py checks. That is deliberate and it is not a shortcut: a
  second definition of "what the closing price of STB was" is how two parts of a
  project start disagreeing about reality. Prices, P/E and rolling statistics are
  facts about the market, not part of any evaluation method.

  Everything above that line is this package's own. In particular the rolling
  statistics are read with our own query into our own arrays, rather than through
  database.load_range_stats(), because that function returns the object graph the
  single-symbol engine wants — one RangeDaysClose per row per window, defined in
  single/models.py. This package has no use for those objects and no wish to
  depend on them.

TWO REPRESENTATION CHOICES WORTH KNOWING

  1. NUMPY ARRAYS, NOT A DICT OF OBJECTS PER ROW.
     A portfolio loop reads one number for one symbol on one day, tens of
     millions of times over a run. `median[window][i]` is a memory read;
     `cal[i].rangeDayCloses[w].pct50(False)` is two dict lookups, an attribute
     walk and a method call. Same information, and the array form also drops the
     per-row object overhead across a 50-symbol universe.

  2. REAL VND EVERYWHERE.
     The range_stats table stores prices multiplied by 1000 — a leftover from
     when the price source quoted thousands of dong — and the older code
     multiplies its closes by 1000 to match. The factor cancels out of every
     return, because shares are money/price and value is shares*price, so
     nothing there was ever wrong. But it makes reported share counts a
     thousandth of the truth, and a mistake in either direction is invisible
     until it is very expensive.

     Here the stats are divided by 1000 on load and closes are used as stored, so
     a price is a price and a share count is a share count. Both sides of every
     comparison move together, so the conditions are unaffected.
"""

import sqlite3
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from database import DB_PATH


@dataclass
class WindowStats:
    """
    Rolling statistics for ONE window size, aligned to the symbol's row index.

    NaN marks a row the table had nothing for. Every read goes through the
    accessors below, which turn NaN into None, so a missing statistic can never
    be silently compared against — a NaN comparison is False in every direction
    and would disable a condition rather than announce itself.
    """
    window: int
    median: np.ndarray
    top: np.ndarray
    bottom: np.ndarray
    mean: np.ndarray
    # Quartiles. No rule reads them — they are here because the per-symbol chart
    # draws the same band single/median1000's does, and a chart that showed a
    # different set of references than the one the reader already knows would be
    # worse than no chart.
    p25: np.ndarray = None
    p75: np.ndarray = None

    def _at(self, arr: np.ndarray, i: int):
        if i < 0 or i >= len(arr):
            return None
        v = arr[i]
        return None if v != v else float(v)


@dataclass
class SymbolSeries:
    """
    Everything this package knows about one symbol.

    `closes` and `pes` are indexed by row number, as are every WindowStats array
    and `dates`. `row_of` maps the other way, from a calendar date back to that
    row. That mapping is the whole reason this class exists: a portfolio loop
    runs on dates, every condition is written against a row index, and two
    symbols listed years apart have different row numbers on the same date.
    """
    symbol: str
    dates: list                       # pd.Timestamp per row
    closes: np.ndarray                # VND
    pes: np.ndarray                   # NaN where the symbol had no P/E
    stats: dict = field(default_factory=dict)   # window -> WindowStats
    row_of: dict = field(default_factory=dict)  # pd.Timestamp -> row index
    warmup: int = 0                   # first row any condition may be evaluated on

    def __len__(self) -> int:
        return len(self.closes)

    # ── Accessors used by rules and scorers ───────────────────────────────────

    def close(self, i: int) -> float:
        return float(self.closes[i])

    def pe(self, i: int):
        v = self.pes[i]
        return None if v != v else float(v)

    def median(self, window: int, i: int):
        s = self.stats.get(window)
        return None if s is None else s._at(s.median, i)

    def top(self, window: int, i: int):
        s = self.stats.get(window)
        return None if s is None else s._at(s.top, i)

    def bottom(self, window: int, i: int):
        s = self.stats.get(window)
        return None if s is None else s._at(s.bottom, i)

    def mean(self, window: int, i: int):
        s = self.stats.get(window)
        return None if s is None else s._at(s.mean, i)

    def p25(self, window: int, i: int):
        s = self.stats.get(window)
        return None if s is None else s._at(s.p25, i)

    def p75(self, window: int, i: int):
        s = self.stats.get(window)
        return None if s is None else s._at(s.p75, i)

    def reference(self, kind: str, window: int, i: int):
        """One of 'median' / 'top' / 'bottom' / 'mean', chosen by name."""
        try:
            return getattr(self, kind)(window, i)
        except AttributeError:
            raise ValueError(f"unknown reference {kind!r}")


# ── Loading ───────────────────────────────────────────────────────────────────

_STATS_SCALE = 1000.0    # range_stats is stored at price * 1000; see the module docstring


def load_symbol(symbol: str, windows, min_rows: int = 0
                ) -> "tuple[SymbolSeries | None, str | None]":
    """
    Returns (series, None) or (None, skip_reason).

    `windows` is the set of window sizes any rule or scorer will read. Naming
    them matters: range_stats holds around 1500 windows per symbol and loading
    all of them is by far the slowest thing in a run.

    WARMUP IS THE LONGEST WINDOW, MINUS ONE

      A row is evaluable once every window behind it is FULL. The statistics are
      built with a minimum period of one observation, so row 0 holds the median
      of a single day, row 5 the median of six, and only at row `window - 1` is
      there a complete window behind it. That row is the first honest one, so
      warmup = max(windows) - 1.

      Getting this boundary wrong is silent. Too early and the first decisions
      are taken against a median of almost nothing, which is not a median. Too
      late and history is thrown away — and because the wallet then makes its
      first purchase on a different day at a different price, every number
      downstream shifts slightly, with nothing to indicate why.

      There is no signal-warmup arithmetic here because there are no signals. The
      single-symbol runner needs a much more involved rule, since its gates read
      trend signals and z-scores that each begin on their own date; importing
      that would be importing a rule for a problem this package does not have.
      When a condition here starts reading such a signal, this is where it gets
      reckoned with.
    """
    windows = sorted({int(w) for w in windows})
    if not windows:
        raise ValueError("at least one window is required")

    prices = _load_prices(symbol)
    if prices.empty:
        return None, "no prices"
    if len(prices) < max(min_rows, max(windows) + 1):
        return None, f"only {len(prices)} rows"

    pes = _load_pes(symbol)
    df = prices.merge(pes, on="date", how="left")
    # Forward-filled because a P/E is only recomputed when a new quarterly report
    # lands; between reports the last one is still the best available reading.
    # A stretch with no P/E at all — a company loss-making over a trailing year —
    # stays NaN before the first report and is carried afterwards, which is a
    # known wart of the shared pipeline rather than something invented here.
    df["pe_ratio"] = df["pe_ratio"].ffill()

    dates = [pd.Timestamp(d) for d in df["date"]]
    series = SymbolSeries(
        symbol=symbol,
        dates=dates,
        closes=df["close"].to_numpy(dtype=float),
        pes=df["pe_ratio"].to_numpy(dtype=float),
        row_of={d: i for i, d in enumerate(dates)},
        warmup=max(windows) - 1,
    )

    stats = _load_window_stats(symbol, windows, {str(d.date()): i
                                                 for i, d in enumerate(dates)},
                               len(dates))
    missing = [w for w in windows if w not in stats]
    if missing:
        return None, f"no range_stats for window(s) {missing}"
    series.stats = stats

    if len(series) - series.warmup <= 0:
        return None, f"nothing left after {series.warmup} bars of warmup"
    return series, None


def _load_prices(symbol: str) -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as con:
        return pd.read_sql(
            "SELECT date, close FROM daily_prices WHERE symbol = ? ORDER BY date",
            con, params=(symbol,))


def _load_pes(symbol: str) -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as con:
        return pd.read_sql(
            "SELECT date, pe_ratio FROM pe_ratios WHERE symbol = ? ORDER BY date",
            con, params=(symbol,))


def _load_window_stats(symbol: str, windows: list, date_to_row: dict,
                       n_rows: int) -> dict:
    """
    Rolling statistics for the named windows, as arrays aligned to row index.

    direction = 'back' only. The table also holds forward-looking rows, which are
    hindsight and must never reach a decision.
    """
    placeholders = ",".join("?" * len(windows))
    sql = (f"SELECT range_days, date, median, local_top, local_bottom, local_avg, "
           f"p25, p75 "
           f"FROM range_stats "
           f"WHERE symbol = ? AND direction = 'back' AND range_days IN ({placeholders})")

    out: dict = {}
    for w in windows:
        out[w] = WindowStats(
            window=w,
            median=np.full(n_rows, np.nan),
            top=np.full(n_rows, np.nan),
            bottom=np.full(n_rows, np.nan),
            mean=np.full(n_rows, np.nan),
            p25=np.full(n_rows, np.nan),
            p75=np.full(n_rows, np.nan),
        )

    seen = set()
    with sqlite3.connect(DB_PATH) as con:
        for rd, date, median, top, bottom, mean, p25, p75 in con.execute(
                sql, (symbol, *windows)):
            i = date_to_row.get(date)
            if i is None:
                continue
            ws = out[rd]
            ws.median[i] = median / _STATS_SCALE
            ws.top[i] = top / _STATS_SCALE
            ws.bottom[i] = bottom / _STATS_SCALE
            ws.mean[i] = mean / _STATS_SCALE
            if p25 is not None:
                ws.p25[i] = p25 / _STATS_SCALE
            if p75 is not None:
                ws.p75[i] = p75 / _STATS_SCALE
            seen.add(rd)

    return {w: ws for w, ws in out.items() if w in seen}
