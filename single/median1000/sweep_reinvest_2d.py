"""
Sweep the two reinvest price triggers against each other:
PERCENT_REINVEST x PERCENT_REINVEST_TOP.

Both have been measured alone and both came out a tie against the other. This asks
the one thing neither could: do they COMPLEMENT each other? The arm ORs them, so a
pair can in principle cover symbols that neither covers by itself.

WHY THERE IS A REASON TO EXPECT IT

  They are good on different symbols, which is the only situation where an OR is
  worth anything.

    PERCENT_REINVEST = 10   asks "is the price back near its usual level". It is
                            what carries the typical symbol: median +20.14 against
                            the top trigger's +22.04, and it wins the 35-way round
                            robin on 23 head-to-heads.
    PERCENT_REINVEST_TOP    asks "has the price fallen far from its peak". Its
                            aggregate lead is three symbols wide — VND +430,
                            HPG +265, HAG +240 — and its worst symbol is -121
                            against the median trigger's family at -155.7.

  One is broad and shallow, the other narrow and deep, and they fire on different
  days by construction: the days the top trigger adds are days the price is still
  at least 10% ABOVE its median, which is exactly where the median trigger is
  silent.

WHAT "COMPLEMENTARY" HAS TO MEAN HERE

  Not "the cell scores well" — a pair can score well because one of its halves is
  carrying it, and reading the heat map alone would call that success. It has to
  beat what either half does ALONE.

  So every pair is also compared against its own row's None column and its own
  column's None row, and scored against whichever of those two is BETTER. Beating
  the weaker half proves nothing. That table sits beside the heat map and is the
  one to read first.

THE GRID

      PERCENT_REINVEST      None, -10, 0, 5, 10, 20, 35
                            None is the trigger off, which turns the row into
                            "top trigger only". 10 is live. The 1D sweep found
                            -5..+35 all within a few points, so the row spans that
                            band rather than hunting a new optimum.
      PERCENT_REINVEST_TOP  None, -30 .. -70
                            None turns the column into "median trigger only". The
                            1D sweep put everything useful between -30 and -70,
                            with -50 the best cell.

  Live (10, None) is a cell in this grid, so it is the reference every other cell
  is paired against, and the None row and None column give the two "alone" arms
  the synergy table needs. Neither axis moves the warmup.

  The timeout stays on everywhere except (None, None), where the factory falls
  back to the base class and the valve goes with it — that one cell is a floor,
  not a candidate.

Usage:
    python single/median1000/sweep_reinvest_2d.py             # all symbols
    python single/median1000/sweep_reinvest_2d.py FPT GMD     # a subset
    python single/median1000/sweep_reinvest_2d.py --rescore
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import json
import math
import statistics as st
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np
import pandas as pd

import database as db
from single.runner import load_symbol_df, run_estimate
from single.median1000 import config
from single.median1000.factory import make_median_strategies, make_interval_strategies

MEDS = [None, -10, 0, 5, 10, 20, 35]                    # 7
TOPS = [None, -30, -35, -40, -45, -50, -55, -60, -70]   # 9
#       Live is (75, 10). The reinvest axis runs past 60 because a 2-symbol smoke
#       test on FPT and GMD put its best cell exactly on a 60 ceiling, and a grid
#       whose winner sits on its own edge has not found an optimum, only a wall.
#
#       Five cells have PERCENT_REINVEST >= PERCENT_SELL. They are not degenerate:
#       the factory hands reinvest a reference to the sell arm, so on a bar where
#       the sell would fire the reinvest stands down, and what those cells mean is
#       "return whenever we are not actually selling". Worth having in the grid,
#       and worth knowing they are a different shape from the rest of it.

LIVE = (config.PERCENT_REINVEST, config.PERCENT_REINVEST_TOP)

OUT  = Path(__file__).parent / "sweep_reinvest_2d.html"
RAW  = Path(__file__).parent / "sweep_reinvest_2d_raw.json"
PROG = Path(__file__).parent / "sweep_reinvest_2d_progress.html"


def _key(s, r):
    return f"{s}|{r}"


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

        # A gate that is off is not loaded, so its warmup cannot push the start
        # index forward for a filter nobody is applying.
        s3 = sig(1000, "signal3_sharpe") if config.MIN_SIGNAL3 is not None else {}
        s1 = (sig(config.SELL_SIGNAL1_WINDOW, "signal1_slope")
              if config.SELL_MIN_SIGNAL1 is not None else {})
        ri = (s1 if (s1 and config.REINVEST_SIGNAL1_WINDOW == config.SELL_SIGNAL1_WINDOW)
              else (sig(config.REINVEST_SIGNAL1_WINDOW, "signal1_slope")
                    if config.REINVEST_MIN_SIGNAL1 is not None else {}))
        z = {}
        if config.SELL_MIN_ZDEV is not None:
            zd = db.load_zdev(sym, 1000, config.SELL_ZDEV_WINDOW)
            if zd.empty:
                return sym, None, f"no z_dev at stat_window={config.SELL_ZDEV_WINDOW}"
            for dt, v in zd["z_dev"].items():
                i = d2i.get(pd.Timestamp(dt))
                if i is not None and v is not None:
                    z[i] = float(v)

        # Neither swept axis is a window, so this is the same for every cell.
        start_idx = max([1000, buy_w, sell_w]
                        + [min(m) for m in (s1, s3, ri, z) if m])
        eval_bars = len(df) - start_idx
        if config.MIN_EVAL_BARS and eval_bars < config.MIN_EVAL_BARS:
            return sym, None, f"only {eval_bars} bars after warmup"

        b0, s0, r0 = make_interval_strategies()
        base = run_estimate(sym, df, config.INTERVAL_MONEY, b0, s0, r0, crc,
                            start_index=start_idx)["allRatioGrowth"]

        out = {}
        for pm in MEDS:
            for pt in TOPS:
                buy, sell, rei = make_median_strategies(
                    signal3_map=s3, signal1_map=s1, reinvest_signal1_map=ri,
                    zdev_map=z, percent_reinvest=pm, percent_reinvest_top=pt)
                r = run_estimate(sym, df, config.INTERVAL_MONEY, buy, sell, rei,
                                 crc, start_index=start_idx)
                out[_key(pm, pt)] = (round(r["allRatioGrowth"] - base, 4),
                                     r["totalBuys"], r["totalSells"],
                                     r["totalReinvest"])
        return sym, out, None
    except Exception as e:
        return sym, None, f"{type(e).__name__}: {e}"


def apply_exclusions(per_symbol: dict) -> dict:
    drop = {s.upper() for s in getattr(config, "EXCLUDE_SYMBOLS", [])}
    hit = sorted(drop & {s.upper() for s in per_symbol})
    if not hit:
        return per_symbol
    kept = {s: d for s, d in per_symbol.items() if s.upper() not in drop}
    print(f"  EXCLUDE_SYMBOLS {hit}: {len(per_symbol)} -> {len(kept)} symbols")
    return kept


def _neighbours(s, r):
    """The up-to-8 cells around one, in grid coordinates rather than value."""
    i, j = MEDS.index(s), TOPS.index(r)
    out = []
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            a, b = i + di, j + dj
            if (di or dj) and 0 <= a < len(MEDS) and 0 <= b < len(TOPS):
                out.append(_key(MEDS[a], TOPS[b]))
    return out


def aggregate(per_symbol: dict) -> dict:
    """
    {metric: {key: value}}.

    paired  the median per-symbol difference against the live cell. Never
            subtract two aggregate columns instead: changing a parameter
            reorders the symbols, so the symbol at the median of one column is
            not the symbol at the median of the other.
    pairp   the sign-test p for that difference, over decided symbols only.
    nb      how many of the cell's up-to-8 grid neighbours also beat live
            significantly. The best of 56 cells looks good whether or not any
            edge exists; a cell its neighbours agree with is harder to get by
            luck.
    reis    mean reinvests per symbol. The hypothesis this sweep exists to test
            predicts this rises as the dead zone narrows, because the price
            condition starts firing where only the timeout used to reach.
    """
    keys = [_key(s, r) for s in MEDS for r in TOPS]
    syms = [s for s in per_symbol if all(k in per_symbol[s] for k in keys)]
    grids = {m: {} for m in ("mean", "median", "win", "worst", "vote",
                             "paired", "pairp", "nb", "buys", "sells", "reis")}
    if not syms:
        return grids

    m = np.array([[per_symbol[s][k][0] for k in keys] for s in syms])
    # Round robin, one vote per symbol: immune to a single dominant symbol, and
    # blind to size. Read it beside the mean, never instead of it.
    for i, k in enumerate(keys):
        col = m[:, i][:, None]
        grids["vote"][k] = int(((col - m > 1e-9).sum(axis=0)
                                > (m - col > 1e-9).sum(axis=0)).sum())
    for i, k in enumerate(keys):
        vals = sorted(m[:, i].tolist())
        grids["mean"][k]   = st.mean(vals)
        grids["median"][k] = st.median(vals)
        grids["win"][k]    = 100 * sum(1 for v in vals if v > 0) / len(vals)
        grids["worst"][k]  = vals[0]
        grids["buys"][k]   = st.mean([per_symbol[s][k][1] for s in syms])
        grids["sells"][k]  = st.mean([per_symbol[s][k][2] for s in syms])
        grids["reis"][k]   = st.mean([per_symbol[s][k][3] for s in syms])

    live_k = _key(*LIVE)
    if live_k in keys:
        base = m[:, keys.index(live_k)]
        for i, k in enumerate(keys):
            d = m[:, i] - base
            up  = int((d > 1e-9).sum())
            dec = int((np.abs(d) > 1e-9).sum())
            grids["paired"][k] = float(np.median(d))
            grids["pairp"][k] = (
                sum(math.comb(dec, j) for j in range(up, dec + 1)) / 2 ** dec
                if dec else 1.0)
        good = {k for k in keys
                if grids["paired"][k] > 0 and grids["pairp"][k] < 0.05}
        for s in MEDS:
            for r in TOPS:
                k = _key(s, r)
                grids["nb"][k] = sum(1 for n in _neighbours(s, r) if n in good)
    return grids


def synergy(per_symbol: dict) -> list:
    """
    [(key, med_alone, top_alone, both, gain_over_best_alone, up, down, p)].

    The question this sweep exists for. "Complementary" is not "the cell scores
    well" — a cell can score well purely because one of its two triggers is good.
    It means the pair beats what either does ALONE, so each cell is compared
    against its own row's None column and its own column's None row, and the
    comparison that counts is against whichever of those two is better.

    Every figure is a paired per-symbol median, never a difference of aggregates.
    """
    syms = sorted(per_symbol)
    def med_of_diff(a, b):
        d = [per_symbol[s][a][0] - per_symbol[s][b][0] for s in syms]
        up  = sum(1 for v in d if v >  1e-9)
        dn  = sum(1 for v in d if v < -1e-9)
        dec = up + dn
        p = (sum(math.comb(dec, j) for j in range(up, dec + 1)) / 2 ** dec
             if dec else 1.0)
        return st.median(d), up, dn, p
    def agg(k):
        return st.mean(per_symbol[s][k][0] for s in syms)

    out = []
    for pm in MEDS:
        for pt in TOPS:
            if pm is None or pt is None:
                continue                      # not a pair
            k        = _key(pm, pt)
            med_only = _key(pm, None)
            top_only = _key(None, pt)
            if not all(x in per_symbol[syms[0]] for x in (k, med_only, top_only)):
                continue
            # Beat the BETTER of the two halves, not the average of them: a pair
            # that only beats its weaker half has added nothing.
            better = med_only if agg(med_only) >= agg(top_only) else top_only
            g, up, dn, p = med_of_diff(k, better)
            out.append((k, agg(med_only), agg(top_only), agg(k), g, up, dn, p))
    return sorted(out, key=lambda r: -r[4])


def save_raw(per_symbol, skipped, elapsed):
    RAW.write_text(json.dumps({
        "meta": {
            # Positional layout of every cell tuple. Two orders grew up across these
            # sweeps and they differ only by position, so a reader that assumes the
            # wrong one reports buys as reinvests and says nothing.
            "fields": ["diff", "buys", "sells", "reinvests"],
            "sells": MEDS, "reis": TOPS, "live": list(LIVE),
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
    PROG.write_text(f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<meta http-equiv="refresh" content="3"><title>reinvest median x top sweep</title><style>
body{{font-family:sans-serif;background:#0b1220;color:#e2e8f0;padding:24px}}
.bar{{background:#1e293b;border-radius:6px;height:22px;width:520px;overflow:hidden}}
.fill{{background:#22c55e;height:100%;width:{pct:.1f}%}}
.k{{color:#64748b}} .v{{font-weight:700}}</style></head><body>
<h2>sell &times; reinvest sweep &mdash; {'running' if done < total else 'done'}</h2>
<div class="bar"><div class="fill"></div></div>
<p><span class="v">{done} / {total}</span> symbols <span class="k">({pct:.0f}%)</span></p>
<p><span class="k">grid</span> <span class="v">{len(MEDS)}&times;{len(TOPS)}
= {len(MEDS)*len(TOPS)}</span> cells per symbol</p>
<p><span class="k">elapsed</span> <span class="v">{el/60:.1f} min</span>&nbsp;&nbsp;
<span class="k">eta</span> <span class="v">
{('%.1f min' % (eta/60)) if done and done < total else '&mdash;'}</span></p>
<p class="k">{note}</p></body></html>""", encoding="utf-8")


METRICS = {
    "mean":   ("Mean diff",           "%", +1),
    "paired": ("Paired vs live",      "%", +1),
    "pairp":  ("Sign-test p",         "",  -1),
    "nb":     ("Neighbours agreeing", "",  +1),
    "vote":   ("Cells beaten",        "",  +1),
    "median": ("Median diff",         "%", +1),
    "win":    ("Win rate",            "%", +1),
    "worst":  ("Worst symbol",        "%", +1),
    "buys":   ("Buys",                "",  0),
    "sells":  ("Sells",               "",  0),
    "reis":   ("Reinvests",           "",  0),
}


def build_html(grids, per_symbol, n_syms, skipped, elapsed):
    rows = ""
    for m, (label, unit, direction) in METRICS.items():
        g = grids.get(m) or {}
        if not g or direction == 0:
            continue
        # direction -1 means lower is better; reporting the sign-test's worst
        # cell as its best is the mistake this guards against.
        bk, bv = (max if direction > 0 else min)(g.items(), key=lambda kv: kv[1])
        s, r = bk.split("|")
        rows += (f"<tr><td style='text-align:left'>{label}</td>"
                 f"<td><b>median={s}, top={r}</b></td>"

                 f"<td style='color:#4ade80'>{bv:+.2f}{unit}</td></tr>")

    grows = "".join(
        f"<tr><td>{k.replace('|', ' / ')}</td>"
        f"<td>{ma:+.1f}</td><td>{ta:+.1f}</td><td>{bo:+.1f}</td>"
        f"<td style='color:{'#4ade80' if g > 0 and p < 0.05 else '#f87171' if g < 0 else '#e2e8f0'}"
        f";font-weight:600'>{g:+.2f}</td>"
        f"<td style='color:#64748b'>{up}/{up+dn}  p={p:.3f}</td></tr>"
        for k, ma, ta, bo, g, up, dn, p in synergy(per_symbol)[:14])

    skip_html = ("<p class='note'>Skipped: "
                 + ", ".join(f"{s} ({w})" for s, w in sorted(skipped)) + "</p>"
                 ) if skipped else ""

    data = {m: {k: (round(v, 3) if isinstance(v, float) else v)
                for k, v in (grids.get(m) or {}).items()} for m in METRICS}
    opts = "".join(f"<option value='{m}'{' selected' if m == 'paired' else ''}>{lbl}</option>"
                   for m, (lbl, _, _) in METRICS.items())

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>reinvest median x top sweep</title><style>
body{{font-family:sans-serif;background:#0b1220;color:#e2e8f0;padding:20px}}
table{{border-collapse:collapse;font-size:12px;margin:10px 0}}
th,td{{border:1px solid #1e293b;padding:5px 8px;text-align:center}}
th{{background:#111c30;color:#94a3b8}}
.note{{color:#94a3b8;font-size:13px;line-height:1.7;max-width:980px}}
select{{background:#111c30;color:#e2e8f0;border:1px solid #334155;padding:6px 10px;
  border-radius:6px;font-size:14px}}
.card{{background:#0f172a;border:1px solid #1e293b;border-radius:8px;
  padding:12px 16px;margin:12px 12px 12px 0;display:inline-block;vertical-align:top}}
.wrap{{overflow-x:auto}}
code{{color:#e2e8f0}}
</style></head><body>
<h2>Sell threshold &times; reinvest threshold</h2>
<p class="note">{n_syms} symbols, {len(MEDS)}&times;{len(TOPS)} =
{len(MEDS)*len(TOPS)} cells, {elapsed/60:.1f} min. Everything else stays at its
configured value; only the two reinvest price triggers move, and neither touches
the warmup.<br>
<b>What this asks.</b> Both triggers have been measured alone and both tied. They
are good on different symbols — the median one carries the typical symbol, the top
one carries VND, HPG and HAG and has the better tail — and the arm ORs them, so
the open question is whether the pair covers what neither covers by itself.<br>
<b>Read the synergy table before the heat map.</b> A cell can score well because
one of its halves is carrying it; complementary means beating what either half
does ALONE.<br>
Live cell: <b>PERCENT_REINVEST={LIVE[0]}, PERCENT_REINVEST_TOP={LIVE[1]}</b> —
every paired figure is against it. The None row is "top trigger only", the None
column is "median trigger only", and (None, None) is a floor rather than a
candidate: the factory drops the whole arm there, timeout included.</p>
{skip_html}

<div class="card"><b>What each metric prefers</b>
<table><thead><tr><th>metric</th><th>best cell</th>
<th>value</th></tr></thead><tbody>{rows}</tbody></table>
<span class="note">Mean follows the largest symbol; vote gives every symbol one
vote and is blind to size. A cell winning only one of them tells you which.</span>
</div>

<div class="card"><b>Do the two actually complement each other?</b>
<table><thead><tr><th>median / top</th><th>median alone</th><th>top alone</th>
<th>both</th><th>vs better half</th><th>up / p</th></tr></thead>
<tbody>{grows}</tbody></table>
<span class="note">A cell scoring well proves nothing on its own — one of its two
triggers may be carrying it. Complementary means the pair beats what either does
ALONE, so the last two columns compare each cell against whichever of its own
row-None and column-None cells is better. The first three columns are means, for
orientation only; the comparison is a paired per-symbol median. Top 14 by gain.
</span></div>

<p><b>Heat map:</b> <select id="metric">{opts}</select>
<span class="note">rows = PERCENT_REINVEST, columns = PERCENT_REINVEST_TOP</span></p>
<div class="wrap"><table id="grid"></table></div>
<p class="note"><b>Read the plateau, not the best cell.</b> The best of
{len(MEDS)*len(TOPS)} cells looks good whether or not any edge exists &mdash;
about 3 of them reach p&lt;0.05 by chance alone. Check <i>Neighbours agreeing</i>
before believing any single cell, and check <i>Reinvests</i> to see whether a
winning cell actually changed the re-entry behaviour or just moved the sells.</p>

<script>
const DATA = {json.dumps(data)};
// Labels for display, and the SAME strings Python used to build the keys. Both
// axes carry None, and json.dumps writes that as null: joining null with '|' in
// JS gives "null|-30" while the key is "None|-30", which blanked the entire None
// row and the entire None column — the two the synergy table is built on. Same
// trap as the whole-valued q that blanked columns in the earlier sweeps, so the
// fix is the same: never let JS reconstruct a key.
const SS = {json.dumps([str(x) for x in MEDS])};
const RS = {json.dumps([str(x) for x in TOPS])};
const LIVE = {json.dumps([str(x) for x in LIVE])};
function render() {{
  const m = document.getElementById('metric').value;
  const g = DATA[m];
  const vals = Object.values(g).filter(v => v !== null && v !== undefined);
  if (!vals.length) return;
  const lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
  let h = '<thead><tr><th>median \\\\ top</th>';
  RS.forEach(r => {{ h += '<th>' + r + '</th>'; }});
  h += '</tr></thead><tbody>';
  SS.forEach(function(s) {{
    h += "<tr><th style='text-align:right'>" + s + '</th>';
    RS.forEach(function(r) {{
      const v = g[s + '|' + r];
      if (v === null || v === undefined) {{
        h += "<td style='color:#475569'>&mdash;</td>"; return;
      }}
      const f = hi === lo ? 0.5 : (v - lo) / (hi - lo);
      const bg = f >= 0.5
        ? 'rgba(34,197,94,' + (0.10 + 0.62 * (f - 0.5) * 2).toFixed(2) + ')'
        : 'rgba(239,68,68,' + (0.10 + 0.62 * (0.5 - f) * 2).toFixed(2) + ')';
      const dec = (m === 'pairp') ? 3 : (m === 'vote' || m === 'buys'
                  || m === 'sells' || m === 'reis') ? 1 : 0;
      const txt = (v >= 0 && m !== 'pairp' ? '+' : '') + v.toFixed(dec);
      const live = (s === LIVE[0] && r === LIVE[1]);
      h += "<td style='background:" + bg
         + (live ? ';outline:2px solid #60a5fa;outline-offset:-2px' : '')
         + "' title='median " + s + ", top " + r + "'>"
         + txt + '</td>';
    }});
    h += '</tr>';
  }});
  document.getElementById('grid').innerHTML = h + '</tbody>';
}}
document.getElementById('metric').addEventListener('change', render);
render();
</script>
</body></html>"""


def _report(per_symbol, skipped, elapsed):
    per_symbol = apply_exclusions(per_symbol)
    if not per_symbol:
        print("every symbol was excluded"); return
    grids = aggregate(per_symbol)
    pr, pp, nb = grids["paired"], grids["pairp"], grids["nb"]
    live_k = _key(*LIVE)

    print(f"\nlive cell  PERCENT_REINVEST={LIVE[0]}, PERCENT_REINVEST_TOP={LIVE[1]}  "
          f"  mean {grids['mean'].get(live_k, float('nan')):+.2f}  "
          f"sells {grids['sells'].get(live_k, float('nan')):.2f}  "
          f"reinvests {grids['reis'].get(live_k, float('nan')):.2f}")

    good = sorted(((pr[k], k) for k in pr if pr[k] > 0 and pp[k] < 0.05), reverse=True)
    print(f"\ncells beating live with p<0.05: {len(good)}/{len(pr)}")
    if good:
        print(f"{'median':>7}{'top':>7}{'paired':>9}{'p':>8}{'nb':>4}"
              f"{'mean':>8}{'vote':>6}{'sells':>7}{'reis':>7}")
        for _, k in good[:15]:
            s, r = k.split("|")
            print(f"{s:>7}{r:>7}{pr[k]:+9.2f}{pp[k]:8.3f}{nb[k]:4d}"
                  f"{grids['mean'][k]:8.1f}{grids['vote'][k]:6d}"
                  f"{grids['sells'][k]:7.2f}{grids['reis'][k]:7.2f}")
        solid = [k for _, k in good if nb[k] >= 4]
        print(f"  with 4+ agreeing neighbours: {len(solid)}"
              f"{' — ' + ', '.join(solid[:6]) if solid else ' (none: isolated cells only)'}")
    print(f"  cells whose paired median is exactly 0.00: "
          f"{sum(1 for k in pr if abs(pr[k]) < 1e-9)}/{len(pr)}")

    syn = synergy(per_symbol)
    print("\ndo the two complement each other?  each pair vs its own BETTER half")
    print(f"{'median/top':>12}{'med alone':>11}{'top alone':>11}{'both':>9}"
          f"{'gain':>9}{'up/dec':>9}{'p':>8}")
    for k, ma, ta, bo, g, up, dn, pv in syn[:12]:
        print(f"{k:>12}{ma:>11.1f}{ta:>11.1f}{bo:>9.1f}{g:>+9.2f}"
              f"{f'{up}/{up+dn}':>9}{pv:>8.3f}")
    win = [r for r in syn if r[4] > 1e-9 and r[7] < 0.05]
    print(f"\n  pairs beating their own better half at p<0.05: {len(win)}/{len(syn)}")
    for k, ma, ta, bo, g, up, dn, pv in win:
        print(f"    {k:>10}  gain {g:+.2f}  p {pv:.3f}  ({up}/{up+dn})")
    print(f"  pairs whose gain is exactly 0.00: "
          f"{sum(1 for r in syn if abs(r[4]) < 1e-9)}/{len(syn)}")

    for name, title in (("paired", "paired vs live"), ("reis", "mean reinvests")):
        g = grids[name]
        # Both axes carry None, so every label goes through str() rather than a
        # numeric format.
        print(f"\n{title}   rows=PERCENT_REINVEST  cols=PERCENT_REINVEST_TOP")
        print(f"{'':>6} " + " ".join(f"{str(r):>7}" for r in TOPS))
        for s in MEDS:
            print(f"{str(s):>6} " + " ".join(f"{g.get(_key(s,r), float('nan')):7.2f}"
                                             for r in TOPS))

    print("\nwhat each metric prefers:")
    for m, (label, unit, d) in METRICS.items():
        gg = grids.get(m) or {}
        if not gg or d == 0:
            continue
        bk, bv = (max if d > 0 else min)(gg.items(), key=lambda kv: kv[1])
        s, r = bk.split("|")
        print(f"  {label:<20} median={s:<5} top={r:<5}"
              f" -> {bv:+.2f}{unit}")

    OUT.write_text(build_html(grids, per_symbol, len(per_symbol),
                              skipped, elapsed),
                   encoding="utf-8")
    print(f"\nreport -> {OUT}")


def main():
    args  = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]

    if "--rescore" in flags:
        if not RAW.exists():
            print(f"no raw data at {RAW} — run the sweep first"); return
        per, skipped, elapsed = load_raw()
        print(f"re-scoring {len(per)} symbols from {RAW.name}")
        _report(per, skipped, elapsed)
        return

    syms = [s.upper() for s in args] or db.list_symbols()
    print(f"Sweeping {len(MEDS)}x{len(TOPS)} = {len(MEDS)*len(TOPS)} cells "
          f"over {len(syms)} symbols")
    print(f"live cell (PERCENT_REINVEST={LIVE[0]}, PERCENT_REINVEST_TOP={LIVE[1]}) is "
          f"{'in' if _key(*LIVE) in [_key(s, r) for s in MEDS for r in TOPS] else 'NOT IN'}"
          f" the grid")
    t0 = time.time()
    per_symbol, skipped, done = {}, [], 0
    write_progress(0, len(syms), t0, "starting workers…")
    print(f"progress -> {PROG}")

    with ProcessPoolExecutor() as ex:
        futures = {ex.submit(eval_symbol, s): s for s in syms}
        for fut in as_completed(futures):
            sym, res, note = fut.result()
            done += 1
            if res is None:
                skipped.append((sym, note))
                print(f"[{done}/{len(syms)}] {sym} skipped — {note}", flush=True)
            else:
                per_symbol[sym] = res
                print(f"[{done}/{len(syms)}] {sym} ok", flush=True)
            write_progress(done, len(syms), t0, f"last: {sym}")

    if not per_symbol:
        print("nothing to report"); return
    elapsed = time.time() - t0
    save_raw(per_symbol, skipped, elapsed)
    print(f"raw -> {RAW}")
    _report(per_symbol, skipped, elapsed)
    print(f"({elapsed/60:.1f} min)   re-score with: "
          f"python {Path(__file__).name} --rescore")


if __name__ == "__main__":
    main()
