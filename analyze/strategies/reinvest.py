from dataclasses import dataclass, field
from ..models import InvestmentTracker, DeltaToActionMatrix
from ..engine import Reinvestor


class ReinvestStrategy:
    def considerReinvest(self, tracker: InvestmentTracker, index, close, pe, cal_range_close, isPrint):
        pass


@dataclass
class ReInvestBottomStrategy(ReinvestStrategy):
    percentReinvest: float = 0
    use_pe: bool = False

    def considerReinvest(self, tracker: InvestmentTracker, index, close, pe, cal_range_close, isPrint):
        if tracker.totalReserveFinal <= 0:
            return
        current = pe if self.use_pe else close
        if current is None:
            return
        avgPrice        = tracker.totalReserveFinal / (tracker.totalReserveShare or 1)
        decreasePercent = (avgPrice - current) / avgPrice
        if decreasePercent > self.percentReinvest / 100:
            Reinvestor().reinvest(tracker, tracker.totalReserveFinal, index, close, isPrint)


@dataclass
class ReInvestBottomOfTopStrategy(ReinvestStrategy):
    localRangeDays: int = 1
    decreasePercent: float = 1
    use_pe: bool = False

    def considerReinvest(self, tracker: InvestmentTracker, index, close, pe, cal_range_close, isPrint):
        if tracker.totalReserveFinal <= 0:
            return
        current = pe if self.use_pe else close
        if current is None:
            return
        if index not in cal_range_close or self.localRangeDays not in cal_range_close[index].rangeDayCloses:
            return
        localTop = cal_range_close[index].rangeDayCloses[self.localRangeDays].top(self.use_pe)
        if current < localTop and (localTop - current) / localTop > self.decreasePercent / 100:
            Reinvestor().reinvest(tracker, tracker.totalReserveFinal, index, close, isPrint)


@dataclass
class ReInvestPartialStrategy(ReinvestStrategy):
    deltaToActions: list[DeltaToActionMatrix] = field(default_factory=list)
    lastIndexAction: int = 0
    use_pe: bool = False

    def considerReinvest(self, tracker: InvestmentTracker, index, close, pe, cal_range_close, isPrint):
        if tracker.totalReserveFinal <= 0:
            return
        current = pe if self.use_pe else close
        if current is None:
            return
        if index not in cal_range_close:
            return
        for action in self.deltaToActions:
            if action.rangeDays in cal_range_close[index].rangeDayCloses:
                localTop     = cal_range_close[index].rangeDayCloses[action.rangeDays].top(self.use_pe)
                deltaPercent = (localTop - current) / localTop * 100
                if action.fromPercent <= deltaPercent < action.toPercent:
                    if index - self.lastIndexAction >= 10:
                        self.lastIndexAction = index
                        partialVolumn = tracker.totalReserveFinal * (action.actionPercent / 100)
                        Reinvestor().reinvest(tracker, partialVolumn, index, close, isPrint)
                        return


@dataclass
class ReInvestUnderMA1000Strategy(ReinvestStrategy):
    use_pe: bool = False

    def considerReinvest(self, tracker: InvestmentTracker, index, close, pe, cal_range_close, isPrint):
        if tracker.totalReserveFinal <= 0 or index <= 1000:
            return
        current = pe if self.use_pe else close
        if current is None:
            return
        if 1000 in cal_range_close[index].rangeDayCloses:
            if current < cal_range_close[index].rangeDayCloses[1000].avg(self.use_pe):
                Reinvestor().reinvest(tracker, tracker.totalReserveFinal, index, close, isPrint)


@dataclass
class ReInvestUnderMA1000OrMaxHoldTimeStrategy(ReinvestStrategy):
    maxHoldTime: int = 10_000_000
    use_pe: bool = False

    def considerReinvest(self, tracker: InvestmentTracker, index, close, pe, cal_range_close, isPrint):
        if tracker.totalReserveFinal <= 0:
            return
        current = pe if self.use_pe else close
        if current is not None and index > 1000 and 1000 in cal_range_close[index].rangeDayCloses:
            if current < cal_range_close[index].rangeDayCloses[1000].avg(self.use_pe):
                Reinvestor().reinvest(tracker, tracker.totalReserveFinal, index, close, isPrint)
                return
        if tracker.lastSellIndex > 0 and (index - tracker.lastSellIndex) > self.maxHoldTime:
            Reinvestor().reinvest(tracker, tracker.totalReserveFinal, index, close, isPrint)
