"""
Sweep the second sell trigger: PERCENT_SELL_BOTTOM.

Sell when the price is this far above the SELL_MEDIAN_WINDOW LOW, OR'd with the
existing test against the median. None switches it off and the arm is exactly
what it is today, so OFF is both the reference cell and the live configuration.

THE FIRST THING HERE THAT LOOSENS THE SELL ARM INSTEAD OF RESTRAINING IT

  Every previous attempt on this arm was a filter, and all three lost the same
  way:

      SELL_MIN_ZDEV                     0 of 66 cells
      PERCENT_SELL x PERCENT_REINVEST   FPT +91, GMD +428  ->  15 up, 34 down
      SELL_MIN_PELOG                    FPT +88, GMD  +96  ->  19 up, 21 down

  Each fixed the symbol it was built for and each charged the rest of the
  portfolio for it. The reading recorded on SellMedian1000Strategy is that this
  arm is net positive, so quieting it pays the majority to rescue the minority.
  That reading has an obvious untested corollary and this is it: if restraining
  the arm costs, does loosening it pay?

  Expect the mirror-image failure mode. A filter can win by never selling; a
  second trigger can lose by selling constantly. Watch the sells column before
  anything else.

WHAT IT CATCHES THAT THE MEDIAN CANNOT

  A symbol that runs away from its floor while the median chases the price up.
  The distance to the median never opens, so the existing condition stays quiet
  the whole way, while the distance to the window low keeps growing.

THE GRID

  Measured over 58 symbols and 124,382 post-warmup observations:

      p5     p25     p50     p75     p95     p99
      14      70     132     227     488     986      price vs 1000-bar low
     -26       0      24      60     172     386      price vs 1000-bar median

  The two are on completely different scales — the low is a floor, so the
  distance to it is large and one-sided, while the median sits in the middle. A
  threshold that reads as huge next to PERCENT_SELL = 75 is not necessarily
  loose here.

  What matters is how many days the new condition fires on that the old one does
  not, which is the count of sells it ADDS:

      threshold    median symbol    worst symbol    symbols >5%    never fires
           75           57.2%           99.7%            56              0
          150           25.6%           78.4%            48              5
          200           12.3%           78.4%            41             10
          300            2.8%           39.6%            24             24
          400            0.0%           35.7%            10             34
          600            0.0%           21.1%             3             52

  So the usable band is roughly 150 to 600. The grid spans it and both edges: 75
  is kept as the degenerate anchor where the arm sells almost daily, and 1000 as
  the one where it has effectively switched itself off again.

COSTS NO WARMUP

  local_bottom comes out of the same range_stats row the median already does, so
  every cell shares the start index run_all would use anyway and OFF is not
  judged on different bars.

Usage:
    python analyze/median1000/sweep_sell_bottom.py             # all symbols
    python analyze/median1000/sweep_sell_bottom.py FPT GMD     # a subset
    python analyze/median1000/sweep_sell_bottom.py --rescore
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
from analyze.median1000.factory import (make_median_strategies,
                                        make_interval_strategies, build_pelog_map)

QS = [75, 100, 150, 200, 250, 300, 350, 400, 500, 600, 800, 1000]   # 12

# The reference: no second trigger, which is what config has today.
OFF_KEY = "off"

OUT  = Path(__file__).parent / "sweep_sell_bottom.html"
RAW  = Path(__file__).parent / "sweep_sell_bottom_raw.json"
PROG = Path(__file__).parent / "sweep_sell_bottom_progress.html"


def _key(q):
    return f"{q}"


def eval_symbol(sym: str):
    """Returns (sym, {key: (diff, buys, sells, reinvests)}, note)."""
    try:
        df = load_symbol_df(sym)
        if len(df) < 1010:
            return sym, None, f"only {len(df)} rows"

        buy_w  = getattr(config, "BUY_MEDIAN_WINDOW", 1000)
        sell_w = getattr(config, "SELL_MEDIAN_WINDOW", 1000)
        pe_w   = getattr(config, "PE_MEDIAN_WINDOW", 500)
        windows = {1000, buy_w, sell_w}
        if config.SELL_MIN_PELOG is not None:
            windows.add(pe_w)
        crc = db.load_range_stats(symbol=sym, df=df, range_days=windows)
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

        # Every gate stays exactly as configured — this sweep moves the price
        # test, not the filters. A gate that is off is not loaded, so its warmup
        # cannot push the start index for something nobody is applying.
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
        pl = {}
        if config.SELL_MIN_PELOG is not None:
            pl = build_pelog_map(sym, df, crc, pe_w)
            if not pl:
                return sym, None, f"no usable P/E at window={pe_w}"

        start_idx = max([1000, buy_w, sell_w]
                        + [min(m) for m in (s1, s3, ri, z, pl) if m])
        eval_bars = len(df) - start_idx
        if config.MIN_EVAL_BARS and eval_bars < config.MIN_EVAL_BARS:
            return sym, None, f"only {eval_bars} bars after warmup"

        b0, s0, r0 = make_interval_strategies()
        base = run_estimate(sym, df, config.INTERVAL_MONEY, b0, s0, r0, crc,
                            start_index=start_idx)["allRatioGrowth"]

        def cell(pct_bottom):
            buy, sell, rei = make_median_strategies(
                signal3_map=s3, signal1_map=s1, reinvest_signal1_map=ri,
                zdev_map=z, pelog_map=pl, percent_sell_bottom=pct_bottom)
            r = run_estimate(sym, df, config.INTERVAL_MONEY, buy, sell, rei, crc,
                             start_index=start_idx)
            return (round(r["allRatioGrowth"] - base, 4), r["totalBuys"],
                    r["totalSells"], r["totalReinvest"])

        out = {OFF_KEY: cell(None)}
        for q in QS:
            out[_key(q)] = cell(q)
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


def aggregate(per_symbol: dict) -> dict:
    """
    {metric: {key: value}}.

    paired  median per-symbol difference against OFF, which is also live here.
            Never subtract two aggregate columns instead: changing the threshold
            reorders the symbols, so the symbol at the median of one column is
            not the symbol at the median of the other.
    pairp   sign-test p over decided symbols only.
    nb      how many of the cell's two grid neighbours also beat OFF
            significantly. One dimension, so the most it can be is 2.
    """
    keys = [OFF_KEY] + [_key(q) for q in QS]
    syms = [s for s in per_symbol if all(k in per_symbol[s] for k in keys)]
    grids = {m: {} for m in ("mean", "median", "win", "worst", "vote",
                             "paired", "pairp", "nb", "buys", "sells", "reis")}
    if not syms:
        return grids

    m = np.array([[per_symbol[s][k][0] for k in keys] for s in syms])
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

    base = m[:, keys.index(OFF_KEY)]
    for i, k in enumerate(keys):
        d = m[:, i] - base
        up  = int((d > 1e-9).sum())
        dec = int((np.abs(d) > 1e-9).sum())
        grids["paired"][k] = float(np.median(d))
        grids["pairp"][k] = (
            sum(math.comb(dec, j) for j in range(up, dec + 1)) / 2 ** dec
            if dec else 1.0)
    good = {k for k in keys if grids["paired"][k] > 0 and grids["pairp"][k] < 0.05}
    for j, q in enumerate(QS):
        nb = ([QS[j - 1]] if j > 0 else []) + ([QS[j + 1]] if j < len(QS) - 1 else [])
        grids["nb"][_key(q)] = sum(1 for x in nb if _key(x) in good)
    grids["nb"][OFF_KEY] = 0
    return grids


def save_raw(per_symbol, skipped, elapsed):
    RAW.write_text(json.dumps({
        "meta": {"qs": QS, "elapsed": elapsed,
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
<meta http-equiv="refresh" content="3"><title>sell-bottom sweep</title><style>
body{{font-family:sans-serif;background:#0b1220;color:#e2e8f0;padding:24px}}
.bar{{background:#1e293b;border-radius:6px;height:22px;width:520px;overflow:hidden}}
.fill{{background:#22c55e;height:100%;width:{pct:.1f}%}}
.k{{color:#64748b}} .v{{font-weight:700}}</style></head><body>
<h2>second sell trigger sweep &mdash; {'running' if done < total else 'done'}</h2>
<div class="bar"><div class="fill"></div></div>
<p><span class="v">{done} / {total}</span> symbols <span class="k">({pct:.0f}%)</span></p>
<p><span class="k">grid</span> <span class="v">{len(QS)} + off</span> cells per symbol</p>
<p><span class="k">elapsed</span> <span class="v">{el/60:.1f} min</span>&nbsp;&nbsp;
<span class="k">eta</span> <span class="v">
{('%.1f min' % (eta/60)) if done and done < total else '&mdash;'}</span></p>
<p class="k">{note}</p></body></html>""", encoding="utf-8")


def build_html(grids, n_syms, skipped, elapsed):
    off_sells = grids["sells"].get(OFF_KEY, float("nan"))
    rows = ""
    for k in [OFF_KEY] + [_key(q) for q in QS]:
        p, pp = grids["paired"].get(k, 0.0), grids["pairp"].get(k, 1.0)
        sells = grids["sells"].get(k, float("nan"))
        hit = (p > 0 and pp < 0.05)
        # A second trigger can "win" by churning; flag any cell that has more than
        # doubled the trade count so it cannot be read as a clean improvement.
        churn = sells > 2 * off_sells if off_sells == off_sells else False
        rows += (
            f"<tr style='background:{'rgba(34,197,94,0.12)' if hit else 'transparent'}'>"
            f"<td style='text-align:left'>{'<b>OFF</b>' if k == OFF_KEY else k}</td>"
            f"<td style='color:{'#4ade80' if p >= 0 else '#f87171'}'>"
            f"{'' if k == OFF_KEY else f'{p:+.2f}'}</td>"
            f"<td style='color:{'#4ade80' if pp < 0.05 else '#94a3b8'}'>"
            f"{'' if k == OFF_KEY else f'{pp:.3f}'}</td>"
            f"<td>{grids['nb'].get(k, 0)}</td>"
            f"<td>{grids['mean'].get(k, float('nan')):+.1f}</td>"
            f"<td>{grids['median'].get(k, float('nan')):+.1f}</td>"
            f"<td>{grids['vote'].get(k, 0)}</td>"
            f"<td>{grids['worst'].get(k, float('nan')):+.1f}</td>"
            f"<td style='color:{'#fbbf24' if churn else '#e2e8f0'};"
            f"{'font-weight:600' if churn else ''}'>{sells:.2f}</td>"
            f"<td>{grids['buys'].get(k, float('nan')):.0f}</td></tr>")

    skip_html = ("<p class='note'>Skipped: "
                 + ", ".join(f"{s} ({w})" for s, w in sorted(skipped)) + "</p>"
                 ) if skipped else ""

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>second sell trigger sweep</title><style>
body{{font-family:sans-serif;background:#0b1220;color:#e2e8f0;padding:20px}}
table{{border-collapse:collapse;font-size:13px;margin:12px 0}}
th,td{{border:1px solid #1e293b;padding:5px 10px;text-align:center}}
th{{background:#111c30;color:#94a3b8}}
.note{{color:#94a3b8;font-size:13px;line-height:1.7;max-width:1000px}}
code{{color:#e2e8f0}}
</style></head><body>
<h2>Second sell trigger &mdash; PERCENT_SELL_BOTTOM</h2>
<p class="note">{n_syms} symbols, {len(QS)} thresholds plus OFF, {elapsed/60:.1f} min.
Sells when the price is this far above the 1000-bar LOW, OR'd with the existing
test against the median. OFF is both the reference and the live config, so every
paired figure is against what runs today.<br>
<b>This is the first change here that loosens the sell arm rather than
restraining it.</b> Three filters have been tried and all three lost by paying the
portfolio to rescue one or two symbols. The mirror-image failure to watch for is a
cell that wins by trading constantly &mdash; the sells column turns
<span style="color:#fbbf24">amber</span> once a cell more than doubles OFF's
{off_sells:.2f} trades per symbol.<br>
Scale note: the low is a floor, so distance to it is large and one-sided (median
day sits +132% above it) while distance to the median is centred near +24%. A
threshold that looks enormous beside PERCENT_SELL = {getattr(config, 'PERCENT_SELL', 75)}
is not necessarily loose.</p>
{skip_html}
<table><thead><tr>
<th>threshold</th><th>paired vs OFF</th><th>sign-test p</th><th>nb (max 2)</th>
<th>mean</th><th>median</th><th>cells beaten</th><th>worst symbol</th>
<th>sells</th><th>buys</th>
</tr></thead><tbody>{rows}</tbody></table>
<p class="note">Green rows beat OFF with p&lt;0.05 and a positive paired median.
With {len(QS)} cells about one reaches p&lt;0.05 by chance, so read <b>nb</b>: an
isolated winner between two losers is noise, two agreeing neighbours is a
plateau.</p>
</body></html>"""


def _report(per_symbol, skipped, elapsed):
    per_symbol = apply_exclusions(per_symbol)
    if not per_symbol:
        print("every symbol was excluded"); return
    grids = aggregate(per_symbol)
    pr, pp, nb = grids["paired"], grids["pairp"], grids["nb"]
    off_sells = grids["sells"][OFF_KEY]

    print(f"\nOFF (= live)   mean {grids['mean'][OFF_KEY]:+.2f}  "
          f"median {grids['median'][OFF_KEY]:+.2f}  "
          f"sells {off_sells:.2f}  buys {grids['buys'][OFF_KEY]:.0f}")

    print(f"\n{'threshold':>10}{'paired':>9}{'p':>8}{'nb':>4}{'mean':>8}{'median':>8}"
          f"{'vote':>6}{'worst':>9}{'sells':>7}{'x OFF':>7}")
    for q in QS:
        k = _key(q)
        x = grids['sells'][k] / off_sells if off_sells else float("nan")
        print(f"{q:>10}{pr[k]:+9.2f}{pp[k]:8.3f}{nb[k]:4d}{grids['mean'][k]:8.1f}"
              f"{grids['median'][k]:8.1f}{grids['vote'][k]:6d}{grids['worst'][k]:9.1f}"
              f"{grids['sells'][k]:7.2f}{x:7.1f}")

    good = sorted(((pr[_key(q)], q) for q in QS
                   if pr[_key(q)] > 0 and pp[_key(q)] < 0.05), reverse=True)
    print(f"\ncells beating OFF with p<0.05: {len(good)}/{len(QS)}")
    for v, q in good:
        x = grids['sells'][_key(q)] / off_sells if off_sells else float("nan")
        print(f"  {q:>5}  paired {v:+.2f}  p {pp[_key(q)]:.3f}  nb {nb[_key(q)]}  "
              f"sells {grids['sells'][_key(q)]:.2f} ({x:.1f}x OFF)"
              f"{'   <-- CHURN' if x > 2 else ''}")
    if good:
        solid = [q for _, q in good if nb[_key(q)] >= 2]
        print(f"  with both neighbours agreeing: {len(solid)}"
              f"{' — ' + ', '.join(str(q) for q in solid) if solid else ' (isolated cells only)'}")
    print(f"  cells whose paired median is exactly 0.00: "
          f"{sum(1 for q in QS if abs(pr[_key(q)]) < 1e-9)}/{len(QS)}")

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
    print(f"Sweeping {len(QS)} thresholds + off over {len(syms)} symbols")
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
