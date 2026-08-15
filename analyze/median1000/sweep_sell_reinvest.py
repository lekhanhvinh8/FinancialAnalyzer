"""
Sweep the sell threshold against the reinvest threshold: PERCENT_SELL x PERCENT_REINVEST.

The first sweep here that exists because of a MECHANISM rather than because a
parameter had not been measured yet. Both of these have already been swept alone
and both won their own grid. The claim under test is that winning alone is not
enough, because they are coupled.

WHAT COUPLES THEM: THE DEAD ZONE

  The sell arm lets go when the price is PERCENT_SELL above its 1000-day median.
  The reinvest arm is allowed back in when the price is within PERCENT_REINVEST
  of that median. Live, those are 75 and 10, so after a sell the price has to
  fall 65 points before the money may return on merit.

  On a symbol that keeps compounding, it does not fall that far. Measured on the
  two worst long-history losses:

      sell            dev at sell    bars until dev <= +10
      FPT 2015-11-03      77.5%       1101   (4.4 years)
      FPT 2018-01-29      82.0%        538
      FPT 2022-01-19     125.3%       1022
      GMD 2021-06-17      80.4%        950

  REINVEST_TIMEOUT_DAYS is 400, so the clock always gets there first. Five of the
  seven re-entries across FPT and GMD are the timeout firing at exactly 400 bars,
  not the price condition. The timeout is documented as insurance for a regime
  where the price condition stops firing; on a compounder it is the only way back
  in, and it buys at whatever the market costs by then:

      FPT  sold  9.39M  ->  bought back 11.29M  (+20%, 400 bars)
      FPT  sold 15.56M  ->  bought back 19.24M  (+24%, 400 bars)
      FPT  sold 44.21M  ->  bought back 67.57M  (+53%, 400 bars)
      GMD  sold 31.66M  ->  bought back 36.91M  (+17%, 400 bars)
      GMD  sold 41.30M  ->  bought back 61.92M  (+50%, 400 bars)

  Sell high, buy back higher, five times out of seven. FPT ends 85.03 points
  behind buying at every interval and GMD 75.17 behind, on full 2816-bar history.

WHY THE ISOLATED SWEEPS COULD NOT SEE IT

  Not an oversight in either sweep; a consequence of doing them one at a time.

      a5c6ec1  swept PERCENT_REINVEST, settled on 10   -- PERCENT_SELL was 60
      4f8103d  raised PERCENT_SELL from 60 to 75

  The reinvest threshold was chosen against a dead zone of 50 points. Raising the
  sell threshold widened it to 65 and nothing re-examined the pair. Sweeping one
  parameter with the others held live is the right method and it is exactly what
  hides an interaction: each arm was asked whether it was individually optimal,
  never whether the distance between them was.

THE GRID

  Raw percentages on both axes. Neither is a windowed quantity, so there is
  nothing to normalise and no q -- see dispersion.py, where only slope, sharpe
  and dev needed reparameterising.

      PERCENT_SELL      60..90   the 1D sweep's significant band was 65..80 and
                                 the 2D window sweep put every winning cell in
                                 73..78, so the grid spans that and both edges
      PERCENT_REINVEST -10..80   live 10 at the low end, and up past the sell
                                 threshold at the other. The 1D sweep found
                                 -5..+35 all safe and a collapse past +50, but it
                                 measured that against a sell threshold of 60,
                                 which is the coupling this sweep exists to test:
                                 a reinvest ceiling that hurt at one dead-zone
                                 width says nothing about another

  Live (75, 10) is a cell in this grid, so it is the reference every other cell
  is paired against -- unlike sweep_zdev, which had to invent an "off" cell.

  Neither axis moves the warmup, so every cell is judged on identical bars and
  the grid costs no symbols.

READ THE DIAGONALS TOO

  The mechanism is about the DISTANCE between the two thresholds, and cells with
  equal distance lie on a diagonal. The report prints a gap table beside the heat
  map for that reason. Treat it as shape, not as a test: it averages each cell's
  paired median across the cells sharing a gap, which describes cells, not
  symbols, and carries no significance of its own.

WHAT IT FOUND: THE HYPOTHESIS IS DEAD, AND IT DIED THE INTERESTING WAY

  52 symbols, 70 cells, 4.6 min. The mechanism above is real and the sweep
  confirms it — narrowing the dead zone does hand the re-entry back to the price
  condition, exactly as described:

      PERCENT_REINVEST    10 (live)    40     60     80
      reinvests/symbol         3.96  4.71   7.15  16.63

  The prediction about what that would be worth was wrong, and wrong in sign.
  Collapsed along the diagonals, a NARROWER gap is worse and a wider one is
  neutral to slightly better:

      gap        15     30     45   65 (live)    80     85
      paired  -4.63  -2.66  -2.51      -0.62  +0.03  +0.52

  At sell=75 reinvest=60, the narrowest sensible cell, 15 symbols improve and 34
  get worse, paired median -4.85. FPT and GMD improve enormously — +91 and +428 —
  which is precisely what the diagnosis predicted, and they are two symbols out
  of fifty-two. Against them: SHB -173, HPG -172, HCM -163, SSI -161, MBB -121.

  So the dead zone is not a defect that had gone unnoticed. It is protecting the
  portfolio, and FPT and GMD are what it costs.

  This does not retract the diagnosis. The 400-bar timeout really is the only way
  back into a compounder and really does buy higher than it sold. What is retracted
  is that PERCENT_REINVEST is the lever: a global threshold that fixes those two
  charges 34 other symbols for it. Anything that fixes it has to tell a compounder
  apart from an oscillator, which is not a number either of these axes can hold.

  THE ONE THING THAT DID WIN IS NOT ON THE REINVEST AXIS

      sell  reinv  gap  paired      p  nb   up/down/unchanged
        85     10   75   +1.89  0.000   2   29 / 8 / 15
        80     10   70   +1.67  0.000   1   29 / 6 / 17
        90     10   80   +0.93  0.004   1

  All three sit at reinvest=10, i.e. unchanged. The reinvest axis contributes
  nothing; what wins is selling even less often. Not adopted, on three counts:
  no cell has more than 2 agreeing neighbours (with 70 cells about 3.5 reach
  p<0.05 by chance, and there are exactly 3), the size is +1.89 median points
  against a live mean of +52, and config.py records a 1D sweep finding that 85
  and up was NOT significant.

  That last one is not the contradiction it looks like: the 1D sweep paired
  against 60 and this pairs against 75. Paired medians do not chain —
  median(85-60) is not median(85-75) + median(75-60) — so "85 does not beat 60"
  and "85 beats 75" can both hold. The same non-additivity that has been the
  recurring trap here, in its transitive form.

  Nothing rescues the worst symbol either: LPB stays at -90.68 in every cell, and
  the "worst symbol" metric picks the live cell.

Usage:
    python analyze/median1000/sweep_sell_reinvest.py             # all symbols
    python analyze/median1000/sweep_sell_reinvest.py FPT GMD     # a subset
    python analyze/median1000/sweep_sell_reinvest.py --rescore
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

SELLS = [60, 65, 70, 75, 80, 85, 90]                   # 7
REIS  = [-10, 0, 10, 20, 30, 40, 50, 60, 70, 80]       # 10
#       Live is (75, 10). The reinvest axis runs past 60 because a 2-symbol smoke
#       test on FPT and GMD put its best cell exactly on a 60 ceiling, and a grid
#       whose winner sits on its own edge has not found an optimum, only a wall.
#
#       Five cells have PERCENT_REINVEST >= PERCENT_SELL. They are not degenerate:
#       the factory hands reinvest a reference to the sell arm, so on a bar where
#       the sell would fire the reinvest stands down, and what those cells mean is
#       "return whenever we are not actually selling". Worth having in the grid,
#       and worth knowing they are a different shape from the rest of it.

LIVE = (config.PERCENT_SELL, config.PERCENT_REINVEST)

OUT  = Path(__file__).parent / "sweep_sell_reinvest.html"
RAW  = Path(__file__).parent / "sweep_sell_reinvest_raw.json"
PROG = Path(__file__).parent / "sweep_sell_reinvest_progress.html"


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
        for ps in SELLS:
            for pr in REIS:
                buy, sell, rei = make_median_strategies(
                    signal3_map=s3, signal1_map=s1, reinvest_signal1_map=ri,
                    zdev_map=z, percent_sell=ps, percent_reinvest=pr)
                r = run_estimate(sym, df, config.INTERVAL_MONEY, buy, sell, rei,
                                 crc, start_index=start_idx)
                out[_key(ps, pr)] = (round(r["allRatioGrowth"] - base, 4),
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
    i, j = SELLS.index(s), REIS.index(r)
    out = []
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            a, b = i + di, j + dj
            if (di or dj) and 0 <= a < len(SELLS) and 0 <= b < len(REIS):
                out.append(_key(SELLS[a], REIS[b]))
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
    keys = [_key(s, r) for s in SELLS for r in REIS]
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
        for s in SELLS:
            for r in REIS:
                k = _key(s, r)
                grids["nb"][k] = sum(1 for n in _neighbours(s, r) if n in good)
    return grids


def gap_table(grids: dict) -> list:
    """
    [(gap, n_cells, mean paired, best cell, best paired)] by dead-zone width.

    The mechanism is about the DISTANCE between the thresholds, so this collapses
    the grid along its diagonals. It averages each cell's paired median over the
    cells sharing a gap: that is a statement about cells, not about symbols, and
    it carries no p-value. Use it to see whether the effect trends with the gap
    at all, then go back to the individual cells for anything decisive.
    """
    pr = grids.get("paired") or {}
    if not pr:
        return []
    by = {}
    for s in SELLS:
        for r in REIS:
            by.setdefault(s - r, []).append((pr[_key(s, r)], _key(s, r)))
    out = []
    for gap in sorted(by):
        cells = by[gap]
        best = max(cells)
        out.append((gap, len(cells), st.mean(v for v, _ in cells), best[1], best[0]))
    return out


def save_raw(per_symbol, skipped, elapsed):
    RAW.write_text(json.dumps({
        "meta": {
            # Positional layout of every cell tuple. Two orders grew up across these
            # sweeps and they differ only by position, so a reader that assumes the
            # wrong one reports buys as reinvests and says nothing.
            "fields": ["diff", "reinvests", "buys", "sells"],
            "sells": SELLS, "reis": REIS, "live": list(LIVE),
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
<meta http-equiv="refresh" content="3"><title>sell x reinvest sweep</title><style>
body{{font-family:sans-serif;background:#0b1220;color:#e2e8f0;padding:24px}}
.bar{{background:#1e293b;border-radius:6px;height:22px;width:520px;overflow:hidden}}
.fill{{background:#22c55e;height:100%;width:{pct:.1f}%}}
.k{{color:#64748b}} .v{{font-weight:700}}</style></head><body>
<h2>sell &times; reinvest sweep &mdash; {'running' if done < total else 'done'}</h2>
<div class="bar"><div class="fill"></div></div>
<p><span class="v">{done} / {total}</span> symbols <span class="k">({pct:.0f}%)</span></p>
<p><span class="k">grid</span> <span class="v">{len(SELLS)}&times;{len(REIS)}
= {len(SELLS)*len(REIS)}</span> cells per symbol</p>
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


def build_html(grids, n_syms, skipped, elapsed):
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
                 f"<td><b>sell={s}, reinvest={r}</b></td>"
                 f"<td>gap {int(s) - int(r)}</td>"
                 f"<td style='color:#4ade80'>{bv:+.2f}{unit}</td></tr>")

    grows = "".join(
        f"<tr><td>{gap}</td><td>{n}</td>"
        f"<td style='color:{'#4ade80' if mn >= 0 else '#f87171'}'>{mn:+.2f}%</td>"
        f"<td>{bk.replace('|', ' / ')}</td>"
        f"<td style='color:{'#4ade80' if bv >= 0 else '#f87171'}'>{bv:+.2f}%</td></tr>"
        for gap, n, mn, bk, bv in gap_table(grids))

    skip_html = ("<p class='note'>Skipped: "
                 + ", ".join(f"{s} ({w})" for s, w in sorted(skipped)) + "</p>"
                 ) if skipped else ""

    data = {m: {k: (round(v, 3) if isinstance(v, float) else v)
                for k, v in (grids.get(m) or {}).items()} for m in METRICS}
    opts = "".join(f"<option value='{m}'{' selected' if m == 'paired' else ''}>{lbl}</option>"
                   for m, (lbl, _, _) in METRICS.items())

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>sell x reinvest sweep</title><style>
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
<p class="note">{n_syms} symbols, {len(SELLS)}&times;{len(REIS)} =
{len(SELLS)*len(REIS)} cells, {elapsed/60:.1f} min. Everything else stays at its
configured value; only these two move, and neither of them touches the warmup, so
every cell is judged on identical bars.<br>
<b>Why this pair.</b> The sell arm releases at PERCENT_SELL above the median and
the reinvest arm may only return within PERCENT_REINVEST of it, so the gap
between them is a zone the money cannot come back through. Live that gap is
{LIVE[0]} &minus; {LIVE[1]} = <b>{LIVE[0] - LIVE[1]} points</b>, and on a
compounder the price never closes it: FPT took 538 to 1101 bars to fall back
within +10% of its median, while REINVEST_TIMEOUT_DAYS is 400. Five of the seven
FPT and GMD re-entries are that timeout firing, each buying back higher than it
sold.<br>
Live cell: <b>PERCENT_SELL={LIVE[0]}, PERCENT_REINVEST={LIVE[1]}</b> &mdash; every
paired figure is measured against it.</p>
{skip_html}

<div class="card"><b>What each metric prefers</b>
<table><thead><tr><th>metric</th><th>best cell</th><th>gap</th>
<th>value</th></tr></thead><tbody>{rows}</tbody></table>
<span class="note">Mean follows the largest symbol; vote gives every symbol one
vote and is blind to size. A cell winning only one of them tells you which.</span>
</div>

<div class="card"><b>Collapsed along the diagonals</b>
<table><thead><tr><th>gap</th><th>cells</th><th>mean paired</th>
<th>best cell</th><th>its paired</th></tr></thead><tbody>{grows}</tbody></table>
<span class="note">Shape only, no p-value: this averages each cell's paired
median over the cells sharing a gap, which describes cells rather than symbols.
If the effect is really about the distance, this column trends.</span></div>

<p><b>Heat map:</b> <select id="metric">{opts}</select>
<span class="note">rows = PERCENT_SELL, columns = PERCENT_REINVEST</span></p>
<div class="wrap"><table id="grid"></table></div>
<p class="note"><b>Read the plateau, not the best cell.</b> The best of
{len(SELLS)*len(REIS)} cells looks good whether or not any edge exists &mdash;
about 3 of them reach p&lt;0.05 by chance alone. Check <i>Neighbours agreeing</i>
before believing any single cell, and check <i>Reinvests</i> to see whether a
winning cell actually changed the re-entry behaviour or just moved the sells.</p>

<script>
const DATA = {json.dumps(data)};
const SS = {json.dumps(SELLS)}, RS = {json.dumps(REIS)};
const LIVE = {json.dumps(list(LIVE))};
// Keys are built in Python and shipped as strings. Both axes are ints here, so
// the float-key trap that blanked whole columns in the q-based sweeps does not
// apply -- keep it that way if a fractional threshold is ever added.
function render() {{
  const m = document.getElementById('metric').value;
  const g = DATA[m];
  const vals = Object.values(g).filter(v => v !== null && v !== undefined);
  if (!vals.length) return;
  const lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
  let h = '<thead><tr><th>sell \\\\ reinv</th>';
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
         + "' title='sell " + s + ", reinvest " + r + ", gap " + (s - r) + "'>"
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

    print(f"\nlive cell  PERCENT_SELL={LIVE[0]}, PERCENT_REINVEST={LIVE[1]}  "
          f"(gap {LIVE[0]-LIVE[1]})   mean {grids['mean'].get(live_k, float('nan')):+.2f}  "
          f"sells {grids['sells'].get(live_k, float('nan')):.2f}  "
          f"reinvests {grids['reis'].get(live_k, float('nan')):.2f}")

    good = sorted(((pr[k], k) for k in pr if pr[k] > 0 and pp[k] < 0.05), reverse=True)
    print(f"\ncells beating live with p<0.05: {len(good)}/{len(pr)}")
    if good:
        print(f"{'sell':>6}{'reinv':>7}{'gap':>5}{'paired':>9}{'p':>8}{'nb':>4}"
              f"{'mean':>8}{'vote':>6}{'sells':>7}{'reis':>7}")
        for _, k in good[:15]:
            s, r = (int(x) for x in k.split("|"))
            print(f"{s:>6}{r:>7}{s-r:>5}{pr[k]:+9.2f}{pp[k]:8.3f}{nb[k]:4d}"
                  f"{grids['mean'][k]:8.1f}{grids['vote'][k]:6d}"
                  f"{grids['sells'][k]:7.2f}{grids['reis'][k]:7.2f}")
        solid = [k for _, k in good if nb[k] >= 4]
        print(f"  with 4+ agreeing neighbours: {len(solid)}"
              f"{' — ' + ', '.join(solid[:6]) if solid else ' (none: isolated cells only)'}")
    print(f"  cells whose paired median is exactly 0.00: "
          f"{sum(1 for k in pr if abs(pr[k]) < 1e-9)}/{len(pr)}")

    print("\ncollapsed along the diagonals (shape only, no p-value)")
    print(f"{'gap':>5}{'cells':>7}{'mean paired':>13}{'best cell':>12}{'its paired':>12}")
    for gap, n, mn, bk, bv in gap_table(grids):
        print(f"{gap:>5}{n:>7}{mn:>+13.2f}{bk:>12}{bv:>+12.2f}")

    for name, title in (("paired", "paired vs live"), ("reis", "mean reinvests")):
        g = grids[name]
        print(f"\n{title}   rows=PERCENT_SELL  cols=PERCENT_REINVEST")
        print(f"{'':>5} " + " ".join(f"{r:>7}" for r in REIS))
        for s in SELLS:
            print(f"{s:>5} " + " ".join(f"{g.get(_key(s,r), float('nan')):7.2f}"
                                        for r in REIS))

    print("\nwhat each metric prefers:")
    for m, (label, unit, d) in METRICS.items():
        gg = grids.get(m) or {}
        if not gg or d == 0:
            continue
        bk, bv = (max if d > 0 else min)(gg.items(), key=lambda kv: kv[1])
        s, r = bk.split("|")
        print(f"  {label:<20} sell={s:<4} reinvest={r:<5} gap={int(s)-int(r):<4}"
              f" -> {bv:+.2f}{unit}")

    OUT.write_text(build_html(grids, len(per_symbol), skipped, elapsed),
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
    print(f"Sweeping {len(SELLS)}x{len(REIS)} = {len(SELLS)*len(REIS)} cells "
          f"over {len(syms)} symbols")
    print(f"live cell (PERCENT_SELL={LIVE[0]}, PERCENT_REINVEST={LIVE[1]}) is "
          f"{'in' if _key(*LIVE) in [_key(s, r) for s in SELLS for r in REIS] else 'NOT IN'}"
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
