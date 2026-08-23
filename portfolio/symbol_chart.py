"""
One Plotly chart per symbol: its price, the reference the rule tests it against,
and every trade the portfolio made in it.

WHY A SEPARATE FILE PER SYMBOL RATHER THAN A PANEL IN THE REPORT

  An inline chart has to be small enough to sit inside a table and share the
  page's scroll, which rules out the two things this chart is for — zooming into
  a six-month stretch to see why a buy fired, and hovering a marker to read what
  it cost. A tab of its own gets the full viewport and Plotly's interaction for
  free, which is exactly the arrangement single/median1000 arrived at with its
  <symbol>_backtest.html files.

  Marker shapes and colours are deliberately identical to that chart — green
  triangle up for a buy, red triangle down for a sell, orange diamond for a
  reinvest. Two methods, two engines, but a person reading both should not have
  to learn the legend twice.

WHAT THE TWO LINES MEAN

  Price, and the rolling median the buy rule measures it against. Together they
  are the whole condition made visible: the rule buys while the price is under
  the median by more than the configured margin, so the markers should cluster
  where the blue line sits at or below the dashed one, and stop where it runs
  away. If they do not, the chart is showing a bug rather than a strategy.

  The margin itself is drawn as a third, fainter line — median x (1 + threshold)
  — so the reader can see the actual boundary rather than having to imagine it.
"""

from pathlib import Path

import plotly.graph_objects as go


# Same as single/median1000's backtest chart. See the module docstring.
_EVENT_STYLE = {
    "buy":      ("Mua",         "rgba(34,197,94,0.75)",  "#15803d", "triangle-up",   9),
    "sell":     ("Bán",         "rgba(239,68,68,0.75)",  "#991b1b", "triangle-down", 9),
    "reinvest": ("Tái đầu tư",  "rgba(249,115,22,0.75)", "#c2410c", "diamond",       8),
}


def build_symbol_chart(symbol: str, series, position, window: int,
                       max_premium: float, out_dir: Path) -> Path:
    """
    Write out_dir/<symbol>.html and return the path.

    `series` is the SymbolSeries, `position` the Position holding its trades.
    """
    lo = series.warmup
    n = len(series)
    dates = series.dates[lo:n]
    prices = [series.close(i) for i in range(lo, n)]
    medians = [series.median(window, i) for i in range(lo, n)]
    # The boundary the rule actually tests, not the median itself.
    limits = [m * (1 + max_premium / 100) if m else None for m in medians]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=dates, y=medians, name=f"Median {window} phiên",
        line=dict(color="#94a3b8", width=1.4, dash="dash"),
        hovertemplate="Median: %{y:,.0f}<extra></extra>"))
    fig.add_trace(go.Scatter(
        x=dates, y=limits, name=f"Ngưỡng mua (median +{max_premium:g}%)",
        line=dict(color="#cbd5e1", width=1, dash="dot"),
        hovertemplate="Ngưỡng: %{y:,.0f}<extra></extra>"))
    fig.add_trace(go.Scatter(
        x=dates, y=prices, name=f"{symbol} — giá",
        line=dict(color="#2563eb", width=1.7),
        hovertemplate="Giá: %{y:,.0f}<extra></extra>"))

    by_kind: dict = {}
    for t in position.trades if position else []:
        by_kind.setdefault(t.kind, []).append(t)

    for kind, trades in by_kind.items():
        label, fill, border, marker, size = _EVENT_STYLE.get(
            kind, (kind, "rgba(100,116,139,.75)", "#475569", "circle", 8))
        fig.add_trace(go.Scatter(
            x=[t.date for t in trades],
            y=[t.price for t in trades],
            mode="markers", name=f"{label} ({len(trades)})",
            marker=dict(color=fill, size=size, symbol=marker,
                        line=dict(color=border, width=1)),
            customdata=[[t.amount, t.shares] for t in trades],
            hovertemplate=(f"<b>{label}</b><br>%{{x|%Y-%m-%d}}<br>"
                           "Giá: %{y:,.0f}<br>Tiền: %{customdata[0]:,.0f}<br>"
                           "Cổ phiếu: %{customdata[1]:,.1f}<extra></extra>")))

    n_buy = len(by_kind.get("buy", []))
    n_sell = len(by_kind.get("sell", []))
    n_rei = len(by_kind.get("reinvest", []))
    sub = f"{n_buy} lệnh mua"
    if n_sell:
        sub += f" · {n_sell} lệnh bán"
    if n_rei:
        sub += f" · {n_rei} tái đầu tư"
    if position and position.shares > 0:
        sub += (f" · đang giữ {position.shares:,.0f} cp"
                f" · vốn gốc {position.basis:,.0f}đ")

    fig.update_layout(
        # The subtitle is a second line inside the title, so the horizontal
        # legend has to clear BOTH or it lands on top of it. y=1.02 is the usual
        # value and is wrong here for exactly that reason.
        title=dict(text=f"<b>{symbol}</b><br><span style='font-size:13px;color:#64748b'>"
                        f"{sub}</span>", x=0.01, xanchor="left", y=0.96,
                   yanchor="top"),
        hovermode="x unified",
        plot_bgcolor="white", paper_bgcolor="white",
        font=dict(family="IBM Plex Sans, system-ui, sans-serif", size=13),
        legend=dict(orientation="h", yanchor="bottom", y=1.015, x=0),
        margin=dict(l=70, r=24, t=140, b=48),
        xaxis=dict(showgrid=True, gridcolor="#eef2f7",
                   rangeslider=dict(visible=True, thickness=0.06)),
        yaxis=dict(showgrid=True, gridcolor="#eef2f7", tickformat=",.0f",
                   title="VND"),
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{symbol.lower()}.html"
    fig.write_html(str(path), include_plotlyjs="cdn",
                   full_html=True, config={"displaylogo": False})
    return path


def build_all(result, market, config, out_dir: Path) -> dict:
    """
    One chart per symbol the portfolio actually traded. Returns {symbol: filename}.

    Symbols that were never bought are skipped: a chart with no markers says
    nothing the report's table does not already say, and 53 of them would take
    longer to write than the backtest takes to run.
    """
    window = config.BUY_WINDOW
    max_premium = config.BUY_MAX_PREMIUM
    wallet = result["wallet"]

    out = {}
    for symbol, position in wallet.positions.items():
        if not position.trades:
            continue
        path = build_symbol_chart(symbol, market[symbol], position,
                                  window, max_premium, out_dir)
        out[symbol] = path.name
    return out
