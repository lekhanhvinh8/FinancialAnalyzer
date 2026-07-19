from dataclasses import dataclass, field
from ..models import InvestmentTracker, DeltaToActionMatrix
from ..engine import Sellor


class SellStrategy:
    def considerSell(self, tracker: InvestmentTracker, index, close, pe, cal_range_close, isPrint):
        pass


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
        current = pe if self.use_pe else close
        if current is None:
            return
        if index not in cal_range_close or self.localRangeDays not in cal_range_close[index].rangeDayCloses:
            return
        localBottom = cal_range_close[index].rangeDayCloses[self.localRangeDays].bottom(self.use_pe)
        if (current - localBottom) / localBottom > self.percentSell / 100:
            Sellor().sell(tracker, tracker.totalShare * close, index, close, isPrint)



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
        current = pe if self.use_pe else close
        if current is None:
            return
        if 1000 in cal_range_close[index].rangeDayCloses:
            localAvg        = cal_range_close[index].rangeDayCloses[1000].avg(self.use_pe)
            increasePercent = (current - localAvg) / localAvg
            if increasePercent > self.percentSell / 100:
                Sellor().sell(tracker, tracker.totalShare * close, index, close, isPrint)
