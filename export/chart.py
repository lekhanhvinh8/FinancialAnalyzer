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

_DEFAULT_PCT_WINDOW = 1000


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
            (0, f"#2ca02c", f"Cheap  P/E<{p25_s:.1f}"),
            (1, f"#f0c040", f"Fair   P/E {p25_s:.1f}–{median_s:.1f}"),
            (2, f"#ff7f0e", f"High   P/E {median_s:.1f}–{p75_s:.1f}"),
            (3, f"#d62728", f"Exp.   P/E>{p75_s:.1f}"),
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
                hovertemplate=f"<b>%{{x|%Y-%m-%d}}</b><br>{label}: %{{y:,.0f}} pts<extra></extra>",
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
    # 13=pe_mean | 14=price_mean | 15=pe_line | 16=marker
    # Trace layout (bands=True, has_price=False):
    # 0,1,2=bands | 3,4,5=pe_pct | 6=pe_mean | 7=pe_line | 8=marker
    if has_price:
        pe_pct_idx     = [3, 4, 5]
        price_pct_idx  = [10, 11, 12]
        pe_mean_idx    = 13
        price_mean_idx = 14
        pe_line_idx    = n - 2
        marker_idx     = n - 1
    else:
        pe_pct_idx     = [3, 4, 5]
        price_pct_idx  = []
        pe_mean_idx    = 6
        price_mean_idx = None
        pe_line_idx    = n - 2
        marker_idx     = n - 1

    plot_html = fig.to_html(include_plotlyjs="cdn", full_html=False, div_id="peChart")

    pe_dates_json        = json.dumps(pe_dates)
    pe_values_json       = json.dumps(pe_values)
    price_dates_json     = json.dumps(price_data[0] if price_data else [])
    price_values_json    = json.dumps(price_data[1] if price_data else [])
    pe_aligned_json      = json.dumps(price_data[2] if price_data else [])
    global_p25_json      = json.dumps(price_data[3] if price_data else None)
    global_med_json      = json.dumps(price_data[4] if price_data else None)
    global_p75_json      = json.dumps(price_data[5] if price_data else None)

    pe_mean_idx_json    = json.dumps(pe_mean_idx)
    price_mean_idx_json = json.dumps(price_mean_idx)

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
    <label class="chk"><input type="checkbox" id="priceMeanVis" checked> Show</label>
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
    <input type="checkbox" class="pct-price-cb" data-sub="0" checked>
    <span class="dot" style="background:rgba(46,160,67,0.9)"></span>25th</label>
  <span class="off-wrap"><input type="checkbox" id="off-en-prPct25">±<input type="number" id="off-pct-prPct25" class="off-pct" value="50">%</span>
  <label class="chk">
    <input type="checkbox" class="pct-price-cb" data-sub="1" checked>
    <span class="dot" style="background:rgba(100,100,200,0.9)"></span>Med</label>
  <span class="off-wrap"><input type="checkbox" id="off-en-prPctMed">±<input type="number" id="off-pct-prPctMed" class="off-pct" value="50">%</span>
  <label class="chk">
    <input type="checkbox" class="pct-price-cb" data-sub="2" checked>
    <span class="dot" style="background:rgba(220,53,69,0.9)"></span>75th</label>
  <span class="off-wrap"><input type="checkbox" id="off-en-prPct75">±<input type="number" id="off-pct-prPct75" class="off-pct" value="50">%</span>"""

        price_checkbox_js = f"""
document.getElementById('peLineVis').addEventListener('change', function() {{
  Plotly.restyle(gd, {{ visible: [this.checked ? true : 'legendonly'] }}, [{pe_line_idx}]);
}});
document.getElementById('priceColorVis').addEventListener('change', function() {{
  const v = this.checked ? true : 'legendonly';
  Plotly.restyle(gd, {{ visible: [v, v, v, v] }}, [6, 7, 8, 9]);
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
  if (priceValues.length > 0 && colorMode === 'price') {{
    const zoneY = _computeZoneY();
    [6, 7, 8, 9].forEach((ti, i) => {{ gd.data[ti].y = zoneY[i]; }});
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
    if (_hasBands) {{
      if (colorMode === 'price') {{
        [0, 1, 2].forEach((ti, i) => {{
          gd.data[ti].y     = _priceBandY[i];
          gd.data[ti].yaxis = 'y2';
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
    color_mode_bar = """
<div id="color-mode-bar">
  <strong>Color source:</strong>
  <div class="color-toggle">
    <label><input type="radio" name="colorMode" value="pe"><span>P/E</span></label>
    <label><input type="radio" name="colorMode" value="price" checked><span>Price</span></label>
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
    <label class="chk"><input type="checkbox" id="pePctVis"> Show</label>
    <input type="number" id="pePctW" value="{pct_window}" min="20" max="5000" step="50" title="Rolling window (days)">
    <span class="unit">d</span>
  </div>
  <label class="chk" style="margin-left:4px">
    <input type="checkbox" class="pct-pe-cb" data-sub="0" checked>
    <span class="dot" style="background:rgba(46,160,67,0.9)"></span>25th</label>
  <span class="off-wrap"><input type="checkbox" id="off-en-pePct25">±<input type="number" id="off-pct-pePct25" class="off-pct" value="50">%</span>
  <label class="chk">
    <input type="checkbox" class="pct-pe-cb" data-sub="1" checked>
    <span class="dot" style="background:rgba(100,100,200,0.9)"></span>Med</label>
  <span class="off-wrap"><input type="checkbox" id="off-en-pePctMed">±<input type="number" id="off-pct-pePctMed" class="off-pct" value="50">%</span>
  <label class="chk">
    <input type="checkbox" class="pct-pe-cb" data-sub="2" checked>
    <span class="dot" style="background:rgba(220,53,69,0.9)"></span>75th</label>
  <span class="off-wrap"><input type="checkbox" id="off-en-pePct75">±<input type="number" id="off-pct-pePct75" class="off-pct" value="50">%</span>
  {pe_mean_control}
  {price_pct_control if has_price else '''
  <div class="divider"></div>
  <span class="section-label">P/E Line</span>
  <label class="chk"><input type="checkbox" id="peLineVis"> Show</label>'''}
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
  return [0,1,2,3].map(z => priceVals.map((v, i) => {{
    if (zones[i] === z) return v;
    const adj = (i > 0 && zones[i-1] === z) || (i < n-1 && zones[i+1] === z);
    return adj ? v : null;
  }}));
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
  return [0,1,2,3].map(z => priceVals.map((v, i) => {{
    if (zones[i] === z) return v;
    const adj = (i > 0 && zones[i-1] === z) || (i < n-1 && zones[i+1] === z);
    return adj ? v : null;
  }}));
}}

function _computeZoneY() {{
  if (colorBasis === 'mean') {{
    const compareVals = colorMode === 'pe' ? peAlignedValues : priceValues;
    const wId  = colorMode === 'pe' ? 'peMeanW' : 'priceMeanW';
    const pw   = parseInt(document.getElementById(wId).value) || {mean_window};
    const meanArr = rollingMean(compareVals, pw);
    return splitByMean(priceValues, compareVals, meanArr);
  }}
  if (colorMode === 'pe') {{
    const pw = parseInt(document.getElementById('pePctW').value) || {pct_window};
    const p25al = rollingQuantile(peAlignedValues, pw, 0.25);
    const medal  = rollingQuantile(peAlignedValues, pw, 0.50);
    const p75al  = rollingQuantile(peAlignedValues, pw, 0.75);
    return splitByZone(priceValues, peAlignedValues, p25al, medal, p75al, globalP25, globalMed, globalP75);
  }} else {{
    const pw = parseInt(document.getElementById('pricePctW').value) || {pct_window};
    const p25al = rollingQuantile(priceValues, pw, 0.25);
    const medal  = rollingQuantile(priceValues, pw, 0.50);
    const p75al  = rollingQuantile(priceValues, pw, 0.75);
    return splitByZone(priceValues, priceValues, p25al, medal, p75al, globalPriceP25, globalPriceMed, globalPriceP75);
  }}
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
Plotly.restyle(gd, {{ visible: ['legendonly'] }}, [peMeanIdx]);
Plotly.restyle(gd, {{ visible: ['legendonly'] }}, [peLineIdx]);
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
            (0, "#2ca02c", f"Cheap  P/E<{p25:.1f}"),
            (1, "#f0c040", f"Fair   P/E {p25:.1f}–{med:.1f}"),
            (2, "#ff7f0e", f"High   P/E {med:.1f}–{p75:.1f}"),
            (3, "#d62728", f"Exp.   P/E>{p75:.1f}"),
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
                hovertemplate=f"<b>%{{x|%Y-%m-%d}}</b><br>{symbol}: %{{y:,.0f}}<extra></extra>",
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

    # ── P/E line ──────────────────────────────────────────────────────────────
    if has_pe:
        fig.add_trace(go.Scatter(
            x=dates, y=pe_vals,
            mode="lines", name=f"{symbol} P/E",
            line=dict(color="#1f77b4", width=1.8), yaxis="y1",
            hovertemplate="<b>%{x|%Y-%m-%d}</b><br>P/E: %{y:.2f}x<extra></extra>",
        ))
        current = pe_vals[-1]
        fig.add_trace(go.Scatter(
            x=[dates[-1]], y=[current],
            mode="markers+text", marker=dict(size=8, color="#ff7f0e"),
            text=[f"  {current:.2f}x"], textposition="middle right",
            name=f"Current P/E", yaxis="y1",
            hovertemplate=f"<b>%{{x|%Y-%m-%d}}</b><br>P/E: {current:.2f}x<extra></extra>",
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
        xaxis=dict(title="Date", showgrid=True, gridcolor="rgba(200,200,200,0.3)"),
        yaxis=dict(title="P/E (x)", showgrid=True, gridcolor="rgba(200,200,200,0.3)", side="left"),
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
) -> str:
    """
    Export a backtest chart built on top of the full PE chart (all percentile
    lines, mean lines, color toggles), with event markers and condition-zone
    overlays added on top.
    """
    import os
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    _known_indices = {"vn30", "vndiamond", "vnfinlead", "vnindex"}
    if index.lower() in _known_indices:
        fig, pe_dates, pe_values, price_data = pe_chart(index=index, bands=True)
        save_chart(fig, pe_dates, pe_values, price_data, path)
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
            "y": [0.5] * len(infos),
            "text": [hover_fn(i) for i in infos],
            "customdata": prices_at_event,
            "marker": {"symbol": symbol, "size": size, "color": fill,
                       "line": {"color": border, "width": 1}},
            "hovertemplate": (
                f"<b>%{{x}}</b><br>"
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
        for row_i, row in df.iterrows():
            close = row["close"] * 1000
            pe    = row.get("pe_ratio", None)
            b_flags[row_i] = buy_strategy.check(row_i, close, pe, cal_range_close)
            s_flags[row_i] = sell_strategy.check(row_i, close, pe, cal_range_close)
            r_flags[row_i] = reinvest_strategy.check(row_i, close, pe, cal_range_close)

        dates  = [str(times.iloc[i])[:10] for i in range(n)]
        prices = [df["close"].iloc[i] for i in range(n)]  # chart scale (no ×1000)

        for (b, s, r), (color, label) in _COMBO_COLORS.items():
            y_vals = [prices[i] if (b_flags[i] == b and s_flags[i] == s and r_flags[i] == r) else None
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
                "hovertemplate": f"<b>%{{x}}</b><br><span style='color:{color}'>●</span> {label}<br>Price: %{{y:,.2f}}<extra></extra>",
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
<div id="condZonePanel" style="position:fixed;top:12px;left:12px;z-index:999;
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
            color = "green" if v >= 0 else "red"
            return f'<span style="color:{color}">{v:.2f}%</span>'

        def _row(label, value):
            return f"<tr><td>{label}</td><td style='padding-left:24px'>{value}</td></tr>"

        rows = "".join([
            _row("totalMonths",          result.get("totalMonths", 0)),
            _row("totalShare",           f'{result.get("totalShare", 0):,.0f}'),
            _row("totalCapital",         f'{result.get("totalCapital", 0):,.0f}'),
            _row("totalCurrentCapital",  f'{result.get("totalCurrentCapital", 0):,.0f}'),
            _row("finalMoney",           f'{result.get("finalMoney", 0):,.0f}'),
            _row("growthRatio",          _pct(result.get("growthRatio", 0))),
            _row("growthCurrentRatio",   _pct(result.get("growthCurrentRatio", 0))),
            _row("intervalAmount",       f'{result.get("intervalAmount", 0):,.0f}'),
            _row("totalReserveShare",    f'{result.get("totalReserveShare", 0):,.0f}'),
            _row("totalReserveCapital",  f'{result.get("totalReserveCapital", 0):,.0f}'),
            _row("totalReserveFinal",    f'{result.get("totalReserveFinal", 0):,.0f}'),
            _row("reserveGrowthRatio",   _pct(result.get("reserveGrowthRatio", 0))),
            _row("totalBuys",            result.get("totalBuys", 0)),
            _row("totalSells",           result.get("totalSells", 0)),
            _row("totalReinvest",        result.get("totalReinvest", 0)),
            _row("allTotalCapital",      f'{result.get("allTotalCapital", 0):,.0f}'),
            _row("allTotalFinal",        f'{result.get("allTotalFinal", 0):,.0f}'),
            _row("allRatioGrowth",       _pct(result.get("allRatioGrowth", 0))),
        ])
        result_block = f"<div style='padding:16px;font:13px/2 monospace'><table>{rows}</table></div>"

    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    html = html.replace("</body>", result_block + zone_toggle + inject + "</body>")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Backtest chart saved to {path}")
    return path


if __name__ == "__main__":
    import sys, os
    idx = sys.argv[1] if len(sys.argv) > 1 else "vn30"
    os.makedirs("charts", exist_ok=True)
    fig, pe_dates, pe_values, price_data = pe_chart(index=idx, bands=True)
    path = f"charts/pe_{idx}.html"
    save_chart(fig, pe_dates, pe_values, price_data, path)
    os.startfile(path)
