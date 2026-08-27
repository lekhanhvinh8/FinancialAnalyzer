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
    # P/E counterparts. Also chart-only while USE_PE is False, and loaded for the
    # same reason: the reference chart shows a P/E panel and a chart that dropped
    # it would not be the same chart.
    pe_p25: np.ndarray = None
    pe_median: np.ndarray = None
    pe_p75: np.ndarray = None
    pe_mean: np.ndarray = None

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
    caps: np.ndarray = None           # market capitalisation in VND, NaN where unknown
    # {window: array} of signal1_slope, the short-window linear-regression slope
    # of price in percent per day. Loaded only for windows a rule asks for.
    slopes: dict = field(default_factory=dict)
    # Cross-sectional percentile of `caps` among the symbols trading that day,
    # 0 = smallest, 1 = largest. NOT computed here — one symbol cannot see the
    # others. Market fills it after every symbol is loaded; see market.py.
    cap_pct: np.ndarray = None
    stats: dict = field(default_factory=dict)   # window -> WindowStats
    row_of: dict = field(default_factory=dict)  # pd.Timestamp -> row index
    warmup: int = 0                   # first row any condition may be evaluated on
    # True for an aggregate like VN30. It is loaded and tradable — the benchmark
    # has to be buyable as a fallback — but it is NOT a company, and anything
    # that compares companies with each other has to leave it out.
    is_index: bool = False

    def __len__(self) -> int:
        return len(self.closes)

    # ── Accessors used by rules and scorers ───────────────────────────────────

    def close(self, i: int) -> float:
        return float(self.closes[i])

    def pe(self, i: int):
        v = self.pes[i]
        return None if v != v else float(v)

    def cap(self, i: int):
        if self.caps is None:
            return None
        v = self.caps[i]
        return None if v != v else float(v)

    def slope(self, window: int, i: int):
        """
        Short-term momentum: the regression slope of price over `window` bars,
        in percent per day. None when it was never computed for that window or
        the row predates it.
        """
        a = self.slopes.get(window)
        if a is None or i < 0 or i >= len(a):
            return None
        v = a[i]
        return None if v != v else float(v)

    def cap_rank(self, i: int):
        """
        Where this symbol's size ranked among the day's universe, 0..1.

        Relative and not absolute on purpose: the median market cap in this
        database runs about 10 trillion VND in 2015 and 50 trillion in 2026, so
        a fixed threshold would be measuring the calendar rather than the
        company. A percentile means the same thing in both years, and the
        universe always has candidates at every level.
        """
        if self.cap_pct is None:
            return None
        v = self.cap_pct[i]
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

    def pe_stat(self, name: str, window: int, i: int):
        """One of pe_p25 / pe_median / pe_p75 / pe_mean."""
        s = self.stats.get(window)
        return None if s is None else s._at(getattr(s, name), i)

    def reference(self, kind: str, window: int, i: int):
        """One of 'median' / 'top' / 'bottom' / 'mean', chosen by name."""
        try:
            return getattr(self, kind)(window, i)
        except AttributeError:
            raise ValueError(f"unknown reference {kind!r}")


# ── Loading ───────────────────────────────────────────────────────────────────

_STATS_SCALE = 1000.0    # range_stats is stored at price * 1000; see the module docstring


def load_symbol(symbol: str, windows, min_rows: int = 0, slope_windows=()
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
    caps = _load_caps(symbol)
    df = df.merge(caps, on="date", how="left")
    # Forward-filled because a P/E is only recomputed when a new quarterly report
    # lands; between reports the last one is still the best available reading.
    # A stretch with no P/E at all — a company loss-making over a trailing year —
    # stays NaN before the first report and is carried afterwards, which is a
    # known wart of the shared pipeline rather than something invented here.
    df["pe_ratio"] = df["pe_ratio"].ffill()
    # Market cap comes from the same daily table as P/E and has the same gaps;
    # carried forward for the same reason.
    df["market_cap"] = df["market_cap"].ffill()

    dates = [pd.Timestamp(d) for d in df["date"]]
    series = SymbolSeries(
        symbol=symbol,
        dates=dates,
        closes=df["close"].to_numpy(dtype=float),
        pes=df["pe_ratio"].to_numpy(dtype=float),
        caps=df["market_cap"].to_numpy(dtype=float),
        row_of={d: i for i, d in enumerate(dates)},
        warmup=max(windows) - 1,
        is_index=_is_index(symbol),
    )

    stats = _load_window_stats(symbol, windows, {str(d.date()): i
                                                 for i, d in enumerate(dates)},
                               len(dates))
    missing = [w for w in windows if w not in stats]
    if missing:
        return None, f"no range_stats for window(s) {missing}"
    series.stats = stats

    # Trend signals, only for windows a rule actually reads. The table holds
    # ~1500 windows per symbol and millions of rows; asking for all of them
    # would cost more than the whole backtest.
    #
    # NOT allowed to move `warmup`. single/symbol_data.py pushes the start index
    # out until every signal exists, because there a missing gate silently stops
    # filtering. Here a missing slope is handled explicitly by the rule that
    # reads it — see rules.SlopeBelowRule — so the price warmup stays the only
    # thing that decides where the run begins, and the universe does not shrink
    # because one signal started late.
    for w in sorted({int(x) for x in slope_windows}):
        arr = np.full(len(dates), np.nan)
        row_of_str = {str(d.date()): i for i, d in enumerate(dates)}
        with sqlite3.connect(DB_PATH) as con:
            for date, v in con.execute(
                    "SELECT date, signal1_slope FROM trend_signals "
                    "WHERE symbol = ? AND window_days = ?", (symbol, w)):
                i = row_of_str.get(date)
                if i is not None and v is not None:
                    arr[i] = v
        series.slopes[w] = arr

    if len(series) - series.warmup <= 0:
        return None, f"nothing left after {series.warmup} bars of warmup"
    return series, None


def _load_prices(symbol: str) -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as con:
        return pd.read_sql(
            "SELECT date, close FROM daily_prices WHERE symbol = ? ORDER BY date",
            con, params=(symbol,))


def _is_index(symbol: str) -> bool:
    with sqlite3.connect(DB_PATH) as con:
        row = con.execute("SELECT symbol_type FROM symbols WHERE symbol = ?",
                          (symbol,)).fetchone()
    return bool(row) and row[0] == "index"


def _load_caps(symbol: str) -> pd.DataFrame:
    """
    Daily market capitalisation, price x shares, already computed by the shared
    pipeline and stored beside the P/E it was needed for.

    Inherits that pipeline's quarter-end stamping of the share count, so a
    change in shares is visible from the quarter end rather than from its
    announcement. Much milder than the same issue on earnings — a share count
    moves slowly and is announced ahead of time, where a profit figure is a
    surprise — but it is the same mechanism and worth knowing about.
    """
    with sqlite3.connect(DB_PATH) as con:
        return pd.read_sql(
            "SELECT date, total_market_cap AS market_cap FROM pe_ratios "
            "WHERE symbol = ? ORDER BY date", con, params=(symbol,))


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
           f"p25, p75, pe_p25, pe_median, pe_p75, pe_avg "
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
            pe_p25=np.full(n_rows, np.nan),
            pe_median=np.full(n_rows, np.nan),
            pe_p75=np.full(n_rows, np.nan),
            pe_mean=np.full(n_rows, np.nan),
        )

    seen = set()
    with sqlite3.connect(DB_PATH) as con:
        for (rd, date, median, top, bottom, mean, p25, p75,
             pe25, pemed, pe75, peavg) in con.execute(sql, (symbol, *windows)):
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
            # P/E is a ratio, not a price — it is NOT stored at the x1000 scale
            # and must not be divided.
            if pe25 is not None:
                ws.pe_p25[i] = pe25
            if pemed is not None:
                ws.pe_median[i] = pemed
            if pe75 is not None:
                ws.pe_p75[i] = pe75
            if peavg is not None:
                ws.pe_mean[i] = peavg
            seen.add(rd)

    return {w: ws for w, ws in out.items() if w in seen}
