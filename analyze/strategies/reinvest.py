import pandas as pd
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
    firstLocalTop: float
    localRangeDays: int = 1
    decreasePercent: float = 1
    use_pe: bool = False

    def considerReinvest(self, tracker: InvestmentTracker, index, close, pe, cal_range_close, isPrint):
        if tracker.totalReserveFinal <= 0:
            return
        current = pe if self.use_pe else close
        if current is None:
            return
        localTop = self.firstLocalTop
        if index in cal_range_close and self.localRangeDays in cal_range_close[index].rangeDayCloses:
            localTop = cal_range_close[index].rangeDayCloses[self.localRangeDays].top(self.use_pe)
        if current < localTop and (localTop - current) / localTop > self.decreasePercent / 100:
            Reinvestor().reinvest(tracker, tracker.totalReserveFinal, index, close, isPrint)


@dataclass
class ReInvestProphetStrategy(ReinvestStrategy):
    df: pd.DataFrame
    localRangeDays: int = 1
    use_pe: bool = False

    def considerReinvest(self, tracker: InvestmentTracker, index, close, pe, cal_range_close, isPrint):
        current = pe if self.use_pe else close
        if current is None:
            return
        if index in cal_range_close and self.localRangeDays in cal_range_close[index].rangeDayClosesPos:
            localBottom = cal_range_close[index].rangeDayClosesPos[self.localRangeDays].bottom(self.use_pe)
            if current <= localBottom:
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
