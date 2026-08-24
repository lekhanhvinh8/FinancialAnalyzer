"""
One calendar across many symbols.

THE PROBLEM THIS SOLVES

  Every condition in this package is written against a ROW INDEX inside one
  symbol's own series, because that is how the rolling statistics are indexed.
  Two symbols listed years apart have entirely different row numbers on the same
  calendar date, so a portfolio loop cannot be a loop over row indices — it has
  to be a loop over DATES, translating into each symbol's own index on the way
  in. Market owns that translation and nothing else.

WHO TAKES PART ON A GIVEN DAY

  A symbol is eligible on a date when it has a bar there and that bar is at or
  past its own warmup. Warmup is per symbol, so the universe GROWS over the run
  as younger listings come of age.

  The run therefore starts on the first date ANY symbol is eligible, not the
  first date all of them are. Waiting for the youngest would throw away a decade
  of the oldest symbols' history, and "invest in whatever is listed and seasoned
  so far" is also what an investor actually does. The price is that the early
  years are a much narrower portfolio than the late ones — something a report
  must show rather than hide, since a concentrated early portfolio and a broad
  late one are not the same experiment.

MEMORY AND PARALLELISM

  Everything lives in one process, because the wallet is shared and cannot be
  split across workers. That is the opposite of how a per-symbol runner scales,
  and it means a parameter sweep must parallelise over CELLS while loading the
  universe once — loading dominates a run by orders of magnitude.
"""

from dataclasses import dataclass

from .data import load_symbol


@dataclass(frozen=True)
class Bar:
    """One symbol on one day, already known to be eligible."""
    symbol: str
    index: int
    price: float
    pe: "float | None"


@dataclass
class Day:
    date: object
    bars: dict          # symbol -> Bar, eligible symbols only

    def __len__(self) -> int:
        return len(self.bars)


class Market:
    def __init__(self, series: dict, skipped: dict):
        self.series: dict = series
        self.skipped: dict = skipped

        dates: set = set()
        for s in series.values():
            # Only dates the symbol can actually act on join the calendar. A date
            # where every symbol is still in warmup is a day nothing can happen,
            # and including it would only add empty iterations before the start.
            dates.update(d for d, i in s.row_of.items() if i >= s.warmup)
        self.calendar: list = sorted(dates)
        self._rank_caps()

    def _rank_caps(self):
        """
        Fill each  symbol's cap_pct: where its market cap stood among the symbols
        trading that day, 0 = smallest, 1 = largest.

        THIS IS THE ONE CROSS-SECTIONAL COMPUTATION IN THE PACKAGE.

        A Rule sees one symbol and cannot know how big the others are, so a
        relative size test has nowhere to live inside the rule interface. Rather
        than widen that interface — every rule would then have to be handed the
        universe it does not need — the comparison is done once here, while the
        whole universe is in hand, and the answer is written back into each
        symbol as a plain per-row array. Rules stay per-symbol and read
        series.cap_rank(i) like any other statistic.

        Recomputed per DAY rather than once, because membership changes: a
        symbol listing in 2018 shifts everyone else's rank from that day on.

        INDICES ARE EXCLUDED. VN30 is loaded and tradable, because the benchmark
        has to be buyable as a fallback, but its market cap is the SUM of thirty
        companies — it would take the top rank every single day and push every
        real stock down a place. A percentile is a comparison among peers, and an
        index is not a peer.
        """
        import numpy as np

        for s in self.series.values():
            s.cap_pct = np.full(len(s.closes), np.nan)

        for date in self.calendar:
            todays = []
            for sym, s in self.series.items():
                if s.is_index:
                    continue
                i = s.row_of.get(date)
                if i is None:
                    continue
                c = s.cap(i)
                if c is not None and c > 0:
                    todays.append((c, sym, i))
            if len(todays) < 2:
                continue
            todays.sort()
            last = len(todays) - 1
            for pos, (_c, sym, i) in enumerate(todays):
                self.series[sym].cap_pct[i] = pos / last

    @classmethod
    def load(cls, symbols, windows, min_rows: int = 0, on_symbol=None,
             slope_windows=()) -> "Market":
        """
        Load every symbol, dropping those that cannot be evaluated.

        `windows` is every window size the rules and scorers read; naming them
        keeps the loader from pulling ~1500 windows per symbol out of the table.

        Skips are collected rather than raised. In a basket of fifty names a few
        will always be too young or missing statistics, and that is a fact about
        the universe rather than an error in the run — but it is also something
        the caller must be able to report, so it is kept, not swallowed.
        """
        series, skipped = {}, {}
        for symbol in symbols:
            s, reason = load_symbol(symbol, windows, min_rows=min_rows,
                                    slope_windows=slope_windows)
            if s is None:
                skipped[symbol] = reason
            else:
                series[symbol] = s
            if on_symbol:
                on_symbol(symbol, s is not None, reason)

        if not series:
            raise ValueError(f"no symbol could be loaded; skips: {skipped}")
        return cls(series, skipped)

    # ── Iteration ─────────────────────────────────────────────────────────────

    def days(self):
        for date in self.calendar:
            bars = {}
            for symbol, s in self.series.items():
                i = s.row_of.get(date)
                if i is None or i < s.warmup:
                    continue
                bars[symbol] = Bar(symbol=symbol, index=i,
                                   price=s.close(i), pe=s.pe(i))
            yield Day(date=date, bars=bars)

    # ── Lookups ───────────────────────────────────────────────────────────────

    def __getitem__(self, symbol: str):
        return self.series[symbol]

    @property
    def symbols(self) -> list:
        return list(self.series)

    def final_prices(self) -> dict:
        """
        {symbol: its own last close}, for marking the book at the end.

        Each symbol's own last bar, which need not be the last calendar date: one
        that stopped reporting is marked at the last price it had rather than
        dropped from the valuation.
        """
        return {sym: s.close(len(s) - 1) for sym, s in self.series.items()}

    def summary(self) -> str:
        first, last = self.calendar[0], self.calendar[-1]
        out = (f"{len(self.series)} symbols | {len(self.calendar)} trading days | "
               f"{first.date()} -> {last.date()}")
        if self.skipped:
            out += f" | {len(self.skipped)} skipped"
        return out
