import pandas as pd
from dataclasses import dataclass, field
from datetime import datetime
from ..models import InvestmentTracker, DeltaToActionMatrix
from ..engine import Buyer


class BuyStrategy:
    def considerBuy(self, tracker: InvestmentTracker, index, close, cal_range_close, isPrint):
        pass


@dataclass
class BuyIntervalStrategy(BuyStrategy):
    def considerBuy(self, tracker: InvestmentTracker, index, close, cal_range_close, isPrint):
        Buyer().buy(tracker, tracker.intervalAmount, 0, index, close, isPrint)


@dataclass
class BuyBottomStrategy(BuyStrategy):
    df: pd.DataFrame
    firstLocalTop: float
    firstLocalTopDate: datetime
    localRangeDays: int = 1
    decreasePercent: float = 1

    def considerBuy(self, tracker: InvestmentTracker, index, close, cal_range_close, isPrint):
        localTop = self.firstLocalTop
        if index in cal_range_close and self.localRangeDays in cal_range_close[index].rangeDayCloses:
            localTop = cal_range_close[index].rangeDayCloses[self.localRangeDays].localTop
        if close < localTop and (localTop - close) / localTop > self.decreasePercent / 100:
            Buyer().buy(tracker, tracker.intervalAmount, 0, index, close, isPrint)


@dataclass
class BuyMAStrategy(BuyStrategy):
    df: pd.DataFrame
    firstLocalAvg: float
    localRangeDays: int = 1
    decreasePercent: float = 1

    def considerBuy(self, tracker: InvestmentTracker, index, close, cal_range_close, isPrint):
        localAvg = self.firstLocalAvg
        if index in cal_range_close and self.localRangeDays in cal_range_close[index].rangeDayCloses:
            localAvg = cal_range_close[index].rangeDayCloses[self.localRangeDays].localAvg
        if close < localAvg and (localAvg - close) / localAvg > self.decreasePercent / 100:
            Buyer().buy(tracker, tracker.intervalAmount, 0, index, close, isPrint)


@dataclass
class BuyUptrendStrategy(BuyStrategy):
    df: pd.DataFrame
    localRangeDays1: int = 1
    localRangeDays2: int = 1

    def considerBuy(self, tracker: InvestmentTracker, index, close, cal_range_close, isPrint):
        if index not in cal_range_close:
            return
        rc = cal_range_close[index].rangeDayCloses
        if self.localRangeDays1 in rc:
            if close > rc[self.localRangeDays1].localAvg:
                Buyer().buy(tracker, tracker.intervalAmount, 0, index, close, isPrint)
                return
        if self.localRangeDays2 in rc and close > rc[self.localRangeDays2].localAvg:
            Buyer().buy(tracker, tracker.intervalAmount, 0, index, close, isPrint)


@dataclass
class BuyProphetStrategy(BuyStrategy):
    df: pd.DataFrame
    localRangeDays: int = 1

    def considerBuy(self, tracker: InvestmentTracker, index, close, cal_range_close, isPrint):
        if index in cal_range_close and self.localRangeDays in cal_range_close[index].rangeDayClosesPos:
            localBottom = cal_range_close[index].rangeDayClosesPos[self.localRangeDays].localBottom
            if close <= localBottom:
                Buyer().buy(tracker, tracker.intervalAmount, 0, index, close, isPrint)


@dataclass
class BuyPartialStrategy(BuyStrategy):
    deltaToActions: list[DeltaToActionMatrix] = field(default_factory=list)

    def considerBuy(self, tracker: InvestmentTracker, index, close, cal_range_close, isPrint):
        for action in self.deltaToActions:
            if action.rangeDays in cal_range_close[index].rangeDayCloses:
                localBottom  = cal_range_close[index].rangeDayCloses[action.rangeDays].localBottom
                deltaPercent = (close - localBottom) / localBottom * 100
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
    def considerBuy(self, tracker: InvestmentTracker, index, close, cal_range_close, isPrint):
        rc     = cal_range_close[index].rangeDayCloses
        ma50   = rc[50].localAvg
        amount = tracker.intervalAmount * 0.5 if (close - ma50) > 0.3 else tracker.intervalAmount
        Buyer().buy(tracker, amount, 0, index, close, isPrint)
        if tracker.intervalAmount > 0:
            tracker.totalReserveCapital += tracker.intervalAmount
            tracker.totalReserveFinal   += tracker.intervalAmount
            tracker.intervalAmount = 0


@dataclass
class BuyMA1000Strategy(BuyStrategy):
    increasedPercentNotBuy: float = 1_000_000

    def considerBuy(self, tracker: InvestmentTracker, index, close, cal_range_close, isPrint):
        if tracker.intervalAmount <= 0:
            return
        if index > 1000 and 1000 in cal_range_close[index].rangeDayCloses:
            localAvg         = cal_range_close[index].rangeDayCloses[1000].localAvg
            increasedPercent = (close - localAvg) / localAvg
            if increasedPercent > self.increasedPercentNotBuy / 100:
                tracker.totalReserveCapital += tracker.intervalAmount
                tracker.totalReserveFinal   += tracker.intervalAmount
                tracker.intervalAmount = 0
                return
        Buyer().buy(tracker, tracker.intervalAmount, 0, index, close, isPrint)
