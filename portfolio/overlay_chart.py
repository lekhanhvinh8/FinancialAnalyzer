"""
Every symbol on one pair of axes, rebased to a common origin.

WHAT THIS ANSWERS THAT THE PER-SYMBOL CHARTS DO NOT

  Fifty-four charts in fifty-four tabs cannot be compared. Each one is drawn to
  its own price scale, so a line that climbs steeply in one and a line that
  climbs steeply in another may be a tenfold gain and a twenty percent gain. The
  question this package keeps asking -- did the strategy buy the names that went
  on to work -- needs every name on ONE scale, with the trades marked on it.

WHERE A LATE LISTING ENTERS, AND WHY IT IS NOT AT 100

  The obvious rebasing gives every symbol the value 100 on its own first bar.
  It is wrong here, and visibly so: a name listed in 2020 would sit at 100
  beside a name listed in 2015 that had reached 900, and the eye reads that as
  cheap when the only thing it means is young. Every late entrant would appear
  to be at the bottom of the market.

  Rebasing everything to one calendar date is not available either -- most of
  these symbols have no price on the first date any of them do.

  So a symbol ENTERS AT THE MEDIAN OF THE LINES ALREADY DRAWN on its first day.
  Read it as "assume it tracked the basket until it appeared". The consequence
  is the property worth having: vertical distance between two lines at any date
  is their relative performance over the span BOTH existed, and nothing else.
  Nobody is rewarded or punished for their listing date.

  The very first symbols, with no pack to join, start at 100.

WHY THE Y AXIS IS LOGARITHMIC

  These are growth multiples over eleven years, and they range from about a
  third to about twenty times. On a linear axis the top two names occupy the
  whole height and the other fifty are a band at the bottom. On a log axis equal
  vertical distance is equal RATIO, which is what "did better" actually means,
  and a doubling looks the same whether it happened at 100 or at 1000.

WHY THE MARKERS ARE CIRCLES

  The other charts use triangles and diamonds, which read well when there are
  thirty of them on one line. Here there are six hundred and seventy-eight
  across fifty-four lines, and shaped glyphs at that density turn the chart into
  noise. Small circles carry the same three colours, stay out of the way at rest
  and come forward when their line is hovered.

NO CHART LIBRARY

  Same reason as report_html.py: a local file has no CDN, so a dependency would
  have to be vendored. The lines are sampled weekly, which is enough resolution
  for a decade of context and keeps the file to a few hundred kilobytes, while
  the markers keep their exact dates.
"""

import json
from html import escape
from pathlib import Path

import numpy as np

# Every fifth trading day. A decade of weekly closes is plenty of shape for a
# comparison chart, and daily would be 153,000 coordinate pairs of SVG text.
SAMPLE = 5

KIND_COLOR = {"buy": "#22c55e", "sell": "#ef4444", "reinvest": "#f97316"}

# Market cap on the last day, as a chip beside each name.
#
# BY PERCENTILE, NOT BY VALUE. Market cap on this universe is log-normal and
# badly skewed -- the largest name is worth more than the bottom twenty put
# together -- so five equal buckets of VND would put almost every symbol in the
# first one and the scale would carry no information. A percentile spreads the
# basket evenly across the five steps. The exact figure is in the tooltip, so
# nothing is lost by ranking here.
#
# It is also the quantity the strategy itself uses: CapRankScorer ranks, and
# CAP_WEIGHT blends ranks. Colouring by value would show something the plan never
# reads.
#
# SQUARES, BECAUSE THE TRADE MARKERS ARE CIRCLES. Same chart, two meanings, and
# a reader should not have to remember which small dot is which.
#
# THE RAMP HAS TO CARRY ITS OWN ORDER. The first version of this scale ran grey
# to blue to violet to magenta, and it was wrong: those are five hues with no
# order between them, a CATEGORICAL palette used for a quantity. A reader looking
# at one chip could not tell whether it was large or small without going to the
# legend, which defeats the point of putting it on the label at all.
#
# So the ramp now moves along ONE channel that has an order: SATURATION, from
# near-grey to vivid, with lightness held roughly level. More colour = bigger.
#
# Lightness would have been the obvious channel and cannot be used. This page
# renders on a light ground or a dark one depending on the reader's system, and
# "darker = bigger" reverses into "darker = closer to the background" when the
# ground flips. Saturation does not flip.
#
# SIZE CLIMBS TOO, over a wider range than before -- 3.5 to 8.0 px, better than
# double the area. Redundant encoding on a channel nobody can misread, so the
# chip still works for a reader who cannot separate the middle two colours.
#
# The hues stay clear of the green/red/orange the trades use and of the accent
# the hover state uses.
# Generated from HLS rather than picked by eye, which is how the first attempt
# ended up with its top step LESS saturated than the one below it. Lightness is
# pinned at 66% for every step; only saturation climbs, 14 -> 97%.
CAP_STEPS = [
    ("#9CA5B4", 3.5),   # 0-20    bao hoa 14%, gan nhu xam
    ("#8998C8", 4.6),   # 20-40   36%
    ("#7679DB", 5.7),   # 40-60   58%
    ("#9665EC", 6.8),   # 60-80   78%
    ("#E555FC", 8.0),   # 80-100  97%, ruc nhat
]
CAP_BANDS = ["0-20", "20-40", "40-60", "60-80", "80-100"]


def _rebase(market, symbols):
    """
    -> (dates, values, first_pos)

    `values` is one row per symbol over the shared date axis, NaN where the
    symbol had no bar. Rows are filled in listing order, because a symbol's
    starting level is the median of the rows already filled -- see the module
    docstring.
    """
    all_dates = sorted({d for s in (market[x] for x in symbols) for d in s.dates})
    pos = {d: i for i, d in enumerate(all_dates)}

    order = sorted(symbols, key=lambda x: market[x].dates[0])
    values = np.full((len(order), len(all_dates)), np.nan)
    first_pos = {}

    for k, sym in enumerate(order):
        s = market[sym]
        idx = np.array([pos[d] for d in s.dates])
        start = int(idx[0])
        first_pos[sym] = start

        # The pack as it stands on this symbol's first day. `values[:k]` is
        # exactly the rows already placed, so no symbol can influence the level
        # of one that listed before it.
        if k == 0:
            base = 100.0
        else:
            col = values[:k, start]
            m = np.nanmedian(col) if not np.all(np.isnan(col)) else np.nan
            base = float(m) if m == m else 100.0

        closes = np.asarray(s.closes, dtype=float)
        if closes[0] <= 0:
            continue
        values[k, idx] = base * closes / closes[0]

    return all_dates, order, values, first_pos


def _ticks(lo_log, hi_log):
    """Nice round levels for a log axis: 1, 2, 5 per decade, trimmed to range."""
    out, d = [], int(np.floor(lo_log))
    while d <= int(np.ceil(hi_log)):
        for m in (1, 2, 5):
            v = m * 10.0 ** d
            if lo_log <= np.log10(v) <= hi_log:
                out.append(v)
        d += 1
    return out


def _place_labels(ends, top, bottom, gap=10.0):
    """
    Push the end-of-line labels apart so every one of them stays readable.

    WHY THEY CANNOT SIT WHERE THE LINES END

      Fifty-four lines finish inside one column a few hundred pixels tall, and
      after a decade of compounding most of them finish near the middle of it.
      Labels drawn at their natural heights would overlap into an unreadable
      stack. Dropping the colliding ones is worse than moving them: the names
      that collide are the ones in the middle of the pack, which is most of the
      basket.

      So a label keeps its ORDER but not its exact height, and a leader line
      joins it back to the point it belongs to. Reading the column top to bottom
      still ranks the symbols correctly wherever a label has moved.

    THE ALGORITHM, AND WHY THE OBVIOUS ONE IS WRONG

      A single downward pass -- push each label below the previous one -- is not
      enough. It runs the last labels past the bottom of the plot, and clamping
      them there piles them back on top of each other, which is exactly the
      collision it was meant to prevent. Measured on a synthetic cluster at the
      bottom edge, that version left 51 of 54 labels overlapping.

      Correct is: shrink the gap first if the column cannot hold them all, then
      push DOWN from the top, and if the last label still overflows, anchor it at
      the bottom and push back UP. The second pass cannot re-collide anything,
      because it only ever moves a label further from the one below it. Both
      passes together guarantee the spacing and the bounds.
    """
    if not ends:
        return []
    out = sorted(ends, key=lambda e: e["y"])
    n = len(out)
    # Never ask for more room than exists. Below this the labels are unreadable
    # anyway, but overlapping unreadable beats stacked unreadable.
    if n > 1:
        gap = min(gap, (bottom - top) / (n - 1))

    prev = top - gap
    for e in out:
        e["ly"] = max(e["y"], prev + gap)
        prev = e["ly"]

    if out[-1]["ly"] > bottom:
        out[-1]["ly"] = bottom
        for i in range(n - 2, -1, -1):
            out[i]["ly"] = min(out[i]["ly"], out[i + 1]["ly"] - gap)
    return out


def build_overlay(result, market, config, path: Path,
                  charts: dict | None = None) -> Path:
    charts = charts or {}
    benchmark = getattr(config, "BENCHMARK", None)

    symbols = [s for s in market.symbols if len(market[s]) > 1]
    if not symbols:
        raise ValueError("nothing to draw")
    dates, order, values, first_pos = _rebase(market, symbols)
    date_pos = {d: i for i, d in enumerate(dates)}

    W, H = 1180, 640
    pad_l, pad_r, pad_t, pad_b = 62, 56, 20, 46
    w, h = W - pad_l - pad_r, H - pad_t - pad_b
    n = len(dates)

    finite = values[np.isfinite(values) & (values > 0)]
    lo_log, hi_log = np.log10(finite.min()), np.log10(finite.max())
    span = hi_log - lo_log or 1.0
    lo_log -= span * 0.03
    hi_log += span * 0.03
    span = hi_log - lo_log

    def X(p):
        return pad_l + p / (n - 1) * w

    def Y(v):
        return pad_t + h - (np.log10(v) - lo_log) / span * h

    # ── axes ─────────────────────────────────────────────────────────────────
    grid = []
    for v in _ticks(lo_log, hi_log):
        y = Y(v)
        grid.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{pad_l + w}" '
                    f'y2="{y:.1f}" class="grid"/>'
                    f'<text x="{pad_l - 8}" y="{y + 4:.1f}" class="yt">'
                    f'{v:,.0f}</text>')
    # WHY THE CHART IS WIDER THAN THE BACKTEST. The lines run from each symbol's
    # listing, years before any rule could fire: BUY_WINDOW is 1000 bars and no
    # condition can be evaluated until that median exists. Cutting the chart back
    # to the tradable range would hide the very data the median is built from;
    # drawing it without a boundary would invite the question "why did it not buy
    # here". So the dead zone is shaded and labelled.
    first_live = market.calendar[0] if getattr(market, "calendar", None) else None
    if first_live is not None and date_pos.get(first_live, 0) > 0:
        xw = X(date_pos[first_live])
        grid.append(
            f'<rect class="warm" x="{pad_l}" y="{pad_t}" '
            f'width="{xw - pad_l:.1f}" height="{h}"/>'
            f'<line class="edge" x1="{xw:.1f}" y1="{pad_t}" x2="{xw:.1f}" '
            f'y2="{pad_t + h}"/>'
            f'<text class="warmt" x="{xw - 6:.1f}" y="{pad_t + 13}">'
            f'warmup &#183; chưa giao dịch</text>')

    prev = None
    for i, d in enumerate(dates):
        if d.year != prev:
            prev = d.year
            x = X(i)
            grid.append(f'<line x1="{x:.1f}" y1="{pad_t}" x2="{x:.1f}" '
                        f'y2="{pad_t + h}" class="grid"/>'
                        f'<text x="{x:.1f}" y="{pad_t + h + 20}" class="xt">'
                        f'{d.year}</text>')

    # ── one group per symbol ─────────────────────────────────────────────────
    trades_by_symbol = {}
    for sym, p in result["wallet"].positions.items():
        if p.trades:
            trades_by_symbol[sym] = p.trades

    groups, meta, n_marks, ends = [], [], 0, []
    for k, sym in enumerate(order):
        row = values[k]
        live = np.flatnonzero(np.isfinite(row))
        if live.size < 2:
            continue

        keep = list(live[::SAMPLE])
        if keep[-1] != live[-1]:
            keep.append(int(live[-1]))
        d = "M" + " L".join(f"{X(p):.1f},{Y(row[p]):.1f}" for p in keep)

        is_bench = (sym == benchmark)
        cls = "sy bench" if is_bench else "sy"

        dots = []
        for t in trades_by_symbol.get(sym, []):
            p = date_pos.get(market[sym].dates[t.index])
            if p is None or not np.isfinite(row[p]):
                continue
            payload = escape(json.dumps(
                {"sym": sym, "kind": t.kind, "date": str(t.date)[:10],
                 "price": t.price, "amount": t.amount, "shares": t.shares},
                ensure_ascii=False), quote=True)
            dots.append(f'<circle class="d {t.kind}" cx="{X(p):.1f}" '
                        f'cy="{Y(row[p]):.1f}" r="2.4" data-t="{payload}"/>')
        n_marks += len(dots)

        # The last row with a cap, not simply the last row: the cap series has
        # holes at the end for a symbol whose latest filing has not landed, and
        # reading NaN there would drop the chip from exactly the names most
        # likely to be interesting.
        ser = market[sym]
        cap_v = cap_r = None
        for i in range(len(ser) - 1, -1, -1):
            if cap_v is None:
                cap_v = ser.cap(i)
            if cap_r is None:
                cap_r = ser.cap_rank(i)
            if cap_v is not None and cap_r is not None:
                break

        start, end = int(live[0]), int(live[-1])
        counts = {kd: sum(1 for t in trades_by_symbol.get(sym, []) if t.kind == kd)
                  for kd in KIND_COLOR}
        meta.append({
            "sym": sym, "from": str(dates[start])[:10],
            "ret": row[end] / row[start] - 1.0,
            "vs": row[end] / max(row[start], 1e-9),
            "level": float(row[end]), "entry": float(row[start]),
            "bench": is_bench, "n": counts,
            "cap": cap_v, "caprank": cap_r,
            "file": charts.get(sym, ""),
        })
        # The hit path is drawn first and carries a wide transparent stroke: a
        # 1.2px line is not a hover target, and pointer-events:stroke keeps the
        # area to the line itself rather than the box around it.
        # The label slot is filled after every line is known: where a name can
        # go depends on where all the others want to go. See _place_labels.
        ends.append({"i": len(groups), "sym": sym, "bench": is_bench,
                     "x": X(keep[-1]), "y": Y(row[keep[-1]]),
                     "caprank": cap_r})
        groups.append(
            f'<g class="{cls}" data-k="{len(meta) - 1}">'
            f'<path class="hit" d="{d}"/>'
            f'<path class="ln" d="{d}"/>'
            + "".join(dots) + '__LABEL__</g>')

    for e in _place_labels(ends, pad_t, pad_t + h):
        lead = ""
        if abs(e["y"] - e["ly"]) > 1.5 or (pad_l + w + 4) - e["x"] > 4:
            lead = (f'<line class="lead" x1="{e["x"] + 1.5:.1f}" y1="{e["y"]:.1f}" '
                    f'x2="{pad_l + w + 3:.1f}" y2="{e["ly"]:.1f}"/>')
        cr = e.get("caprank")
        if cr is None:
            # An index has no place in a ranking of companies -- market.py
            # excludes it from the cap ranking for that reason -- so it gets an
            # empty outline rather than a colour it has not earned.
            chip = (f'<rect class="cap none" x="{pad_l + w + 4:.1f}" '
                    f'y="{e["ly"] - 2.5:.1f}" width="5" height="5" rx="1.4"/>')
        else:
            colour, size = CAP_STEPS[min(4, int(cr * 5))]
            chip = (f'<rect class="cap" x="{pad_l + w + 6.5 - size / 2:.1f}" '
                    f'y="{e["ly"] - size / 2:.1f}" width="{size:.1f}" '
                    f'height="{size:.1f}" rx="1.4" fill="{colour}"/>')
        # The name is a HANDLE, not a caption. Finding one symbol among fifty
        # by hunting for its line is the problem the labels were added to solve,
        # and it is only half solved while the label itself cannot be pointed at.
        # Height 10 matches the label spacing exactly, so adjacent rows cannot
        # steal each other's hover.
        hit = (f'<rect class="lbhit" x="{pad_l + w + 2:.1f}" '
               f'y="{e["ly"] - 5:.1f}" width="{pad_r - 4}" height="10"/>')
        groups[e["i"]] = groups[e["i"]].replace(
            "__LABEL__",
            lead + chip + f'<text class="lb" x="{pad_l + w + 13:.1f}" '
                          f'y="{e["ly"] + 3:.1f}">{escape(e["sym"])}</text>' + hit)

    return _write(path, config, groups, grid, meta, W, H, n_marks,
                  dates, benchmark)


_CSS = r'''
:root {
  --ground:#F4F6FA; --surface:#FFF; --surface2:#EDF1F7; --line:#D3DBE7;
  --ink:#14202F; --ink2:#46566C; --ink3:#74839A;
  --accent:#1F4FD8; --base:#8A94A6;
  --pos:#1C6B4B; --neg:#B03030;
}
@media (prefers-color-scheme:dark){ :root{
  --ground:#0E141C; --surface:#151D28; --surface2:#1C2734; --line:#2B3949;
  --ink:#E4EBF4; --ink2:#A3B2C6; --ink3:#7386A0;
  --accent:#6E9BFF; --base:#7386A0;
  --pos:#5FCC9C; --neg:#F0857D;
} }
*{box-sizing:border-box}
body{background:var(--ground);color:var(--ink);margin:0;padding:28px 20px 60px;
  font:15px/1.6 "IBM Plex Sans",system-ui,sans-serif}
.wrap{max-width:1220px;margin:0 auto}
h1{font-size:21px;margin:0 0 4px;font-weight:600}
.sub{color:var(--ink2);font-size:13.5px;margin:0 0 18px}
.sub a{color:var(--accent)}
.card{background:var(--surface);border:1px solid var(--line);border-radius:10px;
  padding:14px 12px 8px;margin-bottom:14px}
svg{display:block;width:100%;height:auto}
.grid{stroke:var(--line);stroke-width:1;opacity:.5}
.warm{fill:var(--ink3);opacity:.07}
.edge{stroke:var(--ink3);stroke-width:1;stroke-dasharray:3 3;opacity:.7}
.warmt{fill:var(--ink3);font:500 10px "IBM Plex Mono",monospace;text-anchor:end}
.yt{fill:var(--ink3);font:500 10.5px "IBM Plex Mono",monospace;text-anchor:end}
.xt{fill:var(--ink3);font:500 10.5px "IBM Plex Mono",monospace;text-anchor:middle}

/* One line per symbol. The hit path is invisible and thick; the visible line
   stays thin so fifty of them can overlap without becoming a solid block. */
.ln{fill:none;stroke:var(--ink3);stroke-width:1.1;opacity:.42;
  stroke-linejoin:round;stroke-linecap:round}
.hit{fill:none;stroke:transparent;stroke-width:9;pointer-events:stroke;cursor:pointer}
.lbhit{fill:transparent;pointer-events:all;cursor:pointer}
.bench .ln{stroke:var(--accent);stroke-width:2.2;opacity:.95;stroke-dasharray:6 4}
.lb{fill:var(--ink3);font:500 9px "IBM Plex Mono",monospace;
  pointer-events:none;opacity:.75}
.lead{stroke:var(--ink3);stroke-width:.7;opacity:.3;pointer-events:none}
.cap{pointer-events:none;opacity:.9}
.cap.none{fill:none;stroke:var(--ink3);stroke-width:1;opacity:.5}
.bench .lb{fill:var(--accent);font-weight:600;opacity:1}
.d{opacity:.5;pointer-events:none}
.d.buy{fill:#22c55e} .d.sell{fill:#ef4444} .d.reinvest{fill:#f97316}

/* Hovering one line pushes every other one back rather than hiding it: the pack
   is the reference that makes a single line readable, so it has to stay
   visible, just quiet. */
svg.dim .sy:not(.on) .ln{opacity:.06}
svg.dim .sy:not(.on) .d{opacity:0}
svg.dim .sy:not(.on) .lb{opacity:.18}
svg.dim .sy:not(.on) .lead{opacity:.05}
svg.dim .sy:not(.on) .cap{opacity:.25}
.sy.mute .ln{opacity:.05}
.sy.mute .d{opacity:0}
.sy.mute .lb{opacity:.14}
.sy.mute .cap{opacity:.18}
.sy.mute .lead{opacity:.04}
.sy.found .ln{stroke:var(--accent);stroke-width:2.2;opacity:1}
.sy.found .d{opacity:1}
.sy.found .lb{fill:var(--accent);font-weight:600;opacity:1;font-size:11px}
.sy.on .ln{stroke:var(--accent);stroke-width:2.4;opacity:1}
.sy.on .d{opacity:1;r:4}
.sy.on .lb{fill:var(--accent);font-weight:600;opacity:1;font-size:11px}
.sy.on .lead{stroke:var(--accent);opacity:.8}

#tip{position:fixed;z-index:50;display:none;max-width:420px;background:var(--surface);
  color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:9px 12px;
  font-size:12.5px;line-height:1.55;box-shadow:0 6px 20px rgba(0,0,0,.18);
  font-family:"IBM Plex Mono",monospace}
#tip .th{font-weight:600;font-size:14px;margin-bottom:5px;display:flex;
  align-items:center;gap:8px}
#tip .r{display:flex;gap:10px;color:var(--ink2)}
#tip .r b{color:var(--ink);font-weight:500}
#tip .legend{margin-top:6px;display:flex;gap:12px;align-items:center}
a.open{display:inline-block;font-family:"IBM Plex Mono",monospace;font-size:11px;
  color:var(--accent);text-decoration:none;border:1px solid var(--line);
  border-radius:4px;padding:1px 8px;margin-left:auto;white-space:nowrap}
a.open:hover{background:var(--accent);border-color:var(--accent);color:#fff}
.pos{color:var(--pos)} .neg{color:var(--neg)}
.key{display:flex;gap:18px;flex-wrap:wrap;align-items:center;
  font-size:12.5px;color:var(--ink2);padding:8px 4px 2px}
.key i{display:inline-block;width:9px;height:9px;border-radius:50%;
  margin-right:6px;vertical-align:-1px}
.key .caps{display:inline-flex;gap:7px;align-items:flex-end;margin:0 4px}
.key .cs{display:inline-flex;flex-direction:column;align-items:center;gap:3px}
.key .cs b{display:inline-block;border-radius:1.5px}
.key .cs i{font-style:normal;font-size:9.5px;color:var(--ink3);
  font-family:"IBM Plex Mono",monospace}
.key .dash{display:inline-block;width:16px;border-top:2px dashed var(--accent);
  margin-right:6px;vertical-align:4px}
.find{display:flex;gap:10px;align-items:center;margin:0 0 12px}
#q{background:var(--surface);color:var(--ink);border:1px solid var(--line);
  border-radius:7px;padding:7px 11px;font:13.5px "IBM Plex Mono",monospace;
  width:220px;outline:none}
#q:focus{border-color:var(--accent)}
#qn{color:var(--ink3);font-size:12.5px;font-family:"IBM Plex Mono",monospace}
#qhits{display:flex;gap:5px;flex-wrap:wrap}
#qhits button{background:var(--surface2);color:var(--accent);border:1px solid var(--line);
  border-radius:5px;padding:2px 8px;font:12px "IBM Plex Mono",monospace;cursor:pointer}
#qhits button:hover{background:var(--accent);border-color:var(--accent);color:#fff}
.note{color:var(--ink2);font-size:13px;margin:16px 0 0}
.note b{color:var(--ink);font-weight:600}
'''

_JS = r'''
var META = __META__;
var tip = document.getElementById('tip');
var svg = document.querySelector('svg');
var timer = null;

function place(e){
  var x = e.clientX + 16, y = e.clientY + 16;
  tip.style.left = Math.max(8, Math.min(x, innerWidth - tip.offsetWidth - 12)) + 'px';
  tip.style.top = Math.max(8, Math.min(y, innerHeight - tip.offsetHeight - 12)) + 'px';
}
function money(v){ return v.toLocaleString('vi-VN', {maximumFractionDigits: 0}); }
function pct(v){ return (v >= 0 ? '+' : '') + (v * 100).toFixed(0) + '%'; }
function cap(v){
  return v >= 1e12 ? (v / 1e12).toFixed(1).replace('.', ',') + ' nghìn tỷ'
                   : (v / 1e9).toFixed(0) + ' tỷ';
}

function lineTip(m){
  var cls = m.ret >= 0 ? 'pos' : 'neg';
  var h = '<div class="th">' + m.sym
        + (m.file ? '<a class="open" href="' + m.file + '" target="_blank" '
                    + 'rel="noopener">mở</a>' : '') + '</div>'
    + '<div class="r">từ <b>' + m.from + '</b> · vào ở <b>'
      + m.entry.toFixed(0) + '</b> · nay <b>' + m.level.toFixed(0) + '</b></div>'
    + '<div class="r">so với rổ: <b class="' + cls + '">' + pct(m.ret) + '</b></div>'
    + (m.cap ? '<div class="r">vốn hoá <b>' + cap(m.cap) + '</b>'
               + (m.caprank != null
                  ? ' · phân vị <b>' + (m.caprank * 100).toFixed(0) + '</b>'
                    + ' <span style="color:var(--ink3)">(bậc '
                    + (Math.min(4, Math.floor(m.caprank * 5)) + 1) + '/5)</span>'
                  : '') + '</div>'
             : '');
  var n = m.n, parts = [];
  if (n.buy) parts.push('<span><i style="background:#22c55e"></i>' + n.buy + ' mua</span>');
  if (n.sell) parts.push('<span><i style="background:#ef4444"></i>' + n.sell + ' bán</span>');
  if (n.reinvest) parts.push('<span><i style="background:#f97316"></i>' + n.reinvest + ' tái đt</span>');
  h += parts.length
    ? '<div class="legend">' + parts.join('') + '</div>'
    : '<div class="r" style="color:var(--ink3)">chưa mua lần nào</div>';
  return h;
}

function tradeTip(t, m){
  var L = {buy: 'Mua', sell: 'Bán', reinvest: 'Tái đầu tư'};
  var C = {buy: '#22c55e', sell: '#ef4444', reinvest: '#f97316'};
  return '<div class="th"><i style="display:inline-block;width:10px;height:10px;'
       + 'border-radius:50%;background:' + C[t.kind] + '"></i>' + t.sym + ' · ' + L[t.kind]
       + (m && m.file ? '<a class="open" href="' + m.file + '" target="_blank" '
                        + 'rel="noopener">mở</a>' : '') + '</div>'
    + '<div class="r"><b>' + t.date + '</b> @ <b>' + money(t.price) + '</b></div>'
    + '<div class="r">tiền <b>' + money(t.amount) + 'đ</b> · <b>'
      + t.shares.toLocaleString('vi-VN', {maximumFractionDigits: 1}) + '</b> cp</div>';
}

function show(html, e){
  clearTimeout(timer); tip.innerHTML = html; tip.style.display = 'block'; place(e);
}
function scheduleHide(){
  timer = setTimeout(function(){ tip.style.display = 'none'; }, 300);
}
tip.addEventListener('mouseenter', function(){ clearTimeout(timer); });
tip.addEventListener('mouseleave', scheduleHide);

document.querySelectorAll('.sy').forEach(function(g){
  var m = META[+g.dataset.k];
  function enter(e){
    svg.classList.add('dim');
    document.querySelectorAll('.sy.on').forEach(function(o){ o.classList.remove('on'); });
    g.classList.add('on');
    // Raising the hovered group puts its markers on top of the fifty lines
    // crossing it, which at this density they otherwise hide behind.
    g.parentNode.appendChild(g);
    show(lineTip(m), e);
  }
  g.addEventListener('mouseenter', enter);
  g.addEventListener('mousemove', function(e){
    if (!g.classList.contains('on')) { enter(e); return; }
    // A marker under the cursor is the more specific answer, so it wins over
    // the line it sits on.
    var near = null, best = 8;
    g.querySelectorAll('.d').forEach(function(c){
      var r = c.getBoundingClientRect();
      var dx = e.clientX - (r.x + r.width / 2), dy = e.clientY - (r.y + r.height / 2);
      var dist = Math.sqrt(dx * dx + dy * dy);
      if (dist < best) { best = dist; near = c; }
    });
    show(near ? tradeTip(JSON.parse(near.dataset.t), m) : lineTip(m), e);
  });
  g.addEventListener('mouseleave', function(){
    svg.classList.remove('dim');
    g.classList.remove('on');
    scheduleHide();
  });
});
// SEARCH
//
//   Fifty-four lines and no way to ask "where is this one" was the gap the end
//   labels only half closed: you can read a name once you have found its line,
//   but you still cannot go the other way. Typing mutes everything that does not
//   match, so a symbol's whole path stands alone against the faded pack.
//
//   Matching is a substring, not a prefix, because these tickers are three or
//   four letters and a prefix match on such short names rules out too little to
//   be worth the surprise when "PB" fails to find LPB.
var q = document.getElementById('q');
var qn = document.getElementById('qn');
var qhits = document.getElementById('qhits');
var groups = [].slice.call(document.querySelectorAll('.sy'));

function applyFind(){
  var v = q.value.trim().toUpperCase();
  var found = [];
  groups.forEach(function(g){
    var sym = META[+g.dataset.k].sym.toUpperCase();
    var hit = v !== '' && sym.indexOf(v) !== -1;
    g.classList.toggle('found', hit);
    g.classList.toggle('mute', v !== '' && !hit);
    if (hit) found.push(g);
  });
  // Raise the matches so their markers are not buried under the fifty lines
  // crossing them.
  found.forEach(function(g){ g.parentNode.appendChild(g); });

  qn.textContent = v === '' ? groups.length + ' mã'
                            : found.length + '/' + groups.length + ' mã';
  qhits.innerHTML = '';
  if (v !== '' && found.length && found.length <= 8) {
    found.forEach(function(g){
      var m = META[+g.dataset.k];
      var b = document.createElement('button');
      b.textContent = m.sym;
      b.title = m.file ? 'Mở biểu đồ ' + m.sym : 'Chưa có biểu đồ';
      b.addEventListener('click', function(){
        if (m.file) window.open(m.file, '_blank', 'noopener');
      });
      qhits.appendChild(b);
    });
  }
}
q.addEventListener('input', applyFind);
applyFind();

document.addEventListener('keydown', function(e){
  if (e.key === 'Escape'){
    tip.style.display = 'none';
    svg.classList.remove('dim');
    if (q.value !== ''){ q.value = ''; applyFind(); }
  }
});
'''


def _write(path, config, groups, grid, meta, W, H, n_marks, dates, benchmark):
    """
    One page, everything inline.

    The symbol metadata goes out as JSON and the tooltip is built from it in the
    browser rather than being pre-rendered per line. Fifty-four pre-rendered
    tooltips is fifty-four copies of the same markup in the file, and the marker
    tooltips could not be pre-rendered at all -- there are hundreds of them.
    """
    title = getattr(config, "PLAN_NAME", "portfolio")
    n_sym = len(meta)
    traded = sum(1 for m in meta if sum(m["n"].values()))
    span = f"{str(dates[0])[:10]} - {str(dates[-1])[:10]}"

    js = _JS.replace("__META__", json.dumps(meta, ensure_ascii=False,
                                            separators=(",", ":")))
    # The legend carries the NUMBERS, not just an arrow. "small -> large" tells a
    # reader the direction but not where any single chip sits; the band does.
    cap_key = "".join(
        f'<span class="cs"><b style="background:{c};width:{sz:.1f}px;'
        f'height:{sz:.1f}px"></b><i>{band}</i></span>'
        for (c, sz), band in zip(CAP_STEPS, CAP_BANDS))
    body = f"""<!doctype html>
<html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)} — toàn cảnh</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>{_CSS}</style></head><body><div id="tip"></div>
<div class="wrap">
<h1>Toàn cảnh {n_sym} mã trên cùng một gốc</h1>
<p class="sub">{span} &middot; {traded} mã đã giao dịch &middot; {n_marks} lệnh
&middot; <a href="report.html">&larr; báo cáo tổng</a></p>

<div class="find">
  <input id="q" type="search" placeholder="tìm mã…" autocomplete="off" spellcheck="false">
  <span id="qn"></span>
  <span id="qhits"></span>
</div>

<div class="card">
<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">
{''.join(grid)}
{''.join(groups)}
</svg>
<div class="key">
  <span><i style="background:#22c55e"></i>mua</span>
  <span><i style="background:#ef4444"></i>bán</span>
  <span><i style="background:#f97316"></i>tái đầu tư</span>
  <span><span class="dash"></span>{escape(str(benchmark or '-'))}</span>
  <span style="display:inline-flex;align-items:flex-end;gap:4px">vốn hoá
    <span class="caps">{cap_key}</span>
    <span style="color:var(--ink3);font-size:11px">phân vị</span></span>
  <span style="color:var(--ink3)">di chuột vào một đường &mdash; hoặc vào tên mã ở đầu mút &mdash; để tách nó ra</span>
</div>
</div>

<p class="note">Trục dọc là <b>thang logarit</b>, không phải giá. Mỗi mã bắt đầu từ
<b>trung vị của các đường đang có</b> vào ngày nó lên sàn, nên khoảng cách dọc
giữa hai đường đọc được là <b>hiệu suất tương đối trong quãng cả hai cùng tồn
tại</b> &mdash; ngày niêm yết không cộng hay trừ điểm cho ai. Các đường lấy mẫu
mỗi {SAMPLE} phiên; các chấm giữ đúng ngày giao dịch thật.</p>
</div>
<script>{js}</script>
</body></html>"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path
