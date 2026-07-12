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
    "vn30":      functools.partial(db.load_pe_ratios, "vn30"),
    "vndiamond": functools.partial(db.load_pe_ratios, "vndiamond"),
    "vnfinlead": functools.partial(db.load_pe_ratios, "vnfinlead"),
}

_INDEX_LABELS = {
    "vn30":       "VN30",
    "vndiamond":  "VN Diamond",
    "vnfinlead":  "VN Fin Lead",
}

_INDEX_PRICE_SYMBOL = {
    "vn30":       "VN30",
    "vndiamond":  "VNDIAMOND",
    "vnfinlead":  "VNFINLEAD",
}

_DEFAULT_PCT_WINDOW = 1260   # ~5 years of trading days


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
    mean_window: int = 200,
    median_window: int = 200,
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

    # ── Index price line (y2) — trace 6 if has_price ─────────────────────────
    price_data = None
    if idx_price is not None and not idx_price.empty:
        price_dates  = idx_price.index.strftime("%Y-%m-%d").tolist()
        price_values = idx_price.tolist()
        price_data   = (price_dates, price_values)

        fig.add_trace(go.Scatter(
            x=idx_price.index, y=price_values,
            mode="lines", name=f"{label} Index",
            line=dict(color="rgba(150,150,150,0.5)", width=1.2),
            yaxis="y2",
            hovertemplate=f"<b>%{{x|%Y-%m-%d}}</b><br>{label}: %{{y:,.0f}} pts<extra></extra>",
        ))

        # Price rolling percentile lines (traces 7, 8, 9)
        for q, color, tmpl in [
            (0.25, "rgba(46,160,67,0.9)",   "Price 25th ({w}d)"),
            (0.50, "rgba(100,100,200,0.9)", "Price Median ({w}d)"),
            (0.75, "rgba(220,53,69,0.9)",   "Price 75th ({w}d)"),
        ]:
            fig.add_trace(_pct_trace(idx_price.index, price_values, pct_window, q, tmpl, color, "y2"))

    # ── P/E line ──────────────────────────────────────────────────────────────
    fig.add_trace(go.Scatter(
        x=df["date"], y=pe_values,
        mode="lines", name="Aggregate P/E",
        line=dict(color="#1f77b4", width=1.8), yaxis="y1",
        hovertemplate=(
            "<b>%{x|%Y-%m-%d}</b><br>P/E: %{y:.2f}x<br>"
            "Members: %{customdata}<extra></extra>"
        ),
        customdata=df["member_count"],
    ))

    # ── P/E MA lines ──────────────────────────────────────────────────────────
    fig.add_trace(go.Scatter(
        x=pe_dates, y=_rolling_stat(pe_values, mean_window, "mean"),
        mode="lines", name=f"P/E Mean MA({mean_window})",
        line=dict(color="#e377c2", width=1.5), yaxis="y1",
        hovertemplate="P/E Mean MA: %{y:.2f}x<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=pe_dates, y=_rolling_stat(pe_values, median_window, "median"),
        mode="lines", name=f"P/E Median MA({median_window})",
        line=dict(color="#17becf", width=1.5, dash="dash"), yaxis="y1",
        hovertemplate="P/E Median MA: %{y:.2f}x<extra></extra>",
    ))

    # ── Price MA lines ────────────────────────────────────────────────────────
    if price_data:
        fig.add_trace(go.Scatter(
            x=price_dates, y=_rolling_stat(price_values, mean_window, "mean"),
            mode="lines", name=f"Price Mean MA({mean_window})",
            line=dict(color="#9467bd", width=1.5), yaxis="y2",
            hovertemplate="Price Mean MA: %{y:,.0f}<extra></extra>",
        ))
        fig.add_trace(go.Scatter(
            x=price_dates, y=_rolling_stat(price_values, median_window, "median"),
            mode="lines", name=f"Price Median MA({median_window})",
            line=dict(color="#8c564b", width=1.5, dash="dash"), yaxis="y2",
            hovertemplate="Price Median MA: %{y:,.0f}<extra></extra>",
        ))

    # ── Current P/E marker ────────────────────────────────────────────────────
    fig.add_trace(go.Scatter(
        x=[x1], y=[current],
        mode="markers+text", marker=dict(size=8, color="#ff7f0e"),
        text=[f"  {current:.2f}x"], textposition="middle right",
        name=f"Current P/E ({current_date})", yaxis="y1",
        hovertemplate=f"<b>{current_date}</b><br>P/E: {current:.2f}x<extra></extra>",
    ))

    # ── Layout ────────────────────────────────────────────────────────────────
    date_range_str = f"{df['date'].iloc[0].strftime('%Y')} – {df['date'].iloc[-1].strftime('%Y')}"
    fig.update_layout(
        title=dict(text=f"{title}  <sup>{date_range_str}</sup>", font_size=18),
        xaxis=dict(title="Date", showgrid=True, gridcolor="rgba(200,200,200,0.3)"),
        yaxis=dict(title="P/E (x)", showgrid=True, gridcolor="rgba(200,200,200,0.3)", side="left"),
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

    # Trace layout (bands=True always):
    # 0,1,2=bands | 3,4,5=pe_pct_lines | [6=idx_price | 7,8,9=price_pct_lines] |
    # pe_line | pe_mean | pe_median | [price_mean | price_median] | marker
    if has_price:
        pe_pct_idx    = [3, 4, 5]
        price_pct_idx = [7, 8, 9]
        marker_idx       = n - 1
        price_median_idx = n - 2
        price_mean_idx   = n - 3
        pe_median_idx    = n - 4
        pe_mean_idx      = n - 5
    else:
        pe_pct_idx    = [3, 4, 5]
        price_pct_idx = []
        marker_idx    = n - 1
        pe_median_idx = n - 2
        pe_mean_idx   = n - 3

    plot_html = fig.to_html(include_plotlyjs="cdn", full_html=False, div_id="peChart")

    pe_dates_json     = json.dumps(pe_dates)
    pe_values_json    = json.dumps(pe_values)
    price_dates_json  = json.dumps(price_data[0] if price_data else [])
    price_values_json = json.dumps(price_data[1] if price_data else [])

    # ── Price-side controls (only rendered when price data exists) ────────────
    price_pct_control = ""
    price_ma_control  = ""
    price_js_pct      = ""
    price_js_ma       = ""
    price_checkbox_js = ""

    if has_price:
        price_pct_control = f"""
  <div class="divider"></div>
  <span class="section-label">Price Percentiles</span>
  <div class="ma-group">
    <label class="chk"><input type="checkbox" id="pricePctVis" checked> Show</label>
    <input type="number" id="pricePctW" value="{pct_window}" min="20" max="5000" step="50" title="Rolling window (days)">
    <span class="unit">d</span>
  </div>
  <label class="chk" style="margin-left:4px">
    <input type="checkbox" class="pct-price-cb" data-sub="0" checked>
    <span class="dot" style="background:rgba(46,160,67,0.9)"></span>25th</label>
  <label class="chk">
    <input type="checkbox" class="pct-price-cb" data-sub="1" checked>
    <span class="dot" style="background:rgba(100,100,200,0.9)"></span>Med</label>
  <label class="chk">
    <input type="checkbox" class="pct-price-cb" data-sub="2" checked>
    <span class="dot" style="background:rgba(220,53,69,0.9)"></span>75th</label>"""

        price_ma_control = f"""
  <div class="divider"></div>
  <span class="section-label">Price MA</span>
  <div class="ma-group">
    <span class="dot" style="background:#9467bd"></span>
    <label class="chk"><input type="checkbox" id="priceMeanVis" checked> Mean</label>
    <input type="number" id="priceMeanW" value="200" min="2" max="2000" step="10">
  </div>
  <div class="ma-group">
    <span class="dot" style="background:#8c564b"></span>
    <label class="chk"><input type="checkbox" id="priceMedianVis" checked> Median</label>
    <input type="number" id="priceMedianW" value="200" min="2" max="2000" step="10">
  </div>"""

        price_js_pct = f"""
  const ppw = parseInt(document.getElementById('pricePctW').value) || {pct_window};
  const pricePctVis = document.getElementById('pricePctVis').checked;
  const pricePctSubs = [...document.querySelectorAll('.pct-price-cb')].map(c => c.checked);
  Plotly.restyle(gd, {{
    y: [
      rollingQuantile(priceValues, ppw, 0.25),
      rollingQuantile(priceValues, ppw, 0.50),
      rollingQuantile(priceValues, ppw, 0.75),
    ],
    name: ['Price 25th (' + ppw + 'd)', 'Price Median (' + ppw + 'd)', 'Price 75th (' + ppw + 'd)'],
    visible: [
      (pricePctVis && pricePctSubs[0]) ? true : 'legendonly',
      (pricePctVis && pricePctSubs[1]) ? true : 'legendonly',
      (pricePctVis && pricePctSubs[2]) ? true : 'legendonly',
    ]
  }}, [{price_pct_idx[0]}, {price_pct_idx[1]}, {price_pct_idx[2]}]);"""

        price_js_ma = f"""
  const pmw = parseInt(document.getElementById('priceMeanW').value)   || 200;
  const pdw = parseInt(document.getElementById('priceMedianW').value) || 200;
  Plotly.restyle(gd, {{
    y: [rollingMean(priceValues, pmw), rollingMedian(priceValues, pdw)],
    name: ['Price Mean MA(' + pmw + ')', 'Price Median MA(' + pdw + ')'],
    visible: [
      document.getElementById('priceMeanVis').checked   ? true : 'legendonly',
      document.getElementById('priceMedianVis').checked ? true : 'legendonly',
    ]
  }}, [{price_mean_idx}, {price_median_idx}]);"""

        price_checkbox_js = f"""
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
  Plotly.restyle(gd, {{
    y: [
      rollingQuantile(priceValues, ppw, 0.25),
      rollingQuantile(priceValues, ppw, 0.50),
      rollingQuantile(priceValues, ppw, 0.75),
    ],
    name: ['Price 25th (' + ppw + 'd)', 'Price Median (' + ppw + 'd)', 'Price 75th (' + ppw + 'd)'],
    visible: [
      (vis && subs[0]) ? true : 'legendonly',
      (vis && subs[1]) ? true : 'legendonly',
      (vis && subs[2]) ? true : 'legendonly',
    ]
  }}, [{price_pct_idx[0]}, {price_pct_idx[1]}, {price_pct_idx[2]}]);
}}
document.getElementById('pricePctVis').addEventListener('change', togglePricePct);
document.querySelectorAll('.pct-price-cb').forEach(cb => cb.addEventListener('change', togglePricePct));
document.getElementById('pricePctW').addEventListener('keydown', e => {{ if (e.key==='Enter') recomputePricePct(); }});
document.getElementById('priceMeanVis').addEventListener('change', function() {{
  Plotly.restyle(gd, {{visible: [this.checked ? true : 'legendonly']}}, [{price_mean_idx}]);
}});
document.getElementById('priceMedianVis').addEventListener('change', function() {{
  Plotly.restyle(gd, {{visible: [this.checked ? true : 'legendonly']}}, [{price_median_idx}]);
}});
['priceMeanW','priceMedianW'].forEach(id => {{
  document.getElementById(id).addEventListener('keydown', e => {{ if (e.key==='Enter') updateMA(); }});
}});"""

    controls_html = f"""
<style>
  #ma-controls {{
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
</style>
<div id="ma-controls">
  <span class="section-label">P/E Percentiles</span>
  <div class="ma-group">
    <label class="chk"><input type="checkbox" id="pePctVis" checked> Show</label>
    <input type="number" id="pePctW" value="{pct_window}" min="20" max="5000" step="50" title="Rolling window (days)">
    <span class="unit">d</span>
  </div>
  <label class="chk" style="margin-left:4px">
    <input type="checkbox" class="pct-pe-cb" data-sub="0" checked>
    <span class="dot" style="background:rgba(46,160,67,0.9)"></span>25th</label>
  <label class="chk">
    <input type="checkbox" class="pct-pe-cb" data-sub="1" checked>
    <span class="dot" style="background:rgba(100,100,200,0.9)"></span>Med</label>
  <label class="chk">
    <input type="checkbox" class="pct-pe-cb" data-sub="2" checked>
    <span class="dot" style="background:rgba(220,53,69,0.9)"></span>75th</label>
  {price_pct_control}
  <div class="divider"></div>
  <span class="section-label">P/E MA</span>
  <div class="ma-group">
    <span class="dot" style="background:#e377c2"></span>
    <label class="chk"><input type="checkbox" id="peMeanVis" checked> Mean</label>
    <input type="number" id="peMeanW" value="200" min="2" max="2000" step="10">
  </div>
  <div class="ma-group">
    <span class="dot" style="background:#17becf"></span>
    <label class="chk"><input type="checkbox" id="peMedianVis" checked> Median</label>
    <input type="number" id="peMedianW" value="200" min="2" max="2000" step="10">
  </div>
  {price_ma_control}
  <span class="unit">days</span>
  <button onclick="updateAll()">Apply</button>
</div>
"""

    script = f"""
<script>
const peValues    = {pe_values_json};
const priceValues = {price_values_json};
const peMeanIdx   = {pe_mean_idx};
const peMedianIdx = {pe_median_idx};
const gd = document.getElementById('peChart');

function rollingMean(arr, w) {{
  const out = new Array(arr.length).fill(null);
  let s = 0;
  for (let i = 0; i < arr.length; i++) {{
    s += arr[i];
    if (i >= w) s -= arr[i - w];
    if (i >= w - 1) out[i] = s / w;
  }}
  return out;
}}
function rollingMedian(arr, w) {{
  return arr.map((_, i) => {{
    if (i < w - 1) return null;
    const sl = arr.slice(i - w + 1, i + 1).slice().sort((a, b) => a - b);
    const m = sl.length >> 1;
    return sl.length % 2 === 0 ? (sl[m - 1] + sl[m]) / 2 : sl[m];
  }});
}}
function rollingQuantile(arr, w, p) {{
  return arr.map((_, i) => {{
    if (i < w - 1) return null;
    const sl = arr.slice(i - w + 1, i + 1).slice().sort((a, b) => a - b);
    const pos = p * (sl.length - 1);
    const lo = Math.floor(pos), hi = Math.ceil(pos);
    return sl[lo] + (sl[hi] - sl[lo]) * (pos - lo);
  }});
}}

// Visibility-only toggle — no recompute, single restyle call
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

// Recompute rolling quantiles + update — single restyle call for all 3 traces
function recomputePePct() {{
  const pw = parseInt(document.getElementById('pePctW').value) || {pct_window};
  const vis = document.getElementById('pePctVis').checked;
  const subs = [...document.querySelectorAll('.pct-pe-cb')].map(c => c.checked);
  Plotly.restyle(gd, {{
    y: [
      rollingQuantile(peValues, pw, 0.25),
      rollingQuantile(peValues, pw, 0.50),
      rollingQuantile(peValues, pw, 0.75),
    ],
    name: ['P/E 25th (' + pw + 'd)', 'P/E Median (' + pw + 'd)', 'P/E 75th (' + pw + 'd)'],
    visible: [
      (vis && subs[0]) ? true : 'legendonly',
      (vis && subs[1]) ? true : 'legendonly',
      (vis && subs[2]) ? true : 'legendonly',
    ]
  }}, [{pe_pct_idx[0]}, {pe_pct_idx[1]}, {pe_pct_idx[2]}]);
}}

function updateMA() {{
  const mw = parseInt(document.getElementById('peMeanW').value)   || 200;
  const dw = parseInt(document.getElementById('peMedianW').value) || 200;
  Plotly.restyle(gd, {{
    y: [rollingMean(peValues, mw), rollingMedian(peValues, dw)],
    name: ['P/E Mean MA(' + mw + ')', 'P/E Median MA(' + dw + ')'],
    visible: [
      document.getElementById('peMeanVis').checked   ? true : 'legendonly',
      document.getElementById('peMedianVis').checked ? true : 'legendonly',
    ]
  }}, [peMeanIdx, peMedianIdx]);
  {price_js_ma}
}}

function updateAll() {{ recomputePePct(); {('recomputePricePct();' if has_price else '')} updateMA(); }}

// P/E percentile: checkbox = visibility only, window change = recompute
document.getElementById('pePctVis').addEventListener('change', togglePePct);
document.querySelectorAll('.pct-pe-cb').forEach(cb => cb.addEventListener('change', togglePePct));
document.getElementById('pePctW').addEventListener('keydown', e => {{ if (e.key === 'Enter') recomputePePct(); }});

// P/E MA
document.getElementById('peMeanVis').addEventListener('change', function() {{
  Plotly.restyle(gd, {{visible: [this.checked ? true : 'legendonly']}}, [peMeanIdx]);
}});
document.getElementById('peMedianVis').addEventListener('change', function() {{
  Plotly.restyle(gd, {{visible: [this.checked ? true : 'legendonly']}}, [peMedianIdx]);
}});
['peMeanW', 'peMedianW'].forEach(id => {{
  document.getElementById(id).addEventListener('keydown', e => {{ if (e.key === 'Enter') updateMA(); }});
}});
{price_checkbox_js.replace('updatePercentiles', 'recomputePricePct').replace('togglePricePct', 'togglePricePct')}
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


if __name__ == "__main__":
    import sys, os
    idx = sys.argv[1] if len(sys.argv) > 1 else "vn30"
    os.makedirs("charts", exist_ok=True)
    fig, pe_dates, pe_values, price_data = pe_chart(index=idx, bands=True)
    path = f"charts/pe_{idx}.html"
    save_chart(fig, pe_dates, pe_values, price_data, path)
    os.startfile(path)
