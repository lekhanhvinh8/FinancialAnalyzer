from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class RangeDaysClose:
    localTop: float
    localAvg: float
    localBottom: float
    p25: float = 0.0
    median: float = 0.0
    p75: float = 0.0
    pe_p25: float = 0.0
    pe_median: float = 0.0
    pe_p75: float = 0.0


@dataclass
class IndexCloses:
    rangeDayCloses: dict[int, RangeDaysClose] = field(default_factory=dict)
    rangeDayClosesPos: dict[int, RangeDaysClose] = field(default_factory=dict)


@dataclass
class SellInfo:
    index: int = 0
    time: str = ""
    close: float = 0.0
    localBottom: float = 0.0
    localBottomDate: str = ""
    sellShare: float = 0.0
    sellCapital: float = 0.0
    sellFinal: float = 0.0
    sellGrowthRatito: float = 0.0


@dataclass
class ReinvestInfo:
    index: int = 0
    time: str = ""
    close: float = 0.0
    averageProfitPrice: float = 0.0
    reInvestShare: float = 0.0
    reInvestFinal: float = 0.0
    reInvestCapital: float = 0.0


@dataclass
class BuyedInfo:
    index: int = 0
    time: str = ""
    close: float = 0.0
    localTop: float = 0.0
    localTopDate: str = ""
    finalBuy: float = 0.0
    numberOfShareCanBy: float = 0.0


@dataclass
class DepositAddInfo:
    index: int = 0
    time: str = ""
    close: float = 0.0
    totalReserveInterest: float = 0


@dataclass
class DeltaToActionMatrix:
    rangeDays: int = 0
    fromPercent: float = 0
    toPercent: float = 0
    actionPercent: float = 0


@dataclass
class GrowRatio:
    x: float = 0
    y: float = 0
    z: float = 0
    t: float = 0
    result: float = 0


class InvestmentTracker:
    def __init__(self):
        self.totalShare = 0
        self.totalCapital = 0
        self.totalCurrentCapital = 0

        self.intervalAmount = 0

        self.dateAddInterval = None
        self.dateDepositAdded = None
        self.totalMonths = 0

        self.totalReserveShare = 0
        self.totalReserveCapital = 0
        self.totalReserveFinal = 0

        self.buyedInfos: list[BuyedInfo] = []
        self.sellInfos: list[SellInfo] = []
        self.reinvestInfos: list[ReinvestInfo] = []
        self.depositAddInfos: list[DepositAddInfo] = []

        self.lastBuyIndex = 0
        self.lastSellIndex = 0
        self.lastReinvestIndex = 0

    def add_sell_info(self, info: SellInfo):
        self.sellInfos.append(info)

    def add_reinvest_info(self, info: ReinvestInfo):
        self.reinvestInfos.append(info)

    def add_buyed_info(self, info: BuyedInfo):
        self.buyedInfos.append(info)

    def add_depositAdd_info(self, info: DepositAddInfo):
        self.depositAddInfos.append(info)
