from dataclasses import dataclass, field
from ..models import InvestmentTracker, DeltaToActionMatrix
from ..engine import Reinvestor


class ReinvestStrategy:
    def considerReinvest(self, tracker: InvestmentTracker, index, close, pe, cal_range_close, isPrint):
        pass

    def check(self, index, close, pe, cal_range_close) -> bool:
        return False


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
        if self.check(index, close, pe, cal_range_close):
            Reinvestor().reinvest(tracker, tracker.totalReserveFinal, index, close, isPrint)

    def check(self, index, close, pe, cal_range_close) -> bool:
        current = pe if self.use_pe else close
        if current is None:
            return False
        if index not in cal_range_close or self.localRangeDays not in cal_range_close[index].rangeDayCloses:
            return False
        localTop = cal_range_close[index].rangeDayCloses[self.localRangeDays].top(self.use_pe)
        return current < localTop and (localTop - current) / localTop > self.decreasePercent / 100


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
class ReInvestMedian1000Strategy(ReinvestStrategy):
    percentReinvest: float = 0
    use_pe: bool = False
    timeoutDays: int = 0        # 0 = disabled
    timeoutPercent: float = 0   # threshold used after timeout (same scale as percentReinvest)
    # {row_index: signal1_slope} for a short-term window — REQUIRE slope >= min_signal1
    # before redeploying on the price condition, i.e. wait for momentum to turn up
    # rather than catching a falling knife. Gates check() only, not the timeout.
    # Polarity is the inverse of SellMedian1000Strategy, which uses the same signal
    # to *block* a sell while momentum is still running.
    signal1_map: dict = field(default_factory=dict)
    min_signal1: float = 0.0

    def _slope_ok(self, index) -> bool:
        if not self.signal1_map:
            return True
        return self.signal1_map.get(index, 0.0) >= self.min_signal1

    def considerReinvest(self, tracker: InvestmentTracker, index, close, pe, cal_range_close, isPrint):
        if tracker.totalReserveFinal <= 0:
            return
        # No slope guard here: the requirement applies to the price condition inside
        # check() only. The timeout below stays an unconditional release valve.
        if self.check(index, close, pe, cal_range_close):
            Reinvestor().reinvest(tracker, tracker.totalReserveFinal, index, close, isPrint)
            return
        # Timeout: fire if no sell AND no reinvest within timeoutDays, use looser threshold
        if (self.timeoutDays > 0
                and (tracker.lastSellIndex == 0 or (index - tracker.lastSellIndex) >= self.timeoutDays)
                and (tracker.lastReinvestIndex == 0 or (index - tracker.lastReinvestIndex) >= self.timeoutDays)):
            current = pe if self.use_pe else close
            if current is None:
                return
            if index not in cal_range_close or 1000 not in cal_range_close[index].rangeDayCloses:
                return
            median = cal_range_close[index].rangeDayCloses[1000].pct50(self.use_pe)
            if (current - median) / median * 100 < self.timeoutPercent:
                Reinvestor().reinvest(tracker, tracker.totalReserveFinal, index, close, isPrint)

    def check(self, index, close, pe, cal_range_close) -> bool:
        if index <= 1000:
            return False
        current = pe if self.use_pe else close
        if current is None:
            return False
        if index not in cal_range_close or 1000 not in cal_range_close[index].rangeDayCloses:
            return False
        median = cal_range_close[index].rangeDayCloses[1000].pct50(self.use_pe)
        if (current - median) / median * 100 >= self.percentReinvest:
            return False
        # Only redeploy once short-term momentum has turned up
        return self._slope_ok(index)


@dataclass
class ReInvestUnderMA1000Strategy(ReinvestStrategy):
    use_pe: bool = False

    def considerReinvest(self, tracker: InvestmentTracker, index, close, pe, cal_range_close, isPrint):
        if tracker.totalReserveFinal <= 0 or index <= 1000:
            return
        if self.check(index, close, pe, cal_range_close):
            Reinvestor().reinvest(tracker, tracker.totalReserveFinal, index, close, isPrint)

    def check(self, index, close, pe, cal_range_close) -> bool:
        if index <= 1000:
            return False
        current = pe if self.use_pe else close
        if current is None:
            return False
        if 1000 not in cal_range_close[index].rangeDayCloses:
            return False
        return current < cal_range_close[index].rangeDayCloses[1000].avg(self.use_pe)


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
