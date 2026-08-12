from dataclasses import dataclass, field
from ..models import InvestmentTracker, DeltaToActionMatrix
from ..engine import Buyer


class BuyStrategy:
    def considerBuy(self, tracker: InvestmentTracker, index, close, pe, cal_range_close, isPrint):
        pass

    def check(self, index, close, pe, cal_range_close) -> bool:
        return False


@dataclass
class BuyIntervalStrategy(BuyStrategy):
    def considerBuy(self, tracker: InvestmentTracker, index, close, pe, cal_range_close, isPrint):
        Buyer().buy(tracker, tracker.intervalAmount, 0, index, close, isPrint)

    def check(self, index, close, pe, cal_range_close) -> bool:
        return True


@dataclass
class BuyBottomStrategy(BuyStrategy):
    localRangeDays: int = 1
    decreasePercent: float = 1
    use_pe: bool = False

    def considerBuy(self, tracker: InvestmentTracker, index, close, pe, cal_range_close, isPrint):
        if self.check(index, close, pe, cal_range_close):
            Buyer().buy(tracker, tracker.intervalAmount, 0, index, close, isPrint)

    def check(self, index, close, pe, cal_range_close) -> bool:
        current = pe if self.use_pe else close
        if current is None:
            return False
        if index not in cal_range_close or self.localRangeDays not in cal_range_close[index].rangeDayCloses:
            return False
        localTop = cal_range_close[index].rangeDayCloses[self.localRangeDays].top(self.use_pe)
        return current < localTop and (localTop - current) / localTop > self.decreasePercent / 100


@dataclass
class BuyMAStrategy(BuyStrategy):
    localRangeDays: int = 1
    decreasePercent: float = 1
    use_pe: bool = False

    def considerBuy(self, tracker: InvestmentTracker, index, close, pe, cal_range_close, isPrint):
        if self.check(index, close, pe, cal_range_close):
            Buyer().buy(tracker, tracker.intervalAmount, 0, index, close, isPrint)

    def check(self, index, close, pe, cal_range_close) -> bool:
        current = pe if self.use_pe else close
        if current is None:
            return False
        if index not in cal_range_close or self.localRangeDays not in cal_range_close[index].rangeDayCloses:
            return False
        localAvg = cal_range_close[index].rangeDayCloses[self.localRangeDays].avg(self.use_pe)
        return current < localAvg and (localAvg - current) / localAvg > self.decreasePercent / 100


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
        if index not in cal_range_close:
            return
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
        if index not in cal_range_close:
            return
        rc = cal_range_close[index].rangeDayCloses
        if 50 not in rc:
            return
        ma50    = rc[50].avg(self.use_pe)
        current = (pe if self.use_pe else close) or close
        amount  = tracker.intervalAmount * 0.5 if (current - ma50) > 0.3 else tracker.intervalAmount
        Buyer().buy(tracker, amount, 0, index, close, isPrint)
        if tracker.intervalAmount > 0:
            tracker.totalReserveCapital += tracker.intervalAmount
            tracker.totalReserveFinal   += tracker.intervalAmount
            tracker.intervalAmount = 0


@dataclass
class BuyMedian1000Strategy(BuyStrategy):
    percentBuy: float = 0
    use_pe: bool = False
    # If set, no buy on a bar where this strategy would sell. The engine runs
    # sell before buy, so without it a bar that satisfies both sells the whole
    # position and buys straight back the same day. Cannot happen while
    # PERCENT_BUY <= PERCENT_SELL, since the two price conditions are then
    # complementary — it bites as soon as they are swept or tuned apart.
    # Deliberately the FULL sell check, gates included: the point is to avoid
    # churn on bars that actually sell, not to refuse to buy whenever the price
    # happens to be high.
    # Untyped to keep buy.py from importing sell.py; only .check() is used.
    sell_strategy: object = None

    def considerBuy(self, tracker: InvestmentTracker, index, close, pe, cal_range_close, isPrint):
        if tracker.intervalAmount <= 0:
            return
        if self.check(index, close, pe, cal_range_close):
            Buyer().buy(tracker, tracker.intervalAmount, 0, index, close, isPrint)
        else:
            tracker.totalReserveCapital += tracker.intervalAmount
            tracker.totalReserveFinal   += tracker.intervalAmount
            tracker.intervalAmount = 0

    def check(self, index, close, pe, cal_range_close) -> bool:
        if index <= 1000:
            return False
        current = pe if self.use_pe else close
        if current is None:
            return False
        if index not in cal_range_close or 1000 not in cal_range_close[index].rangeDayCloses:
            return False
        median = cal_range_close[index].rangeDayCloses[1000].pct50(self.use_pe)
        if (current - median) / median * 100 >= self.percentBuy:
            return False
        if self.sell_strategy is not None and self.sell_strategy.check(
                index, close, pe, cal_range_close):
            return False
        return True


@dataclass
class BuyMA1000Strategy(BuyStrategy):
    increasedPercentNotBuy: float = 1_000_000
    use_pe: bool = False

    def considerBuy(self, tracker: InvestmentTracker, index, close, pe, cal_range_close, isPrint):
        if tracker.intervalAmount <= 0:
            return
        if not self.check(index, close, pe, cal_range_close):
            tracker.totalReserveCapital += tracker.intervalAmount
            tracker.totalReserveFinal   += tracker.intervalAmount
            tracker.intervalAmount = 0
            return
        Buyer().buy(tracker, tracker.intervalAmount, 0, index, close, isPrint)

    def check(self, index, close, pe, cal_range_close) -> bool:
        current = pe if self.use_pe else close
        if current is not None and index > 1000 and 1000 in cal_range_close[index].rangeDayCloses:
            localAvg = cal_range_close[index].rangeDayCloses[1000].avg(self.use_pe)
            if (current - localAvg) / localAvg > self.increasedPercentNotBuy / 100:
                return False
        return True
