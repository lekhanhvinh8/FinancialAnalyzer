"""
Build the Median1000 strategy trio from config, in one place.

THE None CONVENTION

  Every gate and condition in config.py can be switched off by setting it to
  None, and None always means the same thing: that condition is not applied.
  What "not applied" does depends on which of the two kinds it is.

  Filters — MIN_SIGNAL3, SELL_MIN_SIGNAL1, SELL_MIN_ZDEV, REINVEST_MIN_SIGNAL1.
  These only ever block an action that the primary condition already wants to
  take. None removes the restriction, so the arm acts MORE often. Implemented by
  handing the strategy an empty map, which is what its `if self.signalX_map`
  guard already tests.

  Primary conditions — PERCENT_BUY, PERCENT_SELL, PERCENT_REINVEST. These are
  the reason an action happens at all, so switching one off replaces the whole
  arm with its neutral base class:

      PERCENT_BUY      = None  ->  BuyIntervalStrategy   buy every interval
      PERCENT_SELL     = None  ->  SellStrategy          never sell
      PERCENT_REINVEST = None  ->  ReinvestStrategy      never reinvest

  Buy looks inverted next to the other two and is not: for the buy arm, doing
  nothing IS buying every interval, because the money has to go somewhere. For
  sell and reinvest, doing nothing is standing still. The asymmetry is in the
  three arms, not in the convention — and these three base classes are exactly
  the comparison arm run_all already measures against.

  Setting all three PERCENT_* to None therefore turns the median1000 arm into
  the interval arm, and every symbol's diff must come out at 0.00. That is a
  cheap end-to-end check on the engine, available at any time.

  This module exists so that the convention lives in one place. run_all and
  sweep_sell_signal1 both build the same trio, and when the rule was written twice
  they disagreed: the sweep honoured None for z_dev in its skip check but still
  applied the gate afterwards.
"""

from analyze.strategies.buy import BuyMedian1000Strategy, BuyIntervalStrategy
from analyze.strategies.sell import SellMedian1000Strategy, SellStrategy
from analyze.strategies.reinvest import ReInvestMedian1000Strategy, ReinvestStrategy
from analyze.median1000 import config

# Distinguishes "caller said nothing, use config" from "caller said None, disable
# it" — both are None to a normal default.
_FROM_CONFIG = object()


def make_median_strategies(signal3_map: dict | None = None,
                           signal1_map: dict | None = None,
                           reinvest_signal1_map: dict | None = None,
                           zdev_map: dict | None = None,
                           min_signal1=_FROM_CONFIG,
                           percent_buy=_FROM_CONFIG,
                           buy_window=_FROM_CONFIG,
                           reinvest_min_signal1=_FROM_CONFIG,
                           percent_reinvest=_FROM_CONFIG,
                           percent_sell=_FROM_CONFIG,
                           sell_window=_FROM_CONFIG,
                           reinvest_timeout_days=_FROM_CONFIG,
                           min_signal3=_FROM_CONFIG):
    """
    Returns (buy, sell, reinvest) built from config, honouring the None
    convention documented at the top of this module.

    min_signal1, percent_buy, buy_window, reinvest_min_signal1,
    percent_reinvest, percent_sell, sell_window and reinvest_timeout_days
    override their config values — the sweeps vary one parameter
    per cell. Passing None disables that one setting
    (per the convention above) while leaving config alone; omitting it uses
    config. buy_window is a size, not a condition, so None is not meaningful for
    it and it is simply passed through.
    """
    s1_min = config.SELL_MIN_SIGNAL1 if min_signal1 is _FROM_CONFIG else min_signal1
    s3_min = config.MIN_SIGNAL3 if min_signal3 is _FROM_CONFIG else min_signal3
    pct_buy = config.PERCENT_BUY if percent_buy is _FROM_CONFIG else percent_buy
    buy_w = (getattr(config, "BUY_MEDIAN_WINDOW", 1000)
             if buy_window is _FROM_CONFIG else buy_window)

    # Sell is built first: the other two hold a reference to it so they can stand
    # down on a bar it would sell. The engine order is sell -> reinvest -> buy, so
    # without that a bar satisfying both conditions liquidates and re-enters the
    # same day. Impossible while PERCENT_BUY <= PERCENT_SELL, since the price
    # conditions are complementary — and immediately real once a sweep moves
    # PERCENT_BUY above PERCENT_SELL.
    pct_sell = (config.PERCENT_SELL
                if percent_sell is _FROM_CONFIG else percent_sell)
    sell_w = (getattr(config, "SELL_MEDIAN_WINDOW", 1000)
              if sell_window is _FROM_CONFIG else sell_window)
    if pct_sell is None:
        sell = SellStrategy()
    else:
        sell = SellMedian1000Strategy(
            percentSell=pct_sell, use_pe=config.USE_PE, medianWindow=sell_w,
            # An empty map is how each gate is switched off; the strategy's own
            # `if self.signalX_map` guard then skips the comparison entirely, so
            # the threshold beside it is never read.
            signal3_map=(signal3_map or {}) if s3_min is not None else {},
            min_signal3=s3_min if s3_min is not None else 0.0,
            signal1_map=(signal1_map or {}) if s1_min is not None else {},
            min_signal1=s1_min if s1_min is not None else 0.0,
            zdev_map=(zdev_map or {}) if config.SELL_MIN_ZDEV is not None else {},
            min_zdev=config.SELL_MIN_ZDEV if config.SELL_MIN_ZDEV is not None else 0.0,
        )

    # A no-op SellStrategy never fires, so there is nothing to stand down for.
    sell_ref = sell if isinstance(sell, SellMedian1000Strategy) else None

    if pct_buy is None:
        buy = BuyIntervalStrategy()
    else:
        buy = BuyMedian1000Strategy(percentBuy=pct_buy, use_pe=config.USE_PE,
                                    medianWindow=buy_w, sell_strategy=sell_ref)

    pct_ri = (config.PERCENT_REINVEST
              if percent_reinvest is _FROM_CONFIG else percent_reinvest)
    if pct_ri is None:
        reinvest = ReinvestStrategy()
    else:
        ri_min = (config.REINVEST_MIN_SIGNAL1
                  if reinvest_min_signal1 is _FROM_CONFIG else reinvest_min_signal1)
        reinvest = ReInvestMedian1000Strategy(
            percentReinvest=pct_ri, use_pe=config.USE_PE,
            timeoutDays=(config.REINVEST_TIMEOUT_DAYS
                         if reinvest_timeout_days is _FROM_CONFIG
                         else reinvest_timeout_days),
            timeoutPercent=config.REINVEST_TIMEOUT_PERCENT,
            signal1_map=(reinvest_signal1_map or {}) if ri_min is not None else {},
            min_signal1=ri_min if ri_min is not None else 0.0,
            sell_strategy=sell_ref,
        )

    return buy, sell, reinvest


def make_interval_strategies():
    """The neutral arm: buy every interval, never sell, never reinvest."""
    return BuyIntervalStrategy(), SellStrategy(), ReinvestStrategy()
