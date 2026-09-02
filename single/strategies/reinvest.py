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
    """
    Redeploy the reserve when the price is attractive. Two price triggers, OR'd,
    plus a timeout valve that ignores both.
    """
    # None means this trigger never fires, NOT that the arm stops reinvesting —
    # the arm has two price triggers and falls back to the base class only when
    # both are None, which factory.py decides. Lets a sweep isolate one from the
    # other.
    percentReinvest: float | None = 0
    # Second price trigger, OR'd with percentReinvest: reinvest once the price has
    # fallen this far from the window HIGH rather than come back to its median.
    # Same comparison direction as percentReinvest — reinvest while dev is BELOW
    # the threshold — but measured against the top, where dev is always <= 0, so
    # the threshold is negative. -30 reads as "at least 30% off the high".
    #
    # What it catches that the median cannot: the fall away from a spike, while
    # the price is still above its own median. That is exactly the state FPT and
    # GMD sit in after a sell, where the median condition never reopens and the
    # 400-bar timeout ends up buying back higher than it sold.
    percentReinvestTop: float | None = None
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
    # Same guard as BuyMedian1000Strategy: no reinvest on a bar that sells. The
    # timeout path below needs no guard — a sell sets tracker.lastSellIndex to
    # this index, so its "timeoutDays since the last sell" test is False here.
    # Untyped to keep reinvest.py from importing sell.py; only .check() is used.
    sell_strategy: object = None

    def _slope_ok(self, index) -> bool:
        if not self.signal1_map:
            return True
        return self.signal1_map.get(index, 0.0) >= self.min_signal1

    # ── the basket, not this symbol ─────────────────────────────────────────
    # {row_index: median_prem} from breadth_signals. The reserve goes back to
    # work only when the whole market is at or below max_breadth. None switches
    # it off. Same shape as the other gates on this class.
    breadth_map: dict = field(default_factory=dict)
    max_breadth: float = None

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
        # The basket has to agree. A market reading we do not have is not
        # a reason to act, so an absent value leaves the gate shut.
        if self.max_breadth is not None:
            b = self.breadth_map.get(index)
            if b is None or b > self.max_breadth:
                return False
        current = pe if self.use_pe else close
        if current is None:
            return False
        if index not in cal_range_close or 1000 not in cal_range_close[index].rangeDayCloses:
            return False
        rc = cal_range_close[index].rangeDayCloses[1000]

        # Same grouping as the sell arm: percentReinvest OR percentReinvestTop,
        # and a group nobody configured does not get a vote.
        if self.percentReinvest is not None or self.percentReinvestTop is not None:
            fired = False
            if self.percentReinvest is not None:
                median = rc.pct50(self.use_pe)
                if median:
                    fired = (current - median) / median * 100 < self.percentReinvest
            # Second way to satisfy the PRICE group, not a bypass of the guards
            # below. Both answer "should we redeploy at all", which does not
            # depend on which condition noticed the opportunity.
            if not fired and self.percentReinvestTop is not None:
                top = rc.top(self.use_pe)
                if top:
                    fired = (current - top) / top * 100 <= self.percentReinvestTop
            if not fired:
                return False

        if self.sell_strategy is not None and self.sell_strategy.check(
                index, close, pe, cal_range_close):
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
