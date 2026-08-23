"""
One interactive chart per symbol, built to match single/median1000's backtest
chart.

WHAT THE REFERENCE CHART ACTUALLY IS

  Reading export/chart.py is not enough to reproduce it — the first two attempts
  here were written that way and both came out wrong. Parsing the Plotly JSON
  and the surrounding markup out of a real vn30_backtest.html shows three parts:

    1. A DUAL-AXIS FIGURE.  P/E on the left on a LOG scale, price on the right,
       linear. Each side carries rolling 25th / median / 75th as dotted lines,
       a rolling mean, and the series itself. Trade markers sit on a hidden
       third axis at a fixed height.

    2. A CONTROL PANEL.  Every line group has a Show checkbox and its own
       WINDOW input, and each line has an optional +/- offset band. Changing a
       window does not reload anything: the raw series are embedded and the
       rolling statistics are recomputed in the browser.

    3. SIGNAL SLIDERS.  Trend-signal windows, with coloured strips under the
       chart.

  Part 3 is dropped here. Those signals are inputs to the single-symbol
  strategy's gates; this method has none, and a control that changed nothing
  would be worse than its absence.

WHAT IS HERE THAT THE REFERENCE HAS NOT

  The buy threshold, median x (1 + premium/100), drawn as a line AND used to
  colour the price line — slate before warmup, green where the rule would buy,
  grey where it would not. The reference colours its price line by P/E zone,
  which is the right choice for a chart about P/E and the wrong one here: this
  rule reads price against its own median and never looks at P/E.

  The threshold input is live. Move it and the boundary and the colouring
  follow, so "what would a stricter rule have bought" is a question the chart
  answers directly.

  THE MARKERS DO NOT MOVE. They are what the backtest actually did, at the
  window and threshold in config.py. Changing the controls re-draws the
  reference lines only, so a mismatch between markers and green is either a
  changed control or a bug — the chart states which window it ran at so the two
  cannot be confused.
"""

import json
from pathlib import Path

import plotly.graph_objects as go

# Copied from the reference chart rather than chosen.
_Q_COLORS = {"p25": "rgba(46,160,67,0.9)",
             "median": "rgba(100,100,200,0.9)",
             "p75": "rgba(220,53,69,0.9)"}
_MEAN_COLOR = "rgba(150,0,200,0.8)"
_PE_LINE = "#1f77b4"

_EVENT_STYLE = {
    "buy":      ("Mua",        "rgba(34,197,94,0.75)",  "#15803d", "triangle-up",   9),
    "sell":     ("Bán",        "rgba(239,68,68,0.75)",  "#991b1b", "triangle-down", 9),
    "reinvest": ("Tái đầu tư", "rgba(249,115,22,0.75)", "#c2410c", "diamond",       8),
}

# Trace order is FIXED so the browser can restyle by index. Every one of these
# is emitted even when empty; markers are appended after.
_T_PE25, _T_PEMED, _T_PE75, _T_PEMEAN, _T_PELINE = 0, 1, 2, 3, 4
_T_P25, _T_PMED, _T_P75, _T_PMEAN, _T_LIMIT = 5, 6, 7, 8, 9
_T_WARM, _T_BUY, _T_NO = 10, 11, 12
_N_FIXED = 13


def build_symbol_chart(symbol: str, series, position, window: int,
                       max_premium: float, out_dir: Path) -> Path:
    n = len(series)
    lo = series.warmup
    dates = [str(d.date()) for d in series.dates]
    prices = [series.close(i) for i in range(n)]
    pes = [series.pe(i) for i in range(n)]
    has_pe = any(v is not None for v in pes)

    def stat(fn, i):
        return fn(window, i) if i >= lo else None

    med = [stat(series.median, i) for i in range(n)]
    limit = [(m * (1 + max_premium / 100) if m else None) for m in med]
    state = ["warmup" if (i < lo or med[i] is None)
             else ("buy" if prices[i] < limit[i] else "no") for i in range(n)]

    fig = go.Figure()

    def dotted(name, y, color, axis, width=1, dash="dot", tmpl="%{y:,.0f}"):
        fig.add_trace(go.Scatter(
            x=dates, y=y, mode="lines", name=name, yaxis=axis,
            line=dict(color=color, width=width, dash=dash),
            hovertemplate=f"{name}: {tmpl}<extra></extra>"))

    # ── y1: P/E ──────────────────────────────────────────────────────────────
    for attr, label, key in (("pe_p25", "P/E 25th", "p25"),
                             ("pe_median", "P/E Median", "median"),
                             ("pe_p75", "P/E 75th", "p75")):
        dotted(f"{label} ({window}d)",
               [series.pe_stat(attr, window, i) if i >= lo else None for i in range(n)],
               _Q_COLORS[key], "y", tmpl="%{y:.2f}x")
    dotted(f"P/E Mean ({window}d)",
           [series.pe_stat("pe_mean", window, i) if i >= lo else None for i in range(n)],
           _MEAN_COLOR, "y", width=1.5, tmpl="%{y:.2f}x")
    fig.add_trace(go.Scatter(
        x=dates, y=pes if has_pe else [None] * n, mode="lines",
        name=f"{symbol} P/E", yaxis="y", visible=True if has_pe else "legendonly",
        line=dict(color=_PE_LINE, width=1.8),
        hovertemplate="P/E: %{y:.2f}x<extra></extra>"))

    # ── y2: price ────────────────────────────────────────────────────────────
    for attr, label in (("p25", "Giá 25th"), ("median", "Giá Median"),
                        ("p75", "Giá 75th")):
        g = getattr(series, attr)
        dotted(f"{label} ({window}d)", [stat(g, i) for i in range(n)],
               _Q_COLORS[attr], "y2")
    dotted(f"Giá Mean ({window}d)", [stat(series.mean, i) for i in range(n)],
           _MEAN_COLOR, "y2", width=1.5)
    fig.add_trace(go.Scatter(
        x=dates, y=limit, mode="lines", yaxis="y2",
        name=f"Ngưỡng mua (median {max_premium:+g}%)",
        line=dict(color="rgba(37,99,235,0.5)", width=1.4),
        hovertemplate="Ngưỡng: %{y:,.0f}<extra></extra>"))

    for key, label, color in (("warmup", "Chưa đánh giá", "#475569"),
                              ("buy", "Đủ điều kiện mua", "#2ca02c"),
                              ("no", "Không đủ điều kiện", "#a0aec0")):
        fig.add_trace(go.Scatter(
            x=dates, y=_segments(state, prices, key), mode="lines",
            name=label, yaxis="y2", connectgaps=False,
            line=dict(color=color, width=1.5),
            hovertemplate="Giá: %{y:,.0f}<extra></extra>"))

    # ── y3: markers ──────────────────────────────────────────────────────────
    by_kind: dict = {}
    for t in (position.trades if position else []):
        by_kind.setdefault(t.kind, []).append(t)
    for kind in ("buy", "sell", "reinvest"):
        trades = by_kind.get(kind)
        if not trades:
            continue
        label, fill, border, marker, size = _EVENT_STYLE[kind]
        fig.add_trace(go.Scatter(
            x=[str(t.date)[:10] for t in trades], y=[0.75] * len(trades),
            mode="markers", name=f"{label} ({len(trades)})", yaxis="y3",
            marker=dict(color=fill, size=size, symbol=marker,
                        line=dict(color=border, width=1)),
            customdata=[[t.price, t.amount, t.shares] for t in trades],
            hovertemplate=(f"<b>{label}</b>  %{{x}}<br>Giá: %{{customdata[0]:,.0f}}<br>"
                           "Tiền: %{customdata[1]:,.0f}<br>"
                           "Cổ phiếu: %{customdata[2]:,.1f}<extra></extra>")))

    sub = f"{len(by_kind.get('buy', []))} lệnh mua"
    for kind, word in (("sell", "lệnh bán"), ("reinvest", "tái đầu tư")):
        if by_kind.get(kind):
            sub += f" · {len(by_kind[kind])} {word}"
    if position and position.shares > 0:
        sub += (f" · giữ {position.shares:,.0f} cp · vốn gốc {position.basis:,.0f}đ"
                f" · giá trị {position.shares * prices[-1]:,.0f}đ")

    fig.update_layout(
        hovermode="x unified", plot_bgcolor="white", paper_bgcolor="white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left",
                    x=0, font=dict(size=11)),
        margin=dict(l=60, r=80, t=60, b=60),
        xaxis=dict(title=dict(text="Date"), showgrid=True,
                   gridcolor="rgba(200,200,200,0.3)", hoverformat="%Y-%m-%d"),
        yaxis=dict(title=dict(text="P/E (x, log)"), type="log", showgrid=True,
                   gridcolor="rgba(200,200,200,0.3)", side="left"),
        yaxis2=dict(title=dict(text=f"{symbol} (VND)"), overlaying="y",
                    side="right", showgrid=False, tickformat=","),
        # Markers live here. Range is far taller than the marker height so they
        # sit near the bottom; hidden because a marker's y carries no meaning.
        yaxis3=dict(overlaying="y", side="left", range=[0, 6], visible=False,
                    fixedrange=True),
    )

    plot = fig.to_html(include_plotlyjs="cdn", full_html=False, div_id="chart",
                       config={"responsive": True, "displaylogo": False})

    payload = json.dumps({
        "dates": dates, "prices": prices, "pes": pes,
        "warmupWindow": window, "premium": max_premium,
        "idx": {"pe25": _T_PE25, "peMed": _T_PEMED, "pe75": _T_PE75,
                "peMean": _T_PEMEAN, "peLine": _T_PELINE,
                "p25": _T_P25, "pMed": _T_PMED, "p75": _T_P75,
                "pMean": _T_PMEAN, "limit": _T_LIMIT,
                "warm": _T_WARM, "buy": _T_BUY, "no": _T_NO},
    }, separators=(",", ":"))

    html = _PAGE.replace("__SYMBOL__", symbol)
    html = html.replace("__SUB__", sub)
    html = html.replace("__SPAN__", f"{dates[0][:4]} — {dates[-1][:4]}")
    html = html.replace("__WINDOW__", str(window))
    html = html.replace("__PREMIUM__", f"{max_premium:g}")
    html = html.replace("__PLOT__", plot)
    html = html.replace("__DATA__", payload)

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{symbol.lower()}.html"
    path.write_text(html, encoding="utf-8")
    return path


def _segments(states, values, want):
    """
    `values` where `states` is `want`, None elsewhere. A point next to a
    matching one is kept so consecutive colours join instead of leaving a
    one-bar gap at every boundary.
    """
    n = len(values)
    out = []
    for i in range(n):
        if states[i] == want:
            out.append(values[i])
        else:
            near = ((i > 0 and states[i - 1] == want)
                    or (i < n - 1 and states[i + 1] == want))
            out.append(values[i] if near else None)
    return out


def build_all(result, market, config, out_dir: Path) -> dict:
    """One chart per symbol the portfolio traded. Returns {symbol: filename}."""
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


_PAGE = """<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__SYMBOL__ — backtest danh mục</title>
<style>
 body{margin:16px;font-family:system-ui,-apple-system,"Segoe UI",sans-serif;
      background:#fff;color:#111}
 h1{font-size:19px;margin:0 0 2px}
 h1 sup{color:#777;font-weight:400;font-size:12px}
 .sub{color:#64748b;font-size:12.5px;margin:0 0 10px}
 #ctrl{display:flex;flex-wrap:wrap;align-items:center;gap:8px;font-size:12.5px;
       background:#f7f8fa;border:1px solid #e2e6ec;border-radius:6px;
       padding:9px 12px;margin-bottom:8px}
 .section-label{font-weight:600;color:#475569;white-space:nowrap}
 .ma-group{display:flex;align-items:center;gap:4px}
 .chk{display:inline-flex;align-items:center;gap:4px;white-space:nowrap;cursor:pointer}
 .dot{display:inline-block;width:9px;height:9px;border-radius:50%}
 input[type=number]{width:62px;font-size:12.5px;text-align:center;
   border:1px solid #cbd5e1;border-radius:4px;padding:2px 4px}
 .unit{color:#94a3b8}
 .divider{width:1px;height:20px;background:#dbe1e9;margin:0 3px}
 button{font-size:12.5px;padding:4px 12px;border:1px solid #2563eb;background:#2563eb;
   color:#fff;border-radius:5px;cursor:pointer}
 button:hover{background:#1d4ed8}
 button.ghost{background:#fff;color:#2563eb}
 #chart{height:calc(100vh - 210px);min-height:420px;width:100%}
 .warn{font-size:12px;color:#92400e;background:#fef3c7;border:1px solid #fde68a;
   border-radius:5px;padding:5px 10px;margin-bottom:8px;display:none}
 .warn.show{display:block}
</style></head><body>

<h1>__SYMBOL__ — Giá &amp; P/E <sup>__SPAN__</sup></h1>
<p class="sub">__SUB__</p>

<div class="warn" id="warn">Các đường tham chiếu đang vẽ ở thông số khác lúc chạy
 backtest (cửa sổ __WINDOW__d, ngưỡng __PREMIUM__%). Marker vẫn là giao dịch thật
 và không đổi.</div>

<div id="ctrl">
  <span class="section-label">Giá — Percentiles</span>
  <div class="ma-group">
    <label class="chk"><input type="checkbox" id="prPctVis" checked> Hiện</label>
    <input type="number" id="prPctW" value="__WINDOW__" min="20" max="5000" step="50"
           title="Cửa sổ (phiên)"><span class="unit">d</span>
  </div>
  <label class="chk"><input type="checkbox" class="pr-cb" data-i="p25">
    <span class="dot" style="background:rgba(46,160,67,0.9)"></span>25th</label>
  <label class="chk"><input type="checkbox" class="pr-cb" data-i="pMed" checked>
    <span class="dot" style="background:rgba(100,100,200,0.9)"></span>Med</label>
  <label class="chk"><input type="checkbox" class="pr-cb" data-i="p75">
    <span class="dot" style="background:rgba(220,53,69,0.9)"></span>75th</label>

  <div class="divider"></div>
  <span class="section-label">Giá — Mean</span>
  <div class="ma-group">
    <label class="chk"><input type="checkbox" id="prMeanVis"> Hiện</label>
    <input type="number" id="prMeanW" value="__WINDOW__" min="5" max="5000" step="10"
           title="Cửa sổ (phiên)"><span class="unit">d</span>
  </div>

  <div class="divider"></div>
  <span class="section-label">Ngưỡng mua</span>
  <div class="ma-group">
    <label class="chk"><input type="checkbox" id="limVis" checked> Hiện</label>
    <span class="unit">median</span>
    <input type="number" id="limPct" value="__PREMIUM__" min="-90" max="500" step="5"
           title="% so với median"><span class="unit">%</span>
  </div>

  <div class="divider"></div>
  <span class="section-label">P/E</span>
  <div class="ma-group">
    <label class="chk"><input type="checkbox" id="peLineVis"> Đường</label>
    <label class="chk"><input type="checkbox" id="pePctVis"> Percentiles</label>
    <label class="chk"><input type="checkbox" id="peMeanVis"> Mean</label>
    <input type="number" id="peW" value="__WINDOW__" min="20" max="5000" step="50"
           title="Cửa sổ (phiên)"><span class="unit">d</span>
  </div>

  <div class="divider"></div>
  <button onclick="applyAll()">Áp dụng</button>
  <button class="ghost" onclick="resetAll()">Về mặc định</button>
</div>

__PLOT__

<script>
var D = __DATA__;
var GD = document.getElementById('chart');

function rollingQuantile(a, w, q) {
  var out = new Array(a.length).fill(null);
  for (var i = w - 1; i < a.length; i++) {
    var win = [];
    for (var j = i - w + 1; j <= i; j++) if (a[j] != null) win.push(a[j]);
    if (win.length < w) continue;
    win.sort(function (x, y) { return x - y; });
    var pos = (win.length - 1) * q, lo = Math.floor(pos), hi = Math.ceil(pos);
    out[i] = win[lo] + (win[hi] - win[lo]) * (pos - lo);
  }
  return out;
}

function rollingMean(a, w) {
  var out = new Array(a.length).fill(null), sum = 0, cnt = 0;
  for (var i = 0; i < a.length; i++) {
    if (a[i] != null) { sum += a[i]; cnt++; }
    if (i >= w) { if (a[i - w] != null) { sum -= a[i - w]; cnt--; } }
    if (i >= w - 1 && cnt === w) out[i] = sum / cnt;
  }
  return out;
}

function segments(state, vals, want) {
  var out = [];
  for (var i = 0; i < vals.length; i++) {
    if (state[i] === want) { out.push(vals[i]); continue; }
    var near = (i > 0 && state[i-1] === want) || (i < vals.length-1 && state[i+1] === want);
    out.push(near ? vals[i] : null);
  }
  return out;
}

function applyAll() {
  var I = D.idx;
  var prW = +document.getElementById('prPctW').value;
  var mnW = +document.getElementById('prMeanW').value;
  var peW = +document.getElementById('peW').value;
  var pct = +document.getElementById('limPct').value;

  var q25 = rollingQuantile(D.prices, prW, 0.25);
  var q50 = rollingQuantile(D.prices, prW, 0.50);
  var q75 = rollingQuantile(D.prices, prW, 0.75);
  var pmean = rollingMean(D.prices, mnW);

  // The threshold and the colouring are derived from the SAME median the buy
  // rule would use at this window, so the two can never disagree on screen.
  var lim = q50.map(function (m) { return m == null ? null : m * (1 + pct / 100); });
  var state = D.prices.map(function (p, i) {
    if (lim[i] == null) return 'warmup';
    return p < lim[i] ? 'buy' : 'no';
  });

  var upd = {};
  upd[I.p25] = q25; upd[I.pMed] = q50; upd[I.p75] = q75;
  upd[I.pMean] = pmean; upd[I.limit] = lim;
  upd[I.warm] = segments(state, D.prices, 'warmup');
  upd[I.buy]  = segments(state, D.prices, 'buy');
  upd[I.no]   = segments(state, D.prices, 'no');

  if (D.pes.some(function (v) { return v != null; })) {
    upd[I.pe25]   = rollingQuantile(D.pes, peW, 0.25);
    upd[I.peMed]  = rollingQuantile(D.pes, peW, 0.50);
    upd[I.pe75]   = rollingQuantile(D.pes, peW, 0.75);
    upd[I.peMean] = rollingMean(D.pes, peW);
  }

  var idxs = Object.keys(upd).map(Number);
  Plotly.restyle(GD, {y: idxs.map(function (k) { return upd[k]; })}, idxs);

  var names = {};
  names[I.p25] = 'Giá 25th (' + prW + 'd)';
  names[I.pMed] = 'Giá Median (' + prW + 'd)';
  names[I.p75] = 'Giá 75th (' + prW + 'd)';
  names[I.pMean] = 'Giá Mean (' + mnW + 'd)';
  names[I.limit] = 'Ngưỡng mua (median ' + (pct >= 0 ? '+' : '') + pct + '%)';
  names[I.pe25] = 'P/E 25th (' + peW + 'd)';
  names[I.peMed] = 'P/E Median (' + peW + 'd)';
  names[I.pe75] = 'P/E 75th (' + peW + 'd)';
  names[I.peMean] = 'P/E Mean (' + peW + 'd)';
  var nk = Object.keys(names).map(Number);
  Plotly.restyle(GD, {name: nk.map(function (k) { return names[k]; })}, nk);

  applyVisibility();
  document.getElementById('warn').classList.toggle(
    'show', prW !== D.warmupWindow || pct !== D.premium);
}

function applyVisibility() {
  var I = D.idx;
  var prPct = document.getElementById('prPctVis').checked;
  var vis = {};
  document.querySelectorAll('.pr-cb').forEach(function (cb) {
    vis[I[cb.dataset.i]] = (prPct && cb.checked) ? true : 'legendonly';
  });
  vis[I.pMean] = document.getElementById('prMeanVis').checked ? true : 'legendonly';
  vis[I.limit] = document.getElementById('limVis').checked ? true : 'legendonly';
  vis[I.peLine] = document.getElementById('peLineVis').checked ? true : 'legendonly';
  var pePct = document.getElementById('pePctVis').checked;
  [I.pe25, I.peMed, I.pe75].forEach(function (k) { vis[k] = pePct ? true : 'legendonly'; });
  vis[I.peMean] = document.getElementById('peMeanVis').checked ? true : 'legendonly';

  var ks = Object.keys(vis).map(Number);
  Plotly.restyle(GD, {visible: ks.map(function (k) { return vis[k]; })}, ks);
}

function resetAll() {
  document.getElementById('prPctW').value = D.warmupWindow;
  document.getElementById('prMeanW').value = D.warmupWindow;
  document.getElementById('peW').value = D.warmupWindow;
  document.getElementById('limPct').value = D.premium;
  document.getElementById('prPctVis').checked = true;
  document.getElementById('limVis').checked = true;
  document.getElementById('prMeanVis').checked = false;
  document.getElementById('peLineVis').checked = false;
  document.getElementById('pePctVis').checked = false;
  document.getElementById('peMeanVis').checked = false;
  document.querySelectorAll('.pr-cb').forEach(function (cb) {
    cb.checked = cb.dataset.i === 'pMed';
  });
  applyAll();
}

document.querySelectorAll('#ctrl input[type=checkbox]').forEach(function (cb) {
  cb.addEventListener('change', applyVisibility);
});
document.querySelectorAll('#ctrl input[type=number]').forEach(function (inp) {
  inp.addEventListener('keydown', function (e) { if (e.key === 'Enter') applyAll(); });
});
// Start from the run's own settings, with the reference lines drawn at the
// window the backtest actually used.
resetAll();
</script>
</body></html>
"""
