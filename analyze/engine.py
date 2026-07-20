import pandas as pd
from .models import (
    InvestmentTracker, BuyedInfo, SellInfo, ReinvestInfo, DepositAddInfo,
)


class Sellor:
    def sell(self, tracker: InvestmentTracker, sellFinal, index, close, isPrint):
        totalFinal = tracker.totalShare * close
        if tracker.totalShare <= 0 or tracker.totalCapital <= 0 or sellFinal <= 0:
            return

        tracker.lastSellIndex = index

        sellShare          = sellFinal * tracker.totalShare / totalFinal
        sellCapital        = sellFinal * tracker.totalCapital / totalFinal
        sellCurrentCapital = sellFinal * tracker.totalCurrentCapital / totalFinal

        tracker.totalReserveShare   += sellShare
        tracker.totalReserveCapital += sellCapital
        tracker.totalReserveFinal   += sellFinal

        tracker.totalShare          -= sellShare
        tracker.totalCapital        -= sellCapital
        tracker.totalCurrentCapital -= sellCurrentCapital

        sellGrowthRatito        = (sellFinal - sellCapital) / sellCapital * 100
        sellcurrentGrowthRatito = (sellFinal - sellCurrentCapital) / sellCurrentCapital * 100

        tracker.add_sell_info(SellInfo(
            index=index, close=close,
            sellShare=sellShare, sellCapital=sellCapital,
            sellFinal=sellFinal, sellGrowthRatito=sellGrowthRatito,
        ))

        if isPrint:
            print(f'sell --- index: {index}, close: {close}, sellShare: {sellShare:.2f}, '
                  f'sellFinal: {sellFinal:.0f}, sellGrowthRatito: {sellGrowthRatito:.2f}%')


class Reinvestor:
    def reinvest(self, tracker: InvestmentTracker, reInvestFinal, index, close, isPrint):
        tracker.lastReinvestIndex = index

        reInvestShare   = reInvestFinal * tracker.totalReserveShare / tracker.totalReserveFinal
        reInvestCapital = reInvestFinal * tracker.totalReserveCapital / tracker.totalReserveFinal

        tracker.totalReserveShare   -= reInvestShare
        tracker.totalReserveCapital -= reInvestCapital
        tracker.totalReserveFinal   -= reInvestFinal

        tracker.totalCapital        += reInvestCapital
        tracker.totalCurrentCapital += reInvestFinal
        tracker.totalShare          += reInvestFinal / close

        tracker.add_reinvest_info(ReinvestInfo(
            index=index, close=close,
            reInvestShare=reInvestShare,
            reInvestFinal=reInvestFinal,
            reInvestCapital=reInvestCapital,
        ))

        if isPrint:
            print(f'reinvest --- index: {index}, close: {close}, '
                  f'reInvestCapital: {reInvestCapital:.0f}, reInvestFinal: {reInvestFinal:.0f}')


class Buyer:
    def buy(self, tracker: InvestmentTracker, finalBuy, reinvestFinal, index, close, isPrint):
        if finalBuy > 0:
            tracker.lastBuyIndex = index
            tracker.intervalAmount  -= finalBuy
            tracker.totalCapital        += finalBuy
            tracker.totalCurrentCapital += finalBuy
            tracker.totalShare          += finalBuy / close
            tracker.add_buyed_info(BuyedInfo(
                index=index, close=close,
                finalBuy=finalBuy, numberOfShareCanBy=finalBuy / close,
            ))


class DepositAdder:
    def add(self, tracker: InvestmentTracker, index, depositPercent, now, isPrint):
        year, month = now.year, now.month
        if (tracker.dateDepositAdded is None
                or year > tracker.dateDepositAdded.year
                or (year == tracker.dateDepositAdded.year and month > tracker.dateDepositAdded.month)):
            tracker.dateDepositAdded = now
            interest = tracker.totalReserveFinal * (depositPercent / 100) / 12
            tracker.totalReserveFinal += interest
            tracker.add_depositAdd_info(DepositAddInfo(
                index=index, totalReserveInterest=interest,
            ))


def estimate(
    df: pd.DataFrame,
    intervalMoney: float,
    buyStrategy,
    sellStrategy,
    reinvestStrategy,
    cal_range_close: dict,
    isPrint: bool = False,
) -> tuple:
    tracker = InvestmentTracker()
    finalClose = df['close'].iloc[-1] * 1000

    for index, row in df.iterrows():
        close   = row['close'] * 1000
        pe      = row.get('pe_ratio', None)
        timeCol = row['time']
        year, month = timeCol.year, timeCol.month

        DepositAdder().add(tracker, index, 4, timeCol, isPrint)

        if (tracker.dateAddInterval is None
                or year > tracker.dateAddInterval.year
                or (year == tracker.dateAddInterval.year and month > tracker.dateAddInterval.month)):
            tracker.intervalAmount += intervalMoney
            tracker.dateAddInterval = timeCol
            tracker.totalMonths += 1

        if sellStrategy is not None:
            sellStrategy.considerSell(tracker, index, close, pe, cal_range_close, isPrint)

        if reinvestStrategy is not None:
            reinvestStrategy.considerReinvest(tracker, index, close, pe, cal_range_close, isPrint)

        if buyStrategy is not None:
            buyStrategy.considerBuy(tracker, index, close, pe, cal_range_close, isPrint)
        else:
            if tracker.intervalAmount > 0:
                tracker.totalReserveCapital += tracker.intervalAmount
                tracker.totalReserveFinal   += tracker.intervalAmount
                tracker.intervalAmount = 0

    finalMoney       = finalClose * tracker.totalShare
    allTotalCapital  = tracker.totalCapital + tracker.totalReserveCapital + tracker.intervalAmount
    allTotalFinal    = finalMoney + tracker.totalReserveFinal + tracker.intervalAmount
    allRatioGrowth   = (allTotalFinal - allTotalCapital) / (allTotalCapital or 1) * 100

    growthRatio        = (finalMoney - tracker.totalCapital) / (tracker.totalCapital or 1) * 100
    growthCurrentRatio = (finalMoney - tracker.totalCurrentCapital) / (tracker.totalCurrentCapital or 1) * 100
    reserveGrowthRatio = (tracker.totalReserveFinal - tracker.totalReserveCapital) / (tracker.totalReserveCapital or 1) * 100

    if isPrint:
        print(f'''
        totalMonths            {tracker.totalMonths}
        totalShare             {round(tracker.totalShare)}
        totalCapital           {round(tracker.totalCapital)}
        totalCurrentCapital    {round(tracker.totalCurrentCapital)}
        finalMoney             {round(finalMoney)}
        growthRatio            {round(growthRatio, 2)}%
        growthCurrentRatio     {round(growthCurrentRatio, 2)}%
        intervalAmount         {round(tracker.intervalAmount)}
        totalReserveShare      {round(tracker.totalReserveShare)}
        totalReserveCapital    {round(tracker.totalReserveCapital)}
        totalReserveFinal      {round(tracker.totalReserveFinal)}
        reserveGrowthRatio     {round(reserveGrowthRatio, 2)}%
        totalBuys              {len(tracker.buyedInfos)}
        totalSells             {len(tracker.sellInfos)}
        totalReinvest          {len(tracker.reinvestInfos)}
        allTotalCapital        {round(allTotalCapital)}
        allTotalFinal          {round(allTotalFinal)}
        allRatioGrowth         {round(allRatioGrowth, 2)}%
        ''')

    extra = {
        "totalMonths":          tracker.totalMonths,
        "totalShare":           tracker.totalShare,
        "totalCapital":         tracker.totalCapital,
        "totalCurrentCapital":  tracker.totalCurrentCapital,
        "finalMoney":           finalMoney,
        "growthRatio":          growthRatio,
        "growthCurrentRatio":   growthCurrentRatio,
        "intervalAmount":       tracker.intervalAmount,
        "totalReserveShare":    tracker.totalReserveShare,
        "totalReserveCapital":  tracker.totalReserveCapital,
        "totalReserveFinal":    tracker.totalReserveFinal,
        "reserveGrowthRatio":   reserveGrowthRatio,
    }
    return allTotalCapital, allTotalFinal, allRatioGrowth, tracker.buyedInfos, tracker.sellInfos, tracker.reinvestInfos, extra
