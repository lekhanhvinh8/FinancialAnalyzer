"""Report for one breadth run: summary, equity curve, signals, trades."""

import json
from datetime import datetime
from html import escape
from pathlib import Path

KIND = {"buy": ("Mua", "#22c55e"), "reinvest": ("Tái đầu tư", "#f97316"),
        "sell": ("Bán", "#ef4444")}


def _line(points, x0, y0, w, h, ymin, ymax):
    if not points or ymax == ymin:
        return ""
    n = len(points) - 1 or 1
    return " ".join(
        f"{x0 + i / n * w:.1f},{y0 + h - (v - ymin) / (ymax - ymin) * h:.1f}"
        for i, v in enumerate(points))


def _curve_svg(plan_curve, base_curve, trades, dates):
    """Equity of both plans, the money paid in, and the trades marked on it."""
    if not plan_curve:
        return "<p class='muted'>không có dữ liệu</p>"

    W, H, pl, pr, pt, pb = 900, 300, 74, 16, 16, 40
    w, h = W - pl - pr, H - pt - pb
    n = len(plan_curve)

    plan = [c["equity"] for c in plan_curve]
    base = [c["equity"] for c in base_curve][:n]
    paid = [c["invested"] for c in plan_curve]
    ymax = max(max(plan), max(base or [0]), max(paid)) * 1.05

    grid, step = [], 500_000_000
    while ymax / step > 8:
        step *= 2
    v = 0
    while v <= ymax:
        y = pt + h - v / ymax * h
        grid.append(f'<line x1="{pl}" y1="{y:.1f}" x2="{pl + w}" y2="{y:.1f}" class="g"/>'
                    f'<text x="{pl - 8}" y="{y + 4:.1f}" class="yt">{v / 1e9:.1f}B</text>')
        v += step

    prev = None
    for i, c in enumerate(plan_curve):
        year = c["date"][:4]
        if year != prev:
            prev = year
            x = pl + i / (n - 1) * w
            grid.append(f'<line x1="{x:.1f}" y1="{pt}" x2="{x:.1f}" y2="{pt + h}" class="g"/>'
                        f'<text x="{x:.1f}" y="{pt + h + 18}" class="xt">{year}</text>')

    # Trades sit on the plan's equity line at the DAY they happened, not the
    # month. The curve is monthly, so the x position is interpolated inside the
    # month -- rounding to the month put a buy on the 1st and a sell on the 2nd
    # at the same pixel, which reads as buying and selling at once.
    months = [c["date"][:7] for c in plan_curve]
    idx_of = {m: i for i, m in enumerate(months)}
    ys = [pt + h - c["equity"] / ymax * h for c in plan_curve]
    marks = []
    for t in trades:
        m = t["date"][:7]
        if m not in idx_of:
            continue
        i0 = idx_of[m]
        frac = (int(t["date"][8:10]) - 1) / 31.0
        i = min(i0 + frac, n - 1)
        x = pl + i / (n - 1) * w
        y = ys[min(i0, len(ys) - 1)]
        label, colour = KIND[t["kind"]]
        tip = escape(f'{label} · {t["date"]} · {t["amount"]:,.0f}đ @ {t["price"]:,.0f}')
        if t["kind"] == "sell":
            shape = (f'<polygon points="{x:.1f},{y - 3:.1f} {x - 5:.1f},{y - 11:.1f} '
                     f'{x + 5:.1f},{y - 11:.1f}" fill="{colour}"/>')
        elif t["kind"] == "reinvest":
            shape = f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.6" fill="{colour}"/>'
        else:
            shape = f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.6" fill="{colour}"/>'
        marks.append(f'<g class="mk" data-tip="{tip}">{shape}'
                     f'<circle cx="{x:.1f}" cy="{y:.1f}" r="7" fill="transparent"/></g>')

    return f'''<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">
{"".join(grid)}
<polyline class="paid" points="{_line(paid, pl, pt, w, h, 0, ymax)}"/>
<polyline class="base" points="{_line(base, pl, pt, w, h, 0, ymax)}"/>
<polyline class="plan" points="{_line(plan, pl, pt, w, h, 0, ymax)}"/>
{"".join(marks)}
</svg>'''


def _signal_svg(curve, key, label, lines=()):
    """One breadth signal over time, with the thresholds that read it."""
    vals = [c.get(key) for c in curve]
    vals = [v if v is not None else 0.0 for v in vals]
    if not vals:
        return ""
    W, H, pl, pr, pt, pb = 900, 130, 74, 16, 12, 26
    w, h = W - pl - pr, H - pt - pb
    lo, hi = min(vals + list(lines)), max(vals + list(lines))
    pad = (hi - lo) * 0.08 or 0.01
    lo, hi = lo - pad, hi + pad

    rules = "".join(
        f'<line x1="{pl}" y1="{pt + h - (t - lo) / (hi - lo) * h:.1f}" '
        f'x2="{pl + w}" y2="{pt + h - (t - lo) / (hi - lo) * h:.1f}" class="thr"/>'
        f'<text x="{pl + w + 2}" y="{pt + h - (t - lo) / (hi - lo) * h + 3:.1f}" '
        f'class="yt" style="text-anchor:start">{t:g}</text>' for t in lines)

    return f'''<div class="sig"><h3>{escape(label)}</h3>
<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">
<text x="{pl - 8}" y="{pt + 10}" class="yt">{hi:.2f}</text>
<text x="{pl - 8}" y="{pt + h}" class="yt">{lo:.2f}</text>
{rules}
<polyline class="sigline" points="{_line(vals, pl, pt, w, h, lo, hi)}"/>
</svg></div>'''


def build(result, bench, plan, config, breadth, path: Path, chart_name="",
          bench_name="DCA") -> Path:
    curve = result.get("curve", [])
    trades = [{"date": str(t.date)[:10], "kind": t.kind, "price": t.price,
               "amount": t.amount, "shares": t.shares}
              for t in result["wallet"].position(config.SYMBOL).trades]
    counts = {k: sum(1 for t in trades if t["kind"] == k) for k in KIND}

    diff = result["growth_%"] - bench["growth_%"]
    rows = [
        ("Tăng trưởng", f'{result["growth_%"]:.2f}%', f'{bench["growth_%"]:.2f}%'),
        ("Vốn đã nạp", f'{result["invested"]:,.0f}', f'{bench["invested"]:,.0f}'),
        ("Giá trị cuối", f'{result["value"]:,.0f}', f'{bench["value"]:,.0f}'),
        ("· cổ phiếu", f'{result["holdings"]:,.0f}', f'{bench["holdings"]:,.0f}'),
        ("· reserve", f'{result["reserve"]:,.0f}', f'{bench["reserve"]:,.0f}'),
        ("· lãi tiền gửi", f'{result["interest"]:,.0f}', f'{bench["interest"]:,.0f}'),
        ("Số tháng", f'{result["months"]}', f'{bench["months"]}'),
        ("Mua", f'{counts["buy"]}', f'{bench["buys"]}'),
        ("Tái đầu tư", f'{counts["reinvest"]}', f'{bench.get("reinvests", 0)}'),
        ("Bán", f'{counts["sell"]}', f'{bench["sells"]}'),
    ]
    body = "".join(f'<tr><td>{a}</td><td class="n">{b}</td><td class="n">{c}</td></tr>'
                   for a, b, c in rows)

    log = "".join(
        f'<tr><td class="mono">{t["date"]}</td>'
        f'<td><span class="k" style="background:{KIND[t["kind"]][1]}"></span>'
        f'{KIND[t["kind"]][0]}</td>'
        f'<td class="n">{t["price"]:,.0f}</td><td class="n">{t["amount"]:,.0f}</td>'
        f'<td class="n">{t["shares"]:,.1f}</td></tr>'
        for t in trades)

    sigs = (_signal_svg(curve, "below_pct", "below_pct — tỷ lệ rổ dưới median",
                        (config.BUY_STRONG_BELOW_PCT, config.BUY_NORMAL_BELOW_PCT))
            + _signal_svg(curve, "n", "n — số mã sau mỗi số liệu",
                          (config.MIN_SYMBOLS,)))

    link = (f'<a class="open" href="{chart_name}" target="_blank">mở biểu đồ '
            f'{config.SYMBOL} →</a>' if chart_name else "")

    html = f'''<!doctype html>
<html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(plan.name)} — báo cáo breadth</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>{_CSS}</style></head><body><div id="tip"></div><div class="wrap">
<h1>{escape(plan.name)}</h1>
<p class="sub">{escape(config.SYMBOL)} &middot; {len(curve)} tháng &middot;
dựng {datetime.now():%Y-%m-%d %H:%M} &middot; {link}</p>

<div class="card"><pre class="plan">{escape(plan.describe())}</pre></div>

<div class="card">
<table><thead><tr><th></th><th>{escape(plan.name)}</th><th>{escape(bench_name)}</th></tr></thead>
<tbody>{body}</tbody></table>
<p class="note {"pos" if diff >= 0 else "neg"}">Chênh lệch: {diff:+.2f}%</p>
</div>

<div class="card"><h2>Vốn theo thời gian</h2>{_curve_svg(curve, bench.get("curve", []), trades, [])}
<div class="key"><span><i class="plan"></i>kế hoạch</span><span><i class="base"></i>DCA</span>
<span><i class="paid"></i>tiền đã nạp</span>
<span><i style="background:#22c55e;border-radius:50%"></i>mua</span>
<span><i style="background:#f97316;border-radius:50%"></i>tái đầu tư</span>
<span><i style="background:#ef4444"></i>bán</span></div></div>

<div class="card"><h2>Tín hiệu</h2>{sigs}</div>

<div class="card"><h2>Lệnh ({len(trades)})</h2>
<table><thead><tr><th>Ngày</th><th>Loại</th><th>Giá</th><th>Tiền</th><th>CP</th></tr></thead>
<tbody>{log}</tbody></table></div>
</div>
<script>
var tip=document.getElementById('tip');
document.querySelectorAll('.mk').forEach(function(g){{
  g.addEventListener('mouseenter',function(e){{
    tip.textContent=g.dataset.tip;tip.style.display='block';
    tip.style.left=Math.min(e.clientX+14,innerWidth-tip.offsetWidth-12)+'px';
    tip.style.top=(e.clientY+14)+'px';}});
  g.addEventListener('mouseleave',function(){{tip.style.display='none';}});
}});
</script></body></html>'''
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return path


_CSS = """
:root{--ground:#F4F6FA;--surface:#FFF;--line:#D3DBE7;--ink:#14202F;--ink2:#46566C;
--ink3:#74839A;--accent:#1F4FD8;--base:#8A94A6;--paid:#A65A00;--pos:#1C6B4B;--neg:#B03030}
@media (prefers-color-scheme:dark){:root{--ground:#0E141C;--surface:#151D28;--line:#2B3949;
--ink:#E4EBF4;--ink2:#A3B2C6;--ink3:#7386A0;--accent:#6E9BFF;--base:#7386A0;--paid:#E0A050;
--pos:#5FCC9C;--neg:#F0857D}}
*{box-sizing:border-box}
body{background:var(--ground);color:var(--ink);margin:0;padding:28px 20px 60px;
font:15px/1.6 "IBM Plex Sans",system-ui,sans-serif}
.wrap{max-width:960px;margin:0 auto}
h1{font-size:21px;margin:0 0 4px}
h2{font-size:15px;margin:0 0 10px;color:var(--ink2);font-weight:600}
h3{font-size:12.5px;margin:0 0 2px;color:var(--ink3);font-weight:500;
font-family:"IBM Plex Mono",monospace}
.sub{color:var(--ink2);font-size:13px;margin:0 0 16px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:10px;
padding:14px 16px;margin-bottom:14px}
pre.plan{margin:0;font:12.5px/1.6 "IBM Plex Mono",monospace;color:var(--ink2);
white-space:pre-wrap}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th{text-align:right;color:var(--ink3);font-weight:500;font-size:12px;
border-bottom:1px solid var(--line);padding:4px 6px}
th:first-child{text-align:left}
td{padding:3px 6px;border-bottom:1px solid var(--line)}
td.n{text-align:right;font-family:"IBM Plex Mono",monospace}
td.mono{font-family:"IBM Plex Mono",monospace;font-size:12.5px}
.k{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}
svg{display:block;width:100%;height:auto}
.g{stroke:var(--line);opacity:.5}
.yt{fill:var(--ink3);font:500 10px "IBM Plex Mono",monospace;text-anchor:end}
.xt{fill:var(--ink3);font:500 10px "IBM Plex Mono",monospace;text-anchor:middle}
.thr{stroke:var(--neg);stroke-width:1;stroke-dasharray:4 3;opacity:.6}
polyline{fill:none;stroke-width:1.6}
polyline.plan{stroke:var(--accent);stroke-width:2}
polyline.base{stroke:var(--base)}
polyline.paid{stroke:var(--paid);stroke-dasharray:5 4}
polyline.sigline{stroke:var(--accent);stroke-width:1.3}
.sig{margin-bottom:10px}
.key{display:flex;gap:16px;flex-wrap:wrap;font-size:12.5px;color:var(--ink2);padding-top:8px}
.key i{display:inline-block;width:10px;height:10px;margin-right:5px;vertical-align:-1px}
.key i.plan{background:var(--accent)}.key i.base{background:var(--base)}
.key i.paid{background:var(--paid)}
.mk{cursor:pointer}
.note{margin:10px 0 0;font-size:13.5px;font-weight:600}
.pos{color:var(--pos)}.neg{color:var(--neg)}
a.open{color:var(--accent);text-decoration:none}
#tip{position:fixed;z-index:50;display:none;background:var(--surface);color:var(--ink);
border:1px solid var(--line);border-radius:6px;padding:6px 10px;font:12.5px
"IBM Plex Mono",monospace;box-shadow:0 6px 20px rgba(0,0,0,.18);pointer-events:none}
"""
