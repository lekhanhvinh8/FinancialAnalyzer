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
    percentSell: float = 0
    use_pe: bool = False
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

    def considerSell(self, tracker: InvestmentTracker, index, close, pe, cal_range_close, isPrint):
        if tracker.totalCurrentCapital <= 0 or tracker.totalShare <= 0:
            return
        if self.check(index, close, pe, cal_range_close):
            Sellor().sell(tracker, tracker.totalShare * close, index, close, isPrint)

    def check(self, index, close, pe, cal_range_close) -> bool:
        if index <= 1000:
            return False
        current = pe if self.use_pe else close
        if current is None:
            return False
        if index not in cal_range_close or 1000 not in cal_range_close[index].rangeDayCloses:
            return False
        median = cal_range_close[index].rangeDayCloses[1000].pct50(self.use_pe)
        if (current - median) / median * 100 <= self.percentSell:
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
        return True
