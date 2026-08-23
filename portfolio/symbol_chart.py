"""
One Plotly chart per symbol, built to match single/median1000's backtest chart.

WHY IT COPIES THAT CHART

  The two methods are independent code and must stay that way, but the person
  reading them is one person, and the obvious question when looking at both is
  "did they buy this name at the same times". That question is only answerable
  if the two pictures are the same picture. A different axis arrangement or a
  different palette would cost a second legend to learn and make the comparison
  by eye impossible.

  So the structure is taken from the reference chart rather than designed:

      y1, LEFT, LOG      P/E: static quantile bands, rolling 25/50/75, mean,
                         and the P/E line itself
      y2, RIGHT, LINEAR  Price: rolling 25/50/75, mean, and the price line
      y3, hidden strip   trade markers, at a fixed height near the bottom

  Colours and dash styles are copied exactly — the rolling quartiles are green /
  blue-violet / red dotted at width 1, both means are purple dotted at width
  1.5, the P/E line is #1f77b4 at 1.8. Marker shapes are single's too: green
  triangle-up for a buy, red triangle-down for a sell, orange diamond for a
  reinvest.

TWO DELIBERATE DEPARTURES

  1. THE PRICE LINE IS COLOURED BY THIS METHOD'S OWN CONDITION.

     single colours it by P/E zone, because a P/E zone is what its chart is
     about. This method's rule reads price against its own median and never
     looks at P/E, so colouring by P/E here would draw a decision the strategy
     does not make. The segments are the buy condition instead:

         slate   before warmup — no decision was possible
         green   the rule would buy
         grey    the rule would not

     That makes the chart self-checking. Markers must fall on green and nowhere
     else; if one sits on grey, the chart has found a bug.

  2. THE THRESHOLD LINE IS DRAWN.

     median x (1 + BUY_MAX_PREMIUM/100), the exact quantity the rule compares
     against. single draws its references and leaves the condition implicit.
     Drawing it means the boundary moves visibly when the config changes.

  P/E stays on the left axis even though no rule reads it, because it is half of
  what the reference chart shows and dropping it would not be the same chart.
"""

from pathlib import Path

import plotly.graph_objects as go

# Copied from single/median1000's backtest chart — see the module docstring.
_QUARTILE_COLORS = {
    "p25":    "rgba(46,160,67,0.9)",
    "median": "rgba(100,100,200,0.9)",
    "p75":    "rgba(220,53,69,0.9)",
}
_MEAN_COLOR = "rgba(150,0,200,0.8)"
_PE_LINE = "#1f77b4"

_EVENT_STYLE = {
    "buy":      ("Mua",        "rgba(34,197,94,0.75)",  "#15803d", "triangle-up",   9),
    "sell":     ("Bán",        "rgba(239,68,68,0.75)",  "#991b1b", "triangle-down", 9),
    "reinvest": ("Tái đầu tư", "rgba(249,115,22,0.75)", "#c2410c", "diamond",       8),
}

# Price-line segments. Same idea as single's P/E zones, different question —
# see the module docstring.
_STATE_STYLE = [
    ("warmup", "Chưa đánh giá", "#475569"),
    ("buy",    "Đủ điều kiện mua", "#2ca02c"),
    ("no",     "Không đủ điều kiện", "#a0aec0"),
]


def _segments(states, values, want):
    """
    `values` where `states` equals `want`, None elsewhere.

    A point adjacent to a matching one is kept rather than nulled, so
    consecutive segments of different colours join instead of leaving a one-bar
    gap at every boundary.
    """
    n = len(values)
    out = []
    for i in range(n):
        if states[i] == want:
            out.append(values[i])
        else:
            near = (i > 0 and states[i - 1] == want) or (i < n - 1 and states[i + 1] == want)
            out.append(values[i] if near else None)
    return out


def build_symbol_chart(symbol: str, series, position, window: int,
                       max_premium: float, out_dir: Path) -> Path:
    n = len(series)
    lo = series.warmup
    # Full history, so the warmup stretch is visible as its own colour rather
    # than simply absent — "we could not decide here" and "we decided not to"
    # are different facts and the chart should not merge them.
    dates = series.dates
    prices = [series.close(i) for i in range(n)]
    pes = [series.pe(i) for i in range(n)]

    medians = [series.median(window, i) if i >= lo else None for i in range(n)]
    limits = [(m * (1 + max_premium / 100) if m else None) for m in medians]

    states = []
    for i in range(n):
        if i < lo or medians[i] is None:
            states.append("warmup")
        else:
            states.append("buy" if prices[i] < limits[i] else "no")

    fig = go.Figure()

    # ── y1: P/E ──────────────────────────────────────────────────────────────
    has_pe = any(v is not None for v in pes)
    if has_pe:
        for attr, label in (("pe_p25", "P/E 25th ({w}d)"),
                            ("pe_median", "P/E Median ({w}d)"),
                            ("pe_p75", "P/E 75th ({w}d)")):
            key = attr.split("_", 1)[1]
            fig.add_trace(go.Scatter(
                x=dates,
                y=[series.pe_stat(attr, window, i) if i >= lo else None
                   for i in range(n)],
                mode="lines", name=label.format(w=window), yaxis="y",
                line=dict(color=_QUARTILE_COLORS[key], width=1, dash="dot"),
                hovertemplate=label.format(w=window) + ": %{y:.2f}x<extra></extra>"))
        fig.add_trace(go.Scatter(
            x=dates,
            y=[series.pe_stat("pe_mean", window, i) if i >= lo else None
               for i in range(n)],
            mode="lines", name=f"P/E Mean ({window}d)", yaxis="y",
            line=dict(color=_MEAN_COLOR, width=1.5, dash="dot"),
            hovertemplate=f"P/E Mean ({window}d)" + ": %{y:.2f}x<extra></extra>"))
        fig.add_trace(go.Scatter(
            x=dates, y=pes, mode="lines", name=f"{symbol} P/E", yaxis="y",
            line=dict(color=_PE_LINE, width=1.8),
            hovertemplate="P/E: %{y:.2f}x<extra></extra>"))

    # ── y2: price ────────────────────────────────────────────────────────────
    for attr, label in (("p25", "Giá 25th ({w}d)"),
                        ("median", "Giá Median ({w}d)"),
                        ("p75", "Giá 75th ({w}d)")):
        getter = getattr(series, attr)
        fig.add_trace(go.Scatter(
            x=dates, y=[getter(window, i) if i >= lo else None for i in range(n)],
            mode="lines", name=label.format(w=window), yaxis="y2",
            line=dict(color=_QUARTILE_COLORS[attr], width=1, dash="dot"),
            hovertemplate=label.format(w=window) + ": %{y:,.0f}<extra></extra>"))
    fig.add_trace(go.Scatter(
        x=dates, y=[series.mean(window, i) if i >= lo else None for i in range(n)],
        mode="lines", name=f"Giá Mean ({window}d)", yaxis="y2",
        line=dict(color=_MEAN_COLOR, width=1.5, dash="dot"),
        hovertemplate=f"Giá Mean ({window}d)" + ": %{y:,.0f}<extra></extra>"))
    fig.add_trace(go.Scatter(
        x=dates, y=limits, mode="lines", yaxis="y2",
        name=f"Ngưỡng mua (median {max_premium:+g}%)",
        line=dict(color="rgba(37,99,235,0.45)", width=1.4),
        hovertemplate="Ngưỡng: %{y:,.0f}<extra></extra>"))

    for key, label, color in _STATE_STYLE:
        if key not in states:
            continue
        fig.add_trace(go.Scatter(
            x=dates, y=_segments(states, prices, key), mode="lines",
            name=label, yaxis="y2", connectgaps=False,
            line=dict(color=color, width=1.5),
            hovertemplate="Giá: %{y:,.0f}<extra></extra>"))

    # ── y3: trade markers ────────────────────────────────────────────────────
    by_kind: dict = {}
    for t in (position.trades if position else []):
        by_kind.setdefault(t.kind, []).append(t)

    for kind in ("buy", "sell", "reinvest"):
        trades = by_kind.get(kind)
        if not trades:
            continue
        label, fill, border, marker, size = _EVENT_STYLE[kind]
        fig.add_trace(go.Scatter(
            x=[t.date for t in trades], y=[0.75] * len(trades),
            mode="markers", name=f"{label} ({len(trades)})", yaxis="y3",
            marker=dict(color=fill, size=size, symbol=marker,
                        line=dict(color=border, width=1)),
            customdata=[[t.price, t.amount, t.shares] for t in trades],
            hovertemplate=(f"<b>{label}</b>  %{{x|%Y-%m-%d}}<br>"
                           "Giá: %{customdata[0]:,.0f}<br>"
                           "Tiền: %{customdata[1]:,.0f}<br>"
                           "Cổ phiếu: %{customdata[2]:,.1f}<extra></extra>")))

    n_buy, n_sell = len(by_kind.get("buy", [])), len(by_kind.get("reinvest", []))
    sub = f"{len(by_kind.get('buy', []))} lệnh mua"
    if by_kind.get("sell"):
        sub += f" · {len(by_kind['sell'])} lệnh bán"
    if by_kind.get("reinvest"):
        sub += f" · {len(by_kind['reinvest'])} tái đầu tư"
    if position and position.shares > 0:
        sub += (f" · giữ {position.shares:,.0f} cp · vốn gốc {position.basis:,.0f}đ"
                f" · giá trị {position.shares * prices[-1]:,.0f}đ")

    span = f"{str(dates[0])[:4]} — {str(dates[-1])[:4]}"
    fig.update_layout(
        title=dict(text=f"{symbol} — Giá & P/E  <sup>{span}</sup><br>"
                        f"<span style='font-size:12.5px;color:#64748b'>{sub}</span>",
                   font=dict(size=18), x=0.01, xanchor="left"),
        hovermode="x unified",
        plot_bgcolor="white", paper_bgcolor="white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                    font=dict(size=11)),
        margin=dict(l=60, r=80, t=150, b=60),
        xaxis=dict(title=dict(text="Date"), showgrid=True,
                   gridcolor="rgba(200,200,200,0.3)", hoverformat="%Y-%m-%d"),
        yaxis=dict(title=dict(text="P/E (x, log)"), type="log", showgrid=True,
                   gridcolor="rgba(200,200,200,0.3)", side="left"),
        yaxis2=dict(title=dict(text=f"{symbol} (VND)"), overlaying="y",
                    side="right", showgrid=False, tickformat=","),
        # The marker strip. Fixed 0..1 with the axis hidden, so markers sit on
        # one line near the bottom regardless of price scale — the reference
        # chart's arrangement, and the reason a marker's y carries no meaning.
        yaxis3=dict(overlaying="y", side="left", range=[0, 6], visible=False,
                    fixedrange=True),
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{symbol.lower()}.html"
    fig.write_html(str(path), include_plotlyjs="cdn", full_html=True,
                   config={"responsive": True, "displaylogo": False})
    return path


def build_all(result, market, config, out_dir: Path) -> dict:
    """
    One chart per symbol the portfolio traded. Returns {symbol: filename}.

    Symbols never bought are skipped: a chart with no markers adds nothing to
    the report's table.
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
