import pandas as pd
from dataclasses import dataclass, field
from ..models import InvestmentTracker, DeltaToActionMatrix
from ..engine import Reinvestor


class ReinvestStrategy:
    def considerReinvest(self, tracker: InvestmentTracker, index, close, cal_range_close, isPrint):
        pass


@dataclass
class ReInvestBottomStrategy(ReinvestStrategy):
    percentReinvest: float = 0

    def considerReinvest(self, tracker: InvestmentTracker, index, close, cal_range_close, isPrint):
        if tracker.totalReserveFinal > 0:
            avgPrice        = tracker.totalReserveFinal / (tracker.totalReserveShare or 1)
            decreasePercent = (avgPrice - close) / avgPrice
            if decreasePercent > self.percentReinvest / 100:
                Reinvestor().reinvest(tracker, tracker.totalReserveFinal, index, close, isPrint)


@dataclass
class ReInvestBottomOfTopStrategy(ReinvestStrategy):
    firstLocalTop: float
    localRangeDays: int = 1
    decreasePercent: float = 1

    def considerReinvest(self, tracker: InvestmentTracker, index, close, cal_range_close, isPrint):
        if tracker.totalReserveFinal > 0:
            localTop = self.firstLocalTop
            if index in cal_range_close and self.localRangeDays in cal_range_close[index].rangeDayCloses:
                localTop = cal_range_close[index].rangeDayCloses[self.localRangeDays].localTop
            if close < localTop and (localTop - close) / localTop > self.decreasePercent / 100:
                Reinvestor().reinvest(tracker, tracker.totalReserveFinal, index, close, isPrint)


@dataclass
class ReInvestProphetStrategy(ReinvestStrategy):
    df: pd.DataFrame
    localRangeDays: int = 1

    def considerReinvest(self, tracker: InvestmentTracker, index, close, cal_range_close, isPrint):
        if index in cal_range_close and self.localRangeDays in cal_range_close[index].rangeDayClosesPos:
            localBottom = cal_range_close[index].rangeDayClosesPos[self.localRangeDays].localBottom
            if close <= localBottom:
                Reinvestor().reinvest(tracker, tracker.totalReserveFinal, index, close, isPrint)


@dataclass
class ReInvestPartialStrategy(ReinvestStrategy):
    deltaToActions: list[DeltaToActionMatrix] = field(default_factory=list)
    lastIndexAction: int = 0

    def considerReinvest(self, tracker: InvestmentTracker, index, close, cal_range_close, isPrint):
        if tracker.totalReserveFinal <= 0:
            return
        for action in self.deltaToActions:
            if action.rangeDays in cal_range_close[index].rangeDayCloses:
                localTop     = cal_range_close[index].rangeDayCloses[action.rangeDays].localTop
                deltaPercent = (localTop - close) / localTop * 100
                if action.fromPercent <= deltaPercent < action.toPercent:
                    if index - self.lastIndexAction >= 10:
                        self.lastIndexAction = index
                        partialVolumn = tracker.totalReserveFinal * (action.actionPercent / 100)
                        Reinvestor().reinvest(tracker, partialVolumn, index, close, isPrint)
                        return


@dataclass
class ReInvestUnderMA1000Strategy(ReinvestStrategy):
    def considerReinvest(self, tracker: InvestmentTracker, index, close, cal_range_close, isPrint):
        if tracker.totalReserveFinal <= 0 or index <= 1000:
            return
        if 1000 in cal_range_close[index].rangeDayCloses:
            if close < cal_range_close[index].rangeDayCloses[1000].localAvg:
                Reinvestor().reinvest(tracker, tracker.totalReserveFinal, index, close, isPrint)


@dataclass
class ReInvestUnderMA1000OrMaxHoldTimeStrategy(ReinvestStrategy):
    maxHoldTime: int = 10_000_000

    def considerReinvest(self, tracker: InvestmentTracker, index, close, cal_range_close, isPrint):
        if tracker.totalReserveFinal <= 0:
            return
        if index > 1000 and 1000 in cal_range_close[index].rangeDayCloses:
            if close < cal_range_close[index].rangeDayCloses[1000].localAvg:
                Reinvestor().reinvest(tracker, tracker.totalReserveFinal, index, close, isPrint)
                return
        if tracker.lastSellIndex > 0 and (index - tracker.lastSellIndex) > self.maxHoldTime:
            Reinvestor().reinvest(tracker, tracker.totalReserveFinal, index, close, isPrint)
