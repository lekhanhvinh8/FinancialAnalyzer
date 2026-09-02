"""
The breadth strategy on one symbol, or on a list.

    python -m single.market_breadth.run_all              # VN30
    python -m single.market_breadth.run_all FPT HPG      # named symbols
    python -m single.market_breadth.run_all --all        # every stock, parallel
    python -m single.market_breadth.run_all --all --workers=4

Buy while the basket is not expensive, sell when it is broadly extended AND this
symbol's own momentum has stopped, reinvest only when the basket is genuinely
cheap. Compared against plain interval buying on the same symbol, which is the
question this has to answer: does reading the market beat ignoring it.

Needs breadth_signals in the database -- run `python -m breadth.run --fresh`
first if it is empty.
"""

import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import pandas as pd

import database as db
from breadth.chart import add_signal_line
from export.chart import save_backtest_chart
from progress import RunAllProgress
from single.median1000.run_all import build_report
from single.market_breadth import config
from single.market_breadth.breadth_map import build_breadth_map, describe
from single.runner import load_symbol_df, run_estimate
from single.strategies.buy import BuyBreadthStrategy, BuyIntervalStrategy
from single.strategies.reinvest import ReInvestBreadthStrategy, ReinvestStrategy
from single.strategies.sell import SellBreadthStrategy, SellStrategy

CHARTS = Path(__file__).resolve().parent / "charts"

# Names kept local so the body reads the same as median1000's; the values live
# in config.py, which is also what the report's parameter panel introspects.
BUY_MAX_BREADTH = config.BUY_MAX_BREADTH
SELL_MIN_BREADTH = config.SELL_MIN_BREADTH
SELL_SIGNAL1_WINDOW = config.SELL_SIGNAL1_WINDOW
SELL_MAX_SIGNAL1 = config.SELL_MAX_SIGNAL1
REINVEST_MAX_BREADTH = config.REINVEST_MAX_BREADTH
REINVEST_PERCENT = config.REINVEST_PERCENT
INTERVAL_MONEY = config.INTERVAL_MONEY
START_INDEX = config.START_INDEX


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


def run_one(symbol: str, chart: bool = True, out_dir: Path = None) -> dict:
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
        out = out_dir or CHARTS
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"{symbol.lower()}_backtest.html"
        save_backtest_chart(
            df, got["buyedInfos"], got["sellInfos"], got["reinvestInfos"],
            path=str(path),
            title=f"{symbol} — market breadth",
            index=symbol.lower(), cal_range_close=cal,
            buy_strategy=buy, sell_strategy=sell, reinvest_strategy=rei,
            result=got, compare_result=base, start_index=START_INDEX,
            sig1_window=SELL_SIGNAL1_WINDOW)

        # The line the decisions were made on. Without it the chart shows three
        # sells with nothing on it that explains them -- the reason lives in the
        # basket, not in this symbol's price.
        x = [str(t)[:10] for t in df["time"]]
        add_signal_line(
            path, x, {"median_prem": [breadth.get(i) for i in range(len(x))]},
            [(BUY_MAX_BREADTH, "mua"), (SELL_MIN_BREADTH, "ban"),
             (REINVEST_MAX_BREADTH, "reinvest")],
            axis_title="median_prem")

    return {"symbol": symbol, "breadth": describe(breadth),
            "plan": got, "base": base, "df": df, "cal": cal,
            "buy": buy, "sell": sell, "reinvest": rei}


def process_symbol(symbol: str, out_dir: Path):
    """
    One symbol in a worker process. Returns plain data, never a progress object:
    RunAllProgress is not picklable and the parent owns it, exactly as
    median1000/run_all.py arranges it.

    The row uses that report's key names -- median_growth_%, median_buys and so
    on -- because it IS that report. "median" there means "the strategy under
    test", not the median statistic.
    """
    t0 = time.time()
    try:
        r = run_one(symbol, out_dir=out_dir)
    except Exception as exc:
        return symbol, None, f"{type(exc).__name__}: {exc}", time.time() - t0

    p, b, df, cal = r["plan"], r["base"], r["df"], r["cal"]
    last = len(df) - 1
    # x1000: range_stats is stored at the raw database scale while df["close"]
    # is not, so comparing them directly gave -99.9% in every vs_* column.
    # median1000/run_all.py does the same multiply for the same reason.
    close_last = float(df["close"].iloc[last]) * 1000

    # Where the last price sits in its own 1000-bar range. Description of the
    # symbol for the reader, not an input to any decision -- same four columns
    # median1000 reports, computed the same way.
    rng = {}
    rc = (cal[last].rangeDayCloses.get(1000) if last in cal else None)
    if rc is not None:
        for name, ref in (("top", rc.top(False)), ("bottom", rc.bottom(False)),
                          ("median", rc.pct50(False)), ("mean", rc.avg(False))):
            rng[f"vs_{name}_%"] = (round((close_last - ref) / ref * 100, 2)
                                   if ref else None)

    def _chk(strategy):
        try:
            return bool(strategy.check(last, close_last, None, cal))
        except Exception:
            return False

    return symbol, {
        "symbol":            symbol,
        "median_growth_%":   p["allRatioGrowth"],
        "median_buys":       p["totalBuys"],
        "median_sells":      p["totalSells"],
        "median_reinvests":  p["totalReinvest"],
        "interval_growth_%": b["allRatioGrowth"],
        "chart":             f"{symbol.lower()}_backtest.html",
        "now_flags":         (_chk(r["buy"]), _chk(r["sell"]), _chk(r["reinvest"])),
        "eval_bars":         len(df) - START_INDEX,
        **rng,
    }, None, time.time() - t0


def main(argv) -> int:
    args = [a for a in argv if not a.startswith("--")]
    flags = [a for a in argv if a.startswith("--")]
    workers = next((int(f.split("=", 1)[1]) for f in flags
                    if f.startswith("--workers=")), None)

    if "--all" in flags:
        from core.universe import resolve
        symbols = resolve("all", ["VIX", "VIC"], extra=["VN30"])
    else:
        symbols = [a.upper() for a in args] or ["VN30"]
    print(f"mua <= {BUY_MAX_BREADTH:g} | ban > {SELL_MIN_BREADTH:g} "
          f"va slope[{SELL_SIGNAL1_WINDOW}] < {SELL_MAX_SIGNAL1} | "
          f"reinvest <= {REINVEST_MAX_BREADTH:g}")

    # A fresh directory per run, like median1000/run_all.py: a rerun must not
    # overwrite the charts a previous one is being read from.
    CHARTS.mkdir(parents=True, exist_ok=True)
    run_dir = CHARTS / datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir.mkdir(exist_ok=True)
    print(f"Output   -> {run_dir}")
    print(f"Progress -> {run_dir / 'run_all_progress.html'}\n", flush=True)

    prog = RunAllProgress(symbols, out=str(run_dir / "run_all_progress.html"))
    t0 = time.time()
    rows, skipped, done = [], [], 0

    with ProcessPoolExecutor(max_workers=workers) as ex:
        n_slots = ex._max_workers
        futures = {ex.submit(process_symbol, sym, run_dir): sym for sym in symbols}

        # The pool runs submissions FIFO, so the first n_slots are the ones
        # actually in flight. Tracked here rather than reported by the workers,
        # which would need a Manager queue just to say "I started".
        for sym in symbols[:n_slots]:
            prog.begin(sym)
        next_start = n_slots

        # as_completed, not map: map yields in submission order, so one slow
        # symbol holds back every result behind it and the page moves in bursts.
        for fut in as_completed(futures):
            sym, row, why, dur = fut.result()
            done += 1
            if row:
                rows.append(row)
                prog.end_ok(sym, dur, median_growth=row["median_growth_%"],
                            buys=row["median_buys"], sells=row["median_sells"],
                            reinvests=row["median_reinvests"],
                            interval_growth=row["interval_growth_%"],
                            chart=row["chart"])
                d = row["median_growth_%"] - row["interval_growth_%"]
                print(f"[{done}/{len(symbols)}] {sym:<7}"
                      f"{row['median_growth_%']:>9.2f}%"
                      f"{row['interval_growth_%']:>11.2f}%{d:>9.2f}%", flush=True)
            else:
                skipped.append((sym, why or "unknown"))
                prog.end_err(sym, why or "unknown")
                print(f"[{done}/{len(symbols)}] {sym:<7}bo qua — {why}", flush=True)
            if next_start < len(symbols):
                prog.begin(symbols[next_start])
                next_start += 1

    prog.finish()
    if rows:
        # The report median1000 already has: filter chips, the long/short split,
        # sign tests, the config panel, index membership. Reimplementing it once
        # produced something far thinner, so this passes THIS module as the
        # config so the panel names the right parameters.
        rep = run_dir / "report_all.html"
        build_report(rows, rep, skipped, config_module=config,
                     title="MarketBreadth")
        wins = sum(1 for r in rows
                   if r["median_growth_%"] > r["interval_growth_%"])
        print(f"\nthang {wins}/{len(rows)} ma ({wins / len(rows):.0%})")
        print(f"Report -> {rep}")
    print(f"Done in {(time.time() - t0) / 60:.1f} min tren {n_slots} workers.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
