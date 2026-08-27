"""
One breadth signal, dressed as a SymbolSeries.

WHY BOTHER

  core/rules.py already knows how to ask "is this below its own median over N
  bars", how to combine conditions with AND and OR, how to report what windows it
  needs and how to describe itself in a sentence. None of that is about prices --
  a Rule takes `series` and `index` and never asks what the numbers mean.

  So rather than writing a second, parallel vocabulary for breadth, the signal is
  given the handful of accessors a Rule reaches for. PremiumBelowRule then works
  unchanged on "share of the basket under its median", and the sentence it prints
  is still true.

  The alternative was a second rules.py with the same shapes and a different
  spelling, which is how two halves of a project start disagreeing about what
  AND means.

TWO READINGS, BOTH AVAILABLE

  ABSOLUTE   ValueAboveRule(0.6) -- "sixty percent of the basket is cheap". The
             natural way to talk about breadth, because the number already has a
             meaning of its own.

  RELATIVE   PremiumBelowRule(window=250, max_premium=-10) -- "breadth is more
             than 10% under its own year". Useful where a signal has no natural
             level, like dispersion, or where the level drifts across a decade.

WARMUP

  max(windows) - 1, matching core.data: the rolling statistics are built with
  min_periods=1, so a value exists from row zero and is meaningless until the
  window has filled. The engine refuses to act before it.
"""

import numpy as np
import pandas as pd


class SignalSeries:
    """
    Read-only view of one signal, with the accessors a Rule uses.

    Rolling statistics are computed lazily and cached per window: a plan usually
    reads one or two windows, and computing all of them up front would be work
    thrown away.
    """

    def __init__(self, name: str, values: np.ndarray, dates: list,
                 counts: np.ndarray = None, warmup: int = 0):
        self.symbol = name
        self.name = name
        self.dates = dates
        self.closes = np.asarray(values, dtype=float)
        self.counts = counts
        self.warmup = warmup
        self.is_index = False
        self.row_of = {d: i for i, d in enumerate(dates)}
        self._stats: dict = {}

    def __len__(self) -> int:
        return len(self.closes)

    # ── the accessors a Rule reaches for ────────────────────────────────────

    def close(self, i: int):
        v = self.closes[i]
        return None if v != v else float(v)

    def pe(self, i: int):
        # Breadth has no P/E. Returning None makes a use_pe rule decline rather
        # than compare against something invented.
        return None

    def cap(self, i: int):
        return None

    def cap_rank(self, i: int):
        return None

    def slope(self, window: int, i: int):
        """
        Regression slope of the signal itself over `window` bars, percent of the
        signal's own scale per bar.

        Not the same quantity as a price slope and deliberately so: `mean_slope`
        already carries the market's momentum, and this answers whether the
        BREADTH is improving, which is a different question.
        """
        a = self._slope_array(window)
        if i < 0 or i >= len(a):
            return None
        v = a[i]
        return None if v != v else float(v)

    def reference(self, kind: str, window: int, i: int):
        st = self._stat(window)
        arr = st.get(kind)
        if arr is None:
            return None
        v = arr[i]
        return None if v != v else float(v)

    def median(self, window: int, i: int):
        return self.reference("median", window, i)

    def mean(self, window: int, i: int):
        return self.reference("mean", window, i)

    def support(self, i: int):
        """How many symbols the day's value rests on. See signals.py on `n`."""
        if self.counts is None:
            return None
        v = self.counts[i]
        return None if v != v else float(v)

    # ── rolling statistics ──────────────────────────────────────────────────

    def _stat(self, window: int) -> dict:
        st = self._stats.get(window)
        if st is None:
            s = pd.Series(self.closes)
            # min_periods=1 to match core.data.load_range_stats. A value
            # therefore exists before the window has filled, and warmup -- not
            # NaN -- is what keeps a rule from reading it.
            r = s.rolling(window, min_periods=1)
            st = {
                "median": r.median().to_numpy(),
                "mean": r.mean().to_numpy(),
                "top": r.max().to_numpy(),
                "bottom": r.min().to_numpy(),
                "p25": r.quantile(0.25).to_numpy(),
                "p75": r.quantile(0.75).to_numpy(),
            }
            self._stats[window] = st
        return st

    def _slope_array(self, window: int) -> np.ndarray:
        key = ("slope", window)
        a = self._stats.get(key)
        if a is None:
            s = pd.Series(self.closes)
            x = np.arange(window, dtype=float)
            x -= x.mean()
            denom = (x * x).sum() or 1.0

            def fit(w):
                y = np.asarray(w, dtype=float)
                if np.isnan(y).any():
                    return np.nan
                return float((x * (y - y.mean())).sum() / denom)

            a = s.rolling(window, min_periods=window).apply(fit, raw=True).to_numpy()
            self._stats[key] = a
        return a


def build(breadth, name: str, windows) -> SignalSeries:
    """SignalSeries for `name`, with warmup set from the windows a plan reads."""
    warmup = max(windows) - 1 if windows else 0
    return SignalSeries(name, breadth.values[name], breadth.dates,
                        counts=breadth.counts, warmup=warmup)
