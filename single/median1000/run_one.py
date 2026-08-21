"""
Test the Median1000 strategy on a single symbol.

Usage:
    python single/median1000/run_one.py
    python single/median1000/run_one.py HPG

Edit config.py to tune strategy parameters.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import os
import pandas as pd
import database as db
from single.runner import load_symbol_df, run_estimate
from export.chart import save_backtest_chart
from single.median1000 import config
from single.median1000.factory import (make_median_strategies,
                                        make_interval_strategies, build_pelog_map)

CHARTS_DIR = Path(__file__).parent / "charts"
SYMBOL     = sys.argv[1].upper() if len(sys.argv) > 1 else "VN30"


def _signal_map(symbol, df, window, col):
    """{row_index: signal value} for one trend-signal window."""
    date_to_idx = {pd.Timestamp(row["time"]): i for i, row in df.iterrows()}
    sig = db.load_trend_signals(symbol, window_days=window)
    out = {}
    if not sig.empty:
        for date, v in sig[col].items():
            idx = date_to_idx.get(pd.Timestamp(date))
            if idx is not None:
                out[idx] = float(v)
    return out


def make_strategies(signal3_map=None, signal1_map=None, reinvest_signal1_map=None,
                    zdev_map=None, pelog_map=None):
    """
    Kept as a thin wrapper so existing callers and the __main__ block below do not
    change, but the trio itself now comes from the factory.

    It used to build its own, and had drifted: no churn guard on the buy or
    reinvest arms (d2ffc39 added that and this copy never got it), no
    BUY/SELL_MEDIAN_WINDOW, and none of SELL_MIN_PELOG, PERCENT_SELL_BOTTOM or
    PERCENT_REINVEST_TOP. It also read the gate thresholds straight from config,
    so a None there would have reached the strategy as a comparison against None
    rather than switching the gate off.

    Every one of those was invisible while the shipped config happened to line up
    — the churn guard in particular can only fire once PERCENT_BUY exceeds
    PERCENT_SELL, which it does not today. That is precisely the failure mode
    factory.py's docstring describes: a rule written twice, agreeing until it
    quietly does not.
    """
    return make_median_strategies(signal3_map, signal1_map,
                                  reinvest_signal1_map, zdev_map, pelog_map)


if __name__ == "__main__":
    db.init_db()
    CHARTS_DIR.mkdir(exist_ok=True)

    df = load_symbol_df(SYMBOL)
    print(f"Loaded {len(df)} rows | {df['time'].iloc[0].date()} -> {df['time'].iloc[-1].date()}")

    cal_range_close = db.load_range_stats(SYMBOL, df)
    if cal_range_close is None:
        print("ERROR: no range_stats in DB for", SYMBOL)
        sys.exit(1)

    s3 = _signal_map(SYMBOL, df, 1000, "signal3_sharpe")
    s1 = _signal_map(SYMBOL, df, config.SELL_SIGNAL1_WINDOW, "signal1_slope")
    ri_s1 = (s1 if config.REINVEST_SIGNAL1_WINDOW == config.SELL_SIGNAL1_WINDOW
             else _signal_map(SYMBOL, df, config.REINVEST_SIGNAL1_WINDOW, "signal1_slope"))

    zmap = {}
    if config.SELL_MIN_ZDEV is not None:
        _zd = db.load_zdev(SYMBOL, 1000, config.SELL_ZDEV_WINDOW)
        _d2i = {pd.Timestamp(r["time"]): i for i, r in df.iterrows()}
        if not _zd.empty:
            for date, z in _zd["z_dev"].items():
                idx = _d2i.get(pd.Timestamp(date))
                if idx is not None and z is not None:
                    zmap[idx] = float(z)

    pmap = {}
    if config.SELL_MIN_PELOG is not None:
        pmap = build_pelog_map(SYMBOL, df, cal_range_close,
                               getattr(config, "PE_MEDIAN_WINDOW", 500))
        if not pmap:
            print(f"ERROR: no usable P/E for {SYMBOL} at "
                  f"window={getattr(config, 'PE_MEDIAN_WINDOW', 500)}")
            sys.exit(1)

    # Start once every input is available — latest first-appearance wins.
    # See run_all.py for why. Both arms use the same index.
    first_idx = {
        "median1000":       max(1000, getattr(config, "BUY_MEDIAN_WINDOW", 1000),
                                getattr(config, "SELL_MEDIAN_WINDOW", 1000)),
        "signal1":          min(s1)    if s1    else None,
        "signal3":          min(s3)    if s3    else None,
        "reinvest_signal1": min(ri_s1) if ri_s1 else None,
        "zdev":             min(zmap)  if zmap  else None,
        "pelog":            min(pmap)  if pmap  else None,
    }
    if config.SELL_MIN_ZDEV is not None and not zmap:
        print(f"ERROR: no z_dev for {SYMBOL} at stat_window={config.SELL_ZDEV_WINDOW}")
        sys.exit(1)
    available = {k: v for k, v in first_idx.items() if v is not None}
    start_idx = max(available.values())
    binding   = max(available, key=available.get)
    print(f"Start index: {start_idx} ({df['time'].iloc[start_idx].date()}) "
          f"— bound by '{binding}'")
    print(f"  first available: " + ", ".join(f"{k}={v}" for k, v in sorted(available.items(), key=lambda kv: kv[1])))
    eval_bars = len(df) - start_idx
    print(f"  evaluated bars:  {eval_bars}")
    if config.MIN_EVAL_BARS and eval_bars < config.MIN_EVAL_BARS:
        print(f"  WARNING: below MIN_EVAL_BARS={config.MIN_EVAL_BARS} — run_all would "
              f"skip this symbol; treat the result as an empty sample")

    buy, sell, reinvest = make_strategies(s3, s1, ri_s1, zmap, pmap)
    result = run_estimate(SYMBOL, df, config.INTERVAL_MONEY, buy, sell, reinvest,
                          cal_range_close, start_index=start_idx)

    b0, s0, r0 = make_interval_strategies()
    cmp_result = run_estimate(SYMBOL, df, config.INTERVAL_MONEY, b0, s0, r0,
                              cal_range_close, start_index=start_idx)

    out = CHARTS_DIR / f"{SYMBOL.lower()}_backtest.html"
    save_backtest_chart(
        df,
        result["buyedInfos"], result["sellInfos"], result["reinvestInfos"],
        path=str(out),
        index=SYMBOL.lower(),
        buy_strategy=buy, sell_strategy=sell, reinvest_strategy=reinvest,
        cal_range_close=cal_range_close,
        result=result,
        compare_result=cmp_result,
        start_index=start_idx,
        sig1_window=config.SELL_SIGNAL1_WINDOW,
        sig3_window=1000,   # signal3 is read at window 1000
        zdev_window=config.SELL_ZDEV_WINDOW,
    )
    print(f"\nChart -> {out}")
    os.startfile(out)
