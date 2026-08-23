"""
One Plotly chart per symbol, matching single/median1000's backtest chart.

WHY IT COPIES THAT CHART RATHER THAN INVENTING ITS OWN

  The two methods are independent as code and must stay that way, but the person
  reading them is the same person. A chart here that showed a different set of
  reference lines, or the same lines in different colours, would cost that
  person a second legend to learn for no gain — and worse, would make the two
  charts hard to compare side by side when the obvious question is "did the two
  methods buy this name at the same times".

  So the price panel carries the same references single's does, at the same
  window, in the same colours and dash styles, and the trade markers use the
  same shapes:

      Price 25th  (1000d)   green,  dotted      rgba(46,160,67,0.9)
      Price Median(1000d)   blue,   dotted      rgba(100,100,200,0.9)
      Price 75th  (1000d)   red,    dotted      rgba(220,53,69,0.9)
      Price Mean  (1000d)   grey,   dashed
      Buy                   green   triangle-up
      Sell                  red     triangle-down
      Reinvest              orange  diamond

WHAT IS HERE THAT SINGLE'S CHART DOES NOT HAVE

  The threshold line: median x (1 + BUY_MAX_PREMIUM/100), the exact quantity the
  buy rule compares the price against. single's chart draws the references and
  leaves the condition implicit; drawing it makes the markers checkable by eye —
  they should appear where the price is under that line and stop where it is
  not. If they do not, the chart is showing a bug rather than a strategy.

  It moves when the config does, which is the point: change BUY_MAX_PREMIUM and
  the boundary in the chart moves with the buying.

WHAT IS DELIBERATELY LEFT OUT

  The P/E panel, its percentile bands, and the price line coloured by P/E zone.
  All of that describes a decision made on P/E, and this method's rule reads
  price only (USE_PE is False). Drawing it would imply the strategy looks at
  something it does not. It belongs here the day a rule reads P/E, and the data
  is already loaded for it.
"""

from pathlib import Path

import plotly.graph_objects as go


# Identical to single/median1000's backtest chart. See the module docstring.
_EVENT_STYLE = {
    "buy":      ("Mua",        "rgba(34,197,94,0.75)",  "#15803d", "triangle-up",   9),
    "sell":     ("Bán",        "rgba(239,68,68,0.75)",  "#991b1b", "triangle-down", 9),
    "reinvest": ("Tái đầu tư", "rgba(249,115,22,0.75)", "#c2410c", "diamond",       8),
}

_PCT_LINES = [
    ("p25",    "Giá 25th ({w}d)",   "rgba(46,160,67,0.9)"),
    ("median", "Giá Median ({w}d)", "rgba(100,100,200,0.9)"),
    ("p75",    "Giá 75th ({w}d)",   "rgba(220,53,69,0.9)"),
]


def build_symbol_chart(symbol: str, series, position, window: int,
                       max_premium: float, out_dir: Path) -> Path:
    """Write out_dir/<symbol>.html and return the path."""
    lo = series.warmup
    n = len(series)
    dates = series.dates[lo:n]
    prices = [series.close(i) for i in range(lo, n)]

    fig = go.Figure()

    # Rolling quartiles, dotted, in single's colours.
    for attr, tmpl, color in _PCT_LINES:
        getter = getattr(series, attr)
        fig.add_trace(go.Scatter(
            x=dates, y=[getter(window, i) for i in range(lo, n)],
            mode="lines", name=tmpl.format(w=window),
            line=dict(color=color, width=1, dash="dot"),
            hovertemplate=tmpl.format(w=window) + ": %{y:,.0f}<extra></extra>"))

    fig.add_trace(go.Scatter(
        x=dates, y=[series.mean(window, i) for i in range(lo, n)],
        mode="lines", name=f"Giá Mean ({window}d)",
        line=dict(color="rgba(120,120,120,0.85)", width=1.2, dash="dash"),
        hovertemplate=f"Mean ({window}d)" + ": %{y:,.0f}<extra></extra>"))

    # The buy condition itself. Not in single's chart — see the module docstring.
    fig.add_trace(go.Scatter(
        x=dates,
        y=[(m * (1 + max_premium / 100) if (m := series.median(window, i)) else None)
           for i in range(lo, n)],
        mode="lines", name=f"Ngưỡng mua (median {max_premium:+g}%)",
        line=dict(color="rgba(37,99,235,0.35)", width=1.4),
        hovertemplate="Ngưỡng: %{y:,.0f}<extra></extra>"))

    fig.add_trace(go.Scatter(
        x=dates, y=prices, mode="lines", name=f"{symbol} — giá",
        line=dict(color="#1f77b4", width=1.8),
        hovertemplate="Giá: %{y:,.0f}<extra></extra>"))

    by_kind: dict = {}
    for t in (position.trades if position else []):
        by_kind.setdefault(t.kind, []).append(t)

    for kind in ("buy", "sell", "reinvest"):
        trades = by_kind.get(kind)
        if not trades:
            continue
        label, fill, border, marker, size = _EVENT_STYLE[kind]
        fig.add_trace(go.Scatter(
            x=[t.date for t in trades], y=[t.price for t in trades],
            mode="markers", name=f"{label} ({len(trades)})",
            marker=dict(color=fill, size=size, symbol=marker,
                        line=dict(color=border, width=1)),
            customdata=[[t.amount, t.shares] for t in trades],
            hovertemplate=(f"<b>{label}</b>  %{{x|%Y-%m-%d}}<br>"
                           "Giá: %{y:,.0f}<br>Tiền: %{customdata[0]:,.0f}<br>"
                           "Cổ phiếu: %{customdata[1]:,.1f}<extra></extra>")))

    n_buy, n_sell = len(by_kind.get("buy", [])), len(by_kind.get("sell", []))
    n_rei = len(by_kind.get("reinvest", []))
    sub = f"{n_buy} lệnh mua"
    if n_sell:
        sub += f" · {n_sell} lệnh bán"
    if n_rei:
        sub += f" · {n_rei} tái đầu tư"
    if position and position.shares > 0:
        sub += (f" · đang giữ {position.shares:,.0f} cp · vốn gốc "
                f"{position.basis:,.0f}đ · giá trị {position.shares * prices[-1]:,.0f}đ")

    fig.update_layout(
        # The subtitle is a second line inside the title, so a horizontal legend
        # at the usual y=1.02 lands on top of it.
        title=dict(text=f"<b>{symbol}</b><br><span style='font-size:13px;color:#64748b'>"
                        f"{sub}</span>", x=0.01, xanchor="left", y=0.97,
                   yanchor="top"),
        hovermode="x unified",
        plot_bgcolor="white", paper_bgcolor="white",
        font=dict(family="IBM Plex Sans, system-ui, sans-serif", size=13),
        legend=dict(orientation="h", yanchor="bottom", y=1.01, x=0,
                    font=dict(size=11.5)),
        margin=dict(l=74, r=24, t=150, b=48),
        xaxis=dict(showgrid=True, gridcolor="#eef2f7",
                   rangeslider=dict(visible=True, thickness=0.06)),
        yaxis=dict(showgrid=True, gridcolor="#eef2f7", tickformat=",.0f",
                   title="VND"),
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{symbol.lower()}.html"
    fig.write_html(str(path), include_plotlyjs="cdn", full_html=True,
                   config={"displaylogo": False})
    return path


def build_all(result, market, config, out_dir: Path) -> dict:
    """
    One chart per symbol the portfolio actually traded. Returns {symbol: filename}.

    Symbols never bought are skipped: a chart with no markers says nothing the
    report's table does not, and building all of them would be most of the cost
    for none of the information.
    """
    wallet = result["wallet"]
    out = {}
    for symbol, position in wallet.positions.items():
        if not position.trades:
            continue
        path = build_symbol_chart(symbol, market[symbol], position,
                                  config.BUY_WINDOW, config.BUY_MAX_PREMIUM,
                                  out_dir)
        out[symbol] = path.name
    return out
