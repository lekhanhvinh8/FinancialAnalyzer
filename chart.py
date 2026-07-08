"""
VN30 / VN Diamond Aggregate P/E chart module.

Usage:
    from chart import pe_chart
    fig = pe_chart()                        # VN30, full history, with index price
    fig = pe_chart(index="vndiamond")       # VN Diamond
    fig.show()                              # open in browser
    fig.write_html("pe.html")              # save as HTML

    # or with options:
    fig = pe_chart(start="2018-01-01", bands=True, min_members=5)
"""

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

# vnstock symbol for each index price
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


def pe_chart(
    index: str = "vn30",
    start: str | None = None,
    end: str | None = None,
    min_members: int = 5,
    bands: bool = True,
    title: str | None = None,
) -> go.Figure:
    """
    Build an interactive Plotly figure of aggregate P/E + index price over time.

    Parameters
    ----------
    index       : "vn30" or "vndiamond"
    start       : ISO date string, e.g. "2018-01-01"
    end         : ISO date string, e.g. "2026-07-06"
    min_members : minimum members contributing for a date to be included (default 5)
    bands       : draw percentile bands (cheap / fair / expensive) if True
    title       : chart title (auto-generated if None)

    Returns
    -------
    plotly.graph_objects.Figure
    """
    index = index.lower()
    label = _INDEX_LABELS.get(index, index.upper())
    if title is None:
        title = f"{label} — Aggregate P/E & Index Price"

    df = load_pe(index, start, end, min_members)
    if df.empty:
        raise ValueError("No P/E data in the requested range.")

    pe = df["pe_ratio"]
    current = pe.iloc[-1]
    current_date = df["date"].iloc[-1].strftime("%Y-%m-%d")
    date_start_str = df["date"].iloc[0].strftime("%Y-%m-%d")

    pct25 = pe.quantile(0.25)
    pct50 = pe.quantile(0.50)
    pct75 = pe.quantile(0.75)

    # Fetch index price for same date range
    idx_price = _fetch_index_price(index, date_start_str, current_date)

    fig = go.Figure()

    # ── Percentile bands (on P/E axis = y1) ──────────────────────────────────
    if bands:
        x_fill = [df["date"].iloc[0], df["date"].iloc[-1]]

        def _band(lo, hi, color, name):
            fig.add_trace(go.Scatter(
                x=x_fill + x_fill[::-1],
                y=[lo, lo, hi, hi],
                fill="toself",
                fillcolor=color,
                line=dict(width=0),
                mode="lines",
                name=name,
                hoverinfo="skip",
                showlegend=True,
                yaxis="y1",
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
                annotation_text=lbl,
                annotation_position="top right",
                annotation_font_size=11,
            )

    # ── Index price line (y2, right axis) ────────────────────────────────────
    if idx_price is not None and not idx_price.empty:
        fig.add_trace(go.Scatter(
            x=idx_price.index,
            y=idx_price.values,
            mode="lines",
            name=f"{label} Index",
            line=dict(color="rgba(150,150,150,0.5)", width=1.2),
            yaxis="y2",
            hovertemplate=(
                "<b>%{x|%Y-%m-%d}</b><br>"
                f"{label}: %{{y:,.0f}} pts<extra></extra>"
            ),
        ))

    # ── P/E line (y1, left axis) ─────────────────────────────────────────────
    fig.add_trace(go.Scatter(
        x=df["date"],
        y=df["pe_ratio"],
        mode="lines",
        name="Aggregate P/E",
        line=dict(color="#1f77b4", width=1.8),
        yaxis="y1",
        hovertemplate=(
            "<b>%{x|%Y-%m-%d}</b><br>"
            "P/E: %{y:.2f}x<br>"
            "Members: %{customdata}<extra></extra>"
        ),
        customdata=df["member_count"],
    ))

    # ── Current value marker ──────────────────────────────────────────────────
    fig.add_trace(go.Scatter(
        x=[df["date"].iloc[-1]],
        y=[current],
        mode="markers+text",
        marker=dict(size=8, color="#ff7f0e"),
        text=[f"  {current:.2f}x"],
        textposition="middle right",
        name=f"Current P/E ({current_date})",
        yaxis="y1",
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
            title="P/E (x)",
            showgrid=True,
            gridcolor="rgba(200,200,200,0.3)",
            side="left",
        ),
        yaxis2=dict(
            title=f"{label} Index (pts)",
            overlaying="y",
            side="right",
            showgrid=False,
            tickformat=",",
        ),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        plot_bgcolor="white",
        paper_bgcolor="white",
        margin=dict(l=60, r=80, t=80, b=60),
    )

    return fig


if __name__ == "__main__":
    import sys
    idx = sys.argv[1] if len(sys.argv) > 1 else "vn30"
    fig = pe_chart(index=idx, bands=True)
    fig.show()
