"""
The breadth strategy on one symbol, or on a list.

    python -m single.run_breadth              # VN30
    python -m single.run_breadth FPT HPG      # named symbols

Buy while the basket is not expensive, sell when it is broadly extended AND this
symbol's own momentum has stopped, reinvest only when the basket is genuinely
cheap. Compared against plain interval buying on the same symbol, which is the
question this has to answer: does reading the market beat ignoring it.

Needs breadth_signals in the database -- run `python -m breadth.run --fresh`
first if it is empty.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import pandas as pd

import database as db
from export.chart import save_backtest_chart
from single.breadth_map import build_breadth_map, describe
from single.runner import load_symbol_df, run_estimate
from single.strategies.buy import BuyBreadthStrategy, BuyIntervalStrategy
from single.strategies.reinvest import ReInvestBreadthStrategy, ReinvestStrategy
from single.strategies.sell import SellBreadthStrategy, SellStrategy

CHARTS = Path(__file__).resolve().parent / "charts_breadth"

# ── the strategy ─────────────────────────────────────────────────────────────
BUY_MAX_BREADTH = 60.0        # mua khi median_prem <= 60
SELL_MIN_BREADTH = 70.0       # ban khi median_prem > 70 ...
SELL_SIGNAL1_WINDOW = 120     # ... va da cua chinh ma da dung
SELL_MAX_SIGNAL1 = 0.228
REINVEST_MAX_BREADTH = 10.0   # reinvest khi median_prem <= 10
REINVEST_PERCENT = 100.0

INTERVAL_MONEY = 8_000_000
START_INDEX = 1000            # warmup, matching the 1000-bar reference


def _slope_map(symbol, df, window):
    date_to_idx = {pd.Timestamp(t): i for i, t in enumerate(df["time"])}
    sig = db.load_trend_signals(symbol, window_days=window)
    out = {}
    if not sig.empty:
        for date, v in sig["signal1_slope"].items():
            i = date_to_idx.get(pd.Timestamp(date))
            if i is not None:
                out[i] = float(v)
    return out


def run_one(symbol: str, chart: bool = True) -> dict:
    df = load_symbol_df(symbol)
    cal = db.load_range_stats(symbol, df, range_days={1000})

    breadth = build_breadth_map(df)
    if not breadth:
        raise SystemExit(
            "breadth_signals trong. Chay `python -m breadth.run --fresh` truoc.")
    slopes = _slope_map(symbol, df, SELL_SIGNAL1_WINDOW)

    buy = BuyBreadthStrategy(breadth_map=breadth, max_breadth=BUY_MAX_BREADTH)
    sell = SellBreadthStrategy(breadth_map=breadth, min_breadth=SELL_MIN_BREADTH,
                               signal1_map=slopes, max_signal1=SELL_MAX_SIGNAL1)
    rei = ReInvestBreadthStrategy(breadth_map=breadth,
                                  max_breadth=REINVEST_MAX_BREADTH,
                                  percent=REINVEST_PERCENT)

    got = run_estimate(symbol, df, INTERVAL_MONEY, buy, sell, rei, cal,
                       start_index=START_INDEX)
    base = run_estimate(symbol, df, INTERVAL_MONEY, BuyIntervalStrategy(),
                        SellStrategy(), ReinvestStrategy(), cal,
                        start_index=START_INDEX)

    if chart:
        CHARTS.mkdir(parents=True, exist_ok=True)
        save_backtest_chart(
            df, got["buyedInfos"], got["sellInfos"], got["reinvestInfos"],
            path=str(CHARTS / f"{symbol.lower()}_breadth.html"),
            title=f"{symbol} — breadth strategy",
            index=symbol.lower(), cal_range_close=cal,
            buy_strategy=buy, sell_strategy=sell, reinvest_strategy=rei,
            result=got, compare_result=base, start_index=START_INDEX,
            sig1_window=SELL_SIGNAL1_WINDOW)

    return {"symbol": symbol, "breadth": describe(breadth),
            "plan": got, "base": base}


def main(argv) -> int:
    symbols = [a.upper() for a in argv] or ["VN30"]
    print(f"mua <= {BUY_MAX_BREADTH:g} | ban > {SELL_MIN_BREADTH:g} "
          f"va slope[{SELL_SIGNAL1_WINDOW}] < {SELL_MAX_SIGNAL1} | "
          f"reinvest <= {REINVEST_MAX_BREADTH:g}\n")
    print(f"{'ma':<7}{'breadth':>10}{'interval':>12}{'chenh':>10}"
          f"{'mua':>6}{'ban':>5}{'tai':>5}")
    print("-" * 56)
    for s in symbols:
        r = run_one(s)
        p, b = r["plan"], r["base"]
        print(f"{s:<7}{p['allRatioGrowth']:>9.2f}%{b['allRatioGrowth']:>11.2f}%"
              f"{p['allRatioGrowth'] - b['allRatioGrowth']:>9.2f}%"
              f"{p['totalBuys']:>6}{p['totalSells']:>5}{p['totalReinvest']:>5}")
    print(f"\nChart -> {CHARTS}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
