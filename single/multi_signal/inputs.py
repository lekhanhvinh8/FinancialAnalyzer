"""
Everything one symbol's backtest reads, loaded once, for run_all and the sweeps.

WHY THIS IS ONE MODULE

  run_all and every sweep_*.py used to carry their own copy of this loading
  code, and the copies drifted: the sweeps never loaded the breadth map, so once
  config.py switched the breadth gates on, every sweep ran a buy arm that could
  never buy -- a missing breadth reading means "do not act". Nothing failed; the
  numbers were simply about a different strategy than the one run_all reports.

  So the rule is written once. A sweep cell is "run_all with these config
  values", and it reaches the strategies through exactly the same code.

CACHED PER SYMBOL

  A sweep asks for the same symbol under many configurations, and most of them
  read the same signal at the same window. Each loader below caches on its
  arguments, so a 500-cell grid loads each distinct input once.
"""

import pandas as pd

import database as db
from single.runner import load_symbol_df
from single.multi_signal.factory import build_pelog_map


def windows_for(cfg) -> set:
    """The range_stats windows a configuration reads."""
    w = {1000, getattr(cfg, "BUY_MEDIAN_WINDOW", 1000),
         getattr(cfg, "SELL_MEDIAN_WINDOW", 1000)}
    if cfg.SELL_MIN_PELOG is not None:
        w.add(getattr(cfg, "PE_MEDIAN_WINDOW", 500))
    return w


def breadth_on(cfg) -> bool:
    return any(getattr(cfg, k, None) is not None for k in
               ("BUY_MAX_BREADTH", "SELL_MIN_BREADTH", "REINVEST_MAX_BREADTH"))


class SymbolInputs:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.df = load_symbol_df(symbol)
        self.crc = None
        self._d2i = {pd.Timestamp(t): i for i, t in enumerate(self.df["time"])}
        self._cache = {}

    def load_range_stats(self, windows) -> bool:
        self.crc = db.load_range_stats(self.symbol, self.df, range_days=set(windows))
        return self.crc is not None

    def _by_row(self, series) -> dict:
        out = {}
        for date, v in series.items():
            i = self._d2i.get(pd.Timestamp(date))
            if i is not None and v is not None:
                out[i] = float(v)
        return out

    def _cached(self, key, load):
        if key not in self._cache:
            self._cache[key] = load()
        return self._cache[key]

    def trend(self, window: int, col: str) -> dict:
        """signal1_slope or signal3_sharpe at one window, {row: value}."""
        def load():
            d = db.load_trend_signals(self.symbol, window_days=window)
            return {} if d.empty else self._by_row(d[col])
        return self._cached(("trend", window, col), load)

    def zdev(self, stat_window: int) -> dict:
        def load():
            d = db.load_zdev(self.symbol, 1000, stat_window)
            return {} if d.empty else self._by_row(d["z_dev"])
        return self._cached(("zdev", stat_window), load)

    def pelog(self, window: int) -> dict:
        return self._cached(("pelog", window), lambda: build_pelog_map(
            self.symbol, self.df, self.crc, window))

    def breadth(self, signal: str, universe: str, window: int) -> dict:
        from single.multi_signal.breadth_map import build_breadth_map
        return self._cached(("breadth", signal, universe, window),
                            lambda: build_breadth_map(self.df, signal=signal,
                                                      universe=universe,
                                                      window=window))

    def maps(self, cfg):
        """
        (maps, first_idx, skip_reason) for one configuration.

        `maps` are the keyword arguments make_median_strategies takes. A gate set
        to None is not loaded at all: an unused signal must not appear in
        first_idx, or its warmup would push the start index forward for a filter
        that is switched off.

        `first_idx` is the row each input becomes available, by name. The start
        of evaluation is the latest of them -- before that the early period
        would run a different strategy than the later one, because whichever
        inputs are missing simply do not filter. The breadth line is left out on
        purpose here; see run_all for why that is a known open question.
        """
        buy_w = getattr(cfg, "BUY_MEDIAN_WINDOW", 1000)
        sell_w = getattr(cfg, "SELL_MEDIAN_WINDOW", 1000)

        s3 = self.trend(1000, "signal3_sharpe") if cfg.MIN_SIGNAL3 is not None else {}
        s1 = (self.trend(cfg.SELL_SIGNAL1_WINDOW, "signal1_slope")
              if cfg.SELL_MIN_SIGNAL1 is not None else {})
        ri = {}
        if cfg.REINVEST_MIN_SIGNAL1 is not None:
            ri = (s1 if s1 and cfg.REINVEST_SIGNAL1_WINDOW == cfg.SELL_SIGNAL1_WINDOW
                  else self.trend(cfg.REINVEST_SIGNAL1_WINDOW, "signal1_slope"))
        z = {}
        if cfg.SELL_MIN_ZDEV is not None:
            z = self.zdev(cfg.SELL_ZDEV_WINDOW)
            if not z:
                return None, None, f"no z_dev at stat_window={cfg.SELL_ZDEV_WINDOW}"
        pl = {}
        if cfg.SELL_MIN_PELOG is not None:
            pe_w = getattr(cfg, "PE_MEDIAN_WINDOW", 500)
            pl = self.pelog(pe_w)
            if not pl:
                return None, None, f"no usable P/E at window={pe_w}"
        bm = (self.breadth(cfg.BREADTH_SIGNAL, cfg.BREADTH_UNIVERSE, cfg.BREADTH_WINDOW)
              if breadth_on(cfg) else {})

        first_idx = {
            # The reinvest arm still guards on index > 1000; buy and sell each
            # guard on their own window, so the longest of the three sets the floor.
            "median1000":       max(1000, buy_w, sell_w),
            "signal1":          min(s1) if s1 else None,
            "signal3":          min(s3) if s3 else None,
            "reinvest_signal1": min(ri) if ri else None,
            "zdev":             min(z) if z else None,
            "pelog":            min(pl) if pl else None,
        }
        maps = dict(signal3_map=s3, signal1_map=s1, reinvest_signal1_map=ri,
                    zdev_map=z, pelog_map=pl, breadth_map=bm)
        return maps, {k: v for k, v in first_idx.items() if v is not None}, None
