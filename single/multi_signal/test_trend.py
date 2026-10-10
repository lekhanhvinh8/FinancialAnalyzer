"""
The index trend reading and the three gates that read it, and the trading cost
the engine can now charge -- a trend filter trades often enough for it to matter.

Run with:  python -m single.multi_signal.test_trend

No database: the readings are checked on a made-up series whose answers are
known by hand, and the gates on hand-built maps.
"""

import sys

import numpy as np
import pandas as pd

from single.multi_signal.trend_map import compute
from single.strategies.buy import BuyMedian1000Strategy
from single.strategies.sell import SellMedian1000Strategy
from single.strategies.reinvest import ReInvestMedian1000Strategy
from core.window_stats import IndexCloses, RangeDaysClose


def main() -> int:
    fails = []

    def check(cond, msg):
        if not cond:
            fails.append(msg)

    # 300 flat bars at 100, then 100 bars at 110.
    idx = pd.date_range("2020-01-01", periods=400, freq="D")
    close = pd.Series([100.0] * 300 + [110.0] * 100, index=idx)
    t = compute(close)
    check(t["ma200"].iloc[:199].isna().all(), "ma200 must be NaN before 200 bars")
    check(abs(t["ma200"].iloc[299]) < 1e-9, "flat series sits exactly on its MA")
    # bar 300: MA = (199*100 + 110)/200 = 100.05, so +9.945%
    check(abs(t["ma200"].iloc[300] - (110 / 100.05 - 1) * 100) < 1e-9,
          "ma200 at the first 110 bar")
    check(t["mom12_1"].iloc[:252].isna().all(), "mom12_1 must be NaN before 252 bars")
    # bar 330: close 21 bars ago is bar 309 (110), 252 bars ago is bar 78 (100)
    check(abs(t["mom12_1"].iloc[330] - 10.0) < 1e-9, "mom12_1 skips the last month")
    check(abs(t["mom12_1"].iloc[315]) < 1e-9, "mom12_1 ignores the last 21 bars")

    # Gates. Row 1500, a range row so the median-window guards pass.
    i = 1500
    crc = {i: IndexCloses()}
    crc[i].rangeDayCloses[1000] = RangeDaysClose(200, 100, 50, 80, 100, 120,
                                                 0, 0, 0, 0, 0, 0)
    for value, buy_ok, sell_ok in ((3.0, True, False), (-1.0, False, True)):
        tm = {i: value}
        buy = BuyMedian1000Strategy(percentBuy=None, trend_map=tm, min_trend=0.0)
        sell = SellMedian1000Strategy(percentSell=None, trend_map=tm, max_trend=0.0)
        rei = ReInvestMedian1000Strategy(percentReinvest=None, trend_map=tm, min_trend=0.0)
        check(buy.check(i, 100.0, None, crc) == buy_ok, f"buy at trend {value}")
        check(sell.check(i, 100.0, None, crc) == sell_ok, f"sell at trend {value}")
        check(rei.check(i, 100.0, None, crc) == buy_ok, f"reinvest at trend {value}")
    # A missing reading means do not act, on every arm.
    for s in (BuyMedian1000Strategy(percentBuy=None, min_trend=0.0),
              SellMedian1000Strategy(percentSell=None, max_trend=0.0),
              ReInvestMedian1000Strategy(percentReinvest=None, min_trend=0.0)):
        check(not s.check(i, 100.0, None, crc), f"{type(s).__name__} acted without a reading")
    # Off means off: no map, no threshold, the gate takes no part.
    check(BuyMedian1000Strategy(percentBuy=None).check(i, 100.0, None, crc),
          "a buy arm with no conditions must buy")

    # Costs. A flat price, DCA with a 1% buy cost: every dong buys 0.99 of a
    # dong's shares, so the result is exactly -1%. A full sell and reinvest at a
    # flat price with 0.5% / 0.25% then leaves 0.995 * 0.9975 of the holding.
    from single.engine import estimate, Sellor, Reinvestor
    from single.models import InvestmentTracker
    from single.strategies.buy import BuyIntervalStrategy
    days = pd.DataFrame({"time": pd.date_range("2020-01-01", periods=90, freq="D"),
                         "close": [1.0] * 90})
    _, _, g, *_ = estimate(days, 1000.0, BuyIntervalStrategy(), None, None, {},
                           buy_cost=0.01)
    check(abs(g - (-1.0)) < 1e-9, f"1% buy cost should give -1.00%, got {g:.4f}")
    _, _, g0, *_ = estimate(days, 1000.0, BuyIntervalStrategy(), None, None, {})
    check(abs(g0) < 1e-9, "zero cost must leave a flat price at 0%")
    tr = InvestmentTracker()
    tr.buyCost, tr.sellCost = 0.0025, 0.005
    tr.totalShare = tr.totalCapital = tr.totalCurrentCapital = 990.0
    Sellor().sell(tr, 990.0, 1, 1.0, False)
    Reinvestor().reinvest(tr, tr.totalReserveFinal, 2, 1.0, False)
    check(abs(tr.totalShare - 990 * 0.995 * 0.9975) < 1e-9, "sell + reinvest cost")

    if fails:
        print(f"LOI ({len(fails)}):")
        for f in fails:
            print("  -", f)
        return 1
    print("OK — ma200 va mom12_1 dung so tinh tay, ba cong doc dung chieu, "
          "thieu so lieu thi dung yen, phi tru dung")
    return 0


if __name__ == "__main__":
    sys.exit(main())
