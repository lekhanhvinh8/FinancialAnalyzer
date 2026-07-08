"""
VN30 / VN Diamond Aggregate P/E chart module.

Usage:
    from chart import pe_chart, save_chart

    fig, pe_dates, pe_values = pe_chart()           # VN30, full history
    fig, pe_dates, pe_values = pe_chart(index="vndiamond")
    fig.show()                                       # static view in browser
    save_chart(fig, pe_dates, pe_values, "pe.html") # interactive MA controls

CLI:
    python chart.py vn30
    python chart.py vndiamond
"""

import json

import numpy as np
import pandas as pd
import plotly.graph_objects as go

import database as db

_PE_LOADERS = {
    "vn30":      db.load_pe_history,
    "vndiamond": db.load_pe_vndiamond,
}

_INDEX_LABELS = {
    "vn30":      "VN30",
    "vndiamond": "VN Diamond",
}

_INDEX_PRICE_SYMBOL = {
    "vn30":      "VN30",
    "vndiamond": "VNDIAMOND",
}


def load_pe(
    index: str = "vn30",
    start: str | None = None,
    end: str | None = None,
    min_members: int = 5,
) -> pd.DataFrame:
    """Load P/E history from DB, filtered by date range and minimum member count."""
    index = index.lower()
    loader = _PE_LOADERS.get(index)
    if loader is None:
        raise ValueError(f"Unknown index '{index}'. Choose from: {list(_PE_LOADERS)}")
    db.init_db()
    df = loader(start, end)
    df = df.reset_index()
    df = df.dropna(subset=["pe_ratio"])
    df = df[df["member_count"] >= min_members]
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


def _fetch_index_price(index: str, start: str, end: str) -> pd.Series | None:
    """Fetch index price history from vnstock. Returns None on failure."""
    symbol = _INDEX_PRICE_SYMBOL.get(index.lower())
    if not symbol:
        return None
    try:
        from vnstock.api.quote import Quote
        q = Quote(symbol=symbol, source="VCI")
        df = q.history(start=start, end=end, interval="1D")
        if df is None or df.empty:
            return None
        df["time"] = pd.to_datetime(df["time"]).dt.normalize()
        df = df.set_index("time").sort_index()
        return df["close"]
    except Exception:
        return None


def _rolling_mean(values: list[float], window: int) -> list[float | None]:
    s = pd.Series(values)
    return s.rolling(window, min_periods=window).mean().where(lambda x: x.notna(), other=None).tolist()


def _rolling_median(values: list[float], window: int) -> list[float | None]:
    s = pd.Series(values)
    return s.rolling(window, min_periods=window).median().where(lambda x: x.notna(), other=None).tolist()


def pe_chart(
    index: str = "vn30",
    start: str | None = None,
    end: str | None = None,
    min_members: int = 5,
    bands: bool = True,
    mean_window: int = 200,
    median_window: int = 200,
    title: str | None = None,
) -> tuple[go.Figure, list, list]:
    """
    Build an interactive Plotly figure of aggregate P/E + index price over time,
    with rolling mean and median MA lines.

    Parameters
    ----------
    index         : "vn30" or "vndiamond"
    start         : ISO date string, e.g. "2018-01-01"
    end           : ISO date string
    min_members   : minimum members contributing for a date to be included
    bands         : draw percentile bands (cheap / fair / expensive) if True
    mean_window   : initial rolling mean window in trading days (default 200)
    median_window : initial rolling median window in trading days (default 200)
    title         : chart title (auto-generated if None)

    Returns
    -------
    (fig, pe_dates, pe_values) — figure + raw data for interactive MA controls
    """
    index = index.lower()
    label = _INDEX_LABELS.get(index, index.upper())
    if title is None:
        title = f"{label} — Aggregate P/E & Index Price"

    df = load_pe(index, start, end, min_members)
    if df.empty:
        raise ValueError("No P/E data in the requested range.")

    pe = df["pe_ratio"]
    pe_dates = df["date"].dt.strftime("%Y-%m-%d").tolist()
    pe_values = pe.tolist()

    current = pe.iloc[-1]
    current_date = df["date"].iloc[-1].strftime("%Y-%m-%d")
    date_start_str = df["date"].iloc[0].strftime("%Y-%m-%d")

    pct25 = pe.quantile(0.25)
    pct50 = pe.quantile(0.50)
    pct75 = pe.quantile(0.75)

    idx_price = _fetch_index_price(index, date_start_str, current_date)

    fig = go.Figure()

    # ── Percentile bands ──────────────────────────────────────────────────────
    if bands:
        x_fill = [df["date"].iloc[0], df["date"].iloc[-1]]

        def _band(lo, hi, color, name):
            fig.add_trace(go.Scatter(
                x=x_fill + x_fill[::-1],
                y=[lo, lo, hi, hi],
                fill="toself", fillcolor=color,
                line=dict(width=0), mode="lines",
                name=name, hoverinfo="skip", showlegend=True, yaxis="y1",
            ))

        _band(pe.min(),    pct25,    "rgba(46,160,67,0.15)",  "Cheap (< 25th pct)")
        _band(pct25,       pct75,    "rgba(255,200,0,0.12)",  "Fair (25–75th pct)")
        _band(pct75,       pe.max(), "rgba(220,53,69,0.15)",  "Expensive (> 75th pct)")

        for val, lbl, color in [
            (pct25, f"25th  {pct25:.1f}x", "rgba(46,160,67,0.8)"),
            (pct50, f"Med   {pct50:.1f}x",  "rgba(100,100,200,0.8)"),
            (pct75, f"75th  {pct75:.1f}x", "rgba(220,53,69,0.8)"),
        ]:
            fig.add_hline(
                y=val, line=dict(color=color, width=1, dash="dot"),
                annotation_text=lbl, annotation_position="top right",
                annotation_font_size=11,
            )

    # ── Index price line (y2) ─────────────────────────────────────────────────
    if idx_price is not None and not idx_price.empty:
        fig.add_trace(go.Scatter(
            x=idx_price.index, y=idx_price.values,
            mode="lines", name=f"{label} Index",
            line=dict(color="rgba(150,150,150,0.5)", width=1.2),
            yaxis="y2",
            hovertemplate=(
                "<b>%{x|%Y-%m-%d}</b><br>"
                f"{label}: %{{y:,.0f}} pts<extra></extra>"
            ),
        ))

    # ── P/E line ──────────────────────────────────────────────────────────────
    fig.add_trace(go.Scatter(
        x=df["date"], y=pe_values,
        mode="lines", name="Aggregate P/E",
        line=dict(color="#1f77b4", width=1.8), yaxis="y1",
        hovertemplate=(
            "<b>%{x|%Y-%m-%d}</b><br>"
            "P/E: %{y:.2f}x<br>"
            "Members: %{customdata}<extra></extra>"
        ),
        customdata=df["member_count"],
    ))

    # ── Rolling mean MA ───────────────────────────────────────────────────────
    mean_y = _rolling_mean(pe_values, mean_window)
    fig.add_trace(go.Scatter(
        x=pe_dates, y=mean_y,
        mode="lines", name=f"Mean MA({mean_window})",
        line=dict(color="#e377c2", width=1.5, dash="solid"),
        yaxis="y1",
        hovertemplate="Mean MA: %{y:.2f}x<extra></extra>",
    ))

    # ── Rolling median MA ─────────────────────────────────────────────────────
    median_y = _rolling_median(pe_values, median_window)
    fig.add_trace(go.Scatter(
        x=pe_dates, y=median_y,
        mode="lines", name=f"Median MA({median_window})",
        line=dict(color="#17becf", width=1.5, dash="dash"),
        yaxis="y1",
        hovertemplate="Median MA: %{y:.2f}x<extra></extra>",
    ))

    # ── Current value marker ──────────────────────────────────────────────────
    fig.add_trace(go.Scatter(
        x=[df["date"].iloc[-1]], y=[current],
        mode="markers+text", marker=dict(size=8, color="#ff7f0e"),
        text=[f"  {current:.2f}x"], textposition="middle right",
        name=f"Current P/E ({current_date})", yaxis="y1",
        hovertemplate=f"<b>{current_date}</b><br>P/E: {current:.2f}x<extra></extra>",
    ))

    # ── Layout ────────────────────────────────────────────────────────────────
    date_range_str = (
        f"{df['date'].iloc[0].strftime('%Y')} – {df['date'].iloc[-1].strftime('%Y')}"
    )
    fig.update_layout(
        title=dict(text=f"{title}  <sup>{date_range_str}</sup>", font_size=18),
        xaxis=dict(title="Date", showgrid=True, gridcolor="rgba(200,200,200,0.3)"),
        yaxis=dict(
            title="P/E (x)", showgrid=True,
            gridcolor="rgba(200,200,200,0.3)", side="left",
        ),
        yaxis2=dict(
            title=f"{label} Index (pts)", overlaying="y",
            side="right", showgrid=False, tickformat=",",
        ),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        plot_bgcolor="white", paper_bgcolor="white",
        margin=dict(l=60, r=80, t=80, b=60),
    )

    return fig, pe_dates, pe_values


# ── Trace index helpers (must match add_trace order above) ────────────────────
# bands=True:  0=cheap, 1=fair, 2=expensive, 3=idx_price, 4=pe, 5=mean, 6=median, 7=marker
# bands=False:                                3=idx_price, 4=pe, 5=mean, 6=median, 7=marker
# We embed these offsets in the JS so it can find the right trace.
_MEAN_TRACE_OFFSET   = 5   # relative to start (after 3 band traces)
_MEDIAN_TRACE_OFFSET = 6
_NO_BAND_MEAN_OFFSET = 2   # when bands=False: idx_price=0, pe=1, mean=2, median=3, marker=4
_NO_BAND_MEDIAN_OFFSET = 3


def save_chart(
    fig: go.Figure,
    pe_dates: list,
    pe_values: list,
    path: str = "pe_chart.html",
    bands: bool = True,
) -> str:
    """
    Save the P/E chart as a self-contained HTML file with interactive
    Mean MA and Median MA controls (visibility toggle + window length input).

    Returns the saved file path.
    """
    # Identify mean/median trace indices (0-based)
    n = len(fig.data)
    mean_idx   = n - 3   # second-to-last before marker
    median_idx = n - 2   # last before marker

    plot_html = fig.to_html(include_plotlyjs="cdn", full_html=False, div_id="peChart")

    dates_json  = json.dumps(pe_dates)
    values_json = json.dumps(pe_values)

    controls_html = f"""
<style>
  #ma-controls {{
    font-family: sans-serif; font-size: 13px;
    display: flex; gap: 32px; align-items: center;
    padding: 10px 16px; background: #f8f9fa;
    border: 1px solid #dee2e6; border-radius: 6px;
    margin-bottom: 8px; flex-wrap: wrap;
  }}
  #ma-controls label {{ display: flex; align-items: center; gap: 6px; cursor: pointer; }}
  #ma-controls input[type=number] {{
    width: 70px; padding: 3px 6px; border: 1px solid #ced4da;
    border-radius: 4px; font-size: 13px;
  }}
  .ma-group {{ display: flex; align-items: center; gap: 10px; }}
  .dot {{ width: 14px; height: 3px; display: inline-block; border-radius: 2px; }}
  .dot-mean   {{ background: #e377c2; }}
  .dot-median {{ background: #17becf; border-top: 2px dashed #17becf; height: 0; }}
</style>

<div id="ma-controls">
  <div class="ma-group">
    <span class="dot dot-mean"></span>
    <label><input type="checkbox" id="meanVisible" checked> Mean MA</label>
    <input type="number" id="meanWindow" value="200" min="2" max="2000" step="10">
    <span style="color:#888">days</span>
  </div>
  <div class="ma-group">
    <span class="dot dot-median"></span>
    <label><input type="checkbox" id="medianVisible" checked> Median MA</label>
    <input type="number" id="medianWindow" value="200" min="2" max="2000" step="10">
    <span style="color:#888">days</span>
  </div>
  <button onclick="updateMA()" style="padding:4px 14px;cursor:pointer;border-radius:4px;border:1px solid #aaa;">Apply</button>
</div>
"""

    script = f"""
<script>
const peDates  = {dates_json};
const peValues = {values_json};
const meanIdx   = {mean_idx};
const medianIdx = {median_idx};
const gd = document.getElementById('peChart');

function rollingMean(arr, w) {{
  return arr.map((_, i) => {{
    if (i < w - 1) return null;
    let s = 0;
    for (let j = i - w + 1; j <= i; j++) s += arr[j];
    return s / w;
  }});
}}

function rollingMedian(arr, w) {{
  return arr.map((_, i) => {{
    if (i < w - 1) return null;
    const slice = arr.slice(i - w + 1, i + 1).slice().sort((a, b) => a - b);
    const mid = Math.floor(slice.length / 2);
    return slice.length % 2 === 0 ? (slice[mid - 1] + slice[mid]) / 2 : slice[mid];
  }});
}}

function updateMA() {{
  const mw = parseInt(document.getElementById('meanWindow').value)   || 200;
  const dw = parseInt(document.getElementById('medianWindow').value) || 200;
  const mVisible = document.getElementById('meanVisible').checked;
  const dVisible = document.getElementById('medianVisible').checked;

  const meanY   = rollingMean(peValues, mw);
  const medianY = rollingMedian(peValues, dw);

  // Update label in legend
  const mLabel = 'Mean MA(' + mw + ')';
  const dLabel = 'Median MA(' + dw + ')';

  Plotly.restyle(gd,
    {{ y: [meanY],   name: [mLabel],  visible: [mVisible  ? true : 'legendonly'] }},
    [meanIdx]
  );
  Plotly.restyle(gd,
    {{ y: [medianY], name: [dLabel],  visible: [dVisible  ? true : 'legendonly'] }},
    [medianIdx]
  );
}}

// Also wire up checkboxes for instant toggle (no recompute needed)
document.getElementById('meanVisible').addEventListener('change', function() {{
  Plotly.restyle(gd, {{ visible: [this.checked ? true : 'legendonly'] }}, [meanIdx]);
}});
document.getElementById('medianVisible').addEventListener('change', function() {{
  Plotly.restyle(gd, {{ visible: [this.checked ? true : 'legendonly'] }}, [medianIdx]);
}});

// Apply on Enter key in inputs
['meanWindow','medianWindow'].forEach(id => {{
  document.getElementById(id).addEventListener('keydown', e => {{
    if (e.key === 'Enter') updateMA();
  }});
}});
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
    fig, pe_dates, pe_values = pe_chart(index=idx, bands=True)
    path = f"pe_{idx}.html"
    save_chart(fig, pe_dates, pe_values, path)
    os.startfile(path)
