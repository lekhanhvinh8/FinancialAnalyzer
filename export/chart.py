"""
VN30 / VN Diamond Aggregate P/E chart module.

Usage:
    from chart import pe_chart, save_chart

    fig, pe_dates, pe_values, price_data = pe_chart()
    fig, pe_dates, pe_values, price_data = pe_chart(index="vndiamond")
    fig.show()                                        # static view
    save_chart(fig, pe_dates, pe_values, price_data, "pe.html")  # interactive

CLI:
    python chart.py vn30
    python chart.py vndiamond
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
import pandas as pd
import plotly.graph_objects as go

import database as db

import functools
_PE_LOADERS = {
    # Key is the internal index id (lowercase); the bound symbol is how it is
    # stored, which is uppercase like every other table. See syncs/calculate.py.
    "vn30":      functools.partial(db.load_pe_ratios, "VN30"),
    "vn30exvic": functools.partial(db.load_pe_ratios, "VN30EXVIC"),
    "vndiamond": functools.partial(db.load_pe_ratios, "VNDIAMOND"),
    "vnfinlead": functools.partial(db.load_pe_ratios, "VNFINLEAD"),
}

_INDEX_LABELS = {
    "vn30":       "VN30",
    "vn30exvic":  "VN30 ex-VIC",
    "vndiamond":  "VN Diamond",
    "vnfinlead":  "VN Fin Lead",
}

_INDEX_PRICE_SYMBOL = {
    "vn30":       "VN30",
    "vndiamond":  "VNDIAMOND",
    "vnfinlead":  "VNFINLEAD",
}

# Market context on every P/E chart, valuation and backtest alike: lines to read
# the market by eye, which no strategy reads. Pinned here rather than imported
# from breadth/ for the same reason save_backtest_chart takes its windows as
# arguments — export/ must not depend on a strategy package. The prem basket is
# the one the breadth profile decides on, so the two lines agree where both show.
CONTEXT_EXVIC = "VN30EXVIC"                                   # pe_ratios symbol
CONTEXT_PREM  = ("all-VIC-VIX", 1000, "base", "prem_median")  # breadth_signals key

# Price-line colors/labels per P/E zone (cheap → expensive). The hover anchor
# feeds these per point as customdata, so the tooltip's dot and label match the
# line segment under the cursor.
_ZONE_COLORS   = ["#2ca02c", "#f0c040", "#ff7f0e", "#d62728"]
_ZONE_LABELS   = ["Cheap", "Fair", "High", "Exp."]
_NO_ZONE_COLOR = "#888888"
# Bars before a backtest's start index — a state of its own, distinct from
# "evaluated, no condition true". See save_backtest_chart.
_NOT_EVALUATED_COLOR = "#475569"
_NO_ZONE_LABEL = "—"

_DEFAULT_PCT_WINDOW = 1000

# z_dev strip: which stored configuration the charts read, and how densely the
# stat-window slider is populated. See syncs/zdev.py for the sweep itself.
ZDEV_MEDIAN_WINDOW = 1000
ZDEV_WINDOW_STEP   = 10
SIGNAL_WINDOW_STEP = 10   # same idea for trend_signals — see _inject_signals_into_html


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_pe(index="vn30", start=None, end=None, min_members=5) -> pd.DataFrame:
    index = index.lower()
    loader = _PE_LOADERS.get(index)
    if loader is None:
        raise ValueError(f"Unknown index '{index}'. Choose from: {list(_PE_LOADERS)}")
    db.init_db()
    df = loader(start, end).reset_index()
    df = df.dropna(subset=["pe_ratio"])
    df = df[df["member_count"] >= min_members]
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


def _fetch_index_price(index: str, start: str, end: str) -> pd.Series | None:
    symbol = _INDEX_PRICE_SYMBOL.get(index.lower())
    if not symbol:
        return None
    try:
        from vnstock.api.quote import Quote
        df = Quote(symbol=symbol, source="VCI").history(start=start, end=end, interval="1D")
        if df is None or df.empty:
            return None
        df["time"] = pd.to_datetime(df["time"]).dt.normalize()
        return df.set_index("time").sort_index()["close"]
    except Exception:
        return None


def _context_series(dates: list[str]) -> dict:
    """
    The market-context series (see CONTEXT_EXVIC / CONTEXT_PREM) on `dates`,
    each carried forward from its last known day; None where it has no value
    yet or where the stored value is missing (VN30 ex-VIC has no P/E through
    2015–16). Empty when neither is stored.
    """
    idx = pd.DatetimeIndex(pd.to_datetime(dates))
    with db._conn() as con:
        exvic = pd.read_sql(
            "SELECT date, pe_ratio AS v FROM pe_ratios WHERE symbol=? ORDER BY date",
            con, params=(CONTEXT_EXVIC,))
        prem = pd.read_sql(
            "SELECT date, value AS v FROM breadth_signals WHERE universe=? AND window_days=?"
            " AND variant=? AND signal=? ORDER BY date",
            con, params=CONTEXT_PREM)
    out = {}
    for key, df in (("exvic", exvic), ("prem", prem)):
        if df.empty:
            continue
        s = df.set_index(pd.to_datetime(df["date"]))["v"].astype(float)
        # method="ffill" takes the value AT the nearest earlier date, NaN
        # included, so a stored gap stays a gap instead of being bridged.
        vals = s.reindex(idx, method="ffill")
        out[key] = [None if v != v else float(v) for v in vals]
    return out


def _rolling_stat(values, window, stat):
    """stat: 'mean' | 'median' | float quantile 0-1"""
    s = pd.Series(values)
    if stat == "mean":
        return s.rolling(window, min_periods=window).mean().where(s.notna()).tolist()
    if stat == "median":
        return s.rolling(window, min_periods=window).median().where(s.notna()).tolist()
    return s.rolling(window, min_periods=window).quantile(stat).where(s.notna()).tolist()


def _pct_trace(dates, values, window, quantile, name_tmpl, color, yaxis):
    """Rolling percentile as a Scatter trace. name_tmpl receives window, e.g. 'P/E 25th ({w}d)'"""
    y = _rolling_stat(values, window, quantile)
    return go.Scatter(
        x=dates, y=y,
        mode="lines",
        name=name_tmpl.format(w=window),
        line=dict(color=color, width=1, dash="dot"),
        yaxis=yaxis,
        hovertemplate=name_tmpl.format(w=window) + ": %{y:,.2f}<extra></extra>",
        showlegend=True,
    )


# ── Main chart builder ────────────────────────────────────────────────────────

def pe_chart(
    index: str = "vn30",
    start: str | None = None,
    end: str | None = None,
    min_members: int = 5,
    bands: bool = True,
    mean_window: int = 1000,
    median_window: int = 1000,
    pct_window: int = _DEFAULT_PCT_WINDOW,
    title: str | None = None,
) -> tuple:
    """
    Build an interactive Plotly figure of aggregate P/E + index price.

    Returns (fig, pe_dates, pe_values, price_data)
    where price_data = (price_dates, price_values) or None.
    """
    index = index.lower()
    label = _INDEX_LABELS.get(index, index.upper())
    if title is None:
        title = f"{label} — Aggregate P/E & Index Price"

    df = load_pe(index, start, end, min_members)
    if df.empty:
        raise ValueError("No P/E data in the requested range.")

    pe = df["pe_ratio"]
    pe_dates  = df["date"].dt.strftime("%Y-%m-%d").tolist()
    pe_values = pe.tolist()
    current      = pe.iloc[-1]
    current_date = df["date"].iloc[-1].strftime("%Y-%m-%d")
    x0 = df["date"].iloc[0]
    x1 = df["date"].iloc[-1]

    idx_price = _fetch_index_price(index, df["date"].iloc[0].strftime("%Y-%m-%d"), current_date)

    fig = go.Figure()

    # ── P/E percentile bands (static fill, full history) ─────────────────────
    if bands:
        pct25_full = pe.quantile(0.25)
        pct75_full = pe.quantile(0.75)
        x_fill = [x0, x1]
        for lo, hi, color, name in [
            (pe.min(),   pct25_full, "rgba(46,160,67,0.15)",  "Cheap (< 25th)"),
            (pct25_full, pct75_full, "rgba(255,200,0,0.12)",  "Fair (25–75th)"),
            (pct75_full, pe.max(),   "rgba(220,53,69,0.15)",  "Expensive (> 75th)"),
        ]:
            fig.add_trace(go.Scatter(
                x=x_fill + x_fill[::-1], y=[lo, lo, hi, hi],
                fill="toself", fillcolor=color, line=dict(width=0),
                mode="lines", name=name, hoverinfo="skip",
                showlegend=True, yaxis="y1",
            ))

    # ── P/E rolling percentile lines (traces 3, 4, 5) ────────────────────────
    for q, color, tmpl in [
        (0.25, "rgba(46,160,67,0.9)",   "P/E 25th ({w}d)"),
        (0.50, "rgba(100,100,200,0.9)", "P/E Median ({w}d)"),
        (0.75, "rgba(220,53,69,0.9)",   "P/E 75th ({w}d)"),
    ]:
        fig.add_trace(_pct_trace(df["date"], pe_values, pct_window, q, tmpl, color, "y1"))

    # ── Index price line (y2) — 4 colored traces if has_price ────────────────
    price_data = None
    if idx_price is not None and not idx_price.empty:
        price_dates  = idx_price.index.strftime("%Y-%m-%d").tolist()
        price_values = idx_price.tolist()

        # Align PE to price dates for zone coloring
        pe_aligned = (
            df.set_index("date")["pe_ratio"]
              .reindex(idx_price.index, method="ffill")
              .tolist()
        )
        price_data   = (price_dates, price_values, pe_aligned,
                        float(pe.quantile(0.25)), float(pe.quantile(0.50)), float(pe.quantile(0.75)))
        _, _, _, p25_s, median_s, p75_s = price_data

        def _zone(v):
            if v is None or (isinstance(v, float) and v != v): return -1
            if v < p25_s:    return 0
            if v < median_s: return 1
            if v < p75_s:    return 2
            return 3

        zones = [_zone(v) for v in pe_aligned]
        n_p   = len(price_values)

        PRICE_ZONES = [
            (0, _ZONE_COLORS[0], f"Cheap  P/E<{p25_s:.1f}"),
            (1, _ZONE_COLORS[1], f"Fair   P/E {p25_s:.1f}–{median_s:.1f}"),
            (2, _ZONE_COLORS[2], f"High   P/E {median_s:.1f}–{p75_s:.1f}"),
            (3, _ZONE_COLORS[3], f"Exp.   P/E>{p75_s:.1f}"),
        ]
        for z, color, name in PRICE_ZONES:
            y_zone = []
            for i in range(n_p):
                if zones[i] == z:
                    y_zone.append(price_values[i])
                else:
                    adj = (i > 0 and zones[i-1] == z) or (i < n_p-1 and zones[i+1] == z)
                    y_zone.append(price_values[i] if adj else None)
            fig.add_trace(go.Scatter(
                x=idx_price.index, y=y_zone,
                mode="lines", name=name,
                line=dict(color=color, width=1.5),
                legendgroup="price_color", legendgrouptitle_text=f"{label} Price",
                yaxis="y2",
                # Hover is served by the gap-free anchor trace below: these four are
                # null outside their zone, and "x unified" would otherwise pull each
                # one's nearest non-null point (weeks away) into the tooltip.
                hoverinfo="skip",
            ))

        # Price rolling percentile lines (traces 7, 8, 9)
        for q, color, tmpl in [
            (0.25, "rgba(46,160,67,0.9)",   "Price 25th ({w}d)"),
            (0.50, "rgba(100,100,200,0.9)", "Price Median ({w}d)"),
            (0.75, "rgba(220,53,69,0.9)",   "Price 75th ({w}d)"),
        ]:
            fig.add_trace(_pct_trace(idx_price.index, price_values, pct_window, q, tmpl, color, "y2"))

    # ── P/E rolling mean ─────────────────────────────────────────────────────
    pe_mean_vals = pd.Series(pe_values).rolling(mean_window, min_periods=1).mean().tolist()
    fig.add_trace(go.Scatter(
        x=df["date"], y=pe_mean_vals,
        mode="lines", name=f"P/E Mean ({mean_window}d)",
        line=dict(color="rgba(150,0,200,0.8)", width=1.5, dash="dot"),
        yaxis="y1",
    ))

    # ── Price rolling mean ────────────────────────────────────────────────────
    if idx_price is not None and not idx_price.empty:
        price_mean_vals = pd.Series(price_values).rolling(mean_window, min_periods=1).mean().tolist()
        fig.add_trace(go.Scatter(
            x=idx_price.index, y=price_mean_vals,
            mode="lines", name=f"Price Mean ({mean_window}d)",
            line=dict(color="rgba(150,0,200,0.8)", width=1.5, dash="dot"),
            yaxis="y2",
        ))

        # ── Price hover anchor (trace 15) ────────────────────────────────────
        # Invisible, gap-free copy of the price series. The four colored zone
        # traces are hoverinfo="skip", so this is the single source of the price
        # row in the unified tooltip — always at the hovered date. Plotly's row
        # swatch is per-trace, so the zone color rides along per point in
        # customdata and is drawn as a ● inside the row text instead.
        fig.add_trace(go.Scatter(
            x=idx_price.index, y=price_values,
            mode="lines", name=f"{label} Price",
            line=dict(width=0, color=_NO_ZONE_COLOR),
            yaxis="y2", showlegend=False, legendgroup="price_color",
            customdata=[
                [_ZONE_COLORS[z], _ZONE_LABELS[z]] if z >= 0 else [_NO_ZONE_COLOR, _NO_ZONE_LABEL]
                for z in zones
            ],
            # No date here — "x unified" already prints it once in the header.
            hovertemplate=(
                "<span style='color:%{customdata[0]}'>●</span> "
                "%{customdata[1]}: %{y:,.0f} pts<extra></extra>"
            ),
        ))

    # ── P/E line ──────────────────────────────────────────────────────────────
    fig.add_trace(go.Scatter(
        x=df["date"], y=pe_values,
        mode="lines", name="Aggregate P/E",
        line=dict(color="#1f77b4", width=1.8), yaxis="y1",
        hovertemplate="P/E: %{y:.2f}x<br>Members: %{customdata}<extra></extra>",
        customdata=df["member_count"],
    ))


    # ── Current P/E marker ────────────────────────────────────────────────────
    fig.add_trace(go.Scatter(
        x=[x1], y=[current],
        mode="markers+text", marker=dict(size=8, color="#ff7f0e"),
        text=[f"  {current:.2f}x"], textposition="middle right",
        name=f"Current P/E ({current_date})", yaxis="y1",
        hovertemplate=f"P/E: {current:.2f}x<extra></extra>",
    ))

    # ── Layout ────────────────────────────────────────────────────────────────
    date_range_str = f"{df['date'].iloc[0].strftime('%Y')} – {df['date'].iloc[-1].strftime('%Y')}"
    fig.update_layout(
        title=dict(text=f"{title}  <sup>{date_range_str}</sup>", font_size=18),
        xaxis=dict(title="Date", showgrid=True, gridcolor="rgba(200,200,200,0.3)", hoverformat="%Y-%m-%d"),
        yaxis=dict(title="P/E (x, log)", type="log", showgrid=True, gridcolor="rgba(200,200,200,0.3)", side="left"),
        yaxis2=dict(title=f"{label} Index (pts)", overlaying="y", side="right", showgrid=False, tickformat=","),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        plot_bgcolor="white", paper_bgcolor="white",
        margin=dict(l=60, r=80, t=80, b=60),
    )

    return fig, pe_dates, pe_values, price_data


# ── Interactive HTML export ───────────────────────────────────────────────────

def save_chart(
    fig: go.Figure,
    pe_dates: list,
    pe_values: list,
    price_data: tuple | None = None,
    path: str = "pe_chart.html",
    pct_window: int = _DEFAULT_PCT_WINDOW,
    mean_window: int = 1000,
) -> str:
    """
    Save the chart as a self-contained HTML with interactive controls:
    - P/E percentile lines: rolling 25th / Median / 75th with adjustable window
    - Price percentile lines: rolling 25th / Median / 75th with adjustable window
    - P/E Mean MA + Median MA: window input + visibility checkbox
    - Price Mean MA + Median MA: window input + visibility checkbox
    """
    n = len(fig.data)
    has_price = price_data is not None

    # Trace layout (bands=True, has_price=True):
    # 0,1,2=bands | 3,4,5=pe_pct | 6,7,8,9=price_colored | 10,11,12=price_pct |
    # 13=pe_mean | 14=price_mean | 15=price_hover_anchor | 16=pe_line | 17=marker
    # Trace layout (bands=True, has_price=False):
    # 0,1,2=bands | 3,4,5=pe_pct | 6=pe_mean | 7=pe_line | 8=marker
    if has_price:
        pe_pct_idx       = [3, 4, 5]
        price_pct_idx    = [10, 11, 12]
        pe_mean_idx      = 13
        price_mean_idx   = 14
        price_anchor_idx = 15
        pe_line_idx      = n - 2
        marker_idx       = n - 1
    else:
        pe_pct_idx       = [3, 4, 5]
        price_pct_idx    = []
        pe_mean_idx      = 6
        price_mean_idx   = None
        price_anchor_idx = None
        pe_line_idx      = n - 2
        marker_idx       = n - 1

    plot_html = fig.to_html(include_plotlyjs="cdn", full_html=False, div_id="peChart")

    pe_dates_json        = json.dumps(pe_dates)
    pe_values_json       = json.dumps(pe_values)
    price_dates_json     = json.dumps(price_data[0] if price_data else [])
    price_values_json    = json.dumps(price_data[1] if price_data else [])
    pe_aligned_json      = json.dumps(price_data[2] if price_data else [])
    global_p25_json      = json.dumps(price_data[3] if price_data else None)
    global_med_json      = json.dumps(price_data[4] if price_data else None)
    global_p75_json      = json.dumps(price_data[5] if price_data else None)

    ctx = _context_series(price_data[0]) if has_price else {}
    exvic_json = json.dumps(ctx.get("exvic", []))
    prem_json  = json.dumps(ctx.get("prem", []))

    pe_mean_idx_json      = json.dumps(pe_mean_idx)
    price_mean_idx_json   = json.dumps(price_mean_idx)
    price_anchor_idx_json = json.dumps(price_anchor_idx)
    zone_colors_json      = json.dumps(_ZONE_COLORS)
    zone_labels_json      = json.dumps(_ZONE_LABELS)
    no_zone_color_json    = json.dumps(_NO_ZONE_COLOR)
    no_zone_label_json    = json.dumps(_NO_ZONE_LABEL)

    pe_mean_control = f"""
  <div class="divider"></div>
  <span class="section-label">P/E Mean</span>
  <div class="ma-group">
    <label class="chk"><input type="checkbox" id="peMeanVis"> Show</label>
    <input type="number" id="peMeanW" value="{mean_window}" min="5" max="5000" step="10" title="Rolling window (days)">
    <span class="unit">d</span>
  </div>
  <span class="off-wrap"><input type="checkbox" id="off-en-peMean">±<input type="number" id="off-pct-peMean" class="off-pct" value="50">%</span>"""

    price_pct_control = ""
    price_checkbox_js = ""
    color_mode_bar = ""

    if has_price:
        price_pct_control = f"""
  <div class="divider"></div>
  <span class="section-label">P/E Line</span>
  <label class="chk"><input type="checkbox" id="peLineVis"> Show</label>
  <div class="divider"></div>
  <span class="section-label">Price Mean</span>
  <div class="ma-group">
    <label class="chk"><input type="checkbox" id="priceMeanVis"> Show</label>
    <input type="number" id="priceMeanW" value="{mean_window}" min="5" max="5000" step="10" title="Rolling window (days)">
    <span class="unit">d</span>
  </div>
  <span class="off-wrap"><input type="checkbox" id="off-en-prMean">±<input type="number" id="off-pct-prMean" class="off-pct" value="50">%</span>
  <div class="divider"></div>
  <span class="section-label">Price Line</span>
  <label class="chk"><input type="checkbox" id="priceColorVis" checked> Show</label>
  <div class="divider"></div>
  <span class="section-label">Price Percentiles</span>
  <div class="ma-group">
    <label class="chk"><input type="checkbox" id="pricePctVis" checked> Show</label>
    <input type="number" id="pricePctW" value="{pct_window}" min="20" max="5000" step="50" title="Rolling window (days)">
    <span class="unit">d</span>
  </div>
  <label class="chk" style="margin-left:4px">
    <input type="checkbox" class="pct-price-cb" data-sub="0">
    <span class="dot" style="background:rgba(46,160,67,0.9)"></span>25th</label>
  <span class="off-wrap"><input type="checkbox" id="off-en-prPct25">±<input type="number" id="off-pct-prPct25" class="off-pct" value="50">%</span>
  <label class="chk">
    <input type="checkbox" class="pct-price-cb" data-sub="1" checked>
    <span class="dot" style="background:rgba(100,100,200,0.9)"></span>Med</label>
  <span class="off-wrap"><input type="checkbox" id="off-en-prPctMed">±<input type="number" id="off-pct-prPctMed" class="off-pct" value="50">%</span>
  <label class="chk">
    <input type="checkbox" class="pct-price-cb" data-sub="2">
    <span class="dot" style="background:rgba(220,53,69,0.9)"></span>75th</label>
  <span class="off-wrap"><input type="checkbox" id="off-en-prPct75">±<input type="number" id="off-pct-prPct75" class="off-pct" value="50">%</span>"""

        price_checkbox_js = f"""
document.getElementById('peLineVis').addEventListener('change', function() {{
  Plotly.restyle(gd, {{ visible: [this.checked ? true : 'legendonly'] }}, [{pe_line_idx}]);
}});
document.getElementById('priceColorVis').addEventListener('change', function() {{
  const v = this.checked ? true : 'legendonly';
  // {price_anchor_idx} is the invisible hover-anchor trace — hide it with the
  // colored zone lines so the tooltip's price row disappears too.
  Plotly.restyle(gd, {{ visible: [v, v, v, v, v] }}, [6, 7, 8, 9, {price_anchor_idx}]);
}});
function togglePricePct() {{
  const vis = document.getElementById('pricePctVis').checked;
  const subs = [...document.querySelectorAll('.pct-price-cb')].map(c => c.checked);
  Plotly.restyle(gd, {{
    visible: [
      (vis && subs[0]) ? true : 'legendonly',
      (vis && subs[1]) ? true : 'legendonly',
      (vis && subs[2]) ? true : 'legendonly',
    ]
  }}, [{price_pct_idx[0]}, {price_pct_idx[1]}, {price_pct_idx[2]}]);
}}
function recomputePricePct() {{
  const ppw = parseInt(document.getElementById('pricePctW').value) || {pct_window};
  const vis = document.getElementById('pricePctVis').checked;
  const subs = [...document.querySelectorAll('.pct-price-cb')].map(c => c.checked);
  const layoutUpd = {{'yaxis2.range': priceY2Range}};
  if (priceValues.length > 0 && _COLOR_SRC[colorMode].pctW === 'pricePctW') {{
    const zoneY = _computeZoneY();
    [6, 7, 8, 9].forEach((ti, i) => {{ gd.data[ti].y = zoneY[i]; }});
    _syncAnchorZones(zoneY.zones);
  }}
  const prP25Y = rollingQuantile(priceValues, ppw, 0.25);
  const prMedY = rollingQuantile(priceValues, ppw, 0.50);
  const prP75Y = rollingQuantile(priceValues, ppw, 0.75);
  Plotly.update(gd, {{
    y: [prP25Y, prMedY, prP75Y],
    name: ['Price 25th (' + ppw + 'd)', 'Price Median (' + ppw + 'd)', 'Price 75th (' + ppw + 'd)'],
    visible: [
      (vis && subs[0]) ? true : 'legendonly',
      (vis && subs[1]) ? true : 'legendonly',
      (vis && subs[2]) ? true : 'legendonly',
    ]
  }}, layoutUpd, [{price_pct_idx[0]}, {price_pct_idx[1]}, {price_pct_idx[2]}]);
  _applyOffset('prPct25', prP25Y);
  _applyOffset('prPctMed', prMedY);
  _applyOffset('prPct75', prP75Y);
}}
document.getElementById('pricePctVis').addEventListener('change', togglePricePct);
document.querySelectorAll('.pct-price-cb').forEach(cb => cb.addEventListener('change', togglePricePct));
document.getElementById('pricePctW').addEventListener('keydown', e => {{ if (e.key==='Enter') recomputePricePct(); }});
function recomputePriceMean() {{
  const w = parseInt(document.getElementById('priceMeanW').value) || {mean_window};
  const vis = document.getElementById('priceMeanVis').checked;
  const meanY = rollingMean(priceValues, w);
  Plotly.update(gd, {{
    y: [meanY],
    name: ['Price Mean (' + w + 'd)'],
    visible: [vis ? true : 'legendonly'],
  }}, {{'yaxis2.range': priceY2Range}}, [priceMeanIdx]);
  _applyOffset('prMean', meanY);
}}
document.getElementById('priceMeanVis').addEventListener('change', function() {{
  Plotly.update(gd, {{ visible: [this.checked ? true : 'legendonly'] }}, {{'yaxis2.range': priceY2Range}}, [priceMeanIdx]);
}});
document.getElementById('priceMeanW').addEventListener('keydown', e => {{ if (e.key==='Enter') recomputePriceMean(); }});
// Save original band state (PE-based, y1) and pre-compute price bands (y2)
const _hasBands     = gd.data[0] && gd.data[0].fill === 'toself';
const _origBandY    = _hasBands ? [0,1,2].map(i => gd.data[i].y.slice()) : null;
const _origBandYax  = _hasBands ? [0,1,2].map(i => gd.data[i].yaxis)    : null;
const _origBandName = _hasBands ? [0,1,2].map(i => gd.data[i].name)      : null;
const _priceBandY   = _hasBands ? [
  [_priceMin, _priceMin, globalPriceP25, globalPriceP25],
  [globalPriceP25, globalPriceP25, globalPriceP75, globalPriceP75],
  [globalPriceP75, globalPriceP75, _priceMax, _priceMax],
] : null;
function _applyColorSwitch() {{
  if (priceValues.length > 0) {{
    const zoneY = _computeZoneY();
    [6, 7, 8, 9].forEach((ti, i) => {{ gd.data[ti].y = zoneY[i]; }});
    _syncAnchorZones(zoneY.zones);
    if (_hasBands) {{
      // The bands follow the colour source: drawn on that series' own axis
      // at its whole-history 25th/75th.
      const ctxAxis = {{ exvic: 'y', prem: 'y9' }}[colorMode];
      if (colorMode === 'price') {{
        [0, 1, 2].forEach((ti, i) => {{
          gd.data[ti].y     = _priceBandY[i];
          gd.data[ti].yaxis = 'y2';
        }});
      }} else if (ctxAxis) {{
        const [q25, , q75, lo, hi] = _COLOR_SRC[colorMode].g;
        [[lo, q25], [q25, q75], [q75, hi]].forEach(([a, b], i) => {{
          gd.data[i].y     = [a, a, b, b];
          gd.data[i].yaxis = ctxAxis;
        }});
      }} else {{
        [0, 1, 2].forEach((ti, i) => {{
          gd.data[ti].y     = _origBandY[i];
          gd.data[ti].yaxis = _origBandYax[i];
        }});
      }}
    }}
    gd.layout.yaxis2.range     = priceY2Range;
    gd.layout.yaxis2.autorange = false;
    Plotly.redraw(gd);
  }}
}}

document.querySelectorAll('input[name="colorBasis"]').forEach(r => {{
  r.addEventListener('change', function() {{
    colorBasis = this.value;
    _applyColorSwitch();
  }});
}});

document.querySelectorAll('input[name="colorMode"]').forEach(r => {{
  r.addEventListener('change', function() {{
    colorMode = this.value;
    _applyColorSwitch();
  }});
}});"""
    ctx_radios = "".join(
        f'\n    <label><input type="radio" name="colorMode" value="{k}"><span>{lbl}</span></label>'
        for k, lbl in (("exvic", "P/E ex-VIC"), ("prem", "Prem")) if k in ctx)
    color_mode_bar = f"""
<div id="color-mode-bar">
  <strong>Color source:</strong>
  <div class="color-toggle">
    <label><input type="radio" name="colorMode" value="pe"><span>P/E</span></label>
    <label><input type="radio" name="colorMode" value="price" checked><span>Price</span></label>{ctx_radios}
  </div>
  <strong style="margin-left:16px">Color method:</strong>
  <div class="color-toggle">
    <label><input type="radio" name="colorBasis" value="percentiles" checked><span>Percentiles</span></label>
    <label><input type="radio" name="colorBasis" value="mean"><span>Mean</span></label>
  </div>
</div>"""

    controls_html = f"""
<style>
  #ctrl {{
    font-family: sans-serif; font-size: 13px;
    display: flex; gap: 14px; align-items: center;
    padding: 10px 16px; background: #f8f9fa;
    border: 1px solid #dee2e6; border-radius: 6px;
    margin-bottom: 8px; flex-wrap: wrap;
  }}
  .section-label {{ font-weight: 600; color: #444; white-space: nowrap; }}
  .chk {{ display: flex; align-items: center; gap: 5px; cursor: pointer; white-space: nowrap; }}
  input[type=number] {{
    width: 65px; padding: 2px 5px; border: 1px solid #ced4da;
    border-radius: 4px; font-size: 13px;
  }}
  .ma-group {{ display: flex; align-items: center; gap: 7px; }}
  .dot {{ width: 16px; height: 3px; display: inline-block; border-radius: 2px; }}
  .divider {{ width: 1px; height: 28px; background: #ced4da; flex-shrink: 0; }}
  .unit {{ color: #777; font-size: 12px; }}
  button {{ padding: 4px 14px; cursor: pointer; border-radius: 4px; border: 1px solid #aaa; }}
  .off-wrap {{ display: flex; align-items: center; gap: 2px; font-size: 11px; color: #888; }}
  .off-wrap input[type=checkbox] {{ width: 12px; height: 12px; }}
  .off-pct {{ width: 38px !important; padding: 1px 3px !important; font-size: 11px !important; }}
  .color-toggle {{ display: flex; border: 1px solid #aaa; border-radius: 4px; overflow: hidden; font-size: 13px; }}
  .color-toggle label {{ display: flex; align-items: center; cursor: pointer; }}
  .color-toggle input[type=radio] {{ display: none; }}
  .color-toggle span {{ padding: 4px 14px; background: #fff; color: #555; transition: background .15s, color .15s; }}
  .color-toggle input[type=radio]:checked + span {{ background: #495057; color: #fff; }}
  #color-mode-bar {{
    font-family: sans-serif; font-size: 13px;
    display: flex; align-items: center; gap: 12px;
    padding: 7px 16px; background: #e9ecef;
    border: 1px solid #dee2e6; border-radius: 6px;
    margin-bottom: 8px;
  }}
</style>
<div id="ctrl">
  <span class="section-label">P/E Percentiles</span>
  <div class="ma-group">
    <label class="chk"><input type="checkbox" id="pePctVis" checked> Show</label>
    <input type="number" id="pePctW" value="{pct_window}" min="20" max="5000" step="50" title="Rolling window (days)">
    <span class="unit">d</span>
  </div>
  <label class="chk" style="margin-left:4px">
    <input type="checkbox" class="pct-pe-cb" data-sub="0">
    <span class="dot" style="background:rgba(46,160,67,0.9)"></span>25th</label>
  <span class="off-wrap"><input type="checkbox" id="off-en-pePct25">±<input type="number" id="off-pct-pePct25" class="off-pct" value="50">%</span>
  <label class="chk">
    <input type="checkbox" class="pct-pe-cb" data-sub="1">
    <span class="dot" style="background:rgba(100,100,200,0.9)"></span>Med</label>
  <span class="off-wrap"><input type="checkbox" id="off-en-pePctMed">±<input type="number" id="off-pct-pePctMed" class="off-pct" value="50">%</span>
  <label class="chk">
    <input type="checkbox" class="pct-pe-cb" data-sub="2">
    <span class="dot" style="background:rgba(220,53,69,0.9)"></span>75th</label>
  <span class="off-wrap"><input type="checkbox" id="off-en-pePct75">±<input type="number" id="off-pct-pePct75" class="off-pct" value="50">%</span>
  {pe_mean_control}
  {price_pct_control if has_price else '''
  <div class="divider"></div>
  <span class="section-label">P/E Line</span>
  <label class="chk"><input type="checkbox" id="peLineVis"> Show</label>'''}
  {''.join(f'''
  <div class="divider"></div>
  <span class="section-label">{lbl}</span>
  <label class="chk" title="{tip}"><input type="checkbox" id="{k}Vis"> Show</label>'''
    for k, lbl, tip in (
        ("exvic", "VN30 ex-VIC P/E", "VN30 aggregate P/E without VIC — market context, not used by any strategy"),
        ("prem",  "Prem", "Basket prem_median, all-VIC-VIX — market context, independent of the breadth profile's own line"),
    ) if k in ctx)}
  <button onclick="updateAll()">Apply</button>
</div>
{color_mode_bar}
"""

    script = f"""
<script>
const peValues        = {pe_values_json};
const priceValues     = {price_values_json};
const peAlignedValues = {pe_aligned_json};
const globalP25       = {global_p25_json};
const globalMed       = {global_med_json};
const globalP75       = {global_p75_json};
const peLineIdx       = {pe_line_idx};
const peMeanIdx       = {pe_mean_idx_json};
const priceMeanIdx    = {price_mean_idx_json};
// Market context, aligned to the price dates — see _context_series.
const exvicValues     = {exvic_json};
const premValues      = {prem_json};
const gd = document.getElementById('peChart');

// Stable y2 range derived from price data — used to prevent autorange shifting on restyle
const _priceNonNull = priceValues.filter(v => v != null);
const _priceMin = _priceNonNull.length ? Math.min.apply(null, _priceNonNull) : 0;
const _priceMax = _priceNonNull.length ? Math.max.apply(null, _priceNonNull) : 1;
const _pricePad = (_priceMax - _priceMin) * 0.05;
const priceY2Range = [_priceMin - _pricePad, _priceMax + _pricePad];

// Global static quantiles for price (fallback before rolling window fills in price mode)
const _sortedPrices = _priceNonNull.slice().sort((a, b) => a - b);
function _staticQ(sorted, p) {{
  const pos = p * (sorted.length - 1), lo = Math.floor(pos), hi = Math.ceil(pos);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}}
const globalPriceP25 = _sortedPrices.length ? _staticQ(_sortedPrices, 0.25) : null;
const globalPriceMed = _sortedPrices.length ? _staticQ(_sortedPrices, 0.50) : null;
const globalPriceP75 = _sortedPrices.length ? _staticQ(_sortedPrices, 0.75) : null;

let colorMode  = 'price';
let colorBasis = 'percentiles';

function rollingQuantile(arr, w, p) {{
  return arr.map((_, i) => {{
    if (i < w - 1) return null;
    const sl = arr.slice(i - w + 1, i + 1).slice().sort((a, b) => a - b);
    const pos = p * (sl.length - 1);
    const lo = Math.floor(pos), hi = Math.ceil(pos);
    return sl[lo] + (sl[hi] - sl[lo]) * (pos - lo);
  }});
}}

function togglePePct() {{
  const vis = document.getElementById('pePctVis').checked;
  const subs = [...document.querySelectorAll('.pct-pe-cb')].map(c => c.checked);
  Plotly.restyle(gd, {{
    visible: [
      (vis && subs[0]) ? true : 'legendonly',
      (vis && subs[1]) ? true : 'legendonly',
      (vis && subs[2]) ? true : 'legendonly',
    ]
  }}, [{pe_pct_idx[0]}, {pe_pct_idx[1]}, {pe_pct_idx[2]}]);
}}

function splitByZone(priceVals, compareVals, p25arr, medArr, p75arr, fbP25, fbMed, fbP75) {{
  const n = priceVals.length;
  const zones = new Array(n).fill(-1);
  for (let i = 0; i < n; i++) {{
    const pv = compareVals[i];
    if (pv == null) continue;
    const p25 = p25arr[i] != null ? p25arr[i] : fbP25;
    const med = medArr[i] != null ? medArr[i] : fbMed;
    const p75 = p75arr[i] != null ? p75arr[i] : fbP75;
    if (p25 == null) continue;
    if (pv < p25)       zones[i] = 0;
    else if (pv < med)  zones[i] = 1;
    else if (pv < p75)  zones[i] = 2;
    else                zones[i] = 3;
  }}
  const out = [0,1,2,3].map(z => priceVals.map((v, i) => {{
    if (zones[i] === z) return v;
    const adj = (i > 0 && zones[i-1] === z) || (i < n-1 && zones[i+1] === z);
    return adj ? v : null;
  }}));
  out.zones = zones;  // owning zone per point — drives the hover dot color
  return out;
}}

function splitByMean(priceVals, compareVals, meanArr) {{
  const n = priceVals.length;
  const zones = new Array(n).fill(-1);
  for (let i = 0; i < n; i++) {{
    const cv = compareVals[i];
    const m  = meanArr[i];
    if (cv == null || m == null) continue;
    zones[i] = cv < m ? 0 : 3;
  }}
  const out = [0,1,2,3].map(z => priceVals.map((v, i) => {{
    if (zones[i] === z) return v;
    const adj = (i > 0 && zones[i-1] === z) || (i < n-1 && zones[i+1] === z);
    return adj ? v : null;
  }}));
  out.zones = zones;
  return out;
}}

// The hover anchor is one dense trace, so Plotly's per-trace row swatch can't
// show the zone. Feed [color, label] per point instead; the hovertemplate paints
// a ● and names the zone. Must be re-run wherever gd.data[6..9].y is recomputed.
const ZONE_COLORS = {zone_colors_json};
const ZONE_LABELS = {zone_labels_json};
function _syncAnchorZones(zones) {{
  if ({price_anchor_idx_json} == null || !zones) return;
  gd.data[{price_anchor_idx_json}].customdata = zones.map(
    z => (z >= 0 ? [ZONE_COLORS[z], ZONE_LABELS[z]]
                 : [{no_zone_color_json}, {no_zone_label_json}])
  );
}}

// rollingQuantile for series with holes: nulls are left out of each window
// rather than sorted in as zeros. The context series have holes (VN30 ex-VIC
// has no P/E through 2015–16); P/E and price keep the original function.
function rollingQuantileNN(arr, w, p) {{
  return arr.map((_, i) => {{
    if (i < w - 1 || arr[i] == null) return null;
    const sl = arr.slice(i - w + 1, i + 1).filter(v => v != null).sort((a, b) => a - b);
    if (!sl.length) return null;
    const pos = p * (sl.length - 1);
    const lo = Math.floor(pos), hi = Math.ceil(pos);
    return sl[lo] + (sl[hi] - sl[lo]) * (pos - lo);
  }});
}}
function _staticQs(arr) {{
  const s = arr.filter(v => v != null).sort((a, b) => a - b);
  return s.length ? [_staticQ(s, 0.25), _staticQ(s, 0.50), _staticQ(s, 0.75), s[0], s[s.length - 1]]
                  : [null, null, null, null, null];
}}
// What each "Color source" compares, which window inputs drive it, and its
// whole-history quartiles (fallback before the window fills; also the bands).
// VN30 ex-VIC is a P/E, so it follows the P/E windows; prem is measured on
// prices, so it follows the price windows.
const _COLOR_SRC = {{
  pe:    {{ vals: peAlignedValues, pctW: 'pePctW',    meanW: 'peMeanW',    q: rollingQuantile,
            g: [globalP25, globalMed, globalP75] }},
  price: {{ vals: priceValues,     pctW: 'pricePctW', meanW: 'priceMeanW', q: rollingQuantile,
            g: [globalPriceP25, globalPriceMed, globalPriceP75] }},
  exvic: {{ vals: exvicValues,     pctW: 'pePctW',    meanW: 'peMeanW',    q: rollingQuantileNN,
            g: _staticQs(exvicValues) }},
  prem:  {{ vals: premValues,      pctW: 'pricePctW', meanW: 'priceMeanW', q: rollingQuantileNN,
            g: _staticQs(premValues) }},
}};

function _computeZoneY() {{
  const src = _COLOR_SRC[colorMode];
  if (colorBasis === 'mean') {{
    const pw = parseInt(document.getElementById(src.meanW).value) || {mean_window};
    return splitByMean(priceValues, src.vals, rollingMean(src.vals, pw));
  }}
  const pw = parseInt(document.getElementById(src.pctW).value) || {pct_window};
  return splitByZone(priceValues, src.vals,
                     src.q(src.vals, pw, 0.25), src.q(src.vals, pw, 0.50), src.q(src.vals, pw, 0.75),
                     src.g[0], src.g[1], src.g[2]);
}}

function recomputePePct() {{
  const pw  = parseInt(document.getElementById('pePctW').value) || {pct_window};
  const vis = document.getElementById('pePctVis').checked;
  const subs = [...document.querySelectorAll('.pct-pe-cb')].map(c => c.checked);
  const p25 = rollingQuantile(peValues, pw, 0.25);
  const med = rollingQuantile(peValues, pw, 0.50);
  const p75 = rollingQuantile(peValues, pw, 0.75);
  const dataUpd = {{
    y: [p25, med, p75],
    name: ['P/E 25th (' + pw + 'd)', 'P/E Median (' + pw + 'd)', 'P/E 75th (' + pw + 'd)'],
    visible: [
      (vis && subs[0]) ? true : 'legendonly',
      (vis && subs[1]) ? true : 'legendonly',
      (vis && subs[2]) ? true : 'legendonly',
    ]
  }};
  const layoutUpd = {{}};
  if (priceValues.length > 0) {{
    const zoneY = _computeZoneY();
    [6, 7, 8, 9].forEach((ti, i) => {{ gd.data[ti].y = zoneY[i]; }});
    _syncAnchorZones(zoneY.zones);
    layoutUpd['yaxis2.range'] = priceY2Range;
  }}
  Plotly.update(gd, dataUpd, layoutUpd, [{pe_pct_idx[0]}, {pe_pct_idx[1]}, {pe_pct_idx[2]}]);
}}

function rollingMean(arr, w) {{
  return arr.map((_, i) => {{
    const sl = arr.slice(Math.max(0, i - w + 1), i + 1).filter(v => v != null);
    return sl.length ? sl.reduce((a, b) => a + b, 0) / sl.length : null;
  }});
}}

// ── Offset companion lines ────────────────────────────────────────────────────
const _offCfg = [
  {{id:'pePct25', ax:'y',  color:'rgba(46,160,67,0.55)',   name:'P/E 25th offset'}},
  {{id:'pePctMed',ax:'y',  color:'rgba(100,100,200,0.55)', name:'P/E Med offset'}},
  {{id:'pePct75', ax:'y',  color:'rgba(220,53,69,0.55)',   name:'P/E 75th offset'}},
  {{id:'peMean',  ax:'y',  color:'rgba(150,0,200,0.55)',   name:'P/E Mean offset'}},
  {{id:'prPct25', ax:'y2', color:'rgba(46,160,67,0.55)',   name:'Price 25th offset'}},
  {{id:'prPctMed',ax:'y2', color:'rgba(100,100,200,0.55)', name:'Price Med offset'}},
  {{id:'prPct75', ax:'y2', color:'rgba(220,53,69,0.55)',   name:'Price 75th offset'}},
  {{id:'prMean',  ax:'y2', color:'rgba(150,0,200,0.55)',   name:'Price Mean offset'}},
];
const _offStart = gd.data.length;
const _peX  = gd.data[{pe_pct_idx[0]}].x;
const _prX  = priceValues.length ? gd.data[6].x : [];
Plotly.addTraces(gd, _offCfg.map(c => ({{
  x: c.ax === 'y' ? _peX : _prX,
  y: new Array(c.ax === 'y' ? peValues.length : priceValues.length).fill(null),
  mode: 'lines', name: c.name,
  line: {{color: c.color, width: 1.2, dash: 'dash'}},
  yaxis: c.ax, visible: 'legendonly',
}})));
const _oi = {{}};
_offCfg.forEach((c, i) => {{ _oi[c.id] = _offStart + i; }});

// ── Market context lines ──────────────────────────────────────────────────────
// VN30 ex-VIC on the P/E axis; prem on its own right-hand axis, y9 — y3..y7 are
// the backtest's event and signal strips and y8 is the breadth profile's own
// prem line, which this one is independent of. Hidden until ticked, like the
// P/E line.
const _ctxIdx = {{}};
[
  ['exvic', exvicValues, 'y',  '#17becf', 'VN30 ex-VIC P/E', 'VN30 ex-VIC: %{{y:.2f}}x'],
  ['prem',  premValues,  'y9', '#8c564b', 'Prem (all-VIC-VIX)', 'Prem: %{{y:.1f}}%'],
].forEach(([key, ys, ax, color, name, hover]) => {{
  if (!ys.length) return;
  _ctxIdx[key] = gd.data.length;
  Plotly.addTraces(gd, {{
    x: _prX, y: ys, mode: 'lines', name: name, yaxis: ax, visible: 'legendonly',
    line: {{color: color, width: 1.5}}, hovertemplate: hover + '<extra></extra>',
  }});
}});
if ('prem' in _ctxIdx) {{
  Plotly.relayout(gd, {{ yaxis9: {{
    overlaying: 'y', side: 'right', anchor: 'free', position: 1.0, visible: false,
    showgrid: false, zeroline: true, zerolinecolor: '#ccc',
    title: {{text: 'Prem %', font: {{size: 10}}}}, tickfont: {{size: 9}},
  }} }});
}}

// Right-hand axes beyond the price axis (prem here, the breadth profile's y8)
// each take a slot past the plot area, which shrinks to make room. Global so
// breadth/chart.py can call it after adding y8.
function _fitRightAxes() {{
  const premOn = 'prem' in _ctxIdx && document.getElementById('premVis').checked;
  const extra  = [premOn ? 'yaxis9' : null, gd.layout.yaxis8 ? 'yaxis8' : null].filter(Boolean);
  const right  = 1 - 0.06 * extra.length;
  const upd    = {{ 'xaxis.domain': [0, right] }};
  if ('prem' in _ctxIdx) upd['yaxis9.visible'] = premOn;
  extra.forEach((ax, k) => {{ upd[ax + '.position'] = right + 0.06 * (k + 1) - 0.01; }});
  Plotly.relayout(gd, upd);
}}
Object.keys(_ctxIdx).forEach(key => {{
  document.getElementById(key + 'Vis').addEventListener('change', function() {{
    Plotly.restyle(gd, {{ visible: [this.checked ? true : 'legendonly'] }}, [_ctxIdx[key]]);
    if (key === 'prem') _fitRightAxes();
  }});
}});

function _applyOffset(key, baseY) {{
  const idx = _oi[key];
  const en  = document.getElementById('off-en-' + key);
  if (!en) return;
  const vis = en.checked ? true : 'legendonly';
  if (!en.checked) {{ Plotly.restyle(gd, {{visible: [vis]}}, [idx]); return; }}
  const pct = parseFloat(document.getElementById('off-pct-' + key).value) || 50;
  const f   = 1 + pct / 100;
  Plotly.restyle(gd, {{y: [baseY.map(v => v != null ? v * f : null)], visible: [vis]}}, [idx]);
}}

function _wireOffset(key, getBaseY) {{
  const en  = document.getElementById('off-en-' + key);
  const inp = document.getElementById('off-pct-' + key);
  if (!en) return;
  en.addEventListener('change',  () => _applyOffset(key, getBaseY()));
  inp.addEventListener('change', () => {{ if (en.checked) _applyOffset(key, getBaseY()); }});
  inp.addEventListener('keydown', e => {{ if (e.key === 'Enter' && en.checked) _applyOffset(key, getBaseY()); }});
}}

function recomputePeMean() {{
  const w = parseInt(document.getElementById('peMeanW').value) || {mean_window};
  const vis = document.getElementById('peMeanVis').checked;
  const meanY = rollingMean(peValues, w);
  Plotly.update(gd, {{
    y: [meanY],
    name: ['P/E Mean (' + w + 'd)'],
    visible: [vis ? true : 'legendonly'],
  }}, {{}}, [peMeanIdx]);
  _applyOffset('peMean', meanY);
}}

function updateAll() {{ recomputePePct(); recomputePeMean(); {('recomputePricePct(); recomputePriceMean();' if has_price else '')} }}

document.getElementById('pePctVis').addEventListener('change', togglePePct);
document.querySelectorAll('.pct-pe-cb').forEach(cb => cb.addEventListener('change', togglePePct));
document.getElementById('pePctW').addEventListener('keydown', e => {{ if (e.key === 'Enter') recomputePePct(); }});
document.getElementById('peMeanVis').addEventListener('change', function() {{
  Plotly.restyle(gd, {{ visible: [this.checked ? true : 'legendonly'] }}, [peMeanIdx]);
}});
document.getElementById('peMeanW').addEventListener('keydown', e => {{ if (e.key === 'Enter') recomputePeMean(); }});
_wireOffset('pePct25',  () => gd.data[{pe_pct_idx[0]}].y);
_wireOffset('pePctMed', () => gd.data[{pe_pct_idx[1]}].y);
_wireOffset('pePct75',  () => gd.data[{pe_pct_idx[2]}].y);
_wireOffset('peMean',   () => gd.data[peMeanIdx].y);
{'_wireOffset("prPct25",  () => gd.data[' + str(price_pct_idx[0]) + '].y);' if has_price else ''}
{'_wireOffset("prPctMed", () => gd.data[' + str(price_pct_idx[1]) + '].y);' if has_price else ''}
{'_wireOffset("prPct75",  () => gd.data[' + str(price_pct_idx[2]) + '].y);' if has_price else ''}
{'_wireOffset("prMean",   () => gd.data[' + str(price_mean_idx_json) + '].y);' if has_price else ''}
document.getElementById('peLineVis').addEventListener('change', function() {{
  Plotly.restyle(gd, {{ visible: [this.checked ? true : 'legendonly'] }}, [peLineIdx]);
}});
{price_checkbox_js}
// Sync initial visibility with checkbox defaults
togglePePct();
togglePricePct();
Plotly.restyle(gd, {{ visible: ['legendonly'] }}, [peMeanIdx]);
Plotly.restyle(gd, {{ visible: ['legendonly'] }}, [peLineIdx]);
Plotly.restyle(gd, {{ visible: ['legendonly'] }}, [priceMeanIdx]);
// Apply default color mode (price)
_applyColorSwitch();
</script>
"""

    full_html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>P/E Chart</title></head>
<body style="margin:16px">
{controls_html}
{plot_html}
{script}
</body>
</html>"""

    with open(path, "w", encoding="utf-8") as f:
        f.write(full_html)
    print(f"Chart saved to {path}")
    return path


def _stock_pe_chart(df: pd.DataFrame, symbol: str,
                    pct_window: int = _DEFAULT_PCT_WINDOW,
                    mean_window: int = 1000) -> tuple:
    """
    Build a pe_chart()-compatible rich figure from an individual stock's df.
    Returns (fig, pe_dates, pe_values, price_data) — same shape as pe_chart().
    """
    times  = df["time"] if "time" in df.columns else df.index
    dates  = pd.to_datetime([str(t)[:10] for t in times])
    prices = df["close"].tolist()  # DB stores stocks in full VND; markers use i.close/1000 = df["close"]

    has_pe = "pe_ratio" in df.columns and df["pe_ratio"].notna().any()
    if has_pe:
        pe_vals  = df["pe_ratio"].tolist()
        pe_dates = [str(t)[:10] for t in times]
        pe_series = pd.Series(pe_vals)
        p25 = float(pe_series.quantile(0.25))
        med = float(pe_series.quantile(0.50))
        p75 = float(pe_series.quantile(0.75))
    else:
        pe_vals  = []
        pe_dates = []
        p25 = med = p75 = None

    fig = go.Figure()

    # ── P/E percentile bands ──────────────────────────────────────────────────
    if has_pe:
        x_fill = [dates[0], dates[-1]]
        for lo, hi, color, name in [
            (pe_series.min(), p25, "rgba(46,160,67,0.15)",  "Cheap (< 25th)"),
            (p25,            p75, "rgba(255,200,0,0.12)",   "Fair (25–75th)"),
            (p75,    pe_series.max(), "rgba(220,53,69,0.15)", "Expensive (> 75th)"),
        ]:
            fig.add_trace(go.Scatter(
                x=x_fill + x_fill[::-1], y=[lo, lo, hi, hi],
                fill="toself", fillcolor=color, line=dict(width=0),
                mode="lines", name=name, hoverinfo="skip",
                showlegend=True, yaxis="y1",
            ))

        # ── P/E rolling percentile lines (traces 3, 4, 5) ────────────────────
        for q, color, tmpl in [
            (0.25, "rgba(46,160,67,0.9)",   "P/E 25th ({w}d)"),
            (0.50, "rgba(100,100,200,0.9)", "P/E Median ({w}d)"),
            (0.75, "rgba(220,53,69,0.9)",   "P/E 75th ({w}d)"),
        ]:
            fig.add_trace(_pct_trace(dates, pe_vals, pct_window, q, tmpl, color, "y1"))
    else:
        # add 3 empty placeholder traces so save_chart's trace indices still work
        for _ in range(6):
            fig.add_trace(go.Scatter(x=[], y=[], visible=False, showlegend=False))

    # ── Colored price segments by PE zone ────────────────────────────────────
    price_data = None
    if has_pe:
        def _zone(v):
            if v is None or (isinstance(v, float) and v != v): return -1
            if v < p25: return 0
            if v < med: return 1
            if v < p75: return 2
            return 3

        zones = [_zone(v) for v in pe_vals]
        n_p   = len(prices)
        PRICE_ZONES = [
            (0, _ZONE_COLORS[0], f"Cheap  P/E<{p25:.1f}"),
            (1, _ZONE_COLORS[1], f"Fair   P/E {p25:.1f}–{med:.1f}"),
            (2, _ZONE_COLORS[2], f"High   P/E {med:.1f}–{p75:.1f}"),
            (3, _ZONE_COLORS[3], f"Exp.   P/E>{p75:.1f}"),
        ]
        for z, color, name in PRICE_ZONES:
            y_zone = []
            for i in range(n_p):
                if zones[i] == z:
                    y_zone.append(prices[i])
                else:
                    adj = (i > 0 and zones[i-1] == z) or (i < n_p-1 and zones[i+1] == z)
                    y_zone.append(prices[i] if adj else None)
            fig.add_trace(go.Scatter(
                x=dates, y=y_zone,
                mode="lines", name=name,
                line=dict(color=color, width=1.5),
                legendgroup="price_color", legendgrouptitle_text=f"{symbol} Price",
                yaxis="y2",
                # Hover is served by the gap-free anchor trace below — see pe_chart().
                hoverinfo="skip",
            ))

        # ── Price rolling percentile lines (traces 10, 11, 12) ───────────────
        for q, color, tmpl in [
            (0.25, "rgba(46,160,67,0.9)",   "Price 25th ({w}d)"),
            (0.50, "rgba(100,100,200,0.9)", "Price Median ({w}d)"),
            (0.75, "rgba(220,53,69,0.9)",   "Price 75th ({w}d)"),
        ]:
            fig.add_trace(_pct_trace(dates, prices, pct_window, q, tmpl, color, "y2"))

        price_data = (
            [str(d)[:10] for d in dates], prices, pe_vals,
            p25, med, p75,
        )

    # ── P/E rolling mean ─────────────────────────────────────────────────────
    if has_pe:
        pe_mean = pd.Series(pe_vals).rolling(mean_window, min_periods=1).mean().tolist()
        fig.add_trace(go.Scatter(
            x=dates, y=pe_mean,
            mode="lines", name=f"P/E Mean ({mean_window}d)",
            line=dict(color="rgba(150,0,200,0.8)", width=1.5, dash="dot"),
            yaxis="y1",
        ))
        price_mean = pd.Series(prices).rolling(mean_window, min_periods=1).mean().tolist()
        fig.add_trace(go.Scatter(
            x=dates, y=price_mean,
            mode="lines", name=f"Price Mean ({mean_window}d)",
            line=dict(color="rgba(150,0,200,0.8)", width=1.5, dash="dot"),
            yaxis="y2",
        ))

        # ── Price hover anchor (trace 15) — see pe_chart() ───────────────────
        fig.add_trace(go.Scatter(
            x=dates, y=prices,
            mode="lines", name=f"{symbol} Price",
            line=dict(width=0, color=_NO_ZONE_COLOR),
            yaxis="y2", showlegend=False, legendgroup="price_color",
            customdata=[
                [_ZONE_COLORS[z], _ZONE_LABELS[z]] if z >= 0 else [_NO_ZONE_COLOR, _NO_ZONE_LABEL]
                for z in zones
            ],
            # No date here — "x unified" already prints it once in the header.
            hovertemplate=(
                "<span style='color:%{customdata[0]}'>●</span> "
                "%{customdata[1]}: %{y:,.0f}<extra></extra>"
            ),
        ))

    # ── P/E line ──────────────────────────────────────────────────────────────
    if has_pe:
        fig.add_trace(go.Scatter(
            x=dates, y=pe_vals,
            mode="lines", name=f"{symbol} P/E",
            line=dict(color="#1f77b4", width=1.8), yaxis="y1",
            hovertemplate="P/E: %{y:.2f}x<extra></extra>",
        ))
        current = pe_vals[-1]
        fig.add_trace(go.Scatter(
            x=[dates[-1]], y=[current],
            mode="markers+text", marker=dict(size=8, color="#ff7f0e"),
            text=[f"  {current:.2f}x"], textposition="middle right",
            name=f"Current P/E", yaxis="y1",
            hovertemplate=f"P/E: {current:.2f}x<extra></extra>",
        ))
    else:
        # price-only fallback
        fig.add_trace(go.Scatter(
            x=dates, y=prices, mode="lines", name=f"{symbol} Price",
            line=dict(color="#60a5fa", width=1.8), yaxis="y1",
        ))
        fig.add_trace(go.Scatter(x=[], y=[], visible=False, showlegend=False))

    date_range_str = f"{str(dates[0])[:4]} – {str(dates[-1])[:4]}"
    fig.update_layout(
        title=dict(text=f"{symbol} — P/E & Price  <sup>{date_range_str}</sup>", font_size=18),
        xaxis=dict(title="Date", showgrid=True, gridcolor="rgba(200,200,200,0.3)", hoverformat="%Y-%m-%d"),
        yaxis=dict(title="P/E (x, log)", type="log", showgrid=True, gridcolor="rgba(200,200,200,0.3)", side="left"),
        yaxis2=dict(title=f"{symbol} Price (VND)", overlaying="y", side="right", showgrid=False, tickformat=","),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        plot_bgcolor="white", paper_bgcolor="white",
        margin=dict(l=60, r=80, t=80, b=60),
    )

    return fig, pe_dates, pe_vals, price_data


def _save_stock_chart(df: pd.DataFrame, symbol: str, path: str):
    fig, pe_dates, pe_values, price_data = _stock_pe_chart(df, symbol)
    save_chart(fig, pe_dates, pe_values, price_data, path)


def _add_signal_strips(fig: go.Figure, signal_df: pd.DataFrame) -> go.Figure:
    """
    Append 3 colored signal strips below the main chart for the initial window.
    Returns the figure with layout adjusted and signal traces added.
    """
    SIGNALS = [
        ("signal1_slope",  "Signal 1 — Slope",    "y3", [0.22, 0.30]),
        ("signal2_return", "Signal 2 — Return %",  "y4", [0.11, 0.19]),
        ("signal3_sharpe", "Signal 3 — Sharpe",    "y5", [0.00, 0.08]),
    ]

    fig.update_layout(**{
        "yaxis.domain":  [0.32, 1.0],
        "yaxis2.domain": [0.32, 1.0],
    })

    dates = signal_df.index.strftime("%Y-%m-%d").tolist()

    for col, label, yref, domain in SIGNALS:
        vals = signal_df[col].tolist() if col in signal_df.columns else []
        fig.add_trace(go.Scatter(
            x=dates, y=vals,
            mode="markers",
            marker=dict(color=vals, colorscale="RdYlGn", size=3, showscale=False),
            name=label,
            yaxis=yref,
            hovertemplate=f"{label}: %{{y:.3f}}<extra></extra>",
        ))
        yaxis_key = f"yaxis{yref[1:]}" if yref != "y" else "yaxis"
        fig.update_layout(**{
            yaxis_key: dict(
                domain=domain, anchor="x",
                showgrid=False, zeroline=True,
                zerolinecolor="rgba(150,150,150,0.4)",
                showticklabels=True, tickfont=dict(size=9),
                title=dict(text=label, font=dict(size=9)),
            )
        })

    return fig


def _build_signal_js(all_windows: dict, yaxis_start: int = 3, is_backtest: bool = False, init_delay: int = 0,
                     default_w1: int = 100, default_w2: int = 500, default_w3: int = 1000,
                     zdev_windows: dict | None = None, default_wz: int = 500) -> str:
    """
    Build the JS snippet that embeds all-window signal data and wires
    3 independent window sliders — one per signal.

    all_windows : {window_days: DataFrame indexed by date}
    """
    DISPLAY_STEP = 5
    data: dict = {}
    for w, df in sorted(all_windows.items()):
        if df.empty:
            continue
        df_s = df.iloc[::DISPLAY_STEP]
        data[w] = {
            "dates": df_s.index.strftime("%Y-%m-%d").tolist(),
            "s1":    [round(v, 4) for v in df_s["signal1_slope"].tolist()],
            "s2":    [round(v, 4) for v in df_s["signal2_return"].tolist()],
            "s3":    [round(v, 4) for v in df_s["signal3_sharpe"].tolist()],
        }

    available = sorted(data.keys())

    # z_dev rides along as a fourth strip: same slider mechanics, own source table.
    zdata: dict = {}
    for w, df in sorted((zdev_windows or {}).items()):
        if df.empty:
            continue
        df_s = df.iloc[::DISPLAY_STEP]
        zdata[w] = {
            "dates": df_s.index.strftime("%Y-%m-%d").tolist(),
            "z":     [round(v, 3) for v in df_s["z_dev"].tolist()],
        }
    z_available = sorted(zdata.keys())
    has_zdev    = "true" if zdata else "false"

    ya, yb, yc = yaxis_start, yaxis_start + 1, yaxis_start + 2
    yd = yaxis_start + 3                      # z_dev strip
    ya_key = "yaxis" if ya == 1 else f"yaxis{ya}"
    yb_key = f"yaxis{yb}"
    yc_key = f"yaxis{yc}"
    yd_key = f"yaxis{yd}"
    ya_ref = "y" if ya == 1 else f"y{ya}"
    yb_ref = f"y{yb}"
    yc_ref = f"y{yc}"
    yd_ref = f"y{yd}"
    resize_main     = "true" if not is_backtest else "false"
    rebase_backtest = "true" if is_backtest else "false"

    return f"""
<script>
(function() {{
  const ALL_SIGNALS = {json.dumps(data)};
  const AVAILABLE   = {json.dumps(available)};
  const ALL_ZDEV    = {json.dumps(zdata)};
  const Z_AVAILABLE = {json.dumps(z_available)};
  const HAS_ZDEV    = {has_zdev};

  function snapTo(list, w) {{
    let best = list[0], bestDiff = Math.abs(w - best);
    for (const v of list) {{
      const d = Math.abs(w - v);
      if (d < bestDiff) {{ best = v; bestDiff = d; }}
    }}
    return best;
  }}
  function snapWindow(w)  {{ return snapTo(AVAILABLE, w); }}
  function snapZWindow(w) {{ return snapTo(Z_AVAILABLE, w); }}

  function initSignals() {{
    const gd = document.getElementById('peChart') || document.querySelector('.plotly-graph-div');
    if (!gd || !gd._fullLayout) {{ setTimeout(initSignals, 200); return; }}

    const initW1 = snapWindow({default_w1});
    const initW2 = snapWindow({default_w2});
    const initW3 = snapWindow({default_w3});
    const initWZ = HAS_ZDEV ? snapZWindow({default_wz}) : 0;

    const resizeMain     = {resize_main};
    const rebaseBacktest = {rebase_backtest};
    // Four strips when z_dev is present, three when it is not — the older layout
    // is kept so a symbol with no z_dev rows does not leave an empty band.
    const zTop = HAS_ZDEV ? 0.39 : 0.30;
    const relayoutArgs = {{
      '{ya_key}': {{ domain: [0.22, 0.29], anchor: 'x', showgrid: false, zeroline: true, tickfont: {{size: 9}}, title: {{text: 'Slope',   font: {{size: 9}}}} }},
      '{yb_key}': {{ domain: [0.11, 0.18], anchor: 'x', showgrid: false, zeroline: true, tickfont: {{size: 9}}, title: {{text: 'Return%', font: {{size: 9}}}} }},
      '{yc_key}': {{ domain: [0.00, 0.07], anchor: 'x', showgrid: false, zeroline: true, tickfont: {{size: 9}}, title: {{text: 'Sharpe',  font: {{size: 9}}}} }},
    }};
    if (HAS_ZDEV) {{
      relayoutArgs['{yd_key}'] = {{
        domain: [0.32, zTop], anchor: 'x', showgrid: false,
        zeroline: true, zerolinecolor: '#888', zerolinewidth: 1,
        tickfont: {{size: 9}}, title: {{text: 'z_dev', font: {{size: 9}}}},
      }};
    }}
    const mainTop = HAS_ZDEV ? 0.42 : 0.32;
    if (resizeMain) {{
      relayoutArgs['yaxis.domain']  = [mainTop, 1.0];
      relayoutArgs['yaxis2.domain'] = [mainTop, 1.0];
    }}
    if (rebaseBacktest) {{
      const bt = HAS_ZDEV ? 0.47 : 0.37;
      relayoutArgs['yaxis.domain']  = [bt, 1.0];
      relayoutArgs['yaxis2.domain'] = [bt, 1.0];
      relayoutArgs['yaxis3.domain'] = HAS_ZDEV ? [0.41, 0.46] : [0.31, 0.36];
    }}
    // +/-1 and +/-2 reference lines on the z_dev strip. Appended, never assigned,
    // so any shapes the base chart already owns survive.
    if (HAS_ZDEV) {{
      const refs = [1, -1, 2, -2].map(function(v) {{
        return {{ type: 'line', xref: 'paper', x0: 0, x1: 1, yref: '{yd_ref}', y0: v, y1: v,
                 line: {{ color: Math.abs(v) === 1 ? '#cbd5e1' : '#f0a0a0', width: 1, dash: 'dot' }},
                 layer: 'below' }};
      }});
      relayoutArgs['shapes'] = (gd.layout.shapes || []).concat(refs);
    }}

    Plotly.relayout(gd, relayoutArgs).then(function() {{
      const baseLen = gd.data.length;
      const d1 = ALL_SIGNALS[initW1], d2 = ALL_SIGNALS[initW2], d3 = ALL_SIGNALS[initW3];
      const newTraces = [
        {{ name: 'Signal 1 — Slope',    mode: 'markers', yaxis: '{ya_ref}', x: d1.dates, y: d1.s1, marker: {{ color: d1.s1, colorscale: 'RdYlGn', size: 3, showscale: false }} }},
        {{ name: 'Signal 2 — Return %', mode: 'markers', yaxis: '{yb_ref}', x: d2.dates, y: d2.s2, marker: {{ color: d2.s2, colorscale: 'RdYlGn', size: 3, showscale: false }} }},
        {{ name: 'Signal 3 — Sharpe',   mode: 'markers', yaxis: '{yc_ref}', x: d3.dates, y: d3.s3, marker: {{ color: d3.s3, colorscale: 'RdYlGn', size: 3, showscale: false }} }},
      ];
      if (HAS_ZDEV) {{
        const dz = ALL_ZDEV[initWZ];
        // A line, not coloured markers: z_dev's sign is the point, so it has to be
        // read against the zero baseline rather than by hue.
        newTraces.push({{
          name: 'z_dev', mode: 'lines', yaxis: '{yd_ref}',
          x: dz.dates, y: dz.z,
          line: {{ color: '#7c3aed', width: 1.2 }},
          hovertemplate: 'z_dev: %{{y:.2f}}<extra></extra>',
        }});
      }}
      return Plotly.addTraces(gd, newTraces).then(function() {{
        const ti1 = baseLen, ti2 = baseLen + 1, ti3 = baseLen + 2, tiZ = baseLen + 3;

        function applySignal(ti, key, rangeEl, numEl, w) {{
          const snapped = snapWindow(w);
          const d = ALL_SIGNALS[snapped];
          if (!d) return;
          rangeEl.value = snapped;
          numEl.value   = snapped;
          Plotly.restyle(gd, {{ x: [d.dates], y: [d[key]], 'marker.color': [d[key]] }}, [ti]);
        }}

        function wire(ti, key, rangeId, numberId) {{
          const rangeEl = document.getElementById(rangeId);
          const numEl   = document.getElementById(numberId);
          rangeEl.addEventListener('input', function() {{
            clearTimeout(rangeEl._t);
            rangeEl._t = setTimeout(function() {{ applySignal(ti, key, rangeEl, numEl, parseInt(rangeEl.value)); }}, 80);
          }});
          numEl.addEventListener('change', function() {{ applySignal(ti, key, rangeEl, numEl, parseInt(numEl.value)); }});
          rangeEl.value = snapWindow(parseInt(rangeEl.value));
          numEl.value   = rangeEl.value;
        }}

        wire(ti1, 's1', 'sig1WinInput', 'sig1WinNumber');
        wire(ti2, 's2', 'sig2WinInput', 'sig2WinNumber');
        wire(ti3, 's3', 'sig3WinInput', 'sig3WinNumber');

        if (HAS_ZDEV) {{
          // Own snap list and no marker.color — z_dev is a line, and its windows
          // come from valuation_zdev, not trend_signals.
          const rangeEl = document.getElementById('zdevWinInput');
          const numEl   = document.getElementById('zdevWinNumber');
          function applyZ(w) {{
            const snapped = snapZWindow(w);
            const d = ALL_ZDEV[snapped];
            if (!d) return;
            rangeEl.value = snapped;
            numEl.value   = snapped;
            Plotly.restyle(gd, {{ x: [d.dates], y: [d.z] }}, [tiZ]);
          }}
          rangeEl.addEventListener('input', function() {{
            clearTimeout(rangeEl._t);
            rangeEl._t = setTimeout(function() {{ applyZ(parseInt(rangeEl.value)); }}, 80);
          }});
          numEl.addEventListener('change', function() {{ applyZ(parseInt(numEl.value)); }});
          rangeEl.value = initWZ;
          numEl.value   = initWZ;
        }}
      }});
    }});
  }}

  if ({init_delay} > 0) {{ setTimeout(initSignals, {init_delay}); }} else {{ initSignals(); }}
}})();
</script>"""


def _inject_signals_into_html(symbol: str, path: str, available_windows: list,
                              default_window: int = 500, yaxis_start: int = 3,
                              is_backtest: bool = False, init_delay: int = 0,
                              default_w1: int = 100, default_w2: int = 500, default_w3: int = 1000,
                              default_wz: int = 500) -> None:
    """Inject 3 independent signal sliders and JS into an already-saved stock chart HTML file."""
    # Only every SIGNAL_WINDOW_STEP-th window is embedded, plus whichever windows
    # the run is actually configured with. All 1500 cost ~36 MB of the ~40 MB file
    # — the same problem z_dev already solves below, and the same fix: the slider
    # snaps to what is present, so it still feels continuous. The configured
    # windows are kept unconditionally, since the chart's job is to show the run
    # that produced it and those need not be round numbers.
    wanted = {default_w1, default_w2, default_w3}
    keep = sorted({w for w in available_windows
                   if w % SIGNAL_WINDOW_STEP == 0 or w in wanted})
    available_windows = keep or available_windows
    wmin, wmax = available_windows[0], available_windows[-1]

    def snap(w):
        return min(available_windows, key=lambda v: abs(v - w))

    iw1, iw2, iw3 = snap(default_w1), snap(default_w2), snap(default_w3)

    placeholders = ",".join("?" * len(available_windows))
    with db._conn() as con:
        all_df = pd.read_sql(
            "SELECT date, window_days, signal1_slope, signal2_return, signal3_sharpe"
            f" FROM trend_signals WHERE symbol=? AND window_days IN ({placeholders})"
            " ORDER BY window_days, date",
            con, params=(symbol, *available_windows),
        )
    all_df["date"] = pd.to_datetime(all_df["date"])
    all_windows = {
        w: grp.set_index("date").drop(columns="window_days")
        for w, grp in all_df.groupby("window_days")
    }

    # z_dev: only every ZDEV_WINDOW_STEP-th stat window is embedded. All 1499 would
    # add ~12 MB to a file that is already tens of MB; every 10th is ~1.2 MB and the
    # slider snaps, so it still feels continuous — and it lands on round numbers.
    with db._conn() as con:
        z_df = pd.read_sql(
            f"""SELECT date, stat_window, z_dev FROM valuation_zdev
                WHERE symbol=? AND median_window=? AND z_dev IS NOT NULL
                  AND stat_window % {ZDEV_WINDOW_STEP} = 0
                ORDER BY stat_window, date""",
            con, params=(symbol, ZDEV_MEDIAN_WINDOW),
        )
    zdev_windows: dict = {}
    if not z_df.empty:
        z_df["date"] = pd.to_datetime(z_df["date"])
        zdev_windows = {
            w: grp.set_index("date").drop(columns="stat_window")
            for w, grp in z_df.groupby("stat_window")
        }
    z_avail = sorted(zdev_windows.keys())
    iwz = min(z_avail, key=lambda v: abs(v - default_wz)) if z_avail else default_wz

    def _slider_row(label, range_id, num_id, init_w, lo=None, hi=None):
        lo = wmin if lo is None else lo
        hi = wmax if hi is None else hi
        return (
            f'<div style="display:flex;align-items:center;gap:8px">'
            f'<span style="width:80px;font-weight:600;color:#555">{label}</span>'
            f'<input id="{range_id}" type="range" min="{lo}" max="{hi}" step="1" value="{init_w}" style="width:460px;cursor:pointer">'
            f'<input id="{num_id}" type="number" min="{lo}" max="{hi}" step="1" value="{init_w}" '
            f'style="width:70px;font-size:13px;font-weight:600;text-align:center;border:1px solid #ccc;border-radius:4px;padding:2px 4px">'
            f'<span style="color:#888">days</span>'
            f'</div>'
        )

    control_html = (
        f'<div id="sigWinCtrl" style="font-family:sans-serif;font-size:13px;'
        f'display:flex;flex-direction:column;gap:6px;padding:8px 16px;'
        f'background:#f0f0f0;border:1px solid #ddd;border-radius:6px;margin-top:6px">'
        + _slider_row("Signal 1 — Slope",    "sig1WinInput", "sig1WinNumber", iw1)
        + _slider_row("Signal 2 — Return%",  "sig2WinInput", "sig2WinNumber", iw2)
        + _slider_row("Signal 3 — Sharpe",   "sig3WinInput", "sig3WinNumber", iw3)
        + (_slider_row("z_dev", "zdevWinInput", "zdevWinNumber", iwz,
                       lo=z_avail[0], hi=z_avail[-1]) if z_avail else "")
        + '</div>'
    )

    js = _build_signal_js(all_windows, yaxis_start=yaxis_start, is_backtest=is_backtest,
                          init_delay=init_delay, default_w1=iw1, default_w2=iw2, default_w3=iw3,
                          zdev_windows=zdev_windows, default_wz=iwz)

    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    html = html.replace(
        '<div id="peChart" class="plotly-graph-div" style="height:100%; width:100%;">',
        '<div id="peChart" class="plotly-graph-div" style="height:calc(100vh - 56px); width:100%;">',
    )
    inject_before = '<div id="peChart"'
    if inject_before in html:
        html = html.replace(inject_before, control_html + inject_before, 1)
    else:
        html = html.replace("</body>", control_html + "</body>")
    html = html.replace("</body>", js + "</body>")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


def save_stock_chart(symbol: str, path: str, default_window: int = 500) -> None:
    """Load price + P/E + trend signals for a stock symbol and save an interactive chart."""
    prices_df = db.load_daily_prices(symbol).reset_index().rename(columns={"date": "time"})
    pe_df     = db.load_pe_ratios(symbol).reset_index().rename(columns={"date": "time"})

    if prices_df.empty:
        print(f"  [chart] {symbol}: no price data — skipping")
        return

    if not pe_df.empty and "pe_ratio" in pe_df.columns:
        df = prices_df.merge(pe_df[["time", "pe_ratio"]], on="time", how="left")
        df["pe_ratio"] = df["pe_ratio"].ffill()
    else:
        df = prices_df

    fig, pe_dates, pe_values, price_data = _stock_pe_chart(df, symbol)

    # Load all available windows from DB
    with db._conn() as con:
        available_windows = [
            r[0] for r in con.execute(
                "SELECT DISTINCT window_days FROM trend_signals WHERE symbol=? ORDER BY window_days",
                (symbol,)
            ).fetchall()
        ]

    if available_windows:
        # Write base HTML first (clean fig, so save_chart trace indices are correct)
        save_chart(fig, pe_dates, pe_values, price_data, path)
        _inject_signals_into_html(symbol, path, available_windows, default_window)
    else:
        save_chart(fig, pe_dates, pe_values, price_data, path)


def save_index_chart(index: str, path: str, default_window: int = 500) -> None:
    """Save index P/E chart with signal strips injected (same as save_stock_chart for stocks)."""
    fig, pe_dates, pe_values, price_data = pe_chart(index=index)
    save_chart(fig, pe_dates, pe_values, price_data, path)

    symbol = index.upper()
    with db._conn() as con:
        available_windows = [
            r[0] for r in con.execute(
                "SELECT DISTINCT window_days FROM trend_signals WHERE symbol=? ORDER BY window_days",
                (symbol,)
            ).fetchall()
        ]
    if available_windows:
        _inject_signals_into_html(symbol, path, available_windows, default_window)


def save_backtest_chart(
    df: pd.DataFrame,
    buyedInfos: list,
    sellInfos: list,
    reinvestInfos: list,
    depositInfos: list | None = None,
    path: str = "charts/backtest.html",
    title: str | None = None,
    index: str = "vn30",
    buy_strategy=None,
    sell_strategy=None,
    reinvest_strategy=None,
    cal_range_close: dict | None = None,
    result: dict | None = None,
    compare_result: dict | None = None,
    start_index: int = 0,
    # Windows the run actually used, so the chart's sliders open on the same
    # values rather than on generic defaults. Passed in rather than imported:
    # export/ should not depend on a strategy package's config.
    sig1_window: int | None = None,
    sig3_window: int | None = None,
    zdev_window: int | None = None,
) -> str:
    """
    Export a backtest chart built on top of the full PE chart (all percentile
    lines, mean lines, color toggles), with event markers and condition-zone
    overlays added on top.
    """
    import os
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    # Only override a slider default when the caller supplied a window; omitted
    # ones keep _inject_signals_into_html's own defaults.
    _slider_defaults = {}
    if sig1_window is not None: _slider_defaults["default_w1"] = sig1_window
    if sig3_window is not None: _slider_defaults["default_w3"] = sig3_window
    if zdev_window is not None: _slider_defaults["default_wz"] = zdev_window

    _known_indices = {"vn30", "vndiamond", "vnfinlead", "vnindex"}
    if index.lower() in _known_indices:
        fig, pe_dates, pe_values, price_data = pe_chart(index=index, bands=True)
        save_chart(fig, pe_dates, pe_values, price_data, path)
        symbol = index.upper()
        with db._conn() as con:
            _idx_windows = [
                r[0] for r in con.execute(
                    "SELECT DISTINCT window_days FROM trend_signals WHERE symbol=? ORDER BY window_days",
                    (symbol,)
                ).fetchall()
            ]
        if _idx_windows:
            _inject_signals_into_html(symbol, path, _idx_windows, yaxis_start=4,
                                      is_backtest=True, init_delay=1500,
                                      **_slider_defaults)
        _yaxis = "y2"
    else:
        # Individual stock: build a styled price+PE chart from df
        _save_stock_chart(df, index.upper(), path)
        _yaxis = "y2" if ("pe_ratio" in df.columns and df["pe_ratio"].notna().any()) else "y"

    times = df["time"] if "time" in df.columns else df.index

    # ── Event marker traces ───────────────────────────────────────────────────
    _EVENTS = [
        (buyedInfos,         "Buy",      "rgba(34,197,94,0.75)",  "#15803d", "triangle-up",   9,
         lambda i: f"Invested: {i.finalBuy:,.0f}"),
        (sellInfos,          "Sell",     "rgba(239,68,68,0.75)",  "#991b1b", "triangle-down", 9,
         lambda i: f"Return: {i.sellFinal:,.0f}  (+{i.sellGrowthRatito:.1f}%)"),
        (reinvestInfos,      "Reinvest", "rgba(249,115,22,0.75)", "#c2410c", "diamond",       8,
         lambda i: f"Reinvested: {i.reInvestFinal:,.0f}"),
        (depositInfos or [], "Deposit",  "rgba(168,85,247,0.75)", "#7e22ce", "star",          9,
         lambda i: f"Interest: {i.totalReserveInterest:,.0f}"),
    ]

    trace_specs = []
    for infos, name, fill, border, symbol, size, hover_fn in _EVENTS:
        if not infos:
            continue
        prices_at_event = [i.close / 1000 for i in infos]
        trace_specs.append({
            "type": "scatter",
            "mode": "markers",
            "name": name,
            "yaxis": "y3",
            "x": [str(times.iloc[i.index])[:10] for i in infos],
            "y": [0.75] * len(infos),
            "text": [hover_fn(i) for i in infos],
            "customdata": prices_at_event,
            "marker": {"symbol": symbol, "size": size, "color": fill,
                       "line": {"color": border, "width": 1}},
            # Events are sparse, so these keep their own hover rather than going
            # through a dense anchor: an anchor only has text on the event's exact
            # trading day, which at ~0.6px per bar is unhittable with a mouse.
            # Plotly's 20px hoverdistance gives a usable grab zone instead — and
            # unlike the price line, the date stays in the template here so a
            # nearby match identifies itself instead of borrowing the header's date.
            "hovertemplate": (
                f"<b>%{{x}}</b> "
                f"<span style='color:{fill}'>●</span> <b>{name}</b><br>"
                f"Price: %{{customdata:,.0f}}<br>%{{text}}<extra></extra>"
            ),
        })

    # ── Condition-zone overlay traces ─────────────────────────────────────────
    # 8 combos of (buy, sell, reinvest) flags → distinct colors
    _COMBO_COLORS = {
        (False, False, False): ("#a0aec0", "No condition"),
        (True,  False, False): ("#22c55e", "Buy zone"),
        (False, True,  False): ("#ef4444", "Sell zone"),
        (False, False, True):  ("#f97316", "Reinvest zone"),
        (True,  False, True):  ("#14b8a6", "Buy + Reinvest"),
        (True,  True,  False): ("#eab308", "Buy + Sell"),
        (False, True,  True):  ("#ec4899", "Sell + Reinvest"),
        (True,  True,  True):  ("#94a3b8", "All conditions"),
    }

    zone_traces = []
    if buy_strategy and sell_strategy and reinvest_strategy and cal_range_close is not None:
        # Build per-row flag arrays
        n = len(df)
        b_flags = [False] * n
        s_flags = [False] * n
        r_flags = [False] * n
        # Only from start_index. check() is stateless and answers for any bar, so
        # without this the zones paint years before the backtest actually begins —
        # BuyMedian1000Strategy.check goes true at bar 1000 while the run may not
        # start until every signal exists, e.g. 1699.
        for row_i, row in df.iterrows():
            if row_i < start_index:
                continue
            close = row["close"] * 1000
            pe    = row.get("pe_ratio", None)
            b_flags[row_i] = buy_strategy.check(row_i, close, pe, cal_range_close)
            s_flags[row_i] = sell_strategy.check(row_i, close, pe, cal_range_close)
            r_flags[row_i] = reinvest_strategy.check(row_i, close, pe, cal_range_close)

        dates  = [str(times.iloc[i])[:10] for i in range(n)]
        prices = [df["close"].iloc[i] for i in range(n)]  # chart scale (no ×1000)

        # Bars before the strategy starts are a third state, distinct from both
        # "evaluated, nothing triggered" and "no overlay at all". Without it the
        # absence of an overlay silently carries meaning: previously (F,F,F)
        # matched here and painted grey "No condition" over years the strategy
        # could not act in; clipping alone then let the underlying P/E colouring
        # show through, which reads as a different chart rather than a state.
        if start_index > 0:
            zone_traces.append({
                "type": "scatter",
                "mode": "lines",
                "name": "Not evaluated",
                "yaxis": _yaxis,
                "x": dates,
                # inclusive of start_index so it meets the first painted zone with no gap
                "y": [prices[i] if i <= min(start_index, n - 1) else None for i in range(n)],
                "connectgaps": False,
                # Same width/opacity as every other condition zone — a dotted or
                # faded line lets the Cheap/Fair/High/Exp layer show through the
                # gaps, which is the very ambiguity this state exists to remove.
                # Only the colour distinguishes it.
                "line": {"color": _NOT_EVALUATED_COLOR, "width": 3},
                "opacity": 0.7,
                "legendgroup": "condzone",
                "hoverinfo": "skip",
            })

        for (b, s, r), (color, label) in _COMBO_COLORS.items():
            y_vals = [prices[i] if (i >= start_index and b_flags[i] == b
                                    and s_flags[i] == s and r_flags[i] == r) else None
                      for i in range(n)]
            if all(v is None for v in y_vals):
                continue
            zone_traces.append({
                "type": "scatter",
                "mode": "lines",
                "name": label,
                "yaxis": _yaxis,
                "x": dates,
                "y": y_vals,
                "connectgaps": False,
                "line": {"color": color, "width": 3},
                "opacity": 0.7,
                "legendgroup": "condzone",
                # Same null-gap problem as the P/E zone traces: under "x unified"
                # Plotly would pull each zone's nearest non-null point (potentially
                # weeks off) into the tooltip. The zone label comes from the
                # gap-free anchor below instead.
                "hoverinfo": "skip",
            })

        # ── Condition-zone hover anchor ──────────────────────────────────────
        # Invisible, gap-free trace that reports which zone the hovered date is
        # in. Unlike the P/E zones these flags are fixed at build time, so no
        # runtime re-sync is needed. Colors/labels come from the same
        # _COMBO_COLORS map that paints the lines, so they can't drift.
        if zone_traces:
            zone_meta = [
                _COMBO_COLORS.get((b_flags[i], s_flags[i], r_flags[i]),
                                  (_NO_ZONE_COLOR, "—"))
                if i >= start_index else (_NOT_EVALUATED_COLOR, "Not evaluated")
                for i in range(n)
            ]
            zone_traces.append({
                "type": "scatter",
                "mode": "lines",
                "name": "Condition zone",
                "yaxis": _yaxis,
                "x": dates,
                "y": prices,
                "line": {"width": 0, "color": _NO_ZONE_COLOR},
                "showlegend": False,
                "legendgroup": "condzone",
                "customdata": [[c, lbl] for c, lbl in zone_meta],
                "hovertemplate": (
                    "<span style='color:%{customdata[0]}'>●</span> "
                    "%{customdata[1]}<extra></extra>"
                ),
            })

    # ── Compare trace (interval buy) ─────────────────────────────────────────
    if compare_result and compare_result.get("buyedInfos"):
        cmp_infos = compare_result["buyedInfos"]
        trace_specs.append({
            "type": "scatter",
            "mode": "markers",
            "name": "Buy (Interval)",
            "yaxis": "y3",
            "x": [str(times.iloc[i.index])[:10] for i in cmp_infos],
            "y": [0.25] * len(cmp_infos),
            "customdata": [i.close / 1000 for i in cmp_infos],
            "text": [f"Invested: {i.finalBuy:,.0f}" for i in cmp_infos],
            "marker": {"symbol": "triangle-up", "size": 9,
                       "color": "rgba(34,197,94,0.75)",
                       "line": {"color": "#15803d", "width": 1}},
            "hovertemplate": (
                "<b>%{x}</b> "
                "<span style='color:rgba(99,179,237,0.75)'>●</span> <b>Buy (Interval)</b><br>"
                "Price: %{customdata:,.0f}<br>%{text}<extra></extra>"
            ),
        })

    # PE chart uses div id="peChart"; plotly write_html uses the first div it creates
    _div_id   = "peChart" if _yaxis == "y2" else None  # None = find first plotly div
    _find_gd  = (
        "document.getElementById('peChart')"
        if _div_id else
        "document.querySelector('.plotly-graph-div')"
    )

    inject = f"""
<script>
setTimeout(function() {{
  var gd = {_find_gd};
  if (!gd) {{ console.error('chart div not found'); return; }}

  // Shrink main axes to leave room for the event strip at the bottom
  var layoutUpdate = {{
    'yaxis.domain':  [0.13, 1],
    'yaxis2.domain': [0.13, 1],
    'yaxis3': {{
      domain: [0, 0.10],
      anchor: 'x',
      fixedrange: true,
      showticklabels: false,
      showgrid: false,
      zeroline: false,
      range: [0, 1],
    }}
  }};
  Plotly.relayout(gd, layoutUpdate).then(function() {{
    var eventTraces = {json.dumps(trace_specs)};
    var zoneTraces  = {json.dumps(zone_traces)};
    var allTraces   = zoneTraces.concat(eventTraces);
    return Plotly.addTraces(gd, allTraces);
  }}).then(function() {{
    console.log('Backtest traces added, total =', gd.data.length);
  }});
}}, 1000);
</script>
"""

    _gd_ref = _find_gd
    zone_toggle = f"""
<div id="condZonePanel" style="position:fixed;bottom:12px;right:12px;z-index:999;
  background:rgba(30,30,30,0.85);color:#ddd;padding:8px 12px;border-radius:8px;
  font:13px/1.6 sans-serif;backdrop-filter:blur(4px);">
  <label style="cursor:pointer;user-select:none;">
    <input type="checkbox" id="condZoneVis" checked
      onchange="(function(){{
        var gd={_gd_ref};
        var vis=document.getElementById('condZoneVis').checked;
        var idx=[];
        gd.data.forEach(function(t,i){{if(t.legendgroup==='condzone')idx.push(i);}});
        if(idx.length)Plotly.restyle(gd,{{visible:[vis?true:'legendonly']}},idx);
      }})()">
    Show condition zones
  </label>
</div>
"""
    result_block = ""
    if result:
        def _pct(v):
            color = "#22c55e" if v >= 0 else "#ef4444"
            return f'<span style="color:{color};font-weight:600">{v:.2f}%</span>'

        FIELDS = [
            ("totalMonths",         lambda r: str(r.get("totalMonths", 0))),
            ("totalShare",          lambda r: f'{r.get("totalShare", 0):,.0f}'),
            ("totalCapital",        lambda r: f'{r.get("totalCapital", 0):,.0f}'),
            ("totalCurrentCapital", lambda r: f'{r.get("totalCurrentCapital", 0):,.0f}'),
            ("finalMoney",          lambda r: f'{r.get("finalMoney", 0):,.0f}'),
            ("growthRatio",         lambda r: _pct(r.get("growthRatio", 0))),
            ("growthCurrentRatio",  lambda r: _pct(r.get("growthCurrentRatio", 0))),
            ("intervalAmount",      lambda r: f'{r.get("intervalAmount", 0):,.0f}'),
            ("totalReserveShare",   lambda r: f'{r.get("totalReserveShare", 0):,.0f}'),
            ("totalReserveCapital", lambda r: f'{r.get("totalReserveCapital", 0):,.0f}'),
            ("totalReserveFinal",   lambda r: f'{r.get("totalReserveFinal", 0):,.0f}'),
            ("reserveGrowthRatio",  lambda r: _pct(r.get("reserveGrowthRatio", 0))),
            ("totalBuys",           lambda r: str(r.get("totalBuys", 0))),
            ("totalSells",          lambda r: str(r.get("totalSells", 0))),
            ("totalReinvest",       lambda r: str(r.get("totalReinvest", 0))),
            ("allTotalCapital",     lambda r: f'{r.get("allTotalCapital", 0):,.0f}'),
            ("allTotalFinal",       lambda r: f'{r.get("allTotalFinal", 0):,.0f}'),
            ("allRatioGrowth",      lambda r: _pct(r.get("allRatioGrowth", 0))),
        ]

        td = "style='padding:3px 16px 3px 0'"
        tdv = "style='padding:3px 16px 3px 0;text-align:right'"

        if compare_result:
            header = f"<tr><th {td}>Field</th><th {tdv}>Median1000</th><th {tdv}>BuyInterval</th></tr>"
            rows   = "".join(
                f"<tr><td {td}>{label}</td><td {tdv}>{fmt(result)}</td><td {tdv}>{fmt(compare_result)}</td></tr>"
                for label, fmt in FIELDS
            )
        else:
            header = f"<tr><th {td}>Field</th><th {tdv}>Value</th></tr>"
            rows   = "".join(
                f"<tr><td {td}>{label}</td><td {tdv}>{fmt(result)}</td></tr>"
                for label, fmt in FIELDS
            )

        result_block = (
            f"<div style='padding:16px;font:13px/1.8 monospace'>"
            f"<table style='border-collapse:collapse'>{header}{rows}</table></div>"
        )

    import dataclasses
    strategy_block = ""
    strategies = [
        ("Buy",     buy_strategy),
        ("Sell",    sell_strategy),
        ("Reinvest",reinvest_strategy),
    ]
    strat_rows = ""
    for label, strat in strategies:
        if strat is None:
            continue
        strat_rows += f"<tr><td colspan='2' style='padding:6px 0 2px;color:#94a3b8;font-weight:600'>{label}: {type(strat).__name__}</td></tr>"
        if dataclasses.is_dataclass(strat):
            for fld in dataclasses.fields(strat):
                v = getattr(strat, fld.name)
                if isinstance(v, dict) and len(v) > 3:
                    v = f"{{...{len(v)} entries}}"
                elif dataclasses.is_dataclass(v):
                    # A field holding another strategy — the churn guard's
                    # reference to the sell arm. Its repr drags in that whole
                    # object including its signal maps, thousands of entries
                    # inline, once per arm that holds it. The object is already
                    # a section of this same table, so name it and stop.
                    v = f"→ {type(v).__name__} (above)"
                strat_rows += f"<tr><td style='padding:1px 16px 1px 12px;color:#64748b'>{fld.name}</td><td style='text-align:right'>{v}</td></tr>"

    if strat_rows:
        strategy_block = (
            f"<div style='padding:16px;font:13px/1.8 monospace'>"
            f"<div style='color:#60a5fa;font-weight:700;font-size:16px;margin-bottom:6px'>Strategy Parameters</div>"
            f"<table style='border-collapse:collapse'>{strat_rows}</table></div>"
        )

    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    html = html.replace("</body>", strategy_block + result_block + zone_toggle + inject + "</body>")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)

    # Inject signal strips for individual stocks (same as pe_<symbol>.html)
    if index.lower() not in _known_indices:
        symbol = index.upper()
        with db._conn() as con:
            available_windows = [
                r[0] for r in con.execute(
                    "SELECT DISTINCT window_days FROM trend_signals WHERE symbol=? ORDER BY window_days",
                    (symbol,)
                ).fetchall()
            ]
        if available_windows:
            _inject_signals_into_html(symbol, path, available_windows, yaxis_start=4,
                                      is_backtest=True, init_delay=1500,
                                      **_slider_defaults)

    print(f"Backtest chart saved to {path}")
    return path


if __name__ == "__main__":
    import sys, os
    idx = sys.argv[1] if len(sys.argv) > 1 else "vn30"
    os.makedirs("charts", exist_ok=True)
    fig, pe_dates, pe_values, price_data = pe_chart(index=idx, bands=True)
    path = f"charts/{idx}_valuation.html"
    save_chart(fig, pe_dates, pe_values, price_data, path)
    os.startfile(path)
