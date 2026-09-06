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
    # Which median the price is measured against. The sell and reinvest arms stay
    # on 1000 whatever this is, so the two conditions stop being complementary as
    # soon as it moves — which is what sell_strategy below is for.
    # percentBuy has to move with it: the price's distance from its own median
    # grows with the window, p95 = 1.29 * w^0.698 (single/multi_signal/dispersion.py),
    # so 60 blocks nothing at w=50 and about a fifth of days at w=1000.
    medianWindow: int = 1000
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

    # ── the basket, not this symbol ─────────────────────────────────────────
    # {row_index: prem_median} from breadth_signals: how far the MEDIAN symbol
    # of the whole basket sits from its own median, in percent. None on
    # max_breadth switches the gate off and the arm is exactly what it was.
    #
    # A gate, not a strategy. It has the same shape as min_signal1 and
    # min_signal3 -- a map plus a threshold -- and giving it its own class
    # made "cheap symbol AND cheap market" impossible to express, because a run
    # could only ever have one buy arm.
    breadth_map: dict = field(default_factory=dict)
    max_breadth: float = None

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
        if index <= self.medianWindow:
            return False
        current = pe if self.use_pe else close
        if current is None:
            return False
        if (index not in cal_range_close
                or self.medianWindow not in cal_range_close[index].rangeDayCloses):
            return False
        # percentBuy = None switches the PRICE trigger off and leaves the arm
        # running on its gates alone -- which is what "buy on the market, not on
        # this symbol" needs. Without it the only way to express that was a
        # separate class.
        if self.percentBuy is not None:
            median = cal_range_close[index].rangeDayCloses[self.medianWindow].pct50(self.use_pe)
            if (current - median) / median * 100 >= self.percentBuy:
                return False
        # The basket has to agree too. A market reading we do not have is not a
        # reason to act, so an absent value leaves the gate shut.
        #
        # Placed after the price conditions and before the filters, as on the
        # sell arm. Every condition here is AND'd, so the order cannot change an
        # outcome — it is for the reader.
        if self.max_breadth is not None:
            b = self.breadth_map.get(index)
            if b is None or b > self.max_breadth:
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
