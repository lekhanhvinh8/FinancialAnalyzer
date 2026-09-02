"""
Per-symbol charts, rendered by export/chart.py — the same code single/multi_signal
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

     ONLY THE SYMBOL-LEVEL PART IS PAINTED. Three separate things decide whether
     a symbol is bought — its own condition, a filter against the rest of the
     universe, and whether it made the day's top K — and only the first belongs
     on a chart of one symbol. Painting the cap filter would draw a zone that
     moves when an unrelated symbol lists; top K is not a condition at all and
     cannot be drawn per bar.

     So the green zone answers "was this symbol itself eligible", and the markers
     answer "was it actually bought". THE GAP BETWEEN THEM IS THE POINT: green
     with no marker is a bar this symbol passed its own test and lost the
     competition anyway.

  4. cal_range_close, straight from database.load_range_stats. Unused by the
     rules here, but the overlay signature requires it.

MARKERS ON THE PRICE LINE

  save_backtest_chart draws its own event markers, but on a separate axis at a
  fixed height — a strip along the bottom, disconnected from the price. That is
  a reasonable choice when the events are sparse and the chart is mostly about
  the P/E band, and it is the wrong one here: the question this package asks of
  a symbol chart is "was the price low when we bought", which cannot be read
  from a marker that is nowhere near the price.

  So a second set is appended AT THE PRICE, on the price axis, after the
  renderer has finished. Same shapes and colours, so it reads as the same
  legend, and every point carries the money and the share count in its hover.
"""

import json
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
        # A rule that was entirely cross-sectional strips to None; nothing about
        # this symbol alone can be drawn for it.
        if self._rule is None:
            return False
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
        # symbol_only(): the cap filter is dropped here on purpose. See the
        # module docstring — the zone is this symbol's own condition, the
        # markers are what survived everything else.
        buy_strategy=_RuleShim(plan.buy_rule.symbol_only(), series),
        sell_strategy=_RuleShim(plan.sell_rule.symbol_only(), series),
        reinvest_strategy=_RuleShim(plan.reinvest_rule.symbol_only(), series),
        cal_range_close=cal_range_close,
        start_index=series.warmup,
    )
    _add_price_markers(path, position, df)
    return str(path) if want_path else path.name


# Same shapes and colours as single/multi_signal's, and as the strip the renderer
# already draws — one legend for the reader, not two.
_PRICE_MARKS = {
    "buy":      ("Mua (tren gia)",        "rgba(34,197,94,0.9)",  "#15803d", "triangle-up",   10),
    "sell":     ("Ban (tren gia)",        "rgba(239,68,68,0.9)",  "#991b1b", "triangle-down", 11),
    "reinvest": ("Tai dau tu (tren gia)", "rgba(249,115,22,0.9)", "#c2410c", "diamond",        9),
}


def _add_price_markers(path: Path, position, df) -> None:
    """
    Append trade markers plotted AT THE PRICE, on the price axis.

    Injected after the fact rather than passed in, because save_backtest_chart
    puts its markers on a fixed-height strip and takes no argument to change
    that. Adding traces to the finished figure is the smaller change: it leaves
    the shared renderer alone, and a renderer used by two packages should not
    grow a parameter for one of them.

    The price axis is y2 for a stock chart — y is the P/E — so the traces say so
    explicitly. Getting that wrong would place every marker against the P/E
    scale, which for a 75,000 VND price on a 0-to-50 axis means somewhere far
    above the top of the chart.
    """
    trades = [t for t in (position.trades if position else [])]
    if not trades:
        return

    dates = [str(d)[:10] for d in df["time"]]
    specs = []
    for kind, (label, fill, border, shape, size) in _PRICE_MARKS.items():
        items = [t for t in trades if t.kind == kind]
        if not items:
            continue
        specs.append({
            "type": "scatter", "mode": "markers", "name": f"{label} ({len(items)})",
            "yaxis": "y2",
            "x": [dates[t.index] if 0 <= t.index < len(dates) else str(t.date)[:10]
                  for t in items],
            "y": [t.price for t in items],
            "customdata": [[t.amount, t.shares] for t in items],
            "marker": {"symbol": shape, "size": size, "color": fill,
                       "line": {"color": border, "width": 1.2}},
            "hovertemplate": (f"<b>{label}</b><br>%{{x}}<br>Gia: %{{y:,.0f}}<br>"
                              "Tien: %{customdata[0]:,.0f}<br>"
                              "CP: %{customdata[1]:,.1f}<extra></extra>"),
            "legendgroup": "price-marks",
        })
    if not specs:
        return

    html = path.read_text(encoding="utf-8")
    script = f"""
<script>
(function add() {{
  var gd = document.querySelector('.plotly-graph-div');
  // The renderer injects its own traces on a timer; wait for the div AND for
  // Plotly itself rather than racing them.
  if (!gd || !window.Plotly || !gd.data) {{ return setTimeout(add, 200); }}
  Plotly.addTraces(gd, {json.dumps(specs)});
}})();
</script>
</body>"""
    path.write_text(html.replace("</body>", script, 1), encoding="utf-8")


def _worker(args):
    """One chart, in its own process. Everything crossing the boundary is picklable."""
    symbol, series, position, plan, window, out_dir = args
    try:
        return symbol, _render(symbol, series, position, plan, window, out_dir), None
    except Exception as exc:
        return symbol, None, f"{type(exc).__name__}: {exc}"


def build_all(result, market, plan, config, out_dir: Path, workers=None,
              on_chart=None) -> dict:
    """
    One chart per symbol the portfolio traded. Returns {symbol: filename}.

    PARALLEL, because the renderer is slow and there is no way around that. It
    embeds the full trend-signal series so the window sliders work offline, and
    walks every bar three times to paint the condition zones — about 30 seconds
    a symbol, which is half an hour for a full universe in sequence. The charts
    are independent, so this is the same answer single/multi_signal's run_all
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

    import time
    t0 = time.time()
    out, done = {}, 0
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_worker, j) for j in jobs]
        for fut in as_completed(futures):
            symbol, name, err = fut.result()
            done += 1
            el = time.time() - t0
            eta = el / done * (len(jobs) - done)
            width = 18
            filled = int(width * done / len(jobs))
            bar = "[" + "#" * filled + "." * (width - filled) + "]"
            tail = f"— {err}" if err else ""
            if not err:
                out[symbol] = name
            print(f"  {bar} {done:>3}/{len(jobs)}  {symbol:<7}{tail:<34}"
                  f"{el:>5.0f}s  con ~{eta:>4.0f}s", flush=True)
            if on_chart:
                on_chart(symbol, err is None, err)
    return out
