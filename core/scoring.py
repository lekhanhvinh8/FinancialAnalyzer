"""
Ordering: of the symbols a rule admitted today, which deserve the money first?

This question does not exist for a single-symbol method — with one candidate
there is nothing to order — which is why it is a piece of this package and not of
any strategy. It is also not one fixed rule. Cheapest against its own median is
the obvious first answer; deepest drawdown, strongest momentum and cheapest P/E
against its own history are all real alternatives, and which one wins is
something to measure. Keeping the scorer a separate object is what makes trying
another one a config change.

    scorer(series, index) -> float,  HIGHER IS BETTER.

WHEN THE SCORE DOES NOTHING

  With allocator.top_k = None the money is split equally over the entire
  candidate list, so first and last receive the same amount and the order changes
  nothing at all. The score only starts doing work once there is a cutoff. That
  is a property of the allocator, not a fault in the scorer — see allocator.py.

WHY THE SCORE SHOULD MATCH THE RULE

  Each scorer below measures the same quantity its arm's rule thresholds against.
  If the two disagreed, the allocator could prefer a symbol the rule barely
  admitted over one it admitted comfortably — the ordering would be arguing with
  the condition instead of refining it.
"""

from dataclasses import dataclass

from .rules import premium


class Scorer:
    """Base: every candidate ties. Order then falls to the tie-break on symbol."""

    def __call__(self, series, index: int) -> float:
        return 0.0

    def windows(self) -> set:
        return set()

    def describe(self) -> str:
        return "none"


class NullScorer(Scorer):
    """
    Explicitly no opinion.

    The right scorer for the equal-weight DCA baseline, where every eligible
    symbol is equally deserving by definition. Giving the baseline an ordering
    would quietly turn it into a second strategy.
    """


@dataclass
class PremiumScorer(Scorer):
    """
    Rank by distance from a rolling reference, in percent.

        cheapest_first=True   most BELOW the reference first   (buy, reinvest)
        cheapest_first=False  most ABOVE the reference first   (sell)

    COMPARABLE ACROSS SYMBOLS, NOT ACROSS WINDOWS

      It is a percentage of each symbol's own reference, so a 75,000 VND stock
      and a 2,000 VND one land on a single scale — which is the only reason a
      portfolio can rank them at all.

      It is not comparable across window sizes: how far a price typically strays
      from its own median widens as the window grows. Every symbol in one run
      shares one window, so within a run the comparison holds.

    Returns 0.0 when the reference is missing. Unreachable for a real candidate —
    the rule has already refused rows inside warmup — and scoring a hypothetical
    one as merely neutral is the safe reading.
    """
    window: int = 1000
    reference: str = "median"
    cheapest_first: bool = True
    use_pe: bool = False

    def __call__(self, series, index: int) -> float:
        current = series.pe(index) if self.use_pe else series.close(index)
        if current is None:
            return 0.0
        p = premium(current, series.reference(self.reference, self.window, index))
        if p is None:
            return 0.0
        return -p if self.cheapest_first else p

    def windows(self) -> set:
        return {self.window}

    def describe(self) -> str:
        direction = "cheapest" if self.cheapest_first else "dearest"
        return f"{direction} vs {self.reference}[{self.window}]"


@dataclass
class DrawdownScorer(Scorer):
    """
    Rank by how far the price has fallen from its own rolling HIGH — deepest
    first.

    Different from PremiumScorer against 'top' only in intent and sign handling,
    and worth its own name because it answers a different question. A symbol can
    sit well above its median and still be halfway down from its peak; those two
    orderings disagree precisely on the names that have spiked and are falling
    back, which is the interesting case for redeploying cash.
    """
    window: int = 1000
    use_pe: bool = False

    def __call__(self, series, index: int) -> float:
        current = series.pe(index) if self.use_pe else series.close(index)
        if current is None:
            return 0.0
        p = premium(current, series.top(self.window, index))
        if p is None:
            return 0.0
        # p <= 0 by construction; the deepest fall is the most negative, and it
        # should rank first, so negate.
        return -p

    def windows(self) -> set:
        return {self.window}

    def describe(self) -> str:
        return f"deepest drawdown vs top[{self.window}]"


@dataclass
class CapRankScorer(Scorer):
    """
    Rank by size within the day's universe: 0 for the smallest symbol trading,
    1 for the largest.

    largest_first=False flips it, which is worth having because the two
    directions are genuinely different bets — large is the benchmark's own tilt,
    small is where an equal-weighted basket gets its edge over a
    capitalisation-weighted index.

    Already a percentile, so it needs no normalising to sit beside another
    scorer in a blend. That is not true of PremiumScorer, whose units are
    percent-away-from-median; see BlendScorer.
    """
    largest_first: bool = True

    def __call__(self, series, index: int) -> float:
        r = series.cap_rank(index)
        if r is None:
            # Neither favoured nor punished. The filter, not the ranking, is
            # where a missing value should have consequences.
            return 0.5
        return r if self.largest_first else 1.0 - r

    def windows(self) -> set:
        return set()

    def describe(self) -> str:
        return "largest cap" if self.largest_first else "smallest cap"


@dataclass
class BlendScorer(Scorer):
    """
    Several scorers combined by weight.

    WHY THIS CANNOT BE A PLAIN WEIGHTED SUM

      The parts are in incompatible units. CapRankScorer returns a percentile in
      0..1; PremiumScorer returns a percentage away from a median, which on this
      universe spans roughly -70 to +10. Adding them with weights would let the
      premium term swamp the cap term by two orders of magnitude, and the weight
      would be describing the units rather than the intent.

      So the blend is over RANKS WITHIN THE DAY'S CANDIDATE LIST, not over raw
      values: each part scores every candidate, the candidates are ranked by that
      part, the ranks are scaled to 0..1, and those are averaged by weight. A
      weight of 0.5/0.5 then means what it looks like.

      That comparison needs the whole list, which a scorer never sees — so
      engine.rank() does the work. This class carries the parts and the weights
      and is never called directly; __call__ exists only to fail loudly if it is.
    """
    parts: list          # [(scorer, weight), ...]

    def __call__(self, series, index: int) -> float:
        raise NotImplementedError(
            "BlendScorer is resolved in engine.rank(), which is the only place "
            "that can see the whole candidate list. It must not be called per "
            "symbol.")

    def windows(self) -> set:
        out = set()
        for sc, _w in self.parts:
            out |= sc.windows()
        return out

    def describe(self) -> str:
        return " + ".join(f"{w:g}x {sc.describe()}" for sc, w in self.parts)
