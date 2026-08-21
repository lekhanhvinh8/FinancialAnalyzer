from dataclasses import dataclass, field
from ..models import InvestmentTracker, DeltaToActionMatrix
from ..engine import Sellor


class SellStrategy:
    def considerSell(self, tracker: InvestmentTracker, index, close, pe, cal_range_close, isPrint):
        pass

    def check(self, index, close, pe, cal_range_close) -> bool:
        return False


@dataclass
class SellTopStrategy(SellStrategy):
    percentSell: float = 0

    def considerSell(self, tracker: InvestmentTracker, index, close, pe, cal_range_close, isPrint):
        if tracker.totalCurrentCapital > 0 and tracker.totalShare > 0:
            totalFinal      = tracker.totalShare * close
            increasePercent = (totalFinal - tracker.totalCurrentCapital) / tracker.totalCurrentCapital
            if increasePercent > self.percentSell / 100:
                Sellor().sell(tracker, totalFinal, index, close, isPrint)


@dataclass
class SellTopOfBottomStrategy(SellStrategy):
    percentSell: float = 0
    localRangeDays: int = 0
    use_pe: bool = False

    def considerSell(self, tracker: InvestmentTracker, index, close, pe, cal_range_close, isPrint):
        if tracker.totalCurrentCapital <= 0 or tracker.totalShare <= 0:
            return
        if self.check(index, close, pe, cal_range_close):
            Sellor().sell(tracker, tracker.totalShare * close, index, close, isPrint)

    def check(self, index, close, pe, cal_range_close) -> bool:
        current = pe if self.use_pe else close
        if current is None:
            return False
        if index not in cal_range_close or self.localRangeDays not in cal_range_close[index].rangeDayCloses:
            return False
        localBottom = cal_range_close[index].rangeDayCloses[self.localRangeDays].bottom(self.use_pe)
        return (current - localBottom) / localBottom > self.percentSell / 100


@dataclass
class SellPartialStrategy(SellStrategy):
    growthToAllocations: list[DeltaToActionMatrix] = field(default_factory=list)
    lastIndexSell: int = 0
    use_pe: bool = False

    def considerSell(self, tracker: InvestmentTracker, index, close, pe, cal_range_close, isPrint):
        if tracker.totalCurrentCapital <= 0 or tracker.totalShare <= 0:
            return
        current = pe if self.use_pe else close
        if current is None:
            return
        if index not in cal_range_close:
            return
        for alloc in self.growthToAllocations:
            if alloc.rangeDays in cal_range_close[index].rangeDayCloses:
                localBottom     = cal_range_close[index].rangeDayCloses[alloc.rangeDays].bottom(self.use_pe)
                increasePercent = (current - localBottom) / localBottom * 100
                if alloc.fromPercent <= increasePercent < alloc.toPercent:
                    if index - self.lastIndexSell >= 10:
                        self.lastIndexSell = index
                        sellFinal = tracker.totalShare * close * (alloc.actionPercent / 100)
                        Sellor().sell(tracker, sellFinal, index, close, isPrint)
                        return


@dataclass
class SellTopOfMA1000Strategy(SellStrategy):
    percentSell: float = 0
    use_pe: bool = False

    def considerSell(self, tracker: InvestmentTracker, index, close, pe, cal_range_close, isPrint):
        if tracker.totalCurrentCapital <= 0 or tracker.totalShare <= 0 or index <= 1000:
            return
        if self.check(index, close, pe, cal_range_close):
            Sellor().sell(tracker, tracker.totalShare * close, index, close, isPrint)

    def check(self, index, close, pe, cal_range_close) -> bool:
        if index <= 1000:
            return False
        current = pe if self.use_pe else close
        if current is None:
            return False
        if 1000 not in cal_range_close[index].rangeDayCloses:
            return False
        localAvg = cal_range_close[index].rangeDayCloses[1000].avg(self.use_pe)
        return (current - localAvg) / localAvg > self.percentSell / 100


@dataclass
class SellMedian1000Strategy(SellStrategy):
    """
    Sell when the price is percentSell above its own median, unless one of the
    gates below says otherwise.

    BEFORE ADDING A FOURTH GATE, READ THIS

      Three independent attempts to restrain this arm have now been measured on
      the full universe, and all three failed the same way:

          attempt                              FPT / GMD        portfolio
          SELL_MIN_ZDEV                            -            0 of 66 cells
          PERCENT_SELL x PERCENT_REINVEST      +91 / +428       15 up, 34 down
          SELL_MIN_PELOG                       +88 /  +96       19 up, 21 down

      Each was built from a real, measured failure — FPT loses 85 points to
      buying at every interval because this arm sells a compounder and the
      400-bar reinvest timeout buys it back higher. Each fixed exactly that, some
      of them spectacularly: the P/E gate moves LPB by +116, and LPB is the worst
      symbol in the run and had not shifted for anything else. And each still
      lost, because the same restraint that saves those symbols costs HPG -340,
      VND -197, SHB -138.

      The pattern is not about any of the three signals. This arm is net positive
      across the portfolio; anything that quiets it pays the majority to rescue
      the minority. A tell to watch for: a candidate gate that looks like it works
      usually turns out to have driven the sell count toward zero on the symbols
      it "fixed" — the P/E gate took FPT from four sells to none.

      So a fourth gate of this shape is not worth building. What the evidence
      actually asks for is something that separates a compounder from an
      oscillator per symbol, which no portfolio-wide threshold on a single signal
      can do.
    """
    # None means this trigger never fires, NOT that the arm stops selling — the
    # arm has two price triggers now and dies only when both are None, which
    # factory.py decides. Lets a sweep isolate one trigger from the other.
    percentSell: float | None = 0
    # Second price trigger, OR'd with percentSell: sell when the price is this far
    # above the window's LOW instead of above its median. None switches it off,
    # leaving the arm exactly as it was.
    #
    # Unlike every gate on this class this one makes the arm act MORE, not less,
    # so it is a primary condition rather than a filter — see factory.py, where
    # the two kinds are distinguished. Worth trying precisely because the three
    # attempts to restrain this arm all lost: if quieting it costs, the question
    # still open is whether loosening it pays.
    percentSellBottom: float | None = None
    use_pe: bool = False
    # Which median the price is measured against, as on the buy arm. The reinvest
    # arm is still fixed at 1000, which is what keeps the backtest start index
    # from moving when this drops below it.
    # percentSell has to move with it: the price's distance from its own median
    # widens with the window, p95 = 1.29 * w^0.698 (single/median1000/dispersion.py).
    medianWindow: int = 1000
    # {row_index: signal3_sharpe} for 1000-day window — block sell when >= min_signal3 (stable/trending → hold)
    signal3_map: dict = field(default_factory=dict)
    min_signal3: float = 0.8
    # {row_index: signal1_slope} for short-term window — block sell when >= min_signal1 (momentum still up → hold)
    signal1_map: dict = field(default_factory=dict)
    min_signal1: float = 0.05
    # {row_index: z_dev} from valuation_zdev — block sell when <= min_zdev, i.e.
    # require the price to be genuinely stretched against this symbol's own norm
    # before selling. Opposite comparison to the two filters above, and
    # deliberately so: those are momentum readings where high means "trend intact,
    # hold", while z_dev is a valuation reading where high is the reason to sell.
    # A low z_dev says the price is only above its trailing median because the
    # business grew into it — not a dislocation, so do not sell.
    zdev_map: dict = field(default_factory=dict)
    min_zdev: float = 1.3
    # {row_index: ln(P/E / its own rolling median)} — block sell when <= min_pelog.
    # Same polarity as z_dev, and the same intent z_dev's comment claims: do not
    # sell a price that is only high because the business grew into it. The
    # difference is that this one can actually see earnings, where z_dev is
    # computed from price alone.
    #
    # The caller is responsible for what goes in the map. Two kinds of gap, and
    # only one of them belongs here:
    #   - before the P/E median has PE_MEDIAN_WINDOW observations behind it the
    #     value is a median of almost nothing (range_stats applies no
    #     min_periods), so those rows must be left OUT by the caller
    #   - a row missing because the company was loss-making for a trailing year
    #     has no P/E at all, and is simply absent — the gate then stands aside,
    #     which is right: a company losing money has no "grew into it" defence
    pelog_map: dict = field(default_factory=dict)
    min_pelog: float = 0.0

    def considerSell(self, tracker: InvestmentTracker, index, close, pe, cal_range_close, isPrint):
        if tracker.totalCurrentCapital <= 0 or tracker.totalShare <= 0:
            return
        if self.check(index, close, pe, cal_range_close):
            Sellor().sell(tracker, tracker.totalShare * close, index, close, isPrint)

    def check(self, index, close, pe, cal_range_close) -> bool:
        if index <= self.medianWindow:
            return False
        current = pe if self.use_pe else close
        if current is None:
            return False
        if (index not in cal_range_close
                or self.medianWindow not in cal_range_close[index].rangeDayCloses):
            return False
        rc = cal_range_close[index].rangeDayCloses[self.medianWindow]
        fired = False
        if self.percentSell is not None:
            median = rc.pct50(self.use_pe)
            if median:
                fired = (current - median) / median * 100 > self.percentSell
        # Second way to satisfy the PRICE test, not a bypass of the gates below:
        # how far the price has run from the window's LOW rather than from its
        # middle. A symbol can double off its floor while its median chases it up,
        # leaving the median test quiet the whole way.
        #
        # Everything after this point still applies. The gates answer "should we
        # sell at all", which does not depend on which of the two conditions
        # noticed the move — letting the new one skip them would not be a second
        # trigger, it would be a hole.
        if not fired and self.percentSellBottom is not None:
            bottom = rc.bottom(self.use_pe)
            if bottom:
                fired = (current - bottom) / bottom * 100 > self.percentSellBottom
        if not fired:
            return False
        # Block sell when short-term momentum (linear regression slope) is still strong — let it run
        if self.signal1_map and self.signal1_map.get(index, 0.0) >= self.min_signal1:
            return False
        # Block sell when long-term Sharpe indicates stable/trending regime — let it run
        if self.signal3_map and self.signal3_map.get(index, 0.0) >= self.min_signal3:
            return False
        # Require the price to be stretched against this symbol's own norm before
        # selling. Missing rows (the z_dev warmup) are skipped rather than treated
        # as 0.0: with this comparison a 0.0 default would block every sell before
        # the warmup completes, which is the opposite of how the filters above
        # behave when a signal is absent.
        if self.zdev_map:
            z = self.zdev_map.get(index)
            if z is not None and z <= self.min_zdev:
                return False
        # Same missing-row rule as z_dev above: absent means the gate stands
        # aside, never that it blocks.
        if self.pelog_map:
            v = self.pelog_map.get(index)
            if v is not None and v <= self.min_pelog:
                return False
        return True
