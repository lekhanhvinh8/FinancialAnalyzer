"""
Per-symbol charts, rendered by export/chart.py — the same code single/median1000
calls.

WHY THIS IS AN ADAPTER AND NOT A CHART

  Three earlier versions here drew their own chart from what the reference one
  LOOKED like. Each got closer and each was still wrong, because the reference
  is not a set of lines — it is a P/E chart with static quantile bands, a price
  line segmented by valuation zone, rolling percentile and mean lines on both
  axes, a control panel that recomputes them at any window, colour-source and
  colour-basis toggles, and condition-zone overlays painted from the strategy's
  own check(). Reimplementing that from screenshots was never going to converge.

  export/chart.py already does all of it. It sits at the repository root beside
  database.py and progress.py, and it is shared infrastructure rather than part
  of either method: sync.py renders with it too. Importing it here is the same
  kind of dependency as importing the database, and it is not a dependency on
  single/ — that package is not imported, and nothing here can change one of its
  results.

  So this module's whole job is translation. It turns portfolio state into the
  four things save_backtest_chart expects and gets out of the way.

THE FOUR TRANSLATIONS

  1. A DataFrame with time / close / pe_ratio, at the raw database price scale.
     Built from this package's own SQL rather than borrowed from
     single/runner.py.

  2. Trade records. save_backtest_chart reads attributes, never types, so
     lightweight stand-ins carrying the field names it looks for are enough —
     .index, .close, .finalBuy / .sellFinal / .reInvestFinal. No import of
     single/models.py, and no chance of drifting from it either.

     WATCH THE SCALE. Those records are read as `i.close / 1000`, because the
     single-symbol engine works in price x 1000. This package works in real VND,
     so the stand-ins have to multiply going in. Getting this wrong puts every
     marker a thousand-fold off the price line — visible immediately, which is
     the one mercy of it.

  3. Rule shims exposing check(index, close, pe, cal_range_close). The
     condition-zone overlay calls that per bar to paint what the strategy would
     have done. A portfolio Rule takes (series, index) instead, so the shim
     closes over the series and ignores the arguments it is handed — which is
     safe precisely because the rule reads its own series and never the passed
     close.

  4. cal_range_close, straight from database.load_range_stats. Unused by the
     rules here, but the overlay signature requires it.
"""

import os
import sqlite3
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

import database as db
from database import DB_PATH
from export.chart import save_backtest_chart


class _Trade:
    """
    Duck-typed stand-in for single's BuyedInfo / SellInfo / ReinvestInfo.

    Every field save_backtest_chart might read is set, so one class covers all
    three kinds and an unused attribute costs nothing.
    """

    def __init__(self, row_index: int, price_vnd: float, amount: float,
                 shares: float, growth_pct: float = 0.0):
        self.index = row_index
        # x1000: the renderer divides by it. See the module docstring.
        self.close = price_vnd * 1000
        self.time = ""
        self.finalBuy = amount
        self.numberOfShareCanBy = shares
        self.sellFinal = amount
        self.sellShare = shares
        self.sellCapital = amount
        self.sellGrowthRatito = growth_pct
        self.reInvestFinal = amount
        self.reInvestShare = shares
        self.reInvestCapital = amount


class _RuleShim:
    """
    Adapts a portfolio Rule to the check(index, close, pe, cal_range_close)
    signature the condition-zone overlay calls.

    close, pe and cal_range_close are accepted and discarded: a portfolio rule
    reads everything it needs out of the series it was given, so passing them
    on would be passing values it has no use for.
    """

    def __init__(self, rule, series):
        self._rule = rule
        self._series = series

    def check(self, index, close=None, pe=None, cal_range_close=None) -> bool:
        try:
            return bool(self._rule.applies(self._series, index))
        except Exception:
            return False


def _load_df(symbol: str) -> pd.DataFrame:
    """time / close / pe_ratio at the raw database scale, as the renderer wants."""
    with sqlite3.connect(DB_PATH) as con:
        prices = pd.read_sql(
            "SELECT date AS time, close FROM daily_prices WHERE symbol = ? "
            "ORDER BY date", con, params=(symbol,))
        pes = pd.read_sql(
            "SELECT date AS time, pe_ratio FROM pe_ratios WHERE symbol = ? "
            "ORDER BY date", con, params=(symbol,))
    df = prices.merge(pes, on="time", how="left")
    df["time"] = pd.to_datetime(df["time"])
    df["pe_ratio"] = df["pe_ratio"].ffill()
    return df.reset_index(drop=True)


def build_symbol_chart(symbol: str, series, position, plan, config,
                       out_dir: Path) -> Path:
    """Single-symbol entry point. build_all uses _render directly, in a pool."""
    return Path(_render(symbol, series, position, plan, config.BUY_WINDOW,
                        out_dir, want_path=True))


def _render(symbol, series, position, plan, window, out_dir, want_path=False):
    df = _load_df(symbol)

    cal_range_close = db.load_range_stats(symbol, df, range_days={window, 1000})

    buys, sells, reinvests = [], [], []
    bucket = {"buy": buys, "sell": sells, "reinvest": reinvests}
    for t in (position.trades if position else []):
        growth = ((t.amount - t.basis) / t.basis * 100) if t.basis else 0.0
        bucket[t.kind].append(
            _Trade(t.index, t.price, t.amount, t.shares, growth))

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{symbol.lower()}_backtest.html"

    save_backtest_chart(
        df, buys, sells, reinvests,
        path=str(path),
        index=symbol,
        buy_strategy=_RuleShim(plan.buy_rule, series),
        sell_strategy=_RuleShim(plan.sell_rule, series),
        reinvest_strategy=_RuleShim(plan.reinvest_rule, series),
        cal_range_close=cal_range_close,
        start_index=series.warmup,
    )
    return str(path) if want_path else path.name


def _worker(args):
    """One chart, in its own process. Everything crossing the boundary is picklable."""
    symbol, series, position, plan, window, out_dir = args
    try:
        return symbol, _render(symbol, series, position, plan, window, out_dir), None
    except Exception as exc:
        return symbol, None, f"{type(exc).__name__}: {exc}"


def build_all(result, market, plan, config, out_dir: Path, workers=None) -> dict:
    """
    One chart per symbol the portfolio traded. Returns {symbol: filename}.

    PARALLEL, because the renderer is slow and there is no way around that. It
    embeds the full trend-signal series so the window sliders work offline, and
    walks every bar three times to paint the condition zones — about 30 seconds
    a symbol, which is half an hour for a full universe in sequence. The charts
    are independent, so this is the same answer single/median1000's run_all
    reached: one process each.

    Failures are caught per symbol rather than aborting: the renderer reaches for
    optional data that not every symbol has, and losing one chart is not worth
    losing the report.
    """
    wallet = result["wallet"]
    jobs = [(sym, market[sym], pos, plan, config.BUY_WINDOW, out_dir)
            for sym, pos in wallet.positions.items() if pos.trades]
    if not jobs:
        return {}

    out_dir.mkdir(parents=True, exist_ok=True)
    workers = workers or min(len(jobs), (os.cpu_count() or 4))

    out, done = {}, 0
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_worker, j) for j in jobs]
        for fut in as_completed(futures):
            symbol, name, err = fut.result()
            done += 1
            if err:
                print(f"  [{done}/{len(jobs)}] {symbol} — {err}", flush=True)
            else:
                out[symbol] = name
                print(f"  [{done}/{len(jobs)}] {symbol}", flush=True)
    return out
