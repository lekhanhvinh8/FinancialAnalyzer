"""VN30 backtest chart, rendered by export/chart.py — the same code single/ uses."""

import dataclasses
import json
import sqlite3
from pathlib import Path

import pandas as pd

import database as db
from database import DB_PATH
from export.chart import save_backtest_chart


class _Trade:
    """Duck-type for save_backtest_chart. It reads attributes, never types."""

    def __init__(self, row, price_vnd, amount, shares, growth=0.0):
        self.index = row
        self.close = price_vnd * 1000     # the renderer divides by 1000
        self.time = ""
        self.finalBuy = amount
        self.numberOfShareCanBy = shares
        self.sellFinal = amount
        self.sellShare = shares
        self.sellCapital = amount
        self.sellGrowthRatito = growth
        self.reInvestFinal = amount
        self.reInvestShare = shares
        self.reInvestCapital = amount


def _load_df(symbol: str) -> pd.DataFrame:
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


# Which signals to draw, and the thresholds as dashed lines. The one the arms
# actually read comes first and is drawn solid; the others are comparisons and
# are drawn faint, so the chart shows both the decision and the alternative.
def _arm_signals(config):
    if getattr(config, "USE_PREM_ARMS", False):
        lines = [(config.BUY_PREM_MAX, "mua"),
                 (config.REINVEST_PREM_MAX, "reinvest"),
                 (config.SELL_PREM_MIN, "ban")]
        used = "prem_trim" if getattr(config, "USE_TRIM_MEAN", False) else "prem_median"
        other = "prem_median" if used == "prem_trim" else "prem_trim"
        return [used, other], [(v, n) for v, n in lines if v is not None]
    return ["below_pct"], [(config.BUY_STRONG_BELOW_PCT, "manh"),
                           (config.BUY_NORMAL_BELOW_PCT, "thuong")]


def add_signal_line(path: Path, x, series: dict, lines=(), axis_title="") -> None:
    """
    Draw one or more dated series on a finished backtest chart, on their own
    right-hand axis, with `lines` as dashed thresholds.

    PUBLIC because single/ needs the same thing. Appended after the renderer has
    run rather than passed in: export/chart.py is shared and should not grow a
    parameter for one caller.

    `x` is the chart's dates as ISO strings; `series` is {name: values aligned to
    x}; `lines` is [(value, label)].
    """
    vals = [v for ys in series.values() for v in ys if v is not None and v == v]
    if not vals:
        return
    lo, hi = min(vals + [v for v, _ in lines]), max(vals + [v for v, _ in lines])
    pad = (hi - lo) * 0.08 or 1.0

    # y8. save_backtest_chart already uses y2..y7 -- y3 carries its Buy/Sell
    # markers and y4..y7 are the signal panels underneath -- so anything lower
    # overwrites one of them.
    STYLE = [("rgba(147,102,240,0.95)", 1.6), ("rgba(0,176,160,0.95)", 1.6)]
    traces = []
    for k, (name, ys) in enumerate(series.items()):
        colour, width = STYLE[min(k, len(STYLE) - 1)]
        traces.append({"type": "scatter", "mode": "lines", "yaxis": "y8",
                       "name": name, "x": x, "y": ys,
                       "line": {"color": colour, "width": width},
                       "hovertemplate": name + ": %{y:.1f}<extra></extra>"})
    for v, label in lines:
        traces.append({"type": "scatter", "mode": "lines", "yaxis": "y8",
                       "name": f"{label} ({v:g})", "x": [x[0], x[-1]], "y": [v, v],
                       "line": {"color": "rgba(147,102,240,0.5)", "width": 1,
                                "dash": "dash"},
                       "hoverinfo": "skip"})

    script = f"""
<script>
// Runs AFTER the renderer's own 1s timer has added its event traces; adding
// first and letting it re-plot on top would drop these again.
setTimeout(function wait() {{
  var gd = document.querySelector('.plotly-graph-div');
  if (!gd || !window.Plotly || !gd.data || !gd.data.length) return setTimeout(wait, 300);
  Plotly.relayout(gd, {{
    'yaxis8': {{overlaying: 'y', side: 'right', anchor: 'free', position: 1.0,
                showgrid: false, range: [{lo - pad:.2f}, {hi + pad:.2f}],
                title: {{text: '{axis_title or list(series)[0]}', font: {{size: 10}}}},
                tickfont: {{size: 9}}, zeroline: false}},
    'xaxis.domain': [0, 0.94]
  }}).then(function() {{ Plotly.addTraces(gd, {json.dumps(traces)}); }});
}}, 1600);
</script>
</body>"""
    html = path.read_text(encoding="utf-8")
    path.write_text(html.replace("</body>", script, 1), encoding="utf-8")


def _add_signal(path: Path, breadth, config, dates) -> None:
    """The deciding signal (and its comparison) for a breadth run."""
    names, lines = _arm_signals(config)
    names = [n for n in names if n in breadth.values]
    if not names:
        return
    x = [str(d)[:10] for d in dates]
    series = {}
    for k, n in enumerate(names):
        by_date = {str(d)[:10]: v for d, v in zip(breadth.dates, breadth.values[n])}
        label = n if k == 0 else f"{n} (so sanh)"
        series[label] = [by_date.get(t) for t in x]
    add_signal_line(path, x, series, lines, axis_title=names[0])


@dataclasses.dataclass
class _ZoneShim:
    """
    Adapts one breadth arm to the check(index, close, pe, cal_range_close) call
    the condition-zone overlay makes per bar.

    The arguments are accepted and ignored: a breadth condition is about the
    BASKET on that date, not about the instrument's own price, so the shim looks
    the date up in the breadth series instead.

    Dataclass because export/chart.py lists a strategy's fields in its parameter
    table; `label` is what shows there.
    """
    label: str
    n_days: int = 0

    def _wire(self, plan, arm, breadth, rows, blocked):
        self._plan, self._arm, self._b = plan, arm, breadth
        self._rows = rows            # df row -> breadth index
        self._blocked = blocked      # arms the sell condition switches off
        self.n_days = len(rows)
        return self

    def check(self, index, close=None, pe=None, cal_range_close=None) -> bool:
        i = self._rows.get(index)
        if i is None or self._b.counts[i] < self._plan.min_symbols:
            return False
        if self._blocked and self._plan.fires(self._plan.sell_when, i):
            return False
        return self._plan.fires(self._arm, i)


def _zones(plan, breadth, dates):
    """Three shims, or None if breadth is not available."""
    if breadth is None:
        return None, None, None
    pos = {str(d)[:10]: i for i, d in enumerate(breadth.dates)}
    rows = {}
    for r, d in enumerate(dates):
        i = pos.get(str(d)[:10])
        if i is not None:
            rows[r] = i
    # The buy and reinvest zones are painted with the sell block applied, so the
    # green shows where the plan would ACT, not merely where its own condition
    # holds. Without that the chart contradicts the trades.
    return (_ZoneShim("buy")._wire(plan, plan.buy_when, breadth, rows, True),
            _ZoneShim("sell")._wire(plan, plan.sell_when, breadth, rows, False),
            _ZoneShim("reinvest")._wire(plan, plan.reinvest_when, breadth, rows, True))


# EXACTLY the renderer's own markers -- shape, size, fill and edge, copied from
# what it emits. The two rows are identical; the ROW is what says which
# strategy, and nothing else should. Drawing the second hollow made the same
# event look like a different kind of event.
_ALT = {
    "buy":      ("triangle-up",   9, "rgba(34,197,94,0.75)", "#15803d"),
    "sell":     ("triangle-down", 9, "rgba(239,68,68,0.75)", "#991b1b"),
    "reinvest": ("diamond",       8, "rgba(249,115,22,0.75)","#c2410c"),
}


def _add_alt_trades(path: Path, alt_result, label: str, symbol: str) -> None:
    """The other strategy's trades, on y3 at a lower height than the main run."""
    by_kind = {}
    for t in alt_result["wallet"].position(symbol).trades:
        by_kind.setdefault(t.kind, []).append(t)
    if not by_kind:
        return

    traces = []
    for kind, items in by_kind.items():
        shape, size, colour, edge = _ALT[kind]
        traces.append({
            "type": "scatter", "mode": "markers", "yaxis": "y3",
            "name": f"{kind} · {label} ({len(items)})",
            "x": [str(t.date)[:10] for t in items],
            "y": [0.30] * len(items),
            "customdata": [[t.price, t.amount] for t in items],
            "marker": {"symbol": shape, "size": size, "color": colour,
                       "line": {"color": edge, "width": 1}},
            "hovertemplate": (f"<b>%{{x}}</b> {kind} · {label}"
                              "<br>Gia: %{customdata[0]:,.0f}"
                              "<br>Tien: %{customdata[1]:,.0f}<extra></extra>"),
        })

    script = f"""
<script>
setTimeout(function wait() {{
  var gd = document.querySelector('.plotly-graph-div');
  if (!gd || !window.Plotly || !gd.data || !gd.data.length) return setTimeout(wait, 300);
  Plotly.addTraces(gd, {json.dumps(traces)});
}}, 1800);
</script>
</body>"""
    html = path.read_text(encoding="utf-8")
    path.write_text(html.replace("</body>", script, 1), encoding="utf-8")


def build(result, config, out_dir: Path, breadth=None, plan=None,
          alt=None) -> Path:
    """
    Chart for the traded instrument, with every trade marked.

    Trades are located by DATE, not by the index they carry: the cached run and
    the full run number their bars differently, and only the date is the same in
    both.
    """
    symbol = config.SYMBOL
    df = _load_df(symbol)
    row_of = {d: i for i, d in enumerate(df["time"])}

    buys, sells, reinvests = [], [], []
    bucket = {"buy": buys, "sell": sells, "reinvest": reinvests}
    for t in result["wallet"].position(symbol).trades:
        row = row_of.get(pd.Timestamp(t.date))
        if row is None:
            continue
        growth = ((t.amount - t.basis) / t.basis * 100) if t.basis else 0.0
        bucket[t.kind].append(_Trade(row, t.price, t.amount, t.shares, growth))

    zb, zs, zr = (_zones(plan, breadth, df["time"]) if plan is not None
                  else (None, None, None))

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{symbol.lower()}_backtest.html"
    save_backtest_chart(
        df, buys, sells, reinvests,
        path=str(path),
        title=f"{symbol} — {config.PLAN_NAME}",
        index=symbol.lower(),
        cal_range_close=db.load_range_stats(symbol, df,
                                            range_days={config.WINDOW, 1000}),
        buy_strategy=zb, sell_strategy=zs, reinvest_strategy=zr,
        result=result,
        start_index=config.WINDOW - 1,
        sig1_window=config.SLOPE_WINDOW,
    )
    if breadth is not None:
        _add_signal(path, breadth, config, df["time"])
    if alt is not None:
        _add_alt_trades(path, alt[1], alt[0], symbol)
    return path
