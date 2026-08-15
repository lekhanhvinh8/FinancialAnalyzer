"""
Sweep the z_dev sell gate: SELL_ZDEV_WINDOW x SELL_MIN_ZDEV.

The one gate never measured on its own. It is currently OFF, so this sweep turns
it back on cell by cell; everything else stays at its configured value.

WHY IT WAS TURNED OFF, AND WHY THAT IS NOT AN ANSWER

  z_dev was switched off in 73b7ce6 for a reason that had nothing to do with its
  merit: a 700-bar stat window on top of the 1000-bar median put the backtest
  start at 1699 and cost 12 of 57 symbols. A quarter of the universe for one gate.

  The performance figure quoted alongside it, mean -2.50, was signal3 AND z_dev
  measured together. signal3 alone has since measured at +6.04, so that -2.50
  cannot be read as z_dev's, and it cannot be subtracted out either — overlapping
  gates do not compose additively.

  So the open question is narrow and specific: at a SHORT stat window, where the
  warmup is affordable, does this gate earn anything?

NO NORMALISATION — MEASURED, NOT ASSUMED

  z_dev is a z-score, so its spread should not depend on the stat window, and it
  does not: p95 = 2.218 * w^0.009 with R^2 = 0.27, which is a flat line with
  noise (dispersion.py zdev). Percentiles are steady across w = 50..700:

      p5     p25     p50     p75     p95
      -2.30  -1.18   -0.15   +1.05   +2.31

  Note the distribution is WIDER than a unit normal, ±2.3 rather than ±1.64, and
  the centre sits slightly below zero. So the raw threshold is directly
  comparable across windows — no k/sqrt(w), no q. This is the one quantity of the
  four in dispersion.py that needed no reparameterisation.

  The old 0.9 blocked a sell whenever z_dev was at or below it, which off that
  distribution is roughly 72% of sell-eligible days. Very restrictive.

POLARITY

  Opposite to the two momentum gates. They block while a reading is HIGH ("trend
  intact, hold"); this one blocks while z_dev is LOW, because a low reading means
  the price is above its trailing median only because the business grew into it
  rather than because it is dislocated. So a HIGHER threshold blocks MORE and
  sells LESS — the reverse of MIN_SIGNAL3 and SELL_MIN_SIGNAL1.

THE WINDOW IS CAPPED AT 400 ON PURPOSE

  Every cell shares one start index, fixed at 1000 + the longest swept window, so
  no cell is judged on more bars than its neighbour. That makes the cap a direct
  cost: 400 puts the start at 1400 and leaves ~50 symbols, against 52 today.
  Including the old 700 would push it to 1700 and take the same 12 symbols that
  caused the gate to be switched off in the first place — which is exactly the
  hypothesis under test, so it is excluded rather than paid for.

WHAT IT FOUND: NOTHING, AND NOW THAT IS MEASURED

  50 symbols, 66 cells plus the off cell, 6.5 min. Reference is the gate off:
  mean +38.16, median +15.25, 1.92 sells per symbol.

  Not one cell beats it. 62 of the 66 have a paired median of exactly 0.00 — at
  almost every setting the gate changes nothing for the typical symbol. The single
  cell reaching p<0.05, w=100 with min_zdev -1.5, has 5 decided symbols out of 50;
  all five improve, for a mean of +1.84. With 66 cells about three would reach
  p<0.05 by chance.

  The strict end is the only place with a real effect and it is the wrong sign: at
  min_zdev >= 2 the gate blocks most sells (1.92 per symbol down to 0.58) and the
  mean falls to between -20 and -30.

  So the answer to the question this sweep existed for — does it earn anything at
  a stat window short enough to afford — is no. The gate stays off.

Usage:
    python analyze/median1000/sweep_zdev.py             # all symbols
    python analyze/median1000/sweep_zdev.py FPT STB     # a subset
    python analyze/median1000/sweep_zdev.py --rescore
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

WINDOWS = [50, 100, 150, 200, 300, 400]                    # 6
QS      = [-2.5, -2.0, -1.5, -1.0, -0.5, 0.0,
           0.5, 0.9, 1.4, 2.0, 2.5]                        # 11 raw thresholds
#          Dense where the 1D sweep found signal (q 0.41..0.50 is the significant
#          band at w=1000), and carried well past p95 because the first run was
#          still climbing at its q=1.3 edge for short windows: paired against
#          q=1.0 that edge was significant at w=20..120 (p 0.000..0.019) while
#          w>=140 had already saturated at 0.00. Live is q=0.375.

# OFF_KEY is the reference every cell is compared against: the gate switched off,
# which is what config currently has. There is no "live cell" in this grid because
# there is no live setting to put in it.
OFF_KEY = "off"

OUT  = Path(__file__).parent / "sweep_zdev.html"
RAW  = Path(__file__).parent / "sweep_zdev_raw.json"
PROG = Path(__file__).parent / "sweep_zdev_progress.html"


# The grid holds raw thresholds, so there is nothing to convert. Kept as an
# identity rather than deleted because the shared report code calls it.
def threshold(q: float, w: int) -> float:
    return q


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
        # One z_dev map per swept stat window. Loaded unconditionally: this is
        # the swept quantity, and config currently has the gate off.
        z_by_w = {}
        for w in WINDOWS:
            zd = db.load_zdev(sym, 1000, w)
            if zd.empty:
                return sym, None, f"no z_dev at stat_window={w}"
            m = {}
            for dt, v in zd["z_dev"].items():
                i = d2i.get(pd.Timestamp(dt))
                if i is not None and v is not None:
                    m[i] = float(v)
            if not m:
                return sym, None, f"no z_dev rows at stat_window={w}"
            z_by_w[w] = m

        # Fixed at the LONGEST swept window's warmup so every cell is judged on
        # the same bars. z_dev's first value lands at median_window + stat_window,
        # so this is 1000 + max(WINDOWS) — the cost the cap is there to bound.
        start_idx = max([1000 + max(WINDOWS)]
                        + [min(m) for m in (s1, s3, ri) if m])
        eval_bars = len(df) - start_idx
        if config.MIN_EVAL_BARS and eval_bars < config.MIN_EVAL_BARS:
            return sym, None, f"only {eval_bars} bars after warmup"

        b0, s0, r0 = make_interval_strategies()
        base = run_estimate(sym, df, config.INTERVAL_MONEY, b0, s0, r0, crc,
                            start_index=start_idx)["allRatioGrowth"]

        out = {}
        # The reference cell: gate off, which is what config has today.
        buy, sell, rei = make_median_strategies(
            signal3_map=s3, signal1_map=s1, reinvest_signal1_map=ri,
            zdev_map={}, min_zdev=None)
        r = run_estimate(sym, df, config.INTERVAL_MONEY, buy, sell, rei, crc,
                         start_index=start_idx)
        out[OFF_KEY] = (round(r["allRatioGrowth"] - base, 4),
                        r["totalBuys"], r["totalSells"])

        for w in WINDOWS:
            zmap = z_by_w[w]
            for q in QS:
                buy, sell, rei = make_median_strategies(
                    signal3_map=s3, signal1_map=s1, reinvest_signal1_map=ri,
                    zdev_map=zmap, min_zdev=q)
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
    # Paired against the gate being OFF, since that is the current config.
    if OFF_KEY in per_symbol[syms[0]]:
        base = np.array([per_symbol[s][OFF_KEY][0] for s in syms])
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
        "meta": {
            # Positional layout of every cell tuple. Read off the return
            # statement in eval_symbol, never assumed: the two orders across
            # these sweeps differ only by position, so a wrong declaration
            # makes a reader report buys as reinvests and say nothing.
            "fields": ["diff", "buys", "sells"],"windows": WINDOWS, "qs": QS, "elapsed": elapsed,
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
    live_w = getattr(config, "SELL_ZDEV_WINDOW", 700)

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
                 f"<td>min_zdev = {float(q):+.2f}</td>"
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
<h2>z_dev sell gate: stat window &times; threshold</h2>
<p class="note">{n_syms} symbols, {len(WINDOWS)}&times;{len(QS)} =
{len(WINDOWS)*len(QS)} cells plus an off cell, {elapsed/60:.1f} min. The gate is
OFF in config, so <b>every comparison is against off</b> — there is no live cell
for this grid.<br>
It blocks a sell while z_dev is at or BELOW the threshold, the opposite polarity
to the two momentum gates: a <b>higher</b> value blocks MORE and sells LESS.
Thresholds are raw — z_dev is a z-score and its spread is flat across stat
windows (p95 = 2.218 &times; w<sup>0.009</sup>, R&sup2; = 0.27; p5 &minus;2.30,
p50 &minus;0.15, p95 +2.31, wider than a unit normal).<br>
Start is fixed at 1000 + {max(WINDOWS)} for every cell — what the window cap
buys. The old 700 would put it at 1700 and take back the 12 symbols that got this
gate switched off.</p>
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
        print(f"{'w':>5}{'q':>6}{'min_zdev':>10}{'paired':>9}{'p':>8}"
              f"{'nb':>4}{'mean':>7}{'vote':>6}{'sells':>7}")
        for _, k in good[:15]:
            w, q = k.split("|")
            w, q = int(w), float(q)
            print(f"{w:>5}{q:>6g}{q:10.2f}{pr[k]:+9.2f}{pp[k]:8.3f}"
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
              f"min_zdev={float(q):+6.2f}  -> {bv:+.2f}{unit}")

    off = g.get(OFF_KEY)
    if off is not None:
        print(f"\nreference: gate OFF -> mean {off:+.1f}, "
              f"sells {grids['sells'][OFF_KEY]:.2f}")
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
