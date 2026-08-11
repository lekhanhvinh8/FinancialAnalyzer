"""
Sweep the signal1 sell filter: SELL_SIGNAL1_WINDOW x SELL_MIN_SIGNAL1.

signal1 blocks ~61% of all sell-eligible days — more than the other two filters
combined — so it looked like the obvious thing to tune. This maps the surface.

WHAT THE GRID CANNOT TELL YOU — READ BEFORE ACTING ON IT

  The filter works. Measured against the sell gate switched off entirely
  (min_signal1 = +inf), signal1 alone is worth +1039 points of gain against 402
  of loss across 44 symbols, net +637:

      mean +14.47    10% trimmed mean +7.31    23/36 symbols improved, p=0.066

  But this grid will not show you that, because the grid is scored on the MEDIAN
  and 20 of 44 symbols are untouched by the filter at any setting. The median
  sits inside that dead zone, so it reads ~0.00 no matter what happens in the
  tails — and the tails are the whole effect. Paired against gate-off, the best
  cell in the grid scores +0.00 (p=0.134) and so does the live setting.

  The effect is real but CONCENTRATED, not broad: VND alone is +277 of the +637,
  and dropping the three largest contributors takes the mean from +14.5 to +2.6.
  Read it as "rescues a handful of symbols", never as "improves the typical one".

  Median was chosen here to resist a single dominant symbol, and it does — but it
  is blind to an effect carried by a minority, which is exactly this one. Mean
  sees it and is hostage to VND. The trimmed mean is the honest lens for this
  question. Whatever the statistic, difference it PER SYMBOL: median(A) - median(B)
  is not median(A - B), and the first is what a heat map of aggregates shows you.

  Two traps this grid sets, both of which caught us:

  - The flat green region at w=10-20 is flat because the gate is INERT there,
    not because it is robust. Blocking share is held constant across windows by
    k/sqrt(w), but persistence is not: at w=10 a block lasts ~36 days on average,
    at w=100 it lasts ~293. A 10-day slope flips sign constantly, so a sell is
    merely postponed and still happens. Going k=0 -> k=4 at w=10 (17x fewer days
    blocked) changes the number of sells by 0.2. A plateau can mean "every value
    works" or "no value does anything" — both render as smooth green.
  - The cell with the best win rate (w=200/k=-1.5, 77%) is the most harmful one
    in the grid, -11.24 points paired. Win rate is measured against the DCA arm,
    not against the gate being off, so it stays high while the gate does damage.

WHERE THE PROBLEM ACTUALLY IS: THE OTHER TWO SELL FILTERS

  Same paired measurement, isolating each gate (44 symbols, diff vs DCA):

      signal1 alone, vs no gates at all      mean +14.47   23/36   p=0.066
      signal3 + z_dev, vs no gates at all    mean  +1.76   13/27   p=0.649
      adding signal3 + z_dev on top of signal1  mean -2.50   10/26   p=0.916

  signal1 is not redundant with them — it is the only one of the three carrying
  weight. signal3 and z_dev contribute almost nothing on their own and cost about
  2.5 mean points when layered on signal1, so signal1 alone (+14.47) beats all
  three together (+11.97). z_dev is not miscomputed (no look-ahead, verified three
  ways); it is simply not paying for itself at SELL_MIN_ZDEV = 0.9.

  Caveat on all of the above: one period, one 44-symbol set, and many things were
  tried against it. p=0.066 is a suggestion, not proof. The direction is
  consistent across mean, trimmed mean and sign test; the magnitude is not to be
  trusted to better than its order.

WHY THE THRESHOLD IS SCALED BY THE WINDOW

  The slope's spread shrinks as the window grows. Measured over all 45 eligible
  symbols (~3.1M observations, 20 windows):

      p95 = 3.991 * w^(-0.494)      R^2 = 0.9994

  i.e. very close to 4/sqrt(w). A fixed threshold therefore means something
  different at every window — at w=200 anything above 0.3 blocks nothing, while
  at w=10 the same number sits mid-distribution. A rectangular grid of raw
  thresholds spends most of its cells on two degenerate states ("never sells"
  and "no filter at all").

  What matters is not the formula but that a column means one thing everywhere,
  and it does — share of sell-eligible days blocked, by window:

      k        -4    -2    -1     0     1     2     4
      w=10    95%   86%   74%   52%   30%   17%    5%
      w=100   95%   86%   75%   56%   36%   21%    6%
      w=200   95%   87%   78%   60%   40%   23%    5%

  So the swept quantity is k, with

      min_signal1 = k / sqrt(window)

  which holds strictness roughly constant across windows: k=-4 blocks ~95% of
  days, k=0 about 55%, k=+4 about 5%. It is arithmetic on the window, not a
  fitted quantile, so it introduces no look-ahead.

READING THE RESULT

  Default score is the MEDIAN per-symbol diff. Mean is available via --mean but
  tracks whichever symbol dominates — VIX has been ~30% of total gains in every
  run, so a mean-scored grid largely maps "what is best for VIX".

  Neither is sufficient alone, and choosing between them is not a matter of
  taste. Median is robust to one dominant symbol and blind to an effect carried
  by a minority; mean sees that effect and is hostage to the dominant symbol.
  When the two disagree, do not pick the one you prefer — that disagreement is
  the finding, and it means the effect lives in the tails. Reach for the trimmed
  mean and for the per-symbol list, not for a third aggregate.

  Per-symbol diffs are saved to sweep_signal1_raw.json, so switching score costs
  seconds instead of another full sweep:

      python sweep_signal1.py --rescore          # median
      python sweep_signal1.py --rescore --mean   # mean

  Look for a plateau, not the maximum. Taking the best of 340 cells will find a
  good-looking number whether or not any edge exists; a contiguous region that
  stays good is evidence, an isolated spike beside bad neighbours is noise. And
  a plateau is still only a candidate — check it against the gate-off baseline,
  paired per symbol, before believing it. Note that at 340 cells about 17 are
  expected to reach p < 0.05 by chance alone, so a single significant cell means
  nothing on its own.

Usage:
    python analyze/median1000/sweep_signal1.py            # all eligible symbols
    python analyze/median1000/sweep_signal1.py FPT VIX    # a subset
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import json
import math
import sqlite3
import statistics as st
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor

import pandas as pd

import database as db
from analyze.models import RangeDaysClose, IndexCloses
from analyze.runner import load_symbol_df, run_estimate
from analyze.strategies.buy import BuyMedian1000Strategy, BuyIntervalStrategy
from analyze.strategies.sell import SellMedian1000Strategy, SellStrategy
from analyze.strategies.reinvest import ReInvestMedian1000Strategy, ReinvestStrategy
from analyze.median1000 import config

WINDOWS = list(range(10, 201, 10))                      # 20
KS      = [round(-4.0 + 0.5 * i, 1) for i in range(17)]   # -4.0 .. 4.0, 17 values
#          Negative k blocks MORE days, positive blocks fewer. The first sweep
#          started at k=0 and so only explored 'block 55% -> block 5%'. That was a
#          mistake: at window 20 the best cell in the row WAS k=0, sitting on the
#          grid edge, so there was no way to tell whether it kept improving below it.
OUT     = Path(__file__).parent / "sweep_signal1.html"
RAW     = Path(__file__).parent / "sweep_signal1_raw.json"
PROG    = Path(__file__).parent / "sweep_signal1_progress.html"
#          Per-symbol diffs are written to RAW before any aggregation. Scoring is a
#          choice (mean tracks whichever symbol dominates; median does not), and
#          without the raw data every change of mind costs another full re-run of
#          work that has already been done.


def _threshold(k: float, window: int) -> float:
    return k / math.sqrt(window)


def _range1000(sym: str, df: pd.DataFrame) -> dict:
    """Only range_days=1000 — the strategies read nothing else, and loading all
    1500 windows is the single slowest step in the pipeline."""
    con = sqlite3.connect("file:stock_data.db?mode=ro", uri=True)
    d2i = {str(pd.Timestamp(df["time"].iloc[i]).date()): i for i in range(len(df))}
    cal = defaultdict(IndexCloses)
    for row in con.execute(
        """SELECT date, local_top, local_avg, local_bottom, p25, median, p75,
                  pe_top, pe_avg, pe_bottom, pe_p25, pe_median, pe_p75
           FROM range_stats WHERE symbol=? AND range_days=1000""", (sym,)):
        i = d2i.get(row[0])
        if i is not None:
            cal[i].rangeDayCloses[1000] = RangeDaysClose(*row[1:])
    con.close()
    return cal


def _idx_map(df: pd.DataFrame) -> dict:
    return {pd.Timestamp(r["time"]): i for i, r in df.iterrows()}


def eval_symbol(sym: str):
    """Returns (sym, {(window, k): diff}, note). diff is median1000 - interval."""
    try:
        df = load_symbol_df(sym)
        if len(df) < 1010:
            return sym, None, f"only {len(df)} rows"
        crc = _range1000(sym, df)
        if not crc:
            return sym, None, "no range_stats"

        d2i = _idx_map(df)

        def sig(window, col):
            d = db.load_trend_signals(sym, window_days=window)
            out = {}
            if not d.empty:
                for dt, v in d[col].items():
                    i = d2i.get(pd.Timestamp(dt))
                    if i is not None:
                        out[i] = float(v)
            return out

        s3 = sig(1000, "signal3_sharpe")
        zd = db.load_zdev(sym, 1000, config.SELL_ZDEV_WINDOW)
        z = {}
        if not zd.empty:
            for dt, v in zd["z_dev"].items():
                i = d2i.get(pd.Timestamp(dt))
                if i is not None and v is not None:
                    z[i] = float(v)
        if config.SELL_MIN_ZDEV is not None and not z:
            return sym, None, "no z_dev"

        # One start index for every cell. Derived with the LONGEST swept window so
        # the evaluated period cannot shift between cells — a cell judged on more
        # bars than its neighbour would not be comparable to it.
        start_idx = max([1000, max(WINDOWS) - 1] +
                        ([min(s3)] if s3 else []) + ([min(z)] if z else []))
        eval_bars = len(df) - start_idx
        if config.MIN_EVAL_BARS and eval_bars < config.MIN_EVAL_BARS:
            return sym, None, f"only {eval_bars} bars after warmup"

        # signal1 once per window, reused across every k
        s1_by_w = {w: sig(w, "signal1_slope") for w in WINDOWS}

        # The interval arm does not depend on the swept parameters — computing it
        # per cell would double the run for an identical answer.
        base = run_estimate(sym, df, config.INTERVAL_MONEY, BuyIntervalStrategy(),
                            SellStrategy(), ReinvestStrategy(), crc,
                            start_index=start_idx)["allRatioGrowth"]

        out = {}
        for w in WINDOWS:
            s1 = s1_by_w[w]
            for k in KS:
                sell = SellMedian1000Strategy(
                    percentSell=config.PERCENT_SELL, use_pe=config.USE_PE,
                    signal3_map=s3, min_signal3=config.MIN_SIGNAL3,
                    signal1_map=s1, min_signal1=_threshold(k, w),
                    zdev_map=z, min_zdev=config.SELL_MIN_ZDEV or 0.0)
                ri = ReInvestMedian1000Strategy(
                    percentReinvest=config.PERCENT_REINVEST, use_pe=config.USE_PE,
                    timeoutDays=config.REINVEST_TIMEOUT_DAYS,
                    timeoutPercent=config.REINVEST_TIMEOUT_PERCENT,
                    signal1_map=s1, min_signal1=config.REINVEST_MIN_SIGNAL1 or 0.0)
                r = run_estimate(sym, df, config.INTERVAL_MONEY,
                                 BuyMedian1000Strategy(percentBuy=config.PERCENT_BUY,
                                                       use_pe=config.USE_PE),
                                 sell, ri, crc, start_index=start_idx)
                out[(w, k)] = r["allRatioGrowth"] - base
        return sym, out, None
    except Exception as e:
        return sym, None, f"{type(e).__name__}: {e}"


def apply_exclusions(per_symbol: dict) -> dict:
    """
    config.EXCLUDE_SYMBOLS is applied HERE rather than before computing, so the
    raw JSON keeps every symbol and the exclusion can be changed by re-scoring
    instead of re-running the sweep.
    """
    drop = {s.upper() for s in getattr(config, "EXCLUDE_SYMBOLS", [])}
    hit = sorted(drop & {s.upper() for s in per_symbol})
    if not hit:
        return per_symbol
    kept = {s: d for s, d in per_symbol.items() if s.upper() not in drop}
    print(f"  EXCLUDE_SYMBOLS {hit}: {len(per_symbol)} -> {len(kept)} symbols")
    return kept


# name -> (label, unit, direction). direction +1 = higher is better, -1 = lower.
# Every metric is computed for every cell and all of them are embedded in the
# HTML, so comparing "which config does each metric prefer" costs nothing and
# needs no re-run.
METRICS = {
    "median": ("Median diff",   "%", +1),
    "mean":   ("Mean diff",     "%", +1),
    "win":    ("Win rate",      "%", +1),
    "p":      ("Sign-test p",   "",  -1),
    "p25":    ("25th pct diff", "%", +1),
    "worst":  ("Worst symbol",  "%", +1),
}


def aggregate(per_symbol: dict):
    """
    Returns {metric_name: {(window, k): value}} for every metric in METRICS.
    Caller is expected to have run apply_exclusions() first.
    """
    grids = {m: {} for m in METRICS}
    for w in WINDOWS:
        for k in KS:
            vals = sorted(d[(w, k)] for d in per_symbol.values() if (w, k) in d)
            if not vals:
                continue
            n = len(vals)
            wins = sum(1 for v in vals if v > 0)
            dec = sum(1 for v in vals if abs(v) > 1e-9)
            grids["median"][(w, k)] = st.median(vals)
            grids["mean"][(w, k)] = st.mean(vals)
            grids["win"][(w, k)] = 100 * wins / n
            grids["p25"][(w, k)] = vals[int(0.25 * (n - 1))]
            grids["worst"][(w, k)] = vals[0]
            # one-sided exact binomial, decided symbols only
            grids["p"][(w, k)] = (
                sum(math.comb(dec, i) for i in range(wins, dec + 1)) / 2 ** dec
                if dec else 1.0)
    return grids


def save_raw(per_symbol: dict, skipped: list, path: Path, elapsed: float = 0.0):
    """JSON keys must be strings, so (window, k) is encoded as 'window|k'."""
    path.write_text(json.dumps({
        "meta": {
            "windows": WINDOWS, "ks": KS, "elapsed": elapsed,
            "config": {c: getattr(config, c) for c in dir(config)
                       if c.isupper() and not c.startswith("_")},
        },
        "skipped": skipped,
        "results": {sym: {f"{w}|{k}": round(v, 4) for (w, k), v in d.items()}
                    for sym, d in per_symbol.items()},
    }), encoding="utf-8")


def load_raw(path: Path):
    raw = json.loads(path.read_text(encoding="utf-8"))
    per_symbol = {
        sym: {(int(kk.split("|")[0]), float(kk.split("|")[1])): v
              for kk, v in d.items()}
        for sym, d in raw["results"].items()
    }
    # elapsed is carried so --rescore can report the original sweep time
    # instead of the ~0s the re-score itself takes.
    return (per_symbol, [tuple(x) for x in raw["skipped"]],
            raw.get("meta", {}).get("elapsed", 0.0))


def _cell_color(v, lo, hi):
    if v is None:
        return "#1e293b", "#64748b"
    if v >= 0:
        f = 0 if hi <= 0 else min(1.0, v / hi)
        return f"rgba(34,197,94,{0.12 + 0.55*f:.2f})", "#dcfce7"
    f = 0 if lo >= 0 else min(1.0, v / lo)
    return f"rgba(239,68,68,{0.12 + 0.55*f:.2f})", "#fee2e2"


def build_html(grids, n_syms, elapsed, skipped):
    live_k = config.SELL_MIN_SIGNAL1 * math.sqrt(config.SELL_SIGNAL1_WINDOW)

    rows = ""
    for m, (label, unit, direction) in METRICS.items():
        g = grids[m]
        if not g:
            continue
        (bw, bk), bv = (max if direction > 0 else min)(g.items(), key=lambda kv: kv[1])
        rows += (f"<tr><td style='text-align:left'>{label}</td>"
                 f"<td>{'higher' if direction > 0 else 'lower'} is better</td>"
                 f"<td><b>w={bw}, k={bk:g}</b></td>"
                 f"<td>min_signal1 = {_threshold(bk, bw):.3f}</td>"
                 f"<td style='color:#4ade80'>{bv:+.2f}{unit}</td></tr>")

    skip_html = ""
    if skipped:
        skip_html = ("<p class='note'>Skipped: " +
                     ", ".join(f"{sy} ({why})" for sy, why in sorted(skipped)) + "</p>")
    excl = getattr(config, "EXCLUDE_SYMBOLS", [])
    excl_html = (f"<p class='note'>EXCLUDE_SYMBOLS: <b>{', '.join(excl)}</b>"
                 f" — left out of every figure here.</p>" if excl else "")

    # Keys are built in Python and shipped as strings. Letting JS build them with
    # `w + "|" + k` silently breaks on whole floats: Python writes "10|-4.0" but
    # JS stringifies -4.0 as "-4", so every round k missed its cell and rendered
    # as an empty dash.
    ks_keys = [repr(float(k)) for k in KS]
    data = {m: {f"{w}|{kk}": grids[m].get((w, k))
                for w in WINDOWS for k, kk in zip(KS, ks_keys)}
            for m in METRICS}
    meta = {m: {"label": lbl, "unit": u, "dir": d} for m, (lbl, u, d) in METRICS.items()}
    opts = "".join(f"<option value='{m}'{' selected' if m == 'median' else ''}>"
                   f"{lbl} ({'higher' if d > 0 else 'lower'} better)</option>"
                   for m, (lbl, _, d) in METRICS.items())

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>signal1 sweep</title><style>
body{{font-family:sans-serif;background:#0b1220;color:#e2e8f0;padding:20px}}
table{{border-collapse:collapse;font-size:12px;margin:10px 0}}
th,td{{border:1px solid #1e293b;padding:5px 8px;text-align:center}}
th{{background:#111c30;color:#94a3b8;font-weight:600}}
.note{{color:#94a3b8;font-size:13px;line-height:1.7;max-width:960px}}
select{{background:#111c30;color:#e2e8f0;border:1px solid #334155;padding:6px 10px;
  border-radius:6px;font-size:14px}}
.card{{background:#0f172a;border:1px solid #1e293b;border-radius:8px;
  padding:12px 16px;margin:12px 0;display:inline-block}}
</style></head><body>
<h2>signal1 sell filter &mdash; window &times; k sweep</h2>

<p class="note">{n_syms} symbols, {len(WINDOWS)}&times;{len(KS)} =
{len(WINDOWS)*len(KS)} cells, swept in {elapsed/60:.1f} min. Threshold is
<code>k/&radic;window</code>, so a column is roughly constant strictness at every
window (k=&minus;4 blocks ~95% of sell-eligible days, k=0 about 55%, k=+4 about 5%).
<br>Live config: <b>window {config.SELL_SIGNAL1_WINDOW},
min_signal1 {config.SELL_MIN_SIGNAL1}</b> (k &asymp; {live_k:.2f}).</p>
{excl_html}{skip_html}

<div class="card"><b>What each metric prefers</b>
<table><thead><tr><th>metric</th><th>direction</th><th>best cell</th>
<th>threshold</th><th>value</th></tr></thead><tbody>{rows}</tbody></table>
<span class="note">Disagreement between metrics is informative: a cell only one
metric likes is probably fitting that metric's quirk. Mean follows whichever
symbol is largest; median and 25th pct do not.</span></div>

<p><b>Heat map:</b> <select id="metric">{opts}</select>
<span class="note" id="dirNote"></span></p>
<table id="grid"></table>
<p class="note"><b>Read the plateau, not the &#9733;.</b> The best of
{len(WINDOWS)*len(KS)} cells looks good by construction; a contiguous good region
is evidence, a lone spike beside poor neighbours is noise.</p>

<script>
const DATA = {json.dumps(data)};
const META = {json.dumps(meta)};
const WS = {json.dumps(WINDOWS)}, KS = {json.dumps(KS)};
const KK = {json.dumps(ks_keys)};   // exact cell-key strings, see note above

function render() {{
  const m = document.getElementById('metric').value;
  const g = DATA[m], meta = META[m];
  const vals = Object.values(g).filter(v => v !== null && v !== undefined);
  if (!vals.length) return;
  const lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
  // Colour always means "good". A lower-is-better metric is inverted here rather
  // than in the data, so the printed numbers stay exactly as measured.
  const good = v => hi === lo ? 0.5
      : (meta.dir > 0 ? (v - lo) / (hi - lo) : (hi - v) / (hi - lo));
  const best = meta.dir > 0 ? hi : lo;
  document.getElementById('dirNote').textContent =
      '   ' + meta.label + ' \u2014 ' + (meta.dir > 0 ? 'higher' : 'lower') + ' is better';

  let h = '<thead><tr><th>window</th>';
  KS.forEach(function(k) {{ h += '<th>k=' + k + '</th>'; }});
  h += '</tr></thead><tbody>';
  WS.forEach(function(w) {{
    h += "<tr><th style='text-align:right'>" + w + '</th>';
    KS.forEach(function(k, j) {{
      const v = g[w + '|' + KK[j]];
      if (v === null || v === undefined) {{
        h += "<td style='color:#475569'>&mdash;</td>"; return;
      }}
      const f = good(v);
      const bg = f >= 0.5
        ? 'rgba(34,197,94,' + (0.10 + 0.62 * (f - 0.5) * 2).toFixed(2) + ')'
        : 'rgba(239,68,68,' + (0.10 + 0.62 * (0.5 - f) * 2).toFixed(2) + ')';
      const star = (v === best) ? ' \u2605' : '';
      const txt = (m === 'p') ? v.toFixed(4)
                : (m === 'win') ? v.toFixed(0) + '%'
                : (v >= 0 ? '+' : '') + v.toFixed(1) + '%';
      h += "<td style='background:" + bg + "'>" + txt + star + '</td>';
    }});
    h += '</tr>';
  }});
  document.getElementById('grid').innerHTML = h + '</tbody>';
}}
document.getElementById('metric').addEventListener('change', render);
render();
</script>
</body></html>"""


def write_progress(done, total, started, current_note=""):
    """
    Live progress while the sweep runs. Self-refreshing, because a sweep is long
    enough that "is it stuck or just slow?" is a real question.

    Note the counter advances in INPUT order, not completion order: ex.map yields
    results in the order symbols were submitted, so a slow symbol early in the
    list holds back everything behind it and the count moves in bursts. The
    elapsed clock is honest either way.
    """
    el = time.time() - started
    pct = 100 * done / total if total else 0
    eta = (el / done * (total - done)) if done else 0
    PROG.write_text(f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<meta http-equiv="refresh" content="3"><title>sweep progress</title><style>
body{{font-family:sans-serif;background:#0b1220;color:#e2e8f0;padding:24px}}
.bar{{background:#1e293b;border-radius:6px;height:22px;width:520px;overflow:hidden}}
.fill{{background:#22c55e;height:100%;width:{pct:.1f}%}}
.k{{color:#64748b}} .v{{font-weight:700}}
</style></head><body>
<h2>signal1 sweep &mdash; {'running' if done < total else 'done'}</h2>
<div class="bar"><div class="fill"></div></div>
<p><span class="v">{done} / {total}</span> symbols
<span class="k">({pct:.0f}%)</span></p>
<p><span class="k">grid</span> <span class="v">{len(WINDOWS)}&times;{len(KS)}
= {len(WINDOWS)*len(KS)}</span> cells per symbol</p>
<p><span class="k">elapsed</span> <span class="v">{el/60:.1f} min</span>
&nbsp;&nbsp;<span class="k">eta</span> <span class="v">
{('%.1f min' % (eta/60)) if done and done < total else '—'}</span></p>
<p class="k">{current_note}</p>
</body></html>""", encoding="utf-8")


def _report(per_symbol, skipped, score, elapsed):
    per_symbol = apply_exclusions(per_symbol)
    if not per_symbol:
        print("every symbol was excluded — nothing to report")
        return
    grids = aggregate(per_symbol)
    OUT.write_text(build_html(grids, len(per_symbol), elapsed, skipped),
                   encoding="utf-8")

    grid = grids[score]
    print(f"\nscore = {score.upper()} per-symbol diff, {len(per_symbol)} symbols")
    print(f"{'w':>5} " + " ".join(f"k={k:<5g}" for k in KS))
    for w in WINDOWS:
        print(f"{w:>5} " + " ".join(
            f"{grid.get((w,k), float('nan')):+7.2f}" for k in KS))

    print("\nwhat each metric prefers:")
    for m, (label, unit, direction) in METRICS.items():
        g = grids[m]
        if not g:
            continue
        (bw, bk), bv = (max if direction > 0 else min)(g.items(), key=lambda kv: kv[1])
        print(f"  {label:<15} w={bw:<4} k={bk:<5g} "
              f"min_signal1={_threshold(bk, bw):.3f}  -> {bv:+.2f}{unit}")
    print(f"\nreport -> {OUT}   (all metrics selectable in the page)")


def main():
    args  = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    score = "mean" if "--mean" in flags else "median"

    # Re-score an existing run without recomputing anything.
    if "--rescore" in flags:
        if not RAW.exists():
            print(f"no raw data at {RAW} — run the sweep first"); return
        per_symbol, skipped, elapsed = load_raw(RAW)
        print(f"re-scoring {len(per_symbol)} symbols from {RAW.name} as {score}")
        _report(per_symbol, skipped, score, elapsed)
        return

    syms = [s.upper() for s in args] or db.list_symbols()
    print(f"Sweeping {len(WINDOWS)}x{len(KS)} = {len(WINDOWS)*len(KS)} combos "
          f"over {len(syms)} symbols")
    t0 = time.time()

    per_symbol, skipped = {}, []
    write_progress(0, len(syms), t0, "starting workers…")
    print(f"progress -> {PROG}")
    with ProcessPoolExecutor() as ex:
        for i, (sym, res, note) in enumerate(ex.map(eval_symbol, syms), 1):
            if res is None:
                skipped.append((sym, note))
                print(f"[{i}/{len(syms)}] {sym} skipped — {note}", flush=True)
            else:
                per_symbol[sym] = res
                print(f"[{i}/{len(syms)}] {sym} ok", flush=True)
            write_progress(i, len(syms), t0, f"last: {sym}")

    if not per_symbol:
        print("nothing to report"); return

    # Written before aggregating, so a crash in the reporting code cannot destroy
    # an hour of computation.
    elapsed = time.time() - t0
    save_raw(per_symbol, skipped, RAW, elapsed)
    print(f"raw -> {RAW}")

    _report(per_symbol, skipped, score, elapsed)
    print(f"({elapsed/60:.1f} min)   re-score with: "
          f"python {Path(__file__).name} --rescore [--mean]")


if __name__ == "__main__":
    main()
