"""
PERCENT_SELL x SELL_MIN_SIGNAL1 x SELL_SIGNAL1_WINDOW — one heat map per price
threshold, so the whole cube can be read by eye.

WHY A THIRD AXIS AFTER TWO FLAT RESULTS

  Two faces through the live point are already measured and both are flat:

      sweep_sell_signal1   window x k at PERCENT_SELL = 75, 340 cells. Every
                           window from 80 to 200 has a best paired median of
                           exactly +0.00, and that is the best of 17 k values.
      sweep_sell_slope     sell x threshold at window 120, 77 cells. Paired
                           median exactly 0.00 in 70 of 70.

  What neither touches is PERCENT_SELL != 75 AND window != 120 at the same time,
  and there is a mechanism that would live exactly there. The hypothesis is about
  LAG: the gate holds a sell while the trailing slope is still positive, and by
  the time it releases, part of the peak is gone. Lag is a function of window
  length above all — a 20-day slope turns quickly, a 200-day slope barely turns at
  all. If the price threshold and the gate interact anywhere, it is across window.

  The honest prior is still that nothing is there. Read WHAT IT FOUND at the
  bottom before spending another run on this family.

THE DEAD ZONE, WHICH IS THE REAL OBSTACLE AND IS NOT A GRID PROBLEM

  Most cells in both earlier sweeps have a paired median of exactly 0.00. Not
  small — zero. The cause is not resolution and cannot be fixed by refining the
  grid: diag_sell_gates counted 9,931 permitted bars producing 122 sells, about
  2.35 sells per symbol over fifteen years. Moving a gate rarely changes which bar
  of a run is first by enough to change any sell, so most symbols come out
  bit-identical and the median of the differences sits on zero.

  So the median alone cannot see a plateau here, and neither can `nb`, which is
  built on it. Two metrics are carried specifically for this:

      dec    how many symbols the cell moves AT ALL against live. A region where
             many symbols move is a region where the parameter does something,
             whatever the median says.
      updn   up minus down among those. The sign test's own statistic, and it
             keeps discriminating when half the sample is frozen.

  Read dec and updn before median. A block of cells with high dec and consistently
  positive updn is a real plateau even if every median in it reads 0.00.

THE GRID

      panels   PERCENT_SELL   30, 40, 50, 60, 70, 80, 85, 90, 100
                              85 is off the step-10 ladder on purpose: it is the
                              standing candidate, at +1.89 paired median with
                              p=0.0004 on two independent runs.
      rows     window         10, 20, 30, 50, 70, 100, 140, 200 — geometric, not
                              linear. The signal's own scale goes as w^-0.494, so
                              even steps waste cells at the long end where that
                              barely changes.
      cols     k              None, then -1.0 to 4.0 by 0.5.

  9 x 8 x 12 = 864 cells.

k IS NORMALISED AND MUST BE

      SELL_MIN_SIGNAL1 = k / sqrt(window)

  The dispersion study puts the slope's p95 at 3.991 * w^-0.494, which is w^-1/2
  to within measurement error. A raw threshold therefore means something entirely
  different at window 10 and at window 200 — 0.228 blocks almost nothing at 10 and
  almost everything at 200 — and a cube built on raw thresholds would be measuring
  the normalisation rather than the gate. k is the same sweep_sell_signal1 used,
  so its 340 cells remain directly comparable to the w-row through 75 here.

THE ONE STRUCTURAL TRAP IN THIS GRID

  PERCENT_BUY = 60. The buy arm fires when the price is BELOW 60% over its median;
  the sell arm fires when it is ABOVE PERCENT_SELL.

      PERCENT_SELL >= 60    the two zones do not overlap. This is the regime every
                            result so far was measured in.
      PERCENT_SELL = 50     they overlap by 10 points
                   = 40     by 20
                   = 30     by 30

  In the overlap both conditions are true on the same bar, and the churn guard
  starts biting: the factory hands the buy arm a reference to the sell arm and it
  stands down on any bar the sell fires, gates included. Without it the position
  would liquidate and re-enter the same day.

  So the bottom three panels are running a DIFFERENT MECHANISM from the rest, not
  merely a looser threshold, and their numbers are not on the same footing as the
  panels at 60 and above. They are kept because nobody has ever measured that
  region, and labelled because comparing across the boundary without knowing is
  how a mechanism change gets read as a parameter effect.

WARMUP IS FREE ON THE WINDOW AXIS

  start_idx is pinned at max(1000, max(WINS) - 1, ...) so every cell shares it.
  The longest window here is 200 and the median window is 1000, so the slope
  warmup never binds and no panel gains bars from a shorter window. sweep_
  reinvest_top is the reminder of what happens otherwise: 72 points of an apparent
  gain turned out to be a start index that had moved.

Usage:
    python analyze/median1000/sweep_sell_slope3d.py             # all symbols
    python analyze/median1000/sweep_sell_slope3d.py FPT GMD     # a subset
    python analyze/median1000/sweep_sell_slope3d.py --rescore
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import json
import math
import statistics as st
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

import pandas as pd

import database as db
from analyze.runner import load_symbol_df, run_estimate
from analyze.median1000 import config
from analyze.median1000.factory import make_median_strategies, make_interval_strategies

SELLS = [30, 40, 50, 60, 70, 80, 85, 90, 100]                 # 9 panels
WINS  = [10, 20, 30, 50, 70, 100, 140, 200]                   # 8 rows
KS    = [None] + [round(-1.0 + 0.5 * i, 1) for i in range(11)]  # 12 cols, -1.0..4.0

LIVE = (config.PERCENT_SELL, config.SELL_SIGNAL1_WINDOW, 2.5)
#      k = 2.5 at window 120 is SELL_MIN_SIGNAL1 = 0.228, the shipped value.
#      Window 120 is NOT on the WINS ladder, so the live cell is not in the grid —
#      see LIVE_REF below. Putting 120 in only to host the reference would bend a
#      geometric axis around one value and buy nothing: the reference has to be
#      computed either way because k=2.5 at w=100 is 0.250, not 0.228.

OUT  = Path(__file__).parent / "sweep_sell_slope3d.html"
RAW  = Path(__file__).parent / "sweep_sell_slope3d_raw.json"
PROG = Path(__file__).parent / "sweep_sell_slope3d_progress.html"

LIVE_REF = "live"
#      Every cell is paired against the ACTUAL shipped configuration, run once per
#      symbol as its own entry rather than borrowed from the nearest grid cell.
#      Nearest-cell would silently compare against 0.250 and call the difference a
#      finding.


def _key(s, w, k):
    return f"{s}|{w}|{k}"


def _threshold(k, w):
    """None keeps the gate off; otherwise the normalisation described above."""
    return None if k is None else k / math.sqrt(w)


def eval_symbol(sym: str):
    """Returns (sym, {key: (diff, buys, sells, reinvests)}, note)."""
    try:
        df = load_symbol_df(sym)
        if len(df) < 1010:
            return sym, None, f"only {len(df)} rows"

        buy_w  = getattr(config, "BUY_MEDIAN_WINDOW", 1000)
        sell_w = getattr(config, "SELL_MEDIAN_WINDOW", 1000)
        crc = db.load_range_stats(symbol=sym, df=df,
                                  range_days={1000, buy_w, sell_w})
        if not crc:
            return sym, None, "no range_stats"

        d2i = {pd.Timestamp(r["time"]): i for i, r in df.iterrows()}

        def sig(window, col):
            d = db.load_trend_signals(sym, window_days=window)
            out = {}
            if not d.empty:
                for dt, v in d[col].items():
                    i = d2i.get(pd.Timestamp(dt))
                    if i is not None:
                        out[i] = float(v)
            return out

        s1_by_w = {w: sig(w, "signal1_slope") for w in WINS}
        missing = [w for w, m in s1_by_w.items() if not m]
        if missing:
            return sym, None, f"no signal1 at window(s) {missing}"
        # The live configuration's own window, which need not be on the ladder.
        s1_live = (s1_by_w[config.SELL_SIGNAL1_WINDOW]
                   if config.SELL_SIGNAL1_WINDOW in s1_by_w
                   else sig(config.SELL_SIGNAL1_WINDOW, "signal1_slope"))
        if not s1_live:
            return sym, None, f"no signal1 at live window {config.SELL_SIGNAL1_WINDOW}"

        s3 = sig(1000, "signal3_sharpe") if config.MIN_SIGNAL3 is not None else {}
        ri = ({} if config.REINVEST_MIN_SIGNAL1 is None
              else sig(config.REINVEST_SIGNAL1_WINDOW, "signal1_slope"))
        z = {}
        if config.SELL_MIN_ZDEV is not None:
            zd = db.load_zdev(sym, 1000, config.SELL_ZDEV_WINDOW)
            if zd.empty:
                return sym, None, f"no z_dev at stat_window={config.SELL_ZDEV_WINDOW}"
            for dt, v in zd["z_dev"].items():
                i = d2i.get(pd.Timestamp(dt))
                if i is not None and v is not None:
                    z[i] = float(v)

        # One start index for every cell. max(WINS) - 1 is 199 and the median
        # window is 1000, so the slope axis never moves it — but it is written out
        # rather than assumed, because the moment someone puts 1200 on the ladder
        # it does move and the whole cube would silently stop being comparable.
        start_idx = max([1000, buy_w, sell_w, max(WINS) - 1,
                         config.SELL_SIGNAL1_WINDOW - 1]
                        + [min(m) for m in (s3, ri, z) if m]
                        + [min(m) for m in s1_by_w.values() if m]
                        + ([min(s1_live)] if s1_live else []))
        eval_bars = len(df) - start_idx
        if config.MIN_EVAL_BARS and eval_bars < config.MIN_EVAL_BARS:
            return sym, None, f"only {eval_bars} bars after warmup"

        b0, s0, r0 = make_interval_strategies()
        base = run_estimate(sym, df, config.INTERVAL_MONEY, b0, s0, r0, crc,
                            start_index=start_idx)["allRatioGrowth"]

        def cell(signal1_map, min_signal1, percent_sell):
            buy, sell, rei = make_median_strategies(
                signal3_map=s3, signal1_map=signal1_map,
                reinvest_signal1_map=ri, zdev_map=z,
                percent_sell=percent_sell, min_signal1=min_signal1)
            r = run_estimate(sym, df, config.INTERVAL_MONEY, buy, sell, rei, crc,
                             start_index=start_idx)
            return (round(r["allRatioGrowth"] - base, 4),
                    r["totalBuys"], r["totalSells"], r["totalReinvest"])

        out = {LIVE_REF: cell(s1_live, config.SELL_MIN_SIGNAL1, config.PERCENT_SELL)}
        for ps in SELLS:
            for w in WINS:
                s1 = s1_by_w[w]
                for k in KS:
                    out[_key(ps, w, k)] = cell(s1, _threshold(k, w), ps)
        return sym, out, None
    except Exception as e:
        return sym, None, f"{type(e).__name__}: {e}"


def apply_exclusions(per_symbol: dict) -> dict:
    """
    Applied at scoring, not before computing, so RAW keeps every symbol and the
    exclusion can be changed by re-scoring. The first reading of sweep_sell_slope
    forgot this step and quoted means contaminated by VIX, which alone swings 574
    points between two cells — enough to flip the sign of any mean in the table.
    """
    drop = {s.upper() for s in getattr(config, "EXCLUDE_SYMBOLS", [])}
    hit = sorted(drop & {s.upper() for s in per_symbol})
    if not hit:
        return per_symbol
    kept = {s: d for s, d in per_symbol.items() if s.upper() not in drop}
    print(f"  EXCLUDE_SYMBOLS {hit}: {len(per_symbol)} -> {len(kept)} symbols")
    return kept


def _neighbours(ps, w, k):
    """
    The up-to-26 cells around one, in grid coordinates rather than value.

    26 and not 8: in three dimensions a cell has 3^3 - 1 neighbours. Using the
    2D count here would call a cell isolated whenever its support sat in the
    adjacent panel, which is precisely the support this sweep exists to look for.
    """
    i, j, l = SELLS.index(ps), WINS.index(w), KS.index(k)
    out = []
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            for dl in (-1, 0, 1):
                a, b, c = i + di, j + dj, l + dl
                if (di or dj or dl) and 0 <= a < len(SELLS) \
                        and 0 <= b < len(WINS) and 0 <= c < len(KS):
                    out.append(_key(SELLS[a], WINS[b], KS[c]))
    return out


# name -> (label, unit, direction). direction +1 = higher is better, -1 = lower,
# 0 = descriptive only and never reported as a "best cell".
METRICS = {
    "paired": ("Paired median vs live", "%", +1),
    "dec":    ("Symbols moved",         "",  +1),
    "updn":   ("Up minus down",         "",  +1),
    "nb":     ("Neighbours agreeing",   "",  +1),
    "pairp":  ("Sign-test p",           "",  -1),
    "pmean":  ("Paired mean vs live",   "%", +1),
    "median": ("Median diff",           "%", +1),
    "mean":   ("Mean diff",             "%", +1),
    "worst":  ("Worst symbol",          "%", +1),
    "sells":  ("Sells",                 "",   0),
}


def aggregate(per_symbol: dict) -> dict:
    syms = sorted(per_symbol)
    grids = {m: {} for m in METRICS}
    keys = [_key(s, w, k) for s in SELLS for w in WINS for k in KS]

    for key in keys:
        vals = sorted(per_symbol[s][key][0] for s in syms)
        grids["median"][key] = st.median(vals)
        grids["mean"][key]   = st.mean(vals)
        grids["worst"][key]  = vals[0]
        grids["sells"][key]  = st.mean(per_symbol[s][key][2] for s in syms)

        d = [per_symbol[s][key][0] - per_symbol[s][LIVE_REF][0] for s in syms]
        up = sum(1 for v in d if v > 1e-9)
        dn = sum(1 for v in d if v < -1e-9)
        dec = up + dn
        grids["paired"][key] = st.median(d)
        grids["pmean"][key]  = st.mean(d)
        grids["dec"][key]    = dec
        grids["updn"][key]   = up - dn
        grids["pairp"][key]  = (sum(math.comb(dec, j) for j in range(up, dec + 1))
                                / 2 ** dec if dec else 1.0)

    # A cell "agrees" if it beats live on the sign test. Deliberately NOT
    # "paired median > 0": in this dead zone that condition is false almost
    # everywhere and nb would read 0 across the whole cube, which looks like a
    # verdict and is an artefact of the statistic.
    good = {k for k in keys if grids["updn"][k] > 0 and grids["pairp"][k] < 0.05}
    for ps in SELLS:
        for w in WINS:
            for k in KS:
                key = _key(ps, w, k)
                grids["nb"][key] = sum(1 for n in _neighbours(ps, w, k) if n in good)
    return grids


def save_raw(per_symbol, skipped, elapsed):
    RAW.write_text(json.dumps({
        "meta": {
            # Positional layout of every cell tuple. Two orders grew up across
            # these sweeps and they differ only by position, so a reader that
            # assumes the wrong one reports buys as reinvests and says nothing.
            "fields": ["diff", "buys", "sells", "reinvests"],
            "sells": SELLS, "windows": WINS, "ks": KS,
            "live": list(LIVE), "live_ref": LIVE_REF,
            "elapsed": elapsed,
            "config": {c: getattr(config, c) for c in dir(config)
                       if c.isupper() and not c.startswith("_")}},
        "skipped": skipped, "results": per_symbol,
    }), encoding="utf-8")


def load_raw():
    raw = json.loads(RAW.read_text(encoding="utf-8"))
    per = {s: {k: tuple(v) for k, v in d.items()} for s, d in raw["results"].items()}
    return per, [tuple(x) for x in raw["skipped"]], raw["meta"].get("elapsed", 0.0)


def write_progress(done, total, started, note=""):
    el = time.time() - started
    pct = 100 * done / total if total else 0
    eta = (el / done * (total - done)) if done else 0
    n = len(SELLS) * len(WINS) * len(KS)
    PROG.write_text(f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<meta http-equiv="refresh" content="3"><title>sell x slope x window sweep</title><style>
body{{font-family:sans-serif;background:#0b1220;color:#e2e8f0;padding:24px}}
.bar{{background:#1e293b;border-radius:6px;height:22px;width:520px;overflow:hidden}}
.fill{{background:#22c55e;height:100%;width:{pct:.1f}%}}
.k{{color:#64748b}} .v{{font-weight:700}}</style></head><body>
<h2>sell &times; slope &times; window &mdash; {'running' if done < total else 'done'}</h2>
<div class="bar"><div class="fill"></div></div>
<p><span class="v">{done} / {total}</span> symbols <span class="k">({pct:.0f}%)</span></p>
<p><span class="k">grid</span> <span class="v">{len(SELLS)}&times;{len(WINS)}&times;{len(KS)}
= {n}</span> cells per symbol</p>
<p><span class="k">elapsed</span> <span class="v">{el/60:.1f} min</span>&nbsp;&nbsp;
<span class="k">eta</span> <span class="v">{eta/60:.1f} min</span></p>
<p class="k">{note}</p>
</body></html>""", encoding="utf-8")


def build_html(grids, n_syms, skipped, elapsed):
    n = len(SELLS) * len(WINS) * len(KS)
    rows = ""
    for m, (label, unit, direction) in METRICS.items():
        g = grids.get(m) or {}
        if not g or direction == 0:
            continue
        bk, bv = (max if direction > 0 else min)(g.items(), key=lambda kv: kv[1])
        s, w, k = bk.split("|")
        rows += (f"<tr><td style='text-align:left'>{label}</td>"
                 f"<td><b>sell={s}, w={w}, k={k}</b></td>"
                 f"<td style='color:#4ade80'>{bv:+.2f}{unit}</td></tr>")

    skip_html = ("<p class='note'>Skipped: "
                 + ", ".join(f"{s} ({w})" for s, w in sorted(skipped)) + "</p>"
                 ) if skipped else ""

    data = {m: {k: (round(v, 3) if isinstance(v, float) else v)
                for k, v in (grids.get(m) or {}).items()} for m in METRICS}
    opts = "".join(f"<option value='{m}'{' selected' if m == 'dec' else ''}>{lbl}</option>"
                   for m, (lbl, _, _) in METRICS.items())
    overlap = [s for s in SELLS if s < getattr(config, "PERCENT_BUY", 60)]

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>sell x slope x window sweep</title><style>
body{{font-family:sans-serif;background:#0b1220;color:#e2e8f0;padding:20px}}
table{{border-collapse:collapse;font-size:11px;margin:4px 0}}
th,td{{border:1px solid #1e293b;padding:3px 5px;text-align:center}}
th{{background:#111c30;color:#94a3b8;font-weight:600}}
.note{{color:#94a3b8;font-size:13px;line-height:1.7;max-width:1000px}}
select{{background:#111c30;color:#e2e8f0;border:1px solid #334155;padding:6px 10px;
  border-radius:6px;font-size:14px}}
.card{{background:#0f172a;border:1px solid #1e293b;border-radius:8px;
  padding:12px 16px;margin:12px 12px 12px 0;display:inline-block;vertical-align:top}}
.panels{{display:flex;flex-wrap:wrap;gap:14px}}
.panel{{background:#0f172a;border:1px solid #1e293b;border-radius:8px;padding:8px 10px}}
.panel h4{{margin:2px 0 6px;font-size:13px;color:#e2e8f0}}
.panel.overlap{{border-color:#7c2d12}}
.panel.overlap h4::after{{content:' — buy/sell zones overlap';color:#fb923c;
  font-weight:400;font-size:11px}}
.live{{outline:2px solid #60a5fa}}
</style></head><body>
<h2>PERCENT_SELL &times; SELL_MIN_SIGNAL1 &times; SELL_SIGNAL1_WINDOW</h2>
<p class="note">{n_syms} symbols, {len(SELLS)}&times;{len(WINS)}&times;{len(KS)} =
{n} cells, {elapsed/60:.1f} min. One panel per PERCENT_SELL; inside a panel, rows
are the slope window and columns are k. The colour scale is SHARED across panels,
so a panel that looks pale is pale.<br>
<b>k is normalised:</b> SELL_MIN_SIGNAL1 = k / sqrt(window). The slope's spread
goes as w<sup>-0.494</sup>, so a raw threshold would mean something different in
every row and the cube would be measuring the normalisation.<br>
<b>Read <i>Symbols moved</i> and <i>Up minus down</i> before <i>Paired median</i>.</b>
The arm makes about 2.35 sells per symbol in fifteen years, so most parameter
moves leave most symbols bit-identical and the paired median sits on exactly 0.00
almost everywhere. A block with high <i>Symbols moved</i> and consistently
positive <i>Up minus down</i> is a real plateau even when every median in it
reads zero.<br>
<b>{n} cells means about {n*5//100} of them clear p&lt;0.05 by chance.</b> Never
believe a single best cell; check <i>Neighbours agreeing</i>, which counts how
many of a cell's 26 three-dimensional neighbours also beat live on the sign
test.<br>
<b>Panels {', '.join(str(s) for s in overlap)} run a different mechanism.</b>
PERCENT_BUY = {getattr(config, 'PERCENT_BUY', 60)}, so below that the sell zone
sits inside the buy zone, both conditions are true on the same bar, and the churn
guard starts biting — the buy arm stands down wherever the sell fires. Those
panels are outlined and are not on the same footing as the rest.<br>
Every cell is paired against the shipped configuration
(PERCENT_SELL={LIVE[0]}, window={LIVE[1]}, k={LIVE[2]} &rarr;
SELL_MIN_SIGNAL1={config.SELL_MIN_SIGNAL1}), run once per symbol as its own entry.
Window {LIVE[1]} is not on the ladder, so no grid cell is the live cell and none
is outlined as one.</p>
{skip_html}

<div class="card"><b>What each metric prefers</b>
<table><thead><tr><th>metric</th><th>best cell</th>
<th>value</th></tr></thead><tbody>{rows}</tbody></table>
<span class="note">Mean follows the largest symbol, median does not. A cell
winning only one of them tells you which.</span></div>

<p><b>Metric:</b> <select id="metric">{opts}</select></p>
<div class="panels" id="panels"></div>

<script>
const DATA = {json.dumps(data)};
// Axis labels are the SAME strings Python used to build the keys. KS carries None
// and json.dumps writes that as null; joining null with '|' in JS gives "null"
// while the key holds "None", which blanked whole rows and columns in two earlier
// sweeps. The fix, again: never let JS reconstruct a key.
const SS = {json.dumps([str(x) for x in SELLS])};
const WS = {json.dumps([str(x) for x in WINS])};
const KKS = {json.dumps([str(x) for x in KS])};
const OVERLAP = {json.dumps([str(x) for x in overlap])};

function render() {{
  const m = document.getElementById('metric').value;
  const g = DATA[m];
  const vals = Object.values(g).filter(v => v !== null && v !== undefined);
  if (!vals.length) return;
  // One scale for the whole cube, not per panel: per-panel scaling makes every
  // panel look equally interesting, which is the opposite of what small multiples
  // are for.
  const lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
  let out = '';
  SS.forEach(function(s) {{
    const over = OVERLAP.indexOf(s) >= 0;
    let h = '<div class="panel' + (over ? ' overlap' : '') + '"><h4>PERCENT_SELL = '
          + s + '</h4><table><thead><tr><th>w \\\\ k</th>';
    KKS.forEach(k => {{ h += '<th>' + k + '</th>'; }});
    h += '</tr></thead><tbody>';
    WS.forEach(function(w) {{
      h += '<tr><th>' + w + '</th>';
      KKS.forEach(function(k) {{
        const v = g[s + '|' + w + '|' + k];
        if (v === undefined || v === null) {{ h += '<td>&mdash;</td>'; return; }}
        const t = hi > lo ? (v - lo) / (hi - lo) : 0.5;
        const bg = 'hsl(' + Math.round(210 - 210 * t) + ',70%,' +
                   Math.round(18 + 26 * t) + '%)';
        h += '<td style="background:' + bg + '">' + v.toFixed(2) + '</td>';
      }});
      h += '</tr>';
    }});
    out += h + '</tbody></table></div>';
  }});
  document.getElementById('panels').innerHTML = out;
}}
document.getElementById('metric').addEventListener('change', render);
render();
</script>
</body></html>"""


def _report(per_symbol, skipped, elapsed):
    per_symbol = apply_exclusions(per_symbol)
    grids = aggregate(per_symbol)
    n = len(SELLS) * len(WINS) * len(KS)
    keys = [_key(s, w, k) for s in SELLS for w in WINS for k in KS]

    zero = sum(1 for k in keys if abs(grids["paired"][k]) < 1e-9)
    print(f"\ncells whose paired median is exactly 0.00: {zero}/{n} "
          f"({100*zero/n:.0f}%) — this is the dead zone, read dec/updn instead")
    sig = [k for k in keys if grids["updn"][k] > 0 and grids["pairp"][k] < 0.05]
    print(f"cells beating live on the sign test at p<0.05: {len(sig)}/{n} "
          f"(about {n*5//100} expected by chance)")
    solid = [k for k in sig if grids["nb"][k] >= 13]
    print(f"  of those, with 13+ of 26 neighbours agreeing: {len(solid)}"
          + (f" — {', '.join(solid[:8])}" if solid else " (none: isolated cells only)"))

    for name, title in (("dec", "symbols moved"), ("updn", "up minus down"),
                        ("paired", "paired median vs live")):
        g = grids[name]
        print(f"\n{title}   rows=PERCENT_SELL  cols=window  (best k per cell)")
        print(f"{'':>6} " + " ".join(f"{w:>7}" for w in WINS))
        for s in SELLS:
            best = [max((g[_key(s, w, k)] for k in KS)) for w in WINS]
            print(f"{s:>6} " + " ".join(f"{v:7.2f}" for v in best))

    print("\nwhat each metric prefers:")
    for m, (label, unit, d) in METRICS.items():
        if d == 0:
            continue
        g = grids[m]
        bk, bv = (max if d > 0 else min)(g.items(), key=lambda kv: kv[1])
        s, w, k = bk.split("|")
        print(f"  {label:<24} sell={s:<5} w={w:<5} k={k:<6} -> {bv:+.2f}{unit}")

    OUT.write_text(build_html(grids, len(per_symbol), skipped, elapsed),
                   encoding="utf-8")
    print(f"\nreport -> {OUT}")


def main():
    args  = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]

    if "--rescore" in flags:
        per, skipped, elapsed = load_raw()
        print(f"re-scoring {len(per)} symbols from {RAW.name}")
        _report(per, skipped, elapsed)
        return

    syms = [s.upper() for s in args] or db.list_symbols()
    n = len(SELLS) * len(WINS) * len(KS)
    print(f"Sweeping {len(SELLS)}x{len(WINS)}x{len(KS)} = {n} cells "
          f"over {len(syms)} symbols")
    print(f"paired against the shipped config: PERCENT_SELL={config.PERCENT_SELL}, "
          f"window={config.SELL_SIGNAL1_WINDOW}, "
          f"SELL_MIN_SIGNAL1={config.SELL_MIN_SIGNAL1}")

    per_symbol, skipped = {}, []
    started = time.time()
    write_progress(0, len(syms), started, "starting")
    with ProcessPoolExecutor() as ex:
        futs = {ex.submit(eval_symbol, s): s for s in syms}
        for i, fut in enumerate(as_completed(futs), 1):
            sym, out, note = fut.result()
            if out:
                per_symbol[sym] = out
            else:
                skipped.append((sym, note))
            print(f"  [{i}/{len(syms)}] {sym}{'' if out else '  SKIP: ' + str(note)}",
                  flush=True)
            write_progress(i, len(syms), started, f"last: {sym}")

    elapsed = time.time() - started
    save_raw(per_symbol, skipped, elapsed)
    print(f"\nraw -> {RAW}   ({elapsed/60:.1f} min)")
    _report(per_symbol, skipped, elapsed)
    print(f"re-score with: python {Path(__file__).name} --rescore")


if __name__ == "__main__":
    db.init_db()
    main()
