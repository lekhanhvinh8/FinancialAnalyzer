"""
Sweep the SELL arm's median window against its threshold: SELL_MEDIAN_WINDOW x q.

The sell arm compared the price to a 1000-day median because that number was
hardcoded. Buy and reinvest stay at their configured windows; only the sell arm
moves.

WHY q AND NOT PERCENT_SELL

  A fixed percentage is not the same condition at different windows. The price's
  distance from its own median widens as the window grows — 59 symbols, 182,522
  observations per window (analyze/median1000/dispersion.py):

      p95 = 1.290 * w^0.698      R^2 = 0.9991      w in 20..1000

  so the swept quantity is

      PERCENT_SELL = q * 1.290 * w^0.698

  and a column is roughly constant strictness at every window: q = 1.0 is that
  window's 95th percentile of price-to-median distance, q = 0 is "sell whenever
  the price is above its median at all". Live, w=1000 with PERCENT_SELL=60, is
  q = 0.375.

  Note the sign runs the opposite way from the buy sweep. Sell fires on
  pct > threshold, so a LARGER q sells LESS.

WHY THESE q VALUES

  The 1D sweep of PERCENT_SELL at w=1000 already narrowed the interesting band: 65
  to 80 is significant against live on the paired sign test, everything below 60
  and above 85 is not. In q terms that band is 0.41 to 0.50, so the grid is dense
  from 0.1 to 0.6 and thins out after. Negative q is dropped — it means selling
  while the price is below its own median, and the 1D sweep found that region
  uniformly bad (p >= 0.97 at every setting below zero).

WHY THE GRID STOPS AT 1000

  The reinvest arm still guards on index > 1000, so any sell window at or below
  that leaves the backtest start where it is and every cell sees the same symbols
  over the same bars. That floor is the reinvest arm's alone now — the buy arm no
  longer provides it, and the day reinvest gets its own window this stops being
  free.

WHAT IT FOUND: THE WINDOW CONTRIBUTES NOTHING

  52 symbols, 750 cells. Five beat live at p<0.05, and they are five consecutive
  windows all sitting in one q column:

      w     q   PERCENT_SELL   paired      p   nb   sells
    880   0.5           73.3    +3.05  0.004    1    2.12
    900   0.5           74.4    +2.53  0.004    2    2.12
    920   0.5           75.6    +2.23  0.007    2    2.15
    940   0.5           76.7    +1.56  0.007    2    2.12
    960   0.5           77.8    +1.55  0.016    1    2.12

  Those are not five window findings. They are the five windows where q=0.5
  happens to land inside the threshold band the 1D sweep already located, 65..80.
  The window is incidental; the threshold is the finding, and it is ~75.

  Extending q past p95 settled the other open question. The q=1.3 edge of the
  first run was still climbing at short windows, so the grid now runs to 4.0. It
  peaks and turns: at w=20 the mean reads 16, 30, 13, 7, 9, 6 across q = 1.3, 1.6,
  2.0, 2.5, 3.0, 4.0. Nothing in that region is significant against live.

TWO LIMITS OF THIS GRID, BOTH WORTH KNOWING BEFORE TRUSTING nb

  The neighbour count reads 0 everywhere at the 4+ threshold, and that is an
  artefact rather than a verdict. At w=900 the q step spans PERCENT_SELL 59.5 to
  74.4 — fifteen points, which is exactly as wide as the significant band itself.
  A band that wide can only ever occupy ONE column, so counting agreement in two
  directions cannot reach 4. nb only means something when the grid resolves the
  effect in both directions; here it does not.

  And the "live" cell is w=1000, q=0.4, which is PERCENT_SELL 64.1 rather than
  the actual 60 — the grid cannot express 60, that would need q=0.375. So every
  comparison in this table is against 64.1. It is why w=1000/q=0.5 reads p=0.063
  here while the 1D sweep's 80-against-60 reads p=0.036.

WATCH THE BUY COUNT

  With different windows on the two arms the buy and sell conditions stop being
  complementary even at equal percentages: the price can be 60% above its
  1000-day median and only 20% above its 200-day one. So the churn guard fires
  across most of this grid rather than in a corner of it, and the buys column
  falling is the guard working, not the strategy improving.

Usage:
    python analyze/median1000/sweep_sell_window.py             # all symbols
    python analyze/median1000/sweep_sell_window.py FPT STB     # a subset
    python analyze/median1000/sweep_sell_window.py --rescore
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
from analyze.runner import load_symbol_df, run_estimate
from analyze.median1000 import config
from analyze.median1000.factory import make_median_strategies, make_interval_strategies

WINDOWS = list(range(20, 1001, 20))                        # 50
QS      = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.8,
           1.0, 1.3, 1.6, 2.0, 2.5, 3.0, 4.0]              # 15
#          Dense where the 1D sweep found signal (q 0.41..0.50 is the significant
#          band at w=1000), and carried well past p95 because the first run was
#          still climbing at its q=1.3 edge for short windows: paired against
#          q=1.0 that edge was significant at w=20..120 (p 0.000..0.019) while
#          w>=140 had already saturated at 0.00. Live is q=0.375.

# p95 = C * w^A, from dispersion.py on 59 symbols, w in 20..1000, R^2 = 0.9991.
# Only ever used to place grid points.
P95_C, P95_A = 1.290, 0.698

OUT  = Path(__file__).parent / "sweep_sell_window.html"
RAW  = Path(__file__).parent / "sweep_sell_window_raw.json"
PROG = Path(__file__).parent / "sweep_sell_window_progress.html"


def threshold(q: float, w: int) -> float:
    return q * P95_C * (w ** P95_A)


def _key(w, q):
    return f"{w}|{q}"


def eval_symbol(sym: str):
    """Returns (sym, {key: (diff, buys, sells)}, note)."""
    try:
        df = load_symbol_df(sym)
        if len(df) < 1010:
            return sym, None, f"only {len(df)} rows"

        # Every swept window plus the 1000 the sell arm needs, in one query.
        crc = db.load_range_stats(sym, df, range_days=set(WINDOWS) | {1000})
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

        # One start index for every cell, and it does not move with the swept
        # window because the grid stops at 1000 and the reinvest arm needs that
        # anyway. Every cell is therefore judged on identical bars.
        #
        # Going past 1000 would change that: a cell at w=1500 would start 500 bars
        # later than one at w=200. It would cost 500 bars on every cell and drop
        # VNDIAMOND and VNFINLEAD below MIN_EVAL_BARS — 50 symbols instead of 52,
        # median eval bars 2315 instead of 2815. Not done; the q edge was the
        # open question, not the window.
        start_idx = max([1000] + [min(m) for m in (s1, s3, ri, z) if m])
        eval_bars = len(df) - start_idx
        if config.MIN_EVAL_BARS and eval_bars < config.MIN_EVAL_BARS:
            return sym, None, f"only {eval_bars} bars after warmup"

        b0, s0, r0 = make_interval_strategies()
        base = run_estimate(sym, df, config.INTERVAL_MONEY, b0, s0, r0, crc,
                            start_index=start_idx)["allRatioGrowth"]

        out = {}
        for w in WINDOWS:
            for q in QS:
                buy, sell, rei = make_median_strategies(
                    signal3_map=s3, signal1_map=s1, reinvest_signal1_map=ri,
                    zdev_map=z, percent_sell=threshold(q, w), sell_window=w)
                r = run_estimate(sym, df, config.INTERVAL_MONEY, buy, sell, rei,
                                 crc, start_index=start_idx)
                out[_key(w, q)] = (round(r["allRatioGrowth"] - base, 4),
                                   r["totalBuys"], r["totalSells"])
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


def _neighbours(w, q):
    """The up-to-8 cells around one, in grid coordinates rather than value."""
    iw, iq = WINDOWS.index(w), QS.index(q)
    out = []
    for dw in (-1, 0, 1):
        for dq in (-1, 0, 1):
            a, b = iw + dw, iq + dq
            if (dw or dq) and 0 <= a < len(WINDOWS) and 0 <= b < len(QS):
                out.append(_key(WINDOWS[a], QS[b]))
    return out


def aggregate(per_symbol: dict) -> dict:
    """
    {metric: {key: value}}.

    Three of these answer questions the plain aggregates cannot:

    paired  the median per-symbol difference against the live cell. Two aggregate
            columns must never be subtracted from each other — the symbol at the
            median of one is a different symbol from the one at the median of
            another, because changing a parameter reorders the ranking.
    pairp   the sign-test p for that difference.
    nb      how many of the cell's up-to-8 grid neighbours are also a significant
            improvement. The best of 750 cells looks good whether or not any edge
            exists; a cell whose neighbours agree is much harder to get by luck.
    """
    keys = [_key(w, q) for w in WINDOWS for q in QS]
    syms = [s for s in per_symbol if all(k in per_symbol[s] for k in keys)]
    grids = {m: {} for m in ("mean", "median", "win", "worst", "vote",
                             "paired", "pairp", "nb", "buys", "sells")}
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
        grids["mean"][k] = st.mean(vals)
        grids["median"][k] = st.median(vals)
        grids["win"][k] = 100 * sum(1 for v in vals if v > 0) / len(vals)
        grids["worst"][k] = vals[0]
        grids["buys"][k] = st.mean([per_symbol[s][k][1] for s in syms])
        grids["sells"][k] = st.mean([per_symbol[s][k][2] for s in syms])

    # Paired against the live cell, per symbol.
    live_w = getattr(config, "SELL_MEDIAN_WINDOW", 1000)
    live_q = min(QS, key=lambda q: abs(threshold(q, live_w) - config.PERCENT_SELL))
    live_k = _key(live_w, live_q)
    if live_k in keys:
        li = keys.index(live_k)
        base = m[:, li]
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
        for w in WINDOWS:
            for q in QS:
                k = _key(w, q)
                grids["nb"][k] = sum(1 for n in _neighbours(w, q) if n in good)
    return grids


def save_raw(per_symbol, skipped, elapsed):
    RAW.write_text(json.dumps({
        "meta": {"windows": WINDOWS, "qs": QS, "elapsed": elapsed,
                 "p95": [P95_C, P95_A],
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
<meta http-equiv="refresh" content="3"><title>buy window sweep</title><style>
body{{font-family:sans-serif;background:#0b1220;color:#e2e8f0;padding:24px}}
.bar{{background:#1e293b;border-radius:6px;height:22px;width:520px;overflow:hidden}}
.fill{{background:#22c55e;height:100%;width:{pct:.1f}%}}
.k{{color:#64748b}} .v{{font-weight:700}}</style></head><body>
<h2>buy window sweep &mdash; {'running' if done < total else 'done'}</h2>
<div class="bar"><div class="fill"></div></div>
<p><span class="v">{done} / {total}</span> symbols <span class="k">({pct:.0f}%)</span></p>
<p><span class="k">grid</span> <span class="v">{len(WINDOWS)}&times;{len(QS)}
= {len(WINDOWS)*len(QS)}</span> cells per symbol</p>
<p><span class="k">elapsed</span> <span class="v">{el/60:.1f} min</span>&nbsp;&nbsp;
<span class="k">eta</span> <span class="v">
{('%.1f min' % (eta/60)) if done and done < total else '&mdash;'}</span></p>
<p class="k">{note}</p></body></html>""", encoding="utf-8")


METRICS = {
    "mean":   ("Mean diff",    "%", +1),
    "paired": ("Paired vs live", "%", +1),
    "pairp":  ("Sign-test p",  "",  -1),
    "nb":     ("Neighbours agreeing", "", +1),
    "vote":   ("Cells beaten", "",  +1),
    "median": ("Median diff",  "%", +1),
    "win":    ("Win rate",     "%", +1),
    "worst":  ("Worst symbol", "%", +1),
    "buys":   ("Buys",         "",  0),
    "sells":  ("Sells",        "",  0),
}


def build_html(grids, n_syms, skipped, elapsed):
    live_w = getattr(config, "SELL_MEDIAN_WINDOW", 1000)
    live_q = config.PERCENT_SELL / (P95_C * live_w ** P95_A) if config.PERCENT_SELL else 0.0

    rows = ""
    for m, (label, unit, direction) in METRICS.items():
        g = grids.get(m) or {}
        if not g or direction == 0:
            continue
        # direction -1 means lower is better; Sign-test p reported its worst
        # cell as its best until this looked at it.
        bk, bv = (max if direction > 0 else min)(g.items(), key=lambda kv: kv[1])
        w, q = bk.split("|")
        rows += (f"<tr><td style='text-align:left'>{label}</td>"
                 f"<td><b>w={w}, q={q}</b></td>"
                 f"<td>PERCENT_SELL = {threshold(float(q), int(w)):.0f}</td>"
                 f"<td style='color:#4ade80'>{bv:+.2f}{unit}</td></tr>")

    skip_html = ("<p class='note'>Skipped: "
                 + ", ".join(f"{s} ({w})" for s, w in sorted(skipped)) + "</p>"
                 ) if skipped else ""

    data = {m: {k: (round(v, 3) if isinstance(v, float) else v)
                for k, v in (grids.get(m) or {}).items()} for m in METRICS}
    opts = "".join(f"<option value='{m}'{' selected' if m == 'mean' else ''}>{lbl}</option>"
                   for m, (lbl, _, _) in METRICS.items())

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>buy window sweep</title><style>
body{{font-family:sans-serif;background:#0b1220;color:#e2e8f0;padding:20px}}
table{{border-collapse:collapse;font-size:11px;margin:10px 0}}
th,td{{border:1px solid #1e293b;padding:4px 6px;text-align:center}}
th{{background:#111c30;color:#94a3b8}}
.note{{color:#94a3b8;font-size:13px;line-height:1.7;max-width:960px}}
select{{background:#111c30;color:#e2e8f0;border:1px solid #334155;padding:6px 10px;
  border-radius:6px;font-size:14px}}
.card{{background:#0f172a;border:1px solid #1e293b;border-radius:8px;
  padding:12px 16px;margin:12px 0;display:inline-block}}
.wrap{{overflow-x:auto}}
</style></head><body>
<h2>Sell arm: median window &times; threshold</h2>
<p class="note">{n_syms} symbols, {len(WINDOWS)}&times;{len(QS)} =
{len(WINDOWS)*len(QS)} cells, {elapsed/60:.1f} min. Buy and reinvest stay on their
configured windows; only the sell arm moves. The threshold is
<code>PERCENT_SELL = q &times; {P95_C} &times; w^{P95_A}</code>, so a column is
roughly constant strictness at every window &mdash; q=1.0 is that window's 95th
percentile of price-to-median distance, q=0 is &ldquo;only buy below the
median&rdquo;.<br>Live: <b>w={live_w}, PERCENT_SELL={config.PERCENT_SELL}</b>
(q &asymp; {live_q:.2f}).</p>
{skip_html}
<div class="card"><b>What each metric prefers</b>
<table><thead><tr><th>metric</th><th>best cell</th><th>threshold</th>
<th>value</th></tr></thead><tbody>{rows}</tbody></table>
<span class="note">Mean follows the largest symbol; vote gives every symbol one
vote and is blind to size. A cell that wins only one of them is telling you which
way it leans.</span></div>

<p><b>Heat map:</b> <select id="metric">{opts}</select></p>
<div class="wrap"><table id="grid"></table></div>
<p class="note"><b>Read the plateau, not the best cell.</b> The best of
{len(WINDOWS)*len(QS)} cells looks good whether or not any edge exists.</p>

<script>
const DATA = {json.dumps(data)};
const WS = {json.dumps(WINDOWS)}, QS = {json.dumps(QS)};
// Cell keys are built in Python and shipped as strings. Letting JS join them with
// w + '|' + q silently drops whole-valued q: Python writes "1000|1.0" and JS
// stringifies 1.0 as "1", so those columns render blank. It cost q=0 and q=1 here
// before anyone noticed.
const QK = {json.dumps([str(q) for q in QS])};
function render() {{
  const m = document.getElementById('metric').value;
  const g = DATA[m];
  const vals = Object.values(g).filter(v => v !== null && v !== undefined);
  if (!vals.length) return;
  const lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
  let h = '<thead><tr><th>w</th>';
  QS.forEach(q => {{ h += '<th>q=' + q + '</th>'; }});
  h += '</tr></thead><tbody>';
  WS.forEach(function(w) {{
    h += "<tr><th style='text-align:right'>" + w + '</th>';
    QS.forEach(function(q, j) {{
      const v = g[w + '|' + QK[j]];
      if (v === null || v === undefined) {{
        h += "<td style='color:#475569'>&mdash;</td>"; return;
      }}
      const f = hi === lo ? 0.5 : (v - lo) / (hi - lo);
      const bg = f >= 0.5
        ? 'rgba(34,197,94,' + (0.10 + 0.62 * (f - 0.5) * 2).toFixed(2) + ')'
        : 'rgba(239,68,68,' + (0.10 + 0.62 * (0.5 - f) * 2).toFixed(2) + ')';
      const txt = (m === 'vote') ? v.toFixed(0)
                : (m === 'buys' || m === 'sells') ? v.toFixed(0)
                : (v >= 0 ? '+' : '') + v.toFixed(0);
      h += "<td style='background:" + bg + "'>" + txt + '</td>';
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
    good = sorted(((pr[k], k) for k in pr if pr[k] > 0 and pp[k] < 0.05),
                  reverse=True)
    print(f"\ncells beating live with p<0.05: {len(good)}/{len(pr)}")
    if good:
        print(f"{'w':>5}{'q':>6}{'PERCENT_SELL':>14}{'paired':>9}{'p':>8}"
              f"{'nb':>4}{'mean':>7}{'vote':>6}{'sells':>7}")
        for _, k in good[:15]:
            w, q = k.split("|")
            w, q = int(w), float(q)
            print(f"{w:>5}{q:>6g}{threshold(q, w):14.1f}{pr[k]:+9.2f}{pp[k]:8.3f}"
                  f"{nb[k]:4d}{grids['mean'][k]:7.0f}{grids['vote'][k]:6d}"
                  f"{grids['sells'][k]:7.2f}")
        ws = sorted({int(k.split("|")[0]) for _, k in good})
        qs = sorted({float(k.split("|")[1]) for _, k in good})
        print(f"  windows {ws[0]}..{ws[-1]}   q {qs}")
        solid = [k for _, k in good if nb[k] >= 4]
        print(f"  with 4+ agreeing neighbours: {len(solid)}"
              f"{' — ' + ', '.join(solid[:6]) if solid else ' (none: isolated cells only)'}")

    OUT.write_text(build_html(grids, len(per_symbol), skipped, elapsed),
                   encoding="utf-8")

    g = grids["mean"]
    print(f"\nmean diff, {len(per_symbol)} symbols")
    print(f"{'w':>5} " + " ".join(f"{q:>6g}" for q in QS))
    for w in WINDOWS:
        print(f"{w:>5} " + " ".join(f"{g.get(_key(w,q), float('nan')):6.0f}" for q in QS))

    print("\nwhat each metric prefers:")
    for m, (label, unit, d) in METRICS.items():
        gg = grids.get(m) or {}
        if not gg or d == 0:
            continue
        bk, bv = (max if d > 0 else min)(gg.items(), key=lambda kv: kv[1])
        w, q = bk.split("|")
        print(f"  {label:<14} w={w:<5} q={q:<6} "
              f"PERCENT_SELL={threshold(float(q), int(w)):7.1f}  -> {bv:+.2f}{unit}")

    live_w = getattr(config, "SELL_MEDIAN_WINDOW", 1000)
    lq = min(QS, key=lambda q: abs(threshold(q, live_w) - config.PERCENT_SELL))
    lk = _key(live_w, lq)
    if lk in g:
        print(f"\nnearest cell to live (w={live_w}, PERCENT_SELL={config.PERCENT_SELL}): "
              f"q={lq} -> mean {g[lk]:+.1f}, vote {grids['vote'][lk]}")
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
    print(f"Sweeping {len(WINDOWS)}x{len(QS)} = {len(WINDOWS)*len(QS)} cells "
          f"over {len(syms)} symbols")
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
