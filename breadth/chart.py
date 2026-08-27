"""VN30 backtest chart, rendered by export/chart.py — the same code single/ uses."""

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


# The signals the arms actually read, with the thresholds drawn as dashed lines.
def _arm_signals(config):
    if getattr(config, "USE_PREM_ARMS", False):
        lines = [(config.BUY_PREM_MAX, "mua"),
                 (config.REINVEST_PREM_MAX, "reinvest"),
                 (config.SELL_PREM_MIN, "ban")]
        return "median_prem", [(v, n) for v, n in lines if v is not None]
    return "below_pct", [(config.BUY_STRONG_BELOW_PCT, "manh"),
                         (config.BUY_NORMAL_BELOW_PCT, "thuong")]


def _add_signal(path: Path, breadth, config, dates) -> None:
    """
    Draw the deciding signal on the finished chart, on its own right-hand axis.

    Appended after the renderer has run rather than passed in: export/chart.py
    is shared with single/ and should not grow a parameter for one package. The
    axis is added by relayout for the same reason.
    """
    name, lines = _arm_signals(config)
    if name not in breadth.values:
        return
    by_date = {str(d)[:10]: v for d, v in zip(breadth.dates, breadth.values[name])}

    x = [str(d)[:10] for d in dates]
    y = [by_date.get(k) for k in x]
    if not any(v is not None and v == v for v in y):
        return

    traces = [{"type": "scatter", "mode": "lines", "name": name, "yaxis": "y3",
               "x": x, "y": y,
               "line": {"color": "rgba(147,102,240,0.85)", "width": 1.4},
               "hovertemplate": name + ": %{y:.2f}<extra></extra>"}]
    for v, label in lines:
        traces.append({"type": "scatter", "mode": "lines",
                       "name": f"{label} ({v:g})", "yaxis": "y3",
                       "x": [x[0], x[-1]], "y": [v, v],
                       "line": {"color": "rgba(147,102,240,0.45)", "width": 1,
                                "dash": "dash"},
                       "hoverinfo": "skip"})

    script = f"""
<script>
(function add() {{
  var gd = document.querySelector('.plotly-graph-div');
  if (!gd || !window.Plotly || !gd.data) return setTimeout(add, 200);
  Plotly.relayout(gd, {{
    'yaxis3': {{overlaying: 'y', side: 'right', showgrid: false,
                title: {{text: '{name}'}}, position: 1.0,
                titlefont: {{size: 10}}, tickfont: {{size: 9}}}}
  }}).then(function() {{ Plotly.addTraces(gd, {json.dumps(traces)}); }});
}})();
</script>
</body>"""
    html = path.read_text(encoding="utf-8")
    path.write_text(html.replace("</body>", script, 1), encoding="utf-8")


def build(result, config, out_dir: Path, breadth=None) -> Path:
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

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{symbol.lower()}_backtest.html"
    save_backtest_chart(
        df, buys, sells, reinvests,
        path=str(path),
        title=f"{symbol} — {config.PLAN_NAME}",
        index=symbol.lower(),
        cal_range_close=db.load_range_stats(symbol, df,
                                            range_days={config.WINDOW, 1000}),
        result=result,
        start_index=config.WINDOW - 1,
        sig1_window=config.SLOPE_WINDOW,
    )
    if breadth is not None:
        _add_signal(path, breadth, config, df["time"])
    return path
