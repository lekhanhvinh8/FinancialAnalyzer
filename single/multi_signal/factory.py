"""
Build the Median1000 strategy trio from config, in one place.

THE None CONVENTION

  Every gate and condition in config.py can be switched off by setting it to
  None, and None always means the same thing: that condition is not applied.
  What "not applied" does depends on which of the two kinds it is.

  Filters — MIN_SIGNAL3, SELL_MIN_SIGNAL1, SELL_MIN_ZDEV, SELL_MIN_PELOG,
  REINVEST_MIN_SIGNAL1.
  These only ever block an action that the primary condition already wants to
  take. None removes the restriction, so the arm acts MORE often. Implemented by
  handing the strategy an empty map, which is what its `if self.signalX_map`
  guard already tests.

  Primary conditions — PERCENT_BUY, PERCENT_SELL, PERCENT_REINVEST. These are
  the reason an action happens at all, so switching one off replaces the whole
  arm with its neutral base class:

      PERCENT_BUY      = None  ->  BuyIntervalStrategy   buy every interval
      PERCENT_SELL     = None  ->  SellStrategy          never sell *
      PERCENT_REINVEST = None  ->  ReinvestStrategy      never reinvest

      * only while PERCENT_SELL_BOTTOM is also None. The sell arm has two price
        conditions and each switches off on its own; the arm falls back to the
        base class when both are off. In the shipped config the bottom condition
        is None, so PERCENT_SELL = None does mean "never sell" and the engine
        check below still holds.

  Buy looks inverted next to the other two and is not: for the buy arm, doing
  nothing IS buying every interval, because the money has to go somewhere. For
  sell and reinvest, doing nothing is standing still. The asymmetry is in the
  three arms, not in the convention — and these three base classes are exactly
  the comparison arm run_all already measures against.

  PERCENT_SELL_BOTTOM and PERCENT_REINVEST_TOP are primary conditions too, but
  SECOND ones rather than the only one, so None removes the extra condition and
  leaves the arm intact instead of replacing it. Neither takes a map, so the
  empty-map idiom the filters use does not apply and the strategy tests them for
  None itself. An arm falls back to its base class only when BOTH of its price
  conditions are None.

  EVERY CONDITION ON EVERY ARM IS AND'D. These two were OR'd with the arm's
  first price test until they became the only ORs in a list of ANDs, and a reader
  had to know which parameters were in the OR group before the condition list
  could be read at all. Both ship as None, so the change is unmeasurable — it is
  a change to what the code says, made while nothing depended on it.

  Setting all three PERCENT_* to None therefore turns the median1000 arm into
  the interval arm, and every symbol's diff must come out at 0.00. That is a
  cheap end-to-end check on the engine, available at any time.

  This module exists so that the convention lives in one place. run_all and
  sweep_sell_signal1 both build the same trio, and when the rule was written twice
  they disagreed: the sweep honoured None for z_dev in its skip check but still
  applied the gate afterwards.
"""

import math

import numpy as np
import pandas as pd

import database as db
from single.strategies.buy import BuyMedian1000Strategy, BuyIntervalStrategy
from single.strategies.sell import SellMedian1000Strategy, SellStrategy
from single.strategies.reinvest import ReInvestMedian1000Strategy, ReinvestStrategy
from single.multi_signal import config

# Distinguishes "caller said nothing, use config" from "caller said None, disable
# it" — both are None to a normal default.
_FROM_CONFIG = object()


def make_median_strategies(signal3_map: dict | None = None,
                           signal1_map: dict | None = None,
                           reinvest_signal1_map: dict | None = None,
                           zdev_map: dict | None = None,
                           pelog_map: dict | None = None,
                           breadth_map: dict | None = None,
                           trend_map: dict | None = None,
                           min_signal1=_FROM_CONFIG,
                           percent_buy=_FROM_CONFIG,
                           buy_window=_FROM_CONFIG,
                           reinvest_min_signal1=_FROM_CONFIG,
                           percent_reinvest=_FROM_CONFIG,
                           percent_reinvest_top=_FROM_CONFIG,
                           percent_sell=_FROM_CONFIG,
                           percent_sell_bottom=_FROM_CONFIG,
                           sell_window=_FROM_CONFIG,
                           reinvest_timeout_days=_FROM_CONFIG,
                           min_signal3=_FROM_CONFIG,
                           min_zdev=_FROM_CONFIG,
                           min_pelog=_FROM_CONFIG,
                           buy_max_breadth=_FROM_CONFIG,
                           sell_min_breadth=_FROM_CONFIG,
                           reinvest_max_breadth=_FROM_CONFIG):
    """
    Returns (buy, sell, reinvest) built from config, honouring the None
    convention documented at the top of this module.

    min_signal1, percent_buy, buy_window, reinvest_min_signal1,
    percent_reinvest, percent_sell, sell_window, reinvest_timeout_days,
    min_signal3, min_zdev and min_pelog override their config values — the sweeps vary one parameter
    per cell. Passing None disables that one setting
    (per the convention above) while leaving config alone; omitting it uses
    config. buy_window is a size, not a condition, so None is not meaningful for
    it and it is simply passed through.
    """
    s1_min = config.SELL_MIN_SIGNAL1 if min_signal1 is _FROM_CONFIG else min_signal1
    s3_min = config.MIN_SIGNAL3 if min_signal3 is _FROM_CONFIG else min_signal3
    z_min  = config.SELL_MIN_ZDEV if min_zdev is _FROM_CONFIG else min_zdev
    pl_min = (getattr(config, "SELL_MIN_PELOG", None)
              if min_pelog is _FROM_CONFIG else min_pelog)
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
    # A second primary condition, so None means "no second trigger". It cannot use
    # the empty-map idiom the filters share — there is no map, only a threshold —
    # and the strategy tests it for None directly.
    pct_sell_bot = (getattr(config, "PERCENT_SELL_BOTTOM", None)
                    if percent_sell_bottom is _FROM_CONFIG else percent_sell_bottom)
    # The arm has two price triggers and stops selling only when BOTH are off.
    # PERCENT_SELL = None on its own now means "no median trigger", which is what
    # lets sweep_sell_bottom judge the bottom trigger on its own instead of only
    # as an increment on top of the median one.
    # An arm stands down only when it has NO condition at all. A breadth gate is
    # a condition, so a profile that switches the price triggers off and the
    # basket on keeps the arm alive -- which is the whole point of merging the
    # two packages.
    sell_breadth = (getattr(config, "SELL_MIN_BREADTH", None)
                    if sell_min_breadth is _FROM_CONFIG else sell_min_breadth)
    # The index trend gates (trend_map.py) are read from config only; a sweep
    # varies them through config overrides like everything else now.
    sell_trend = getattr(config, "SELL_MAX_TREND", None)
    buy_trend = getattr(config, "BUY_MIN_TREND", None)
    ri_trend = getattr(config, "REINVEST_MIN_TREND", None)
    if (pct_sell is None and pct_sell_bot is None and sell_breadth is None
            and sell_trend is None):
        sell = SellStrategy()
    else:
        sell = SellMedian1000Strategy(
            breadth_map=breadth_map or {},
            min_breadth=sell_breadth,
            trend_map=trend_map or {},
            max_trend=sell_trend,
            percentSell=pct_sell, percentSellBottom=pct_sell_bot,
            use_pe=config.USE_PE, medianWindow=sell_w,
            # An empty map is how each gate is switched off; the strategy's own
            # `if self.signalX_map` guard then skips the comparison entirely, so
            # the threshold beside it is never read.
            signal3_map=(signal3_map or {}) if s3_min is not None else {},
            min_signal3=s3_min if s3_min is not None else 0.0,
            signal1_map=(signal1_map or {}) if s1_min is not None else {},
            min_signal1=s1_min if s1_min is not None else 0.0,
            zdev_map=(zdev_map or {}) if z_min is not None else {},
            min_zdev=z_min if z_min is not None else 0.0,
            pelog_map=(pelog_map or {}) if pl_min is not None else {},
            min_pelog=pl_min if pl_min is not None else 0.0,
        )

    # A no-op SellStrategy never fires, so there is nothing to stand down for.
    sell_ref = sell if isinstance(sell, SellMedian1000Strategy) else None

    buy_breadth = (getattr(config, "BUY_MAX_BREADTH", None)
                   if buy_max_breadth is _FROM_CONFIG else buy_max_breadth)
    if pct_buy is None and buy_breadth is None and buy_trend is None:
        buy = BuyIntervalStrategy()
    else:
        buy = BuyMedian1000Strategy(percentBuy=pct_buy, use_pe=config.USE_PE,
                                    breadth_map=breadth_map or {},
                                    max_breadth=buy_breadth,
                                    trend_map=trend_map or {},
                                    min_trend=buy_trend,
                                    medianWindow=buy_w, sell_strategy=sell_ref)

    pct_ri = (config.PERCENT_REINVEST
              if percent_reinvest is _FROM_CONFIG else percent_reinvest)
    # Second primary condition, same shape as PERCENT_SELL_BOTTOM on the sell arm:
    # no map, only a threshold, and the strategy tests it for None itself. The arm
    # falls back to the base class only when BOTH price triggers are off — which
    # also drops the timeout valve with it, since that lives on the same class.
    pct_ri_top = (getattr(config, "PERCENT_REINVEST_TOP", None)
                  if percent_reinvest_top is _FROM_CONFIG else percent_reinvest_top)
    ri_breadth = (getattr(config, "REINVEST_MAX_BREADTH", None)
                  if reinvest_max_breadth is _FROM_CONFIG else reinvest_max_breadth)
    if pct_ri is None and pct_ri_top is None and ri_breadth is None and ri_trend is None:
        reinvest = ReinvestStrategy()
    else:
        ri_min = (config.REINVEST_MIN_SIGNAL1
                  if reinvest_min_signal1 is _FROM_CONFIG else reinvest_min_signal1)
        reinvest = ReInvestMedian1000Strategy(
            breadth_map=breadth_map or {},
            max_breadth=ri_breadth,
            trend_map=trend_map or {},
            min_trend=ri_trend,
            join_or=bool(getattr(config, 'REINVEST_JOIN_OR', False)),
            percentReinvest=pct_ri, percentReinvestTop=pct_ri_top,
            use_pe=config.USE_PE,
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


def build_pelog_map(symbol, df, cal_range_close, window: int | None = None) -> dict:
    """
    {row_index: ln(P/E / its own `window`-row median)} for SELL_MIN_PELOG.

    Lives here rather than in run_all or a sweep because the warmup rule below is
    not obvious and must be identical everywhere. This module's docstring records
    what happens when a shared rule gets written twice.

    cal_range_close must already carry `window` — load_range_stats has to be
    called with it in range_days, or every row is skipped.

    THE WARMUP RULE, AND WHY IT IS NOT JUST "SKIP THE FIRST `window` ROWS"

      range_calc builds these medians with rolling(window, min_periods=1), so
      pe_median is populated from the very first row a symbol has a P/E. On that
      row the median of one observation IS that observation, and ln(P/E/median)
      comes out at exactly 0.000 — the gate reads "P/E is precisely normal" while
      knowing nothing at all. That is worse than reading nothing, because nothing
      makes the gate stand aside. 31 of 59 symbols have P/E starting later than
      their price, which is 13,312 such rows.

      Counting rows is not enough either. The window is a row window, not an
      observation window, and 16 symbols have holes in the middle of their P/E —
      up to 559 consecutive days for KDH — because a company with a non-positive
      trailing-year profit gets no P/E row at all. So the test is on the number of
      REAL observations inside the trailing window, and it must be the full
      `window` of them: a partly-filled window is effectively a shorter one, and
      the spread of this quantity depends on the window (p95 = 0.094 * w^0.360),
      so a threshold would silently mean something stricter there.

    AND THE ROW'S OWN P/E HAS TO BE REAL, NOT CARRIED FORWARD

      runner.load_symbol_df forward-fills pe_ratio, and syncs/range_stats does the
      same before building pe_median, so the two agree — but a loss period has no
      P/E rows at all and the ffill carries the last pre-loss value across it, up
      to 559 days for KDH. Both sides of the ratio then hold the same frozen
      number, ln(P/E/median) drifts to 0, and the gate reports "perfectly normal"
      and BLOCKS the sell for the whole year the company was losing money. That is
      backwards, so rows without a real observation are dropped and the gate stands
      aside there instead.

    Rows that fail either test are simply absent. The strategy treats a missing
    row as "gate stands aside", which is right for all of them: no median worth
    trusting, or no earnings to have grown into the price.
    """
    window = window or getattr(config, "PE_MEDIAN_WINDOW", 500)
    if df is None or "pe_ratio" not in df.columns or not cal_range_close:
        return {}

    pe = pd.to_numeric(df["pe_ratio"], errors="coerce").to_numpy(dtype=float)
    # Real observations only — see above. The raw table has a row per trading day
    # the trailing-year profit was positive, and nothing on the days it was not.
    raw = db.load_pe_ratios(symbol)
    real_dates = set(raw.index) if not raw.empty else set()
    is_real = np.array([pd.Timestamp(t) in real_dates for t in df["time"]], dtype=bool)
    have = np.isfinite(pe) & (pe > 0) & is_real
    if not have.any():
        return {}
    # Prefix sums so the count inside any trailing window is one subtraction.
    filled = np.concatenate(([0], np.cumsum(have)))

    out: dict = {}
    for i in range(len(pe)):
        if not have[i]:
            continue
        lo = i - window + 1
        if lo < 0 or filled[i + 1] - filled[lo] < window:
            continue
        ic = cal_range_close.get(i)
        if ic is None or window not in ic.rangeDayCloses:
            continue
        med = ic.rangeDayCloses[window].pct50(True)
        if med and med > 0:
            out[i] = math.log(pe[i] / med)
    return out
