from dataclasses import dataclass, field
from datetime import datetime
from ..models import InvestmentTracker, DeltaToActionMatrix
from ..engine import Buyer


class BuyStrategy:
    def considerBuy(self, tracker: InvestmentTracker, index, close, pe, cal_range_close, isPrint):
        pass


@dataclass
class BuyIntervalStrategy(BuyStrategy):
    def considerBuy(self, tracker: InvestmentTracker, index, close, pe, cal_range_close, isPrint):
        Buyer().buy(tracker, tracker.intervalAmount, 0, index, close, isPrint)


@dataclass
class BuyBottomStrategy(BuyStrategy):
    firstLocalTop: float
    firstLocalTopDate: datetime
    localRangeDays: int = 1
    decreasePercent: float = 1
    use_pe: bool = False

    def considerBuy(self, tracker: InvestmentTracker, index, close, pe, cal_range_close, isPrint):
        current = pe if self.use_pe else close
        if current is None:
            return
        localTop = self.firstLocalTop
        if index in cal_range_close and self.localRangeDays in cal_range_close[index].rangeDayCloses:
            localTop = cal_range_close[index].rangeDayCloses[self.localRangeDays].top(self.use_pe)
        if current < localTop and (localTop - current) / localTop > self.decreasePercent / 100:
            Buyer().buy(tracker, tracker.intervalAmount, 0, index, close, isPrint)


@dataclass
class BuyMAStrategy(BuyStrategy):
    firstLocalAvg: float
    localRangeDays: int = 1
    decreasePercent: float = 1
    use_pe: bool = False

    def considerBuy(self, tracker: InvestmentTracker, index, close, pe, cal_range_close, isPrint):
        current = pe if self.use_pe else close
        if current is None:
            return
        localAvg = self.firstLocalAvg
        if index in cal_range_close and self.localRangeDays in cal_range_close[index].rangeDayCloses:
            localAvg = cal_range_close[index].rangeDayCloses[self.localRangeDays].avg(self.use_pe)
        if current < localAvg and (localAvg - current) / localAvg > self.decreasePercent / 100:
            Buyer().buy(tracker, tracker.intervalAmount, 0, index, close, isPrint)


@dataclass
class BuyUptrendStrategy(BuyStrategy):
    localRangeDays1: int = 1
    localRangeDays2: int = 1
    use_pe: bool = False

    def considerBuy(self, tracker: InvestmentTracker, index, close, pe, cal_range_close, isPrint):
        current = pe if self.use_pe else close
        if current is None or index not in cal_range_close:
            return
        rc = cal_range_close[index].rangeDayCloses
        if self.localRangeDays1 in rc:
            if current > rc[self.localRangeDays1].avg(self.use_pe):
                Buyer().buy(tracker, tracker.intervalAmount, 0, index, close, isPrint)
                return
        if self.localRangeDays2 in rc and current > rc[self.localRangeDays2].avg(self.use_pe):
            Buyer().buy(tracker, tracker.intervalAmount, 0, index, close, isPrint)



@dataclass
class BuyPartialStrategy(BuyStrategy):
    deltaToActions: list[DeltaToActionMatrix] = field(default_factory=list)
    use_pe: bool = False

    def considerBuy(self, tracker: InvestmentTracker, index, close, pe, cal_range_close, isPrint):
        current = pe if self.use_pe else close
        if current is None:
            current = close
        for action in self.deltaToActions:
            if action.rangeDays in cal_range_close[index].rangeDayCloses:
                localBottom  = cal_range_close[index].rangeDayCloses[action.rangeDays].bottom(self.use_pe)
                deltaPercent = (current - localBottom) / localBottom * 100
                if action.fromPercent <= deltaPercent < action.toPercent:
                    partialVolumn = tracker.intervalAmount * (action.actionPercent / 100)
                    Buyer().buy(tracker, partialVolumn, 0, index, close, isPrint)
                    break

        if tracker.intervalAmount > 0:
            tracker.totalReserveCapital += tracker.intervalAmount
            tracker.totalReserveFinal   += tracker.intervalAmount
            tracker.intervalAmount = 0


@dataclass
class BuyPartialMA(BuyStrategy):
    use_pe: bool = False

    def considerBuy(self, tracker: InvestmentTracker, index, close, pe, cal_range_close, isPrint):
        rc     = cal_range_close[index].rangeDayCloses
        ma50   = rc[50].avg(self.use_pe)
        current = (pe if self.use_pe else close) or close
        amount = tracker.intervalAmount * 0.5 if (current - ma50) > 0.3 else tracker.intervalAmount
        Buyer().buy(tracker, amount, 0, index, close, isPrint)
        if tracker.intervalAmount > 0:
            tracker.totalReserveCapital += tracker.intervalAmount
            tracker.totalReserveFinal   += tracker.intervalAmount
            tracker.intervalAmount = 0


@dataclass
class BuyMA1000Strategy(BuyStrategy):
    increasedPercentNotBuy: float = 1_000_000
    use_pe: bool = False

    def considerBuy(self, tracker: InvestmentTracker, index, close, pe, cal_range_close, isPrint):
        if tracker.intervalAmount <= 0:
            return
        current = pe if self.use_pe else close
        if current is not None and index > 1000 and 1000 in cal_range_close[index].rangeDayCloses:
            localAvg         = cal_range_close[index].rangeDayCloses[1000].avg(self.use_pe)
            increasedPercent = (current - localAvg) / localAvg
            if increasedPercent > self.increasedPercentNotBuy / 100:
                tracker.totalReserveCapital += tracker.intervalAmount
                tracker.totalReserveFinal   += tracker.intervalAmount
                tracker.intervalAmount = 0
                return
        Buyer().buy(tracker, tracker.intervalAmount, 0, index, close, isPrint)
