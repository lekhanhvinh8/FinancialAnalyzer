"""
The basket, reduced to one series per day.

THE INVERSION THAT MAKES THIS A DIFFERENT METHOD

  portfolio/ treats the other fifty-three symbols as COMPETITORS: they are the
  list the money is divided between, and a cross-sectional number like size rank
  exists to order them.

  Here they are EVIDENCE. Nothing in the basket is ever bought. The question is
  what the basket says about the market on a given day, and the answer is spent
  on one instrument -- the index -- so the decision is about timing, not about
  selection.

  Same data, opposite role. That is why this could not be a parameter of the
  other engine.

WHY THIS SIDESTEPS WHAT CLOSED portfolio/

  That strand stopped because the database cannot identify a good company; market
  cap was standing in for quality and is not free-float adjusted. Breadth needs
  neither. It COUNTS symbols rather than weighting them, so free float does not
  enter, and it never has to decide whether a company is good -- only whether the
  market as a whole is cheap or extended.

  The weakness moves rather than disappearing. Fifty-four symbols gave
  fifty-four observations; one instrument over 137 months gives perhaps a dozen
  independent cycles. Everything measured here overfits far more easily than
  anything measured there, and a difference of a few points means nothing.

WHAT IS COMPUTED

  One pass over the calendar after the Market is loaded, the same shape as
  market.py's cap ranking. Every signal is a plain count or quantile over the
  symbols ELIGIBLE that day -- past warmup, with a bar -- and indices are
  excluded throughout, because an aggregate is not a member of the basket it
  aggregates.

    below_pct     share of the basket trading under its own median      0..1
    median_prem   the median distance from median, in percent           %
    p25_prem      the cheap quartile, for how far the tail has gone     %
    slope_pos     share with positive short-window momentum             0..1
    mean_slope    average momentum, percent per day                     %
    spread        p75 minus p25 of premium: agreement or dispersion     %
    median_zdev   the basket's cheapness in units of its own sigma      sigma
    spread_zdev   p75 minus p25 of z_dev: falling together, or rotating sigma
    median_sharpe median signal3_sharpe: momentum divided by volatility
    sharpe_pos    share of the basket with positive sharpe                0..1
    n             how many symbols the day's figures rest on            count

  `n` is not decoration. Early in the run only a handful of symbols are past
  warmup, and a percentage over six symbols is not the same measurement as one
  over fifty. MIN_SYMBOLS in the config refuses to trade on a thin day.
"""

from dataclasses import dataclass, field

import numpy as np


SIGNALS = ("below_pct", "median_prem", "p25_prem", "slope_pos", "mean_slope",
           "spread", "median_zdev", "spread_zdev",
           "median_sharpe", "sharpe_pos")


@dataclass
class BreadthSeries:
    """
    One value per calendar day per signal, plus the count behind each day.

    Deliberately shaped like core.data.SymbolSeries -- `dates`, `row_of`, arrays
    indexed by row -- so that `as_series()` can hand any signal to the existing
    rules without either side knowing about the other. See as_series().
    """
    dates: list
    values: dict                       # name -> np.ndarray, NaN where unknown
    counts: np.ndarray                 # symbols behind each day
    row_of: dict = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.dates)

    def at(self, name: str, i: int):
        v = self.values[name][i]
        return None if v != v else float(v)


def _zdev_per_symbol(market, window: int, stat_window: int) -> dict:
    """
    z_dev for every symbol: how many of its OWN sigmas the price sits from its
    own median.

    WHY NOT JUST AVERAGE dev. A percentage from median is not comparable across
    symbols -- a volatile name is routinely 40% below its median, a stable one
    rarely 15% -- so a median of raw dev mixes two scales. Dividing by each
    symbol's own sigma puts them on one.
    """
    import pandas as pd

    out = {}
    for sym in market.symbols:
        series = market[sym]
        if series.is_index:
            continue
        n = len(series)
        dev = np.full(n, np.nan)
        for i in range(n):
            med = series.median(window, i)
            if med:
                dev[i] = (series.closes[i] - med) / med
        r = pd.Series(dev).rolling(stat_window, min_periods=stat_window)
        z = (dev - r.mean().to_numpy()) / r.std().to_numpy()
        out[sym] = z
    return out


def compute(market, window: int, slope_window: int,
            zdev_stat_window: int = 250) -> BreadthSeries:
    """Walk the calendar once and reduce each day to a handful of numbers."""
    zdev = _zdev_per_symbol(market, window, zdev_stat_window)

    dates, counts = [], []
    cols = {k: [] for k in SIGNALS}

    def push(key, values, fn):
        cols[key].append(fn(values) if len(values) else np.nan)

    for day in market.days():
        prem, slopes, zs, sh = [], [], [], []
        for symbol, bar in day.bars.items():
            series = market[symbol]
            if series.is_index:
                continue
            med = series.median(window, bar.index)
            if med:
                prem.append((bar.price - med) / med * 100.0)
            sl = series.slope(slope_window, bar.index)
            if sl is not None:
                slopes.append(sl)
            s3 = series.sharpe(slope_window, bar.index)
            if s3 is not None:
                sh.append(s3)
            z = zdev.get(symbol)
            if z is not None and bar.index < len(z) and z[bar.index] == z[bar.index]:
                zs.append(float(z[bar.index]))

        dates.append(day.date)
        counts.append(len(prem))

        a = np.asarray(prem)
        push("below_pct", a, lambda v: float((v < 0).mean()))
        push("median_prem", a, lambda v: float(np.median(v)))
        push("p25_prem", a, lambda v: float(np.percentile(v, 25)))
        push("spread", a, lambda v: float(np.percentile(v, 75) - np.percentile(v, 25)))

        b = np.asarray(slopes)
        push("slope_pos", b, lambda v: float((v > 0).mean()))
        push("mean_slope", b, lambda v: float(v.mean()))

        d = np.asarray(sh)
        push("median_sharpe", d, lambda v: float(np.median(v)))
        push("sharpe_pos", d, lambda v: float((v > 0).mean()))

        c = np.asarray(zs)
        push("median_zdev", c, lambda v: float(np.median(v)))
        push("spread_zdev", c,
             lambda v: float(np.percentile(v, 75) - np.percentile(v, 25)))

    return BreadthSeries(
        dates=dates,
        values={k: np.asarray(v, dtype=float) for k, v in cols.items()},
        counts=np.asarray(counts, dtype=float),
        row_of={d: i for i, d in enumerate(dates)},
    )


# ── cache ────────────────────────────────────────────────────────────────────
#
# Computing breadth takes about a second. LOADING the market it is computed from
# takes eight minutes, and calibrating a threshold means looking at the same
# series a dozen times. Saving the reduced series turns that into an instant
# loop, and it is safe to cache precisely because it is a pure function of the
# market and the two windows -- both of which go in the filename.

import numpy as _np
from pathlib import Path as _Path


def cache_path(universe, window: int, slope_window: int) -> _Path:
    tag = universe if isinstance(universe, str) else "list"
    return (_Path(__file__).resolve().parent / "cache"
            / f"breadth_{tag}_{window}_{slope_window}.npz")


def save(breadth: BreadthSeries, path) -> None:
    path = _Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _np.savez_compressed(
        path,
        dates=_np.array([str(d)[:10] for d in breadth.dates]),
        counts=breadth.counts,
        **{f"v_{k}": v for k, v in breadth.values.items()},
    )


def load(path):
    """The cached series, or None if it is not there. Never raises on a miss."""
    path = _Path(path)
    if not path.exists():
        return None
    z = _np.load(path, allow_pickle=False)
    import pandas as _pd
    dates = [_pd.Timestamp(str(d)) for d in z["dates"]]
    values = {k[2:]: z[k] for k in z.files if k.startswith("v_")}
    return BreadthSeries(dates=dates, values=values, counts=z["counts"],
                         row_of={d: i for i, d in enumerate(dates)})
