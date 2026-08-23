"""
The HTML report for one portfolio run.

WHY IT IS NOT SHAPED LIKE single/median1000's report_all.html

  That report has one row per symbol because each symbol IS a separate
  experiment there — its own wallet, its own outcome, independent of every other
  row. Fifty-two rows are fifty-two observations, which is why it can run a sign
  test down the column and quote a median.

  Here there is one experiment. The symbols are components of a single result,
  not repetitions of it, so a per-symbol table cannot be read the same way and no
  statistic can be computed down it. What the rows can honestly say is
  ATTRIBUTION: how much of the one result each name produced.

  The attribution is exact rather than approximate. With profit measured as
  value minus basis per position, the per-symbol profits sum to the portfolio's
  total profit, so the "contribution" column adds up to the growth figure in the
  summary. That identity is what makes the column worth printing — a
  contribution column that did not sum to the total would invite exactly the
  wrong reading.

THE EQUITY CURVE IS THE POINT

  A single end-of-period number cannot distinguish a strategy that beat the
  benchmark steadily for eleven years from one that trailed it for ten and won
  everything in the last eighteen months. Those are different claims about the
  future and the summary row shows them identically.

  Two things are plotted against each other on the same axis: the plan and the
  benchmark, both fed the same contributions on the same dates. The money paid
  in is drawn underneath, so the gap between it and either line is profit and the
  reader can see when the portfolio was actually ahead of its own cost.

NO CHART LIBRARY

  The curve is inline SVG, computed here. A local file has no CDN and an artifact
  would be blocked by its CSP, so a dependency would have to be vendored — for a
  two-series line chart that is not worth it.
"""

from datetime import datetime
from html import escape
from pathlib import Path


# ── Chart ─────────────────────────────────────────────────────────────────────

def _polyline(points, x0, y0, w, h, xmin, xmax, ymin, ymax) -> str:
    if xmax == xmin or ymax == ymin:
        return ""
    out = []
    for i, v in points:
        x = x0 + (i - xmin) / (xmax - xmin) * w
        y = y0 + h - (v - ymin) / (ymax - ymin) * h
        out.append(f"{x:.1f},{y:.1f}")
    return " ".join(out)


def _curve_svg(plan_curve, base_curve, plan_name, base_name) -> str:
    """Two equity curves plus the money paid in, on one linear axis."""
    if not plan_curve:
        return "<p class='muted'>No curve recorded.</p>"

    W, H = 900, 320
    pad_l, pad_r, pad_t, pad_b = 74, 16, 18, 34
    w, h = W - pad_l - pad_r, H - pad_t - pad_b

    n = len(plan_curve)
    xs = list(range(n))
    plan_v = [c["equity"] for c in plan_curve]
    base_v = [c["equity"] for c in base_curve][:n]
    paid_v = [c["invested"] for c in plan_curve]

    ymax = max(max(plan_v), max(base_v) if base_v else 0, max(paid_v)) * 1.04
    ymin = 0.0

    def pts(vals):
        return _polyline(list(zip(xs, vals)), pad_l, pad_t, w, h, 0, n - 1, ymin, ymax)

    # Horizontal gridlines at round billions.
    grid, step = [], 500_000_000
    while ymax / step > 8:
        step *= 2
    v = 0
    while v <= ymax:
        y = pad_t + h - (v - ymin) / (ymax - ymin) * h
        grid.append(
            f'<line x1="{pad_l}" y1="{y:.1f}" x2="{pad_l + w}" y2="{y:.1f}" class="grid"/>'
            f'<text x="{pad_l - 8}" y="{y + 4:.1f}" class="ytick">{v / 1e9:.1f}B</text>')
        v += step

    # Year labels wherever the year changes.
    xticks, prev_year = [], None
    for i, c in enumerate(plan_curve):
        year = c["date"][:4]
        if year != prev_year:
            prev_year = year
            x = pad_l + i / (n - 1) * w
            xticks.append(
                f'<line x1="{x:.1f}" y1="{pad_t}" x2="{x:.1f}" y2="{pad_t + h}" class="grid"/>'
                f'<text x="{x:.1f}" y="{pad_t + h + 20}" class="xtick">{year}</text>')

    return f"""
<div class="chartwrap">
<svg viewBox="0 0 {W} {H}" class="chart" role="img"
     aria-label="Equity of {escape(plan_name)} and {escape(base_name)} against money paid in">
  {''.join(grid)}
  {''.join(xticks)}
  <polyline points="{pts(paid_v)}" class="line-paid"/>
  <polyline points="{pts(base_v)}" class="line-base"/>
  <polyline points="{pts(plan_v)}" class="line-plan"/>
</svg>
<div class="legend">
  <span><i class="sw sw-plan"></i>{escape(plan_name)}</span>
  <span><i class="sw sw-base"></i>{escape(base_name)}</span>
  <span><i class="sw sw-paid"></i>Tiền đã nạp</span>
</div>
</div>"""


# ── Report ────────────────────────────────────────────────────────────────────

def build_report(result, baseline, plan, baseline_plan, config, market,
                 path: Path, load_seconds: float = 0.0) -> Path:
    invested = result["invested"]
    growth, base_growth = result["growth_%"], baseline["growth_%"]

    # Attribution. profit = value - basis per position, and those sum to the
    # portfolio's profit, so `share` sums to `growth`. See the module docstring.
    rows = []
    for sym, h in result["holdings"].items():
        profit = h["value"] - h["basis"]
        rows.append({
            "symbol": sym,
            "basis": h["basis"],
            "value": h["value"],
            "profit": profit,
            "return_%": (profit / h["basis"] * 100) if h["basis"] else 0.0,
            "share": (profit / invested * 100) if invested else 0.0,
            "weight_%": h["weight_%"],
            "buys": h["buys"],
            "sells": h["sells"],
        })
    rows.sort(key=lambda r: -r["share"])

    body = ""
    for r in rows:
        sign = "pos" if r["profit"] >= 0 else "neg"
        body += (
            f'<tr><td class="sym">{escape(r["symbol"])}</td>'
            f'<td class="n">{r["basis"]:,.0f}</td>'
            f'<td class="n">{r["value"]:,.0f}</td>'
            f'<td class="n {sign}">{r["profit"]:+,.0f}</td>'
            f'<td class="n {sign}">{r["return_%"]:+.1f}%</td>'
            f'<td class="n {sign}">{r["share"]:+.2f}</td>'
            f'<td class="n">{r["weight_%"]:.2f}%</td>'
            f'<td class="n">{r["buys"]}</td><td class="n">{r["sells"]}</td></tr>\n')

    winners = [r for r in rows if r["profit"] > 0]
    losers = [r for r in rows if r["profit"] < 0]
    top3 = sum(r["share"] for r in rows[:3])

    def kv(label, a, b=None, cls=""):
        bcell = f'<td class="n">{b}</td>' if b is not None else '<td></td>'
        return f'<tr><th>{label}</th><td class="n {cls}">{a}</td>{bcell}</tr>\n'

    summary = (
        kv("Tăng trưởng", f'{growth:.2f}%', f'{base_growth:.2f}%')
        + kv("Chênh lệch", f'{growth - base_growth:+.2f}%', None,
             "pos" if growth >= base_growth else "neg")
        + kv("Vốn đã nạp", f'{invested:,.0f}', f'{baseline["invested"]:,.0f}')
        + kv("Giá trị cuối", f'{result["final"]:,.0f}', f'{baseline["final"]:,.0f}')
        + kv("Số tháng", result["months"], baseline["months"])
        + kv("Số mã nắm giữ", result["symbols_held"], baseline["symbols_held"])
        + kv("Lệnh mua", f'{result["buys"]:,}', f'{baseline["buys"]:,}')
        + kv("Lệnh bán", f'{result["sells"]:,}', f'{baseline["sells"]:,}')
    )

    cfg = "".join(
        f'<tr><th>{escape(k)}</th><td class="mono">{escape(str(v))}</td></tr>'
        for k, v in [
            ("Rổ", f'{config.UNIVERSE}  →  {len(market.symbols)} mã nạp được'),
            ("Benchmark", config.BENCHMARK),
            ("Fallback", plan.fallback_symbol or "—"),
            ("Buy rule", plan.buy_rule.describe()),
            ("Xếp hạng", plan.buy_scorer.describe()),
            ("Chia tiền", plan.allocator.describe()),
            ("Tiền mỗi tháng", f'{config.CONTRIBUTION:,.0f}'),
            ("Tiền thừa", config.LEFTOVER),
        ])

    skipped = ""
    if market.skipped:
        items = "".join(f'<li><b>{escape(s)}</b> — {escape(str(r))}</li>'
                        for s, r in sorted(market.skipped.items()))
        skipped = (f'<details class="skip"><summary>{len(market.skipped)} mã bị loại'
                   f'</summary><ul>{items}</ul></details>')

    chart = _curve_svg(result.get("curve", []), baseline.get("curve", []),
                       plan.name, baseline_plan.name)

    html = _TEMPLATE.format(
        title=escape(plan.name),
        generated=datetime.now().strftime("%Y-%m-%d %H:%M"),
        period=escape(market.summary()),
        load=f"{load_seconds:.0f}s",
        summary=summary, cfg=cfg, chart=chart, rows=body,
        plan_name=escape(plan.name), base_name=escape(baseline_plan.name),
        n_win=len(winners), n_lose=len(losers), n_all=len(rows),
        top3=f"{top3:+.2f}", growth=f"{growth:.2f}", skipped=skipped,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return path


_TEMPLATE = """<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — báo cáo danh mục</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root {{
  --ground:#F4F6FA; --surface:#FFF; --surface2:#EDF1F7; --line:#D3DBE7;
  --ink:#14202F; --ink2:#46566C; --ink3:#74839A;
  --accent:#1F4FD8; --base:#8A94A6; --paid:#A65A00;
  --pos:#1C6B4B; --neg:#B03030;
}}
@media (prefers-color-scheme:dark){{ :root{{
  --ground:#0E141C; --surface:#151D28; --surface2:#1C2734; --line:#2B3949;
  --ink:#E4EBF4; --ink2:#A3B2C6; --ink3:#7386A0;
  --accent:#6E9BFF; --base:#7386A0; --paid:#E0A050;
  --pos:#5FCC9C; --neg:#F0857D;
}} }}
*{{box-sizing:border-box}}
body{{background:var(--ground);color:var(--ink);margin:0;padding:32px 20px 72px;
  font:15px/1.6 "IBM Plex Sans",system-ui,sans-serif}}
.wrap{{max-width:1080px;margin:0 auto;display:flex;flex-direction:column;gap:30px}}
h1{{font-size:27px;margin:0;font-weight:600;letter-spacing:-.02em}}
h2{{font-size:17px;margin:0 0 12px;font-weight:600}}
.muted{{color:var(--ink3);font-size:13px;margin:2px 0 0}}
.mono,.n,.sym{{font-family:"IBM Plex Mono",ui-monospace,monospace;font-variant-numeric:tabular-nums}}
.card{{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:18px}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}
@media(max-width:800px){{.grid2{{grid-template-columns:1fr}}}}
table{{border-collapse:collapse;width:100%;font-size:13.5px}}
th,td{{padding:7px 10px;border-bottom:1px solid var(--line);text-align:left}}
thead th{{font-size:11px;letter-spacing:.05em;text-transform:uppercase;color:var(--ink3);
  font-family:"IBM Plex Mono",monospace;white-space:nowrap;cursor:pointer;user-select:none}}
thead th:hover{{color:var(--accent)}}
tbody tr:last-child td{{border-bottom:none}}
tbody tr:hover{{background:var(--surface2)}}
.n{{text-align:right}} .sym{{font-weight:500}}
.pos{{color:var(--pos)}} .neg{{color:var(--neg)}}
.kv th{{font-weight:500;color:var(--ink2);border-bottom:1px solid var(--line)}}
.scroll{{overflow-x:auto}}
.chartwrap{{overflow-x:auto}}
.chart{{width:100%;min-width:640px;height:auto;display:block}}
.grid{{stroke:var(--line);stroke-width:1}}
.ytick,.xtick{{fill:var(--ink3);font:11px "IBM Plex Mono",monospace}}
.ytick{{text-anchor:end}} .xtick{{text-anchor:middle}}
polyline{{fill:none;stroke-width:2;stroke-linejoin:round}}
.line-plan{{stroke:var(--accent)}}
.line-base{{stroke:var(--base);stroke-dasharray:5 4}}
.line-paid{{stroke:var(--paid);stroke-width:1.5;stroke-dasharray:2 3}}
.legend{{display:flex;gap:20px;flex-wrap:wrap;margin-top:10px;font-size:12.5px;color:var(--ink2)}}
.sw{{display:inline-block;width:16px;height:3px;border-radius:2px;margin-right:7px;vertical-align:middle}}
.sw-plan{{background:var(--accent)}} .sw-base{{background:var(--base)}} .sw-paid{{background:var(--paid)}}
.note{{color:var(--ink2);font-size:13.5px;margin:12px 0 0}}
details.skip{{margin-top:12px;font-size:13px;color:var(--ink2)}}
details.skip summary{{cursor:pointer;color:var(--ink3)}}
details.skip ul{{margin:8px 0 0;padding-left:20px}}
</style></head><body><div class="wrap">

<header>
  <h1>{title}</h1>
  <p class="muted">{period} · nạp {load} · dựng {generated}</p>
</header>

<div class="grid2">
  <section class="card">
    <h2>Kết quả</h2>
    <table class="kv"><thead><tr><th></th><th class="n">{plan_name}</th>
      <th class="n">{base_name}</th></tr></thead><tbody>{summary}</tbody></table>
  </section>
  <section class="card">
    <h2>Cấu hình</h2>
    <table class="kv"><tbody>{cfg}</tbody></table>
    {skipped}
  </section>
</div>

<section class="card">
  <h2>Đường vốn theo tháng</h2>
  {chart}
  <p class="note">Một con số cuối kỳ không phân biệt được chiến lược thắng đều đặn suốt
  11 năm với chiến lược thua 10 năm rồi thắng hết trong 18 tháng cuối. Đường vốn thì có.</p>
</section>

<section class="card">
  <h2>Đóng góp theo mã</h2>
  <p class="note">Cột <b>Đóng góp</b> là lợi nhuận của mã đó tính theo phần trăm
  <em>tổng vốn đã nạp</em>. Cộng cả cột lại bằng đúng {growth}% ở bảng trên —
  đây là phân rã chính xác, không phải xấp xỉ.
  {n_win} mã lãi, {n_lose} mã lỗ trên {n_all} mã. Ba mã đầu chiếm {top3} điểm.</p>
  <div class="scroll"><table id="tbl"><thead><tr>
    <th data-t="s">Mã</th><th class="n">Vốn gốc</th><th class="n">Giá trị</th>
    <th class="n">Lãi/lỗ</th><th class="n">Suất sinh lời</th><th class="n">Đóng góp (điểm)</th>
    <th class="n">Tỷ trọng</th><th class="n">Mua</th><th class="n">Bán</th>
  </tr></thead><tbody>{rows}</tbody></table></div>
</section>

</div>
<script>
document.querySelectorAll('#tbl thead th').forEach(function(th, i){{
  var asc = false;
  th.addEventListener('click', function(){{
    var tb = document.querySelector('#tbl tbody');
    var rows = Array.prototype.slice.call(tb.rows);
    var txt = function(r){{ return r.cells[i].textContent.trim(); }};
    var num = function(v){{ return parseFloat(v.replace(/[^0-9.\\-]/g,'')) || 0; }};
    var isText = th.dataset.t === 's';
    rows.sort(function(a,b){{
      return isText ? txt(a).localeCompare(txt(b)) : num(txt(a)) - num(txt(b));
    }});
    if (!asc) rows.reverse();
    asc = !asc;
    rows.forEach(function(r){{ tb.appendChild(r); }});
  }});
}});
</script>
</body></html>
"""
