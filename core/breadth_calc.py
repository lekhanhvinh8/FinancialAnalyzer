"""
The basket, reduced to one series per day.

WHY THIS IS IN core/ AND NOT IN breadth/

  It computes a number from prices; it decides nothing. Three consumers read it
  now -- breadth/ trades on it, single/multi_signal/ gates on it, and syncs/
  keeps it current -- and the data layer is not allowed to import a method, so
  a calculation that syncs/ must call cannot live inside one.

  range_calc.py and zdev_calc.py moved out of single/ for exactly this reason
  and the same mistake was repeated here: this file sat in breadth/ while the
  table it fills went unsynced, because the sync could not legally reach it.


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
    prem_median   the median distance from median, in percent           %
    p25_prem      the cheap quartile, for how far the tail has gone     %
    prem_q5..q95  the whole shape, every 5%                             %
    spread        p75 minus p25 of premium: agreement or dispersion     %
    prem_mean     plain mean premium, nothing dropped                   %
    prem_mean_cap the same, weighted by market cap                      %
    prem_trim     mean premium after dropping the 5% tails at each end  %
    prem_trim_sd  its standard deviation, over the same trimmed set     %
    prem_trim_cap the same trimmed mean, weighted by market cap         %
    mean_slope    average momentum, percent per day                     %
    n             how many symbols the day's figures rest on            count

  prem_trim reads one vote per symbol, prem_trim_cap one vote per dong. They part
  company exactly when the large caps and the ordinary listings disagree.

  Five more signals lived here and were deleted: slope_pos, median_zdev,
  spread_zdev, median_sharpe and sharpe_pos. Each was measured against DCA, none
  beat it, and none was ever read again -- the numbers are kept in
  breadth/config.py so the deletion is a record rather than a loss.

  `n` is not decoration. Early in the run only a handful of symbols are past
  warmup, and a percentage over six symbols is not the same measurement as one
  over fifty. MIN_SYMBOLS in the config refuses to trade on a thin day.
"""

from dataclasses import dataclass, field

import numpy as np


# Premium quantiles, every 5%. Storing the whole shape rather than one summary
# is what lets a rule name BOTH parameters of the sentence "F of the basket is
# at least T% above its median": F picks the quantile, T is the threshold.
#
#   F of the basket >= T   <=>   quantile(1 - F) >= T
#
# So F = 0.5 reads prem_q50, F = 0.25 reads prem_q75, F = 0.75 reads prem_q25.
PREM_QS = tuple(range(5, 100, 5))

# Tails dropped before the trimmed mean.
TRIM_LOW, TRIM_HIGH = 5, 95

# mean_slope is COMPUTED BUT NEVER STORED: breadth/strategy.py reads it from the
# series in hand, and nothing has ever read it back from the database. Storing it
# is what kept a "slope120" variant alive in a store where nothing addressed it.
# NAMES SAY WHAT THE NUMBER IS: prem_<how it is aggregated>[_cap if weighted].
#
#   prem_median     the median. Ignores magnitude entirely.
#   prem_mean       the plain mean. Every symbol counts, tails included.
#   prem_mean_cap   the plain mean, weighted by market cap.
#   prem_trim       the mean after dropping the 5% tails at each end.
#   prem_trim_cap   that, weighted by market cap.
#   prem_trim_sd    the standard deviation over the same trimmed set.
#
# THE OLD NAMES HID THE TRIM. "prem_cap" said nothing about being trimmed, so a
# reader asking why VIC was missing from it had to read this file to find out --
# the trim drops VIC at +702% and the name gave no hint. "median_prem" put the
# statistic first while every other name put it last. Both are fixed here; the
# stored rows were renamed with them.
SIGNALS = (("below_pct", "p25_prem", "mean_slope", "spread")
           + tuple(f"prem_q{q}" for q in PREM_QS)
           + ("prem_median", "prem_mean", "prem_mean_cap",
              "prem_trim", "prem_trim_sd", "prem_trim_cap"))


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



def _cap_weighted(prem, caps, trim_mask) -> float:
    """
    Trimmed, cap-weighted mean premium. NaN when nothing survives.

    Kept out of `push` because it needs two aligned arrays, and widening push to
    take a second one would complicate the twenty callers that do not.
    """
    if not len(prem):
        return np.nan
    m = trim_mask(prem) & ~np.isnan(caps)
    if not m.any() or caps[m].sum() <= 0:
        return np.nan
    return float((prem[m] * caps[m]).sum() / caps[m].sum())


def universe_key(spec: str, exclude=()) -> str:
    """
    The name a basket is stored under, built from what the basket IS.

    "all" means every stock. A basket that drops names says so:

        universe_key("all")                  -> "all"
        universe_key("all", ["VIC", "VIX"])  -> "all-VIC-VIX"

    NAMED THIS WAY AFTER THE OLD NAME LIED. Rows computed over 54 symbols, with
    VIC and VIX deliberately removed, were stored under "all" -- so a reader
    asking the database for the market got a basket missing two of the largest
    companies on it, with nothing in the name to say so. Excluded symbols are
    sorted, so the same basket always produces the same key.
    """
    if not exclude:
        return spec
    return spec + "".join("-" + s.upper() for s in sorted(set(exclude)))


def compute(market, window: int, slope_window: int, skip=()) -> BreadthSeries:
    """
    Walk the calendar once and reduce each day to a handful of numbers.

    `skip` leaves symbols out of the basket without leaving them out of the
    LOAD, so two baskets that differ by a few names cost one load and two
    walks -- the load is four minutes, the walk twelve seconds.
    """
    skip = {s.upper() for s in skip}

    dates, counts = [], []
    cols = {k: [] for k in SIGNALS}

    def push(key, values, fn):
        cols[key].append(fn(values) if len(values) else np.nan)

    for day in market.days():
        prem, slopes, caps = [], [], []
        for symbol, bar in day.bars.items():
            if symbol.upper() in skip:
                continue
            series = market[symbol]
            if series.is_index:
                continue
            med = series.median(window, bar.index)
            if med:
                prem.append((bar.price - med) / med * 100.0)
                # Appended in the SAME branch, so caps[i] is the cap of the
                # symbol behind prem[i]. NaN for a symbol with no cap reading:
                # dropping it here would shift the alignment.
                c = series.cap(bar.index)
                caps.append(c if c and c > 0 else np.nan)
            sl = series.slope(slope_window, bar.index)
            if sl is not None:
                slopes.append(sl)

        dates.append(day.date)
        counts.append(len(prem))

        a = np.asarray(prem)
        push("below_pct", a, lambda v: float((v < 0).mean()))
        push("prem_median", a, lambda v: float(np.median(v)))
        push("p25_prem", a, lambda v: float(np.percentile(v, 25)))
        push("spread", a, lambda v: float(np.percentile(v, 75) - np.percentile(v, 25)))
        for q in PREM_QS:
            push(f"prem_q{q}", a, lambda v, q=q: float(np.percentile(v, q)))

        # Trimmed mean: drop the 5% most extreme at each end, then average.
        # A plain mean is dragged by a handful of names that ran 300% or
        # collapsed; the median ignores magnitude entirely. Trimming keeps the
        # magnitude of the ordinary 90% and discards only the tails.
        def _no_trim(v):
            """Keeps everything -- the untrimmed lines reuse _cap_weighted."""
            return np.ones(len(v), dtype=bool)

        def _trim_mask(v):
            lo, hi = np.percentile(v, [TRIM_LOW, TRIM_HIGH])
            m = (v >= lo) & (v <= hi)
            return m if m.any() else np.ones(len(v), dtype=bool)

        def _trim(v):
            return v[_trim_mask(v)]
        push("prem_trim", a, lambda v: float(_trim(v).mean()))
        push("prem_trim_sd", a, lambda v: float(_trim(v).std()))

        # CAP-WEIGHTED, same tails dropped. prem_trim gives PVD the same vote as
        # VCB; this one asks what the money in the market is doing rather than
        # what the average listing is doing. Read the two together: they part
        # company exactly when the big names and the small ones disagree, which
        # is the reading neither line can give alone.
        #
        # Raw cap as the weight, not sqrt or log. The point is to say what the
        # index-sized money sees, and that is what raw cap means; softening it
        # would produce a third thing that is neither this nor prem_trim.
        #
        # Trimmed on PREM, exactly as prem_trim is -- the tails being dropped are
        # extreme moves, not extreme sizes. A symbol with no cap reading drops
        # out of this signal only; it still counts in every other one.
        w = np.asarray(caps)
        cols["prem_trim_cap"].append(_cap_weighted(a, w, _trim_mask))

        # THE SAME TWO LINES WITHOUT THE TRIM, so the trim's effect can be read
        # off rather than argued about. On a day when one symbol is 700% above
        # its median, prem_mean and prem_trim are far apart and the gap IS the
        # answer to "how much is this basket being carried by its extremes".
        #
        # Both are cheap -- the premiums are already in hand -- and having them
        # stored means a question about the trim never needs a rerun.
        cols["prem_mean"].append(float(a.mean()) if len(a) else np.nan)
        cols["prem_mean_cap"].append(_cap_weighted(a, w, _no_trim))

        b = np.asarray(slopes)
        push("mean_slope", b, lambda v: float(v.mean()))

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


def fingerprint(symbols, window: int) -> str:
    """
    A hash of every input a breadth run reads: the window, and each symbol's
    close series.

    ONE RULE FOR TWO CACHES. The database copy and the npz copy go stale for
    exactly the same reasons, so they ask the same question:

        a series was revised   -> that symbol's hash changes
        a series grew          -> that symbol's hash changes
        the universe changed   -> the list of names changes

    Symbols are sorted, so the same universe in a different order hashes the
    same; each name is hashed with its series, so two symbols swapping histories
    cannot cancel out.
    """
    import hashlib
    import database as db
    h = hashlib.sha256()
    h.update(f"w{window}|".encode())
    for sym in sorted(symbols):
        closes = db.load_daily_prices(sym)
        arr = (closes["close"].to_numpy(dtype=float) if not closes.empty
               else _np.empty(0))
        h.update(sym.encode())
        h.update(hashlib.sha256(arr.tobytes()).digest())
    return h.hexdigest()


def cache_path(base, universe, window: int, slope_window) -> _Path:
    """
    Where a run may cache its computed series.

    `base` is the caller's directory, passed in rather than derived from
    __file__: this module lives in core/ now, and a cache is a convenience of
    the thing doing the running, not of the calculation.
    """
    tag = universe if isinstance(universe, str) else "list"
    return _Path(base) / "cache" / f"breadth_{tag}_{window}_{slope_window}.npz"


def save(breadth: BreadthSeries, path, fp: str = "") -> None:
    """`fp` is the fingerprint of the inputs, stored so load() can check it."""
    path = _Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _np.savez_compressed(
        path,
        dates=_np.array([str(d)[:10] for d in breadth.dates]),
        counts=breadth.counts,
        fingerprint=_np.array([fp]),
        **{f"v_{k}": v for k, v in breadth.values.items()},
    )


def load(path, fp: str = None):
    """
    The cached series, or None if it is not there. Never raises on a miss.

    A STALE CACHE IS A MISS. Pass `fp` (from fingerprint()) and a cache built
    from different prices is refused. Without that check a run kept using a
    cache sixteen trading days behind the price table and reported success --
    the same failure the database copy had, from the same cause.

    A CACHE MISSING A SIGNAL IS A MISS, not a partial hit. Adding a signal
    (prem_trim_cap, then called prem_cap) left a cache on disk that predated it, and the run reused that cache,
    reported "2829 ngay (cache)" and stored everything EXCEPT the new signal --
    silently, because nothing compared what was asked for with what came back.
    Recomputing costs a few minutes; a silently absent signal costs an
    investigation.
    """
    path = _Path(path)
    if not path.exists():
        return None
    z = _np.load(path, allow_pickle=False)
    import pandas as _pd
    dates = [_pd.Timestamp(str(d)) for d in z["dates"]]
    values = {k[2:]: z[k] for k in z.files if k.startswith("v_")}
    missing = [k for k in SIGNALS if k not in values]
    if missing:
        print(f"  [cache] bo qua {path.name}: thieu {', '.join(missing)}")
        return None
    if fp is not None:
        stored = str(z["fingerprint"][0]) if "fingerprint" in z.files else ""
        if stored != fp:
            why = "khong co van tay" if not stored else "du lieu gia da doi"
            print(f"  [cache] bo qua {path.name}: {why}")
            return None
    return BreadthSeries(dates=dates, values=values, counts=z["counts"],
                         row_of={d: i for i, d in enumerate(dates)})


# WHICH PARAMETERS EACH SIGNAL ACTUALLY USES
#
# The variant string used to name the whole BATCH: every signal computed in one
# call got "trim5-95_slope120_zdev250", including prem_median (then called
# median_prem), which reads none
# of those three. That is a lie a reader cannot check -- it says the decision
# line depends on a 120-bar slope when it depends only on window_days -- and it
# forced a pointless rewrite of 2829 identical rows every time an unrelated
# parameter moved.
#
# A signal is now named by what it reads, and nothing else.
_TRIM  = ("prem_trim", "prem_trim_sd", "prem_trim_cap")
# COMPUTED BUT NOT STORED. breadth/strategy.py reads mean_slope from the series
# in hand; nothing has ever read it back from the database.
_NOT_STORED = ("mean_slope",)

STORED = tuple(x for x in SIGNALS if x not in _NOT_STORED)


def variant(signal: str) -> str:
    """
    The settings that change THIS signal, other than window_days.

    "base" for a signal that reads only the premium and the window: prem_median,
    prem_mean, prem_mean_cap, the quantiles, below_pct, spread, p25_prem. Not the
    empty string, because the variant is part of a primary key and an empty key
    segment is a trap.

    Takes no window arguments any more. It took a slope window and a z_dev window
    while signals keyed on those existed; after they were deleted the parameters
    stayed behind, addressing nothing, in three config files.
    """
    return f"trim{TRIM_LOW}-{TRIM_HIGH}" if signal in _TRIM else "base"


def save_to_db(breadth: BreadthSeries, universe: str, window: int,
               override: bool = True) -> dict:
    """
    Write each STORED signal under its own variant. Rows written per variant.

    override=False only inserts dates that are not there yet, which is wrong for
    a rebuild -- a changed input can move any row, not only the new ones -- so
    the sync passes True explicitly rather than relying on the default.
    """
    import database as db
    groups = {}
    for name, series in breadth.values.items():
        if name not in STORED:
            continue
        groups.setdefault(variant(name), {})[name] = series
    out = {}
    for v, vals in sorted(groups.items()):
        r = db.save_breadth(universe, window, v, breadth.dates, vals,
                            breadth.counts, override=override)
        out[v] = r
    return out


def load_from_db(universe: str, window: int):
    """
    A stored run as a BreadthSeries, or None if nothing was stored for it.

    Reassembles the variants a run is spread across; one never written simply
    contributes no columns, so a partial store reads back as the signals it has
    rather than as nothing. mean_slope is not among them -- it is never stored.
    """
    import database as db
    import pandas as pd
    wanted = {variant(n) for n in STORED}
    frames = [f for f in (db.load_breadth(universe, window, v) for v in sorted(wanted))
              if not f.empty]
    if not frames:
        return None
    df = pd.concat(frames, axis=1)
    df = df.loc[:, ~df.columns.duplicated()]      # n_symbols is in every frame
    dates = list(df.index)
    counts = df["n_symbols"].to_numpy(dtype=float)
    values = {c: df[c].to_numpy(dtype=float) for c in df.columns if c != "n_symbols"}
    return BreadthSeries(dates=dates, values=values, counts=counts,
                         row_of={d: i for i, d in enumerate(dates)})
