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

import json
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


def _curve_svg(plan_curve, base_curve, plan_name, base_name, trades=None) -> str:
    """
    Two equity curves plus the money paid in, with the trades marked on the
    same time axis.

    WHY THE TRADES BELONG ON THIS CHART

      The curve says WHAT happened to the money; the marks say WHEN the
      strategy acted. Apart, neither answers the question a reader actually
      has — whether the acting had anything to do with the outcome. Do the
      sells cluster at the tops? Do the reinvests land in the dips? Is a flat
      stretch of curve a flat market, or a stretch where nothing was bought?

      Sells and reinvests are drawn individually because there are tens of
      them. Buys run to hundreds, so they become a DENSITY STRIP under the
      axis instead — one tick per month that had any, shaded by how many.
      Drawn as marks they would be a solid wall and say nothing.
    """
    if not plan_curve:
        return "<p class='muted'>No curve recorded.</p>"

    W, H = 900, 320
    pad_l, pad_r, pad_t, pad_b = 74, 16, 18, 46
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

    # ── trade marks ──────────────────────────────────────────────────────────
    # The curve is monthly, so trades are GROUPED BY MONTH and one marker is
    # drawn per month per kind. Drawing them individually looked right and was
    # not: several sells in the same month land on the same pixel, so all but the
    # topmost were unhoverable and invisible — the chart silently under-reported
    # its own activity.
    #
    # Hit areas are a transparent rect larger than the glyph, because a 10px
    # triangle is not a target. And the tooltip is an HTML element driven by
    # mouseenter rather than SVG <title>, which has a delay, cannot be styled,
    # and will not show a list.
    marks, mark_legend = "", ""
    if trades:
        month_x = {c["date"][:7]: pad_l + i / (n - 1) * w
                   for i, c in enumerate(plan_curve)}
        equity = {c["date"][:7]: c["equity"] for c in plan_curve}

        grouped: dict = {}
        for t in trades:
            grouped.setdefault((t["date"][:7], t["kind"]), []).append(t)

        pieces, buy_months = [], {}
        for (month, kind), items in sorted(grouped.items()):
            x = month_x.get(month)
            if x is None:
                continue
            if kind == "buy":
                buy_months[month] = items
                continue
            v = equity.get(month)
            if v is None:
                continue
            y = pad_t + h - (v - ymin) / (ymax - ymin) * h

            # JSON rather than pre-rendered text, because the popover turns each
            # symbol into a link and needs the name as a field, not buried in a
            # sentence.
            head = ("Bán" if kind == "sell" else "Tái đầu tư") + f" · {month}"
            payload = escape(json.dumps({
                "head": head,
                "kind": kind,
                "items": [{"sym": i["symbol"], "price": i["price"],
                           "amount": i["amount"],
                           "after": i["after"] if kind == "sell" else None}
                          for i in items],
            }, ensure_ascii=False), quote=True)

            if kind == "sell":
                glyph = (f'<polygon class="mk-sell" points="{x:.1f},{y - 3:.1f} '
                         f'{x - 5:.1f},{y - 12:.1f} {x + 5:.1f},{y - 12:.1f}"/>')
                hit_y = y - 16
            else:
                glyph = (f'<polygon class="mk-rei" points="{x:.1f},{y + 3:.1f} '
                         f'{x + 5:.1f},{y + 9:.1f} {x:.1f},{y + 15:.1f} '
                         f'{x - 5:.1f},{y + 9:.1f}"/>')
                hit_y = y + 1
            badge = (f'<text class="mk-n" x="{x:.1f}" '
                     f'y="{(y - 15) if kind == "sell" else (y + 25):.1f}">'
                     f'{len(items)}</text>' if len(items) > 1 else "")
            pieces.append(
                f'<g class="mk" data-items="{payload}">{glyph}{badge}'
                f'<rect class="hit" x="{x - 8:.1f}" y="{hit_y:.1f}" '
                f'width="16" height="18"/></g>')

        if buy_months:
            top_n = max(len(v) for v in buy_months.values())
            strip_y = pad_t + h + 5
            for month, items in buy_months.items():
                x = month_x.get(month)
                if x is None:
                    continue
                payload = escape(json.dumps({
                    "head": f"Mua · {month}",
                    "kind": "buy",
                    "items": [{"sym": i["symbol"], "price": i["price"],
                               "amount": i["amount"], "after": None}
                              for i in items],
                }, ensure_ascii=False), quote=True)
                pieces.append(
                    f'<g class="mk" data-items="{payload}">'
                    f'<rect class="mk-buy" x="{x - 2:.1f}" y="{strip_y:.1f}" '
                    f'width="4" height="7" opacity="'
                    f'{0.3 + 0.7 * len(items) / top_n:.2f}"/>'
                    f'<rect class="hit" x="{x - 4:.1f}" y="{strip_y - 2:.1f}" '
                    f'width="8" height="11"/></g>')

        marks = "".join(pieces)
        mark_legend = ('<span><i class="sw sw-mksell"></i>Bán</span>'
                       '<span><i class="sw sw-mkrei"></i>Tái đầu tư</span>'
                       '<span><i class="sw sw-mkbuy"></i>Mua</span>')

    return f"""
<div class="chartwrap">
<svg viewBox="0 0 {W} {H}" class="chart" role="img"
     aria-label="Equity of {escape(plan_name)} and {escape(base_name)} against money paid in">
  {''.join(grid)}
  {''.join(xticks)}
  <polyline points="{pts(paid_v)}" class="line-paid"/>
  <polyline points="{pts(base_v)}" class="line-base"/>
  <polyline points="{pts(plan_v)}" class="line-plan"/>
  {marks}
</svg>
<div class="legend">
  <span><i class="sw sw-plan"></i>{escape(plan_name)}</span>
  <span><i class="sw sw-base"></i>{escape(base_name)}</span>
  <span><i class="sw sw-paid"></i>Tiền đã nạp</span>
  {mark_legend}
</div>
</div>"""


def _trade_log(result, market, plan, config) -> tuple:
    """
    Every executed trade, with the two things that make one reviewable by eye:
    the condition values AT THE TIME, and what the price did AFTERWARDS.

    The hindsight column is the point. A sell cannot be judged by the profit it
    booked — every sell here books a profit, that is what the rule fires on — but
    by what the position went on to do without it. Selling ACB at 3,780 booked a
    gain and cost 473%, and no column that stops at the sale price can show that.

    It is hindsight and is labelled as such. The strategy could not know it; the
    reader is allowed to.
    """
    final = market.final_prices()
    window = config.BUY_WINDOW
    slope_w = getattr(config, "SELL_SIGNAL1_WINDOW", None)
    label = {"buy": "Mua", "sell": "Bán", "reinvest": "Tái đầu tư"}

    rows = []
    for sym, pos in result["wallet"].positions.items():
        series = market[sym]
        for t in pos.trades:
            med = series.median(window, t.index)
            rows.append({
                "date": str(t.date)[:10], "kind": t.kind, "symbol": sym,
                "price": t.price, "amount": t.amount, "shares": t.shares,
                "prem": ((t.price - med) / med * 100) if med else None,
                "slope": series.slope(slope_w, t.index) if slope_w else None,
                "cap": series.cap_rank(t.index),
                "final": final[sym],
                "after": final[sym] / t.price - 1,
            })
    rows.sort(key=lambda r: (r["date"], r["symbol"]))

    def num(v, fmt, dash="—"):
        return dash if v is None else format(v, fmt)

    out = []
    for r in rows:
        # A rise after a BUY is good. After a SELL it is the opposite — the
        # position was given up, so a rise is what the sale cost.
        good = (r["after"] >= 0) if r["kind"] != "sell" else (r["after"] < 0)
        out.append(
            f'<tr data-kind="{r["kind"]}">'
            f'<td class="mono">{r["date"]}</td>'
            f'<td><span class="k k-{r["kind"]}">{label[r["kind"]]}</span></td>'
            f'<td class="sym">{escape(r["symbol"])}</td>'
            f'<td class="n">{r["price"]:,.0f}</td>'
            f'<td class="n">{r["amount"]:,.0f}</td>'
            f'<td class="n">{r["shares"]:,.0f}</td>'
            f'<td class="n">{num(r["prem"], "+.1f")}%</td>'
            f'<td class="n">{num(r["slope"], "+.3f")}</td>'
            f'<td class="n">{num(r["cap"], ".2f")}</td>'
            f'<td class="n">{r["final"]:,.0f}</td>'
            f'<td class="n {"pos" if good else "neg"}">{r["after"]:+.0%}</td>'
            f'</tr>')

    counts = {k: sum(1 for r in rows if r["kind"] == k)
              for k in ("buy", "sell", "reinvest")}
    return "\n".join(out), counts, rows


# ── Report ────────────────────────────────────────────────────────────────────

def build_report(result, baseline, plan, baseline_plan, config, market,
                 path: Path, load_seconds: float = 0.0,
                 charts: dict | None = None) -> Path:
    invested = result["invested"]
    growth, base_growth = result["growth_%"], baseline["growth_%"]

    # Attribution over the WHOLE universe, not just what is held. profit =
    # value - basis per position and those sum to the portfolio's profit, so
    # `share` sums to `growth`; a never-bought symbol contributes 0 and changes
    # no total. See the module docstring.
    rows = []
    for sym, h in result.get("universe", {}).items():
        profit = h["value"] - h["basis"]
        rows.append({
            "symbol": sym,
            "state": h["state"],
            "basis": h["basis"],
            "value": h["value"],
            "profit": profit,
            "return_%": (profit / h["basis"] * 100) if h["basis"] else 0.0,
            "share": (profit / invested * 100) if invested else 0.0,
            "weight_%": h["weight_%"],
            "buys": h["buys"],
            "reinvests": h["reinvests"],
            "sells": h["sells"],
        })
    # Never-bought rows sort to 0 and land between the winners and the losers,
    # which is where they belong: they neither helped nor hurt.
    rows.sort(key=lambda r: -r["share"])

    _STATE = {"held":   ("Đang giữ",      "st-held"),
              "closed": ("Đã bán hết",    "st-closed"),
              "never":  ("Chưa từng mua", "st-never")}
    body = ""
    for r in rows:
        sign = "pos" if r["profit"] > 0 else ("neg" if r["profit"] < 0 else "")
        label, cls = _STATE.get(r["state"], (r["state"], ""))
        # A never-bought row has nothing to report, and printing 0 for every
        # figure would read as a position worth nothing rather than as no
        # position. Em dashes say which.
        dash = r["state"] == "never"

        def cell(value, fmt, klass=""):
            return f'<td class="n {klass}">{"—" if dash else format(value, fmt)}</td>'

        body += (
            f'<tr data-sym="{escape(r["symbol"])}" data-state="{r["state"]}">'
            f'<td class="sym">{escape(r["symbol"])}</td>'
            f'<td><span class="pill {cls}">{label}</span></td>'
            + cell(r["basis"], ",.0f") + cell(r["value"], ",.0f")
            + cell(r["profit"], "+,.0f", sign) + cell(r["return_%"], "+.1f", sign)
            + cell(r["share"], "+.2f", sign) + cell(r["weight_%"], ".2f")
            + f'<td class="n">{r["buys"]}</td>'
            + f'<td class="n">{r["reinvests"]}</td>'
            + f'<td class="n">{r["sells"]}</td>'
            + '<td class="open"></td></tr>\n')

    winners = [r for r in rows if r["profit"] > 0]
    losers = [r for r in rows if r["profit"] < 0]
    never = [r for r in rows if r["state"] == "never"]
    top3 = sum(r["share"] for r in rows[:3])

    def kv(label, a, b=None, cls=""):
        # A leading "·" marks a component of the row above it.
        rowcls = ' class="kv-sub"' if str(label).startswith("·") else ""
        bcell = f'<td class="n">{b}</td>' if b is not None else '<td></td>'
        return f'<tr><th>{label}</th><td class="n {cls}">{a}</td>{bcell}</tr>\n'

    summary = (
        kv("Tăng trưởng", f'{growth:.2f}%', f'{base_growth:.2f}%')
        + kv("Chênh lệch", f'{growth - base_growth:+.2f}%', None,
             "pos" if growth >= base_growth else "neg")
        + kv("Vốn đã nạp", f'{invested:,.0f}', f'{baseline["invested"]:,.0f}')
        + kv("Giá trị cuối", f'{result["final"]:,.0f}', f'{baseline["final"]:,.0f}')
        # Where that final figure actually sits. The three lines below sum to it
        # exactly, and printing them apart is the only way to tell a plan that
        # is fully invested from one sitting on cash — two very different things
        # that a single "final value" reports identically.
        + kv("· cổ phiếu", f'{result["holdings_value"]:,.0f}',
             f'{baseline["holdings_value"]:,.0f}')
        + kv("· tiền dự trữ", f'{result["reserve"]:,.0f}',
             f'{baseline["reserve"]:,.0f}')
        + kv("· tiền chưa giải ngân", f'{result["idle_cash"]:,.0f}',
             f'{baseline["idle_cash"]:,.0f}')
        + kv("· lãi tiền gửi (đã gồm)", f'{result["interest_paid"]:,.0f}',
             f'{baseline["interest_paid"]:,.0f}')
        + kv("Số tháng", result["months"], baseline["months"])
        + kv("Số mã nắm giữ", result["symbols_held"], baseline["symbols_held"])
        + kv("Lệnh mua", f'{result["buys"]:,}', f'{baseline["buys"]:,}')
        + kv("Lệnh bán", f'{result["sells"]:,}', f'{baseline["sells"]:,}')
        + kv("Lệnh tái đầu tư", f'{result["reinvests"]:,}',
             f'{baseline["reinvests"]:,}')
    )

    cfg = "".join(
        f'<tr><th>{escape(k)}</th><td class="mono">{escape(str(v))}</td></tr>'
        for k, v in [
            ("Rổ", f'{config.UNIVERSE}  →  {len(market.symbols)} mã nạp được'),
            ("Benchmark", config.BENCHMARK),
            ("Fallback", plan.fallback_symbol or "—"),
            ("1 · Điều kiện của mã",
             (plan.buy_rule.symbol_only() or plan.buy_rule).describe()),
            ("2 · Lọc so với rổ",
             (f"vốn hoá top {(1 - config.CAP_MIN_RANK) * 100:.0f}%"
              if getattr(config, "CAP_MIN_RANK", None) is not None else "—")),
            ("3 · Phân bổ",
             f"{plan.buy_scorer.describe()} → {plan.allocator.describe()}"),
            ("Tiền mỗi tháng", f'{config.CONTRIBUTION:,.0f}'),
            ("Tiền thừa", config.LEFTOVER),
        ])

    skipped = ""
    if market.skipped:
        items = "".join(f'<li><b>{escape(s)}</b> — {escape(str(r))}</li>'
                        for s, r in sorted(market.skipped.items()))
        skipped = (f'<details class="skip"><summary>{len(market.skipped)} mã bị loại'
                   f'</summary><ul>{items}</ul></details>')

    log_rows, log_counts, log_raw = _trade_log(result, market, plan, config)
    chart = _curve_svg(result.get("curve", []), baseline.get("curve", []),
                       plan.name, baseline_plan.name, trades=log_raw)

    html = _TEMPLATE.format(
        title=escape(plan.name),
        generated=datetime.now().strftime("%Y-%m-%d %H:%M"),
        period=escape(market.summary()),
        load=f"{load_seconds:.0f}s",
        summary=summary, cfg=cfg, chart=chart, rows=body,
        plan_name=escape(plan.name), base_name=escape(baseline_plan.name),
        n_win=len(winners), n_lose=len(losers), n_all=len(rows),
        top3=f"{top3:+.2f}", growth=f"{growth:.2f}", skipped=skipped,
        n_never=len(never),
        charts=json.dumps(charts or {}, separators=(",", ":")),
        log_rows=log_rows,
        n_buy=log_counts["buy"], n_sell=log_counts["sell"],
        n_rei=log_counts["reinvest"],
        slope_head=f"slope[{getattr(config, 'SELL_SIGNAL1_WINDOW', 0)}]",
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
.mk-sell{{fill:#ef4444;stroke:#991b1b;stroke-width:.8}}
.mk-rei{{fill:#f97316;stroke:#c2410c;stroke-width:.8}}
.mk-buy{{fill:#22c55e}}
.mk{{cursor:pointer}}
.hit{{fill:transparent}}
.mk:hover .mk-sell{{fill:#dc2626}}
.mk:hover .mk-rei{{fill:#ea580c}}
.mk:hover .mk-buy{{opacity:1 !important}}
.mk-n{{fill:var(--ink2);font:600 9px "IBM Plex Mono",monospace;text-anchor:middle;pointer-events:none}}
#tip .th{{font-weight:600;margin-bottom:6px;color:var(--ink2)}}
#tip .row{{display:flex;gap:10px;align-items:center;padding:3px 0;white-space:nowrap}}
#tip .s{{font-weight:600;min-width:42px}}
#tip .m{{color:var(--ink2)}}
#tip .aft{{margin-left:auto}}
#tip .row a.open{{margin-left:auto;padding:1px 8px;font-size:11px}}
#tip .aft + a.open{{margin-left:10px}}
#tip{{position:fixed;z-index:50;display:none;max-width:460px;background:var(--surface);color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:8px 11px;font-size:12.5px;line-height:1.5;box-shadow:0 6px 20px rgba(0,0,0,.18);font-family:"IBM Plex Mono",monospace}}
.sw-mksell,.sw-mkrei,.sw-mkbuy{{height:8px;width:8px;border-radius:2px}}
.sw-mksell{{background:#ef4444}} .sw-mkrei{{background:#f97316}} .sw-mkbuy{{background:#22c55e}}
.note{{color:var(--ink2);font-size:13.5px;margin:12px 0 0}}
details.skip{{margin-top:12px;font-size:13px;color:var(--ink2)}}
details.skip summary{{cursor:pointer;color:var(--ink3)}}
details.skip ul{{margin:8px 0 0;padding-left:20px}}
.k{{font-family:"IBM Plex Mono",monospace;font-size:11px;font-weight:600;
   padding:2px 7px;border-radius:3px;white-space:nowrap}}
.k-buy{{color:#15803d;background:rgba(34,197,94,.16)}}
.k-sell{{color:#b03030;background:rgba(239,68,68,.16)}}
.k-reinvest{{color:#c2410c;background:rgba(249,115,22,.16)}}
#log tbody tr{{cursor:default}}
#log tbody tr:hover{{box-shadow:none}}
.chips{{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 12px}}
.chip{{font-size:12.5px;padding:4px 11px;border:1px solid var(--line);
  border-radius:14px;background:var(--surface);color:var(--ink2);cursor:pointer;
  font-family:"IBM Plex Mono",monospace}}
.chip.on{{background:var(--accent);border-color:var(--accent);color:#fff}}
.tall{{max-height:520px;overflow:auto}}
.tall thead th{{position:sticky;top:0;background:var(--surface);z-index:1}}
.pill{{font-size:11px;font-family:"IBM Plex Mono",monospace;padding:2px 7px;
  border-radius:3px;white-space:nowrap}}
.st-held{{color:var(--pos);background:color-mix(in srgb,var(--pos) 14%,transparent)}}
.st-closed{{color:var(--paid);background:color-mix(in srgb,var(--paid) 16%,transparent)}}
.st-never{{color:var(--ink3);background:var(--surface2)}}
.chips{{display:flex;gap:7px;align-items:center;flex-wrap:wrap;margin:10px 0 12px}}
.chip{{font-size:12.5px;font-family:inherit;padding:4px 11px;border-radius:14px;
  border:1px solid var(--line);background:var(--surface);color:var(--ink2);cursor:pointer}}
.chip:hover{{border-color:var(--accent);color:var(--accent)}}
.chip.on{{background:var(--accent);border-color:var(--accent);color:#fff}}
.count{{font-size:12px;color:var(--ink3)}}
tbody tr:hover{{background:var(--surface2)}}
a.open{{display:inline-block;font-family:"IBM Plex Mono",monospace;font-size:11.5px;
 color:var(--accent);text-decoration:none;border:1px solid var(--line);
 border-radius:4px;padding:2px 9px;white-space:nowrap}}
a.open:hover{{background:var(--accent);border-color:var(--accent);color:#fff}}
td.open{{text-align:center}}
.kv-sub th{{padding-left:14px;color:var(--ink3);font-weight:400}}
.kv-sub td{{color:var(--ink2)}}
.hint{{color:var(--ink3);font-size:12.5px;margin:8px 0 0}}
</style></head><body><div id="tip"></div>
<div class="wrap">

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
  {n_win} mã lãi, {n_lose} mã lỗ, {n_never} mã luật chưa bao giờ chấp nhận —
  trên {n_all} mã trong rổ. Ba mã đầu chiếm {top3} điểm.</p>
  <div class="chips">
    <button class="chip on" data-f="all">Tất cả</button>
    <button class="chip" data-f="held">Đang giữ</button>
    <button class="chip" data-f="closed">Đã bán hết</button>
    <button class="chip" data-f="never">Chưa từng mua</button>
    <span class="count" id="chipCount"></span>
  </div>
  <div class="scroll"><table id="tbl"><thead><tr>
    <th data-t="s">Mã</th><th data-t="s">Trạng thái</th><th class="n">Vốn gốc</th><th class="n">Giá trị</th>
    <th class="n">Lãi/lỗ</th><th class="n">Suất sinh lời</th><th class="n">Đóng góp (điểm)</th>
    <th class="n">Tỷ trọng</th><th class="n">Mua</th>
    <th class="n">Tái đầu tư</th><th class="n">Bán</th>
    <th>Chart</th>
  </tr></thead><tbody>{rows}</tbody></table></div>
  <p class="hint">Cột <b>Chart</b> mở biểu đồ giá và các lệnh của mã đó trong tab mới.
  Trên biểu đồ đó, <b>vùng xanh</b> là điều kiện của <em>riêng mã ấy</em> (tầng 1) — không
  gồm lọc vốn hoá hay top-K, vì hai thứ đó phụ thuộc vào các mã khác. <b>Marker</b> là
  lệnh thật. Khoảng cách giữa hai thứ chính là phần bị tầng 2 và 3 loại.</p>
</section>

<section class="card">
  <h2>Nhật ký giao dịch</h2>
  <p class="note">Cột <b>chênh</b>, <b>{slope_head}</b> và <b>vốn hoá</b> là giá trị
  <em>tại thời điểm giao dịch</em> — dùng để kiểm tra luật có chạy đúng không.
  Cột <b>sau đó</b> là <em>hậu nghiệm</em>: giá hôm nay so với giá lúc giao dịch.
  Với lệnh <b>bán</b>, tăng là xấu — đó chính là cái đã bỏ lỡ.</p>
  <div class="chips">
    <button class="chip on" data-k="all">Tất cả</button>
    <button class="chip" data-k="buy">Mua ({n_buy})</button>
    <button class="chip" data-k="sell">Bán ({n_sell})</button>
    <button class="chip" data-k="reinvest">Tái đầu tư ({n_rei})</button>
  </div>
  <div class="scroll tall"><table id="log"><thead><tr>
    <th data-t="s">Ngày</th><th data-t="s">Loại</th><th data-t="s">Mã</th>
    <th class="n">Giá</th><th class="n">Tiền</th><th class="n">Cổ phiếu</th>
    <th class="n">Chênh vs median</th><th class="n">{slope_head}</th>
    <th class="n">Vốn hoá</th><th class="n">Giá hôm nay</th><th class="n">Sau đó</th>
  </tr></thead><tbody>
{log_rows}
  </tbody></table></div>
</section>

</div>
<script>
var CHARTS = {charts};

function applyFilter(f){{
  var shown = 0;
  document.querySelectorAll('#tbl tbody tr').forEach(function(tr){{
    var ok = (f === 'all') || (tr.dataset.state === f);
    tr.style.display = ok ? '' : 'none';
    if (ok) shown++;
  }});
  document.getElementById('chipCount').textContent =
    shown + '/' + document.querySelectorAll('#tbl tbody tr').length + ' mã';
}}
(function(){{
  // WHY THE POPOVER OUTLIVES THE POINTER LEAVING THE MARKER
  //
  //   Every symbol on it carries a "mở" button, and a tooltip that vanishes the
  //   instant the pointer leaves its 16px marker can never have its button
  //   pressed — the gap between the two is crossed with the mouse, and the
  //   tooltip would be gone before the pointer arrived.
  //
  //   So hiding is DEFERRED, and entering the popover cancels it. Hover to read,
  //   walk onto it to click. No click needed to open it, no pinning to remember.
  var tip = document.getElementById('tip');
  var timer = null;

  function place(e){{
    var x = (e && e.clientX != null) ? e.clientX : innerWidth / 2;
    var y = (e && e.clientY != null) ? e.clientY : innerHeight / 2;
    tip.style.left = Math.max(8, Math.min(x + 14, innerWidth - tip.offsetWidth - 12)) + 'px';
    tip.style.top = Math.max(8, Math.min(y + 14, innerHeight - tip.offsetHeight - 12)) + 'px';
  }}

  function money(v){{ return v.toLocaleString('vi-VN', {{maximumFractionDigits: 0}}); }}

  function render(d){{
    var h = '<div class="th">' + d.head + ' · ' + d.items.length + ' lệnh</div>';
    d.items.forEach(function(i){{
      h += '<div class="row"><span class="s">' + i.sym + '</span>'
         + '<span class="m">@ ' + money(i.price) + ' · ' + money(i.amount) + 'đ</span>';
      if (i.after != null) {{
        // After a SELL a rise is the cost of having sold, so the colours invert.
        var cls = (i.after < 0) ? 'pos' : 'neg';
        h += '<span class="aft ' + cls + '">sau đó '
           + (i.after >= 0 ? '+' : '') + (i.after * 100).toFixed(0) + '%</span>';
      }}
      var f = CHARTS[i.sym];
      h += f
        ? '<a class="open" href="' + f + '" target="_blank" rel="noopener" '
          + 'title="Biểu đồ ' + i.sym + ' (tab mới)">mở</a>'
        : '<span class="muted" style="margin-left:auto">—</span>';
      h += '</div>';
    }});
    tip.innerHTML = h;
  }}

  function show(d, e){{ clearTimeout(timer); render(d); tip.style.display = 'block'; place(e); }}
  function scheduleHide(){{ timer = setTimeout(function(){{ tip.style.display = 'none'; }}, 320); }}

  tip.addEventListener('mouseenter', function(){{ clearTimeout(timer); }});
  tip.addEventListener('mouseleave', scheduleHide);

  document.querySelectorAll('.mk').forEach(function(g){{
    var data = JSON.parse(g.dataset.items);
    g.addEventListener('mouseenter', function(e){{ show(data, e); }});
    g.addEventListener('mouseleave', scheduleHide);
    // Click does the same thing as hover. On a touch screen there is no hover at
    // all, and a chart whose only affordance is hovering is unusable there.
    g.addEventListener('click', function(e){{ e.stopPropagation(); show(data, e); }});
  }});

  document.addEventListener('keydown', function(e){{
    if (e.key === 'Escape') tip.style.display = 'none';
  }});
}})();

document.querySelectorAll('.chip').forEach(function(c){{
  c.addEventListener('click', function(){{
    document.querySelectorAll('.chip').forEach(function(o){{ o.classList.remove('on'); }});
    c.classList.add('on');
    applyFilter(c.dataset.f);
  }});
}});
applyFilter('all');

// An explicit link, not a click handler on the row. A whole clickable row is
// undiscoverable — nothing says it is clickable — and it steals text selection
// from every cell in it, so copying a number out of the table opened a chart
// instead.
document.querySelectorAll('#tbl tbody tr').forEach(function(tr){{
  var f = CHARTS[tr.dataset.sym];
  var cell = tr.querySelector('td.open');
  if (!cell) return;
  if (!f) {{ cell.innerHTML = '<span class="muted">—</span>'; return; }}
  var a = document.createElement('a');
  a.className = 'open';
  a.href = f;
  a.target = '_blank';
  a.rel = 'noopener';
  a.textContent = 'mở';
  a.title = 'Biểu đồ ' + tr.dataset.sym + ' (tab mới)';
  cell.appendChild(a);
}});

document.querySelectorAll('.chip').forEach(function(c){{
  c.addEventListener('click', function(){{
    document.querySelectorAll('.chip').forEach(function(o){{ o.classList.remove('on'); }});
    c.classList.add('on');
    var k = c.dataset.k;
    document.querySelectorAll('#log tbody tr').forEach(function(tr){{
      tr.style.display = (k === 'all' || tr.dataset.kind === k) ? '' : 'none';
    }});
  }});
}});

document.querySelectorAll('#log thead th').forEach(function(th, i){{
  var asc = false;
  th.style.cursor = 'pointer';
  th.addEventListener('click', function(){{
    var tb = document.querySelector('#log tbody');
    var rows = Array.prototype.slice.call(tb.rows);
    var txt = function(r){{ return r.cells[i].textContent.trim(); }};
    var isText = th.dataset.t === 's';
    rows.sort(function(a, b){{
      if (isText) return txt(a).localeCompare(txt(b));
      var na = parseFloat(txt(a).replace(/[^0-9.\-]/g, '')) || 0;
      var nb = parseFloat(txt(b).replace(/[^0-9.\-]/g, '')) || 0;
      return na - nb;
    }});
    if (!asc) rows.reverse();
    asc = !asc;
    rows.forEach(function(r){{ tb.appendChild(r); }});
  }});
}});

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
