"""
Sweep the P/E sell gate: SELL_MIN_PELOG.

Blocks a sell while ln(P/E / its own PE_MEDIAN_WINDOW median) is at or below the
threshold — that is, while the P/E is NOT stretched. A higher threshold blocks
more. The gate is off in config, so the reference every cell is paired against is
the OFF cell, not a live setting.

WHY THIS GATE EXISTS

  The price condition cannot tell "expensive" from "the business grew into the
  price". On a compounder the difference is the whole result. FPT ends 85.03
  points behind buying at every interval, on four sells where the price was far
  above its median and the P/E was barely above its own:

      sell date     price vs median    ln(P/E / median), w=500
      2015-11-03         +77.5%                 0.181
      2018-01-29         +82.0%                 0.021
      2022-01-19        +125.3%                 0.262
      2025-04-18         +77.7%                -0.077

  Over FPT's whole history the price condition fires on 926 days and this one on
  217. A threshold of 0.262 blocks all four sells.

THIS IS Z_DEV'S SHAPE, AND Z_DEV LOST 0/66

  Same polarity, same stated purpose. z_dev's comment in sell.py even claims the
  same interpretation — "a low z_dev says the price is only above its trailing
  median because the business grew into it". That claim was never true of z_dev,
  whose formula is a z-score of ln(price / median price) and contains no earnings
  at all. This one does. That is the entire difference, and it is the reason to
  try again rather than a reason to expect success.

  Read this sweep against that prior, not against the FPT table above.

WHY A LEVEL AND NOT A Z-SCORE

  The obvious alternative is the z-score of the same log ratio, which is far more
  uniform across symbols: setting one threshold so the median symbol fires on 5%
  of days, the z-score form has every symbol between 1.5% and 8.4%, while this
  form has 17 symbols near 0% and 9 above 20%.

  Taken alone that argues for the z-score. Two things argue against it. This
  repo's own record is that level measures work here and z-scores do not —
  PERCENT_SELL is a level and it pays, SELL_MIN_ZDEV is a z-score and it does
  not — and the unevenness of the level form is the unevenness the live
  PERCENT_SELL already runs with, 17 quiet symbols against its 18. A z-score also
  answers a different question: it asks whether the P/E is unusual against its
  recent behaviour, not whether it is high, and a P/E drifting steadily to an
  all-time high reads as perfectly normal to it. FPT on 2022-01-19 is +65.7% over
  its median and -3.03 in z units.

  The z-score form is measured and kept as the fallback if this one finds
  nothing.

THE GRID

  Placed off the measured distribution at w=500 (dispersion.py pelog):

      p5      p25     p50     p75     p95
      -0.774  -0.188  +0.012  +0.231  +0.910

  It runs from below p5, where the gate is inert, to past p95, where the arm
  almost never sells — plus None, which removes it outright. Denser between 0.0
  and 0.4, which is where the FPT sells sit and where a useful setting would be.

  The threshold does not transfer across PE_MEDIAN_WINDOW: p95 = 0.094 * w^0.360,
  so this grid is only valid at 500.

EVERY CELL SHARES ONE START INDEX

  Including the OFF cell. The gate needs a full window of real P/E observations
  behind it (see build_pelog_map in factory.py), which for 31 of 59 symbols starts
  later than the price does. Judging OFF on more bars than the others would make
  the comparison meaningless, so OFF pays the same warmup it is being compared
  against. This is the mistake that invalidated a whole sweep in 9c81db9.

Usage:
    python analyze/median1000/sweep_pelog.py             # all symbols
    python analyze/median1000/sweep_pelog.py FPT GMD     # a subset
    python analyze/median1000/sweep_pelog.py --rescore
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

QS = [-0.80, -0.60, -0.40, -0.30, -0.20, -0.10, 0.00, 0.10,
      0.20, 0.25, 0.30, 0.35, 0.40, 0.50, 0.70, 0.90]        # 16

# The reference: gate off, which is what config has. There is no live cell.
OFF_KEY = "off"

OUT  = Path(__file__).parent / "sweep_pelog.html"
RAW  = Path(__file__).parent / "sweep_pelog_raw.json"
PROG = Path(__file__).parent / "sweep_pelog_progress.html"


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
        crc = db.load_range_stats(symbol=sym, df=df,
                                  range_days={1000, buy_w, sell_w, pe_w})
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

        # Loaded unconditionally: this is the swept quantity, and config has the
        # gate off so honouring SELL_MIN_PELOG here would skip every cell.
        pelog = build_pelog_map(sym, df, crc, pe_w)
        if not pelog:
            return sym, None, f"no usable P/E at window={pe_w}"

        # Shared by every cell INCLUDING off, so no cell is judged on more bars
        # than its neighbour.
        start_idx = max([1000, buy_w, sell_w, min(pelog)]
                        + [min(m) for m in (s1, s3, ri, z) if m])
        eval_bars = len(df) - start_idx
        if config.MIN_EVAL_BARS and eval_bars < config.MIN_EVAL_BARS:
            return sym, None, f"only {eval_bars} bars after warmup"

        b0, s0, r0 = make_interval_strategies()
        base = run_estimate(sym, df, config.INTERVAL_MONEY, b0, s0, r0, crc,
                            start_index=start_idx)["allRatioGrowth"]

        def cell(min_pelog):
            buy, sell, rei = make_median_strategies(
                signal3_map=s3, signal1_map=s1, reinvest_signal1_map=ri,
                zdev_map=z, pelog_map=pelog, min_pelog=min_pelog)
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
    {metric: {key: value}}. Same reading protocol as every other sweep here:

    paired  median per-symbol difference against OFF. Never subtract two
            aggregate columns instead — changing a threshold reorders the
            symbols, so the symbol at the median of one column is not the symbol
            at the median of the other.
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
        nb = [QS[j - 1] for _ in (0,) if j > 0] + [QS[j + 1] for _ in (0,) if j < len(QS) - 1]
        grids["nb"][_key(q)] = sum(1 for x in nb if _key(x) in good)
    grids["nb"][OFF_KEY] = 0
    return grids


def save_raw(per_symbol, skipped, elapsed):
    RAW.write_text(json.dumps({
        "meta": {"qs": QS, "pe_window": getattr(config, "PE_MEDIAN_WINDOW", 500),
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
<meta http-equiv="refresh" content="3"><title>pelog sweep</title><style>
body{{font-family:sans-serif;background:#0b1220;color:#e2e8f0;padding:24px}}
.bar{{background:#1e293b;border-radius:6px;height:22px;width:520px;overflow:hidden}}
.fill{{background:#22c55e;height:100%;width:{pct:.1f}%}}
.k{{color:#64748b}} .v{{font-weight:700}}</style></head><body>
<h2>P/E sell gate sweep &mdash; {'running' if done < total else 'done'}</h2>
<div class="bar"><div class="fill"></div></div>
<p><span class="v">{done} / {total}</span> symbols <span class="k">({pct:.0f}%)</span></p>
<p><span class="k">grid</span> <span class="v">{len(QS)} + off</span> cells per symbol</p>
<p><span class="k">elapsed</span> <span class="v">{el/60:.1f} min</span>&nbsp;&nbsp;
<span class="k">eta</span> <span class="v">
{('%.1f min' % (eta/60)) if done and done < total else '&mdash;'}</span></p>
<p class="k">{note}</p></body></html>""", encoding="utf-8")


def build_html(grids, n_syms, skipped, elapsed):
    pe_w = getattr(config, "PE_MEDIAN_WINDOW", 500)
    rows = ""
    for k in [OFF_KEY] + [_key(q) for q in QS]:
        p, pp = grids["paired"].get(k, 0.0), grids["pairp"].get(k, 1.0)
        lbl = ("<b>OFF</b>" if k == OFF_KEY
               else f"{float(k):+.2f} <span style='color:#64748b'>"
                    f"(P/E {(math.exp(float(k))-1)*100:+.0f}%)</span>")
        hit = (p > 0 and pp < 0.05)
        rows += (
            f"<tr style='background:{'rgba(34,197,94,0.12)' if hit else 'transparent'}'>"
            f"<td style='text-align:left'>{lbl}</td>"
            f"<td style='color:{'#4ade80' if p >= 0 else '#f87171'}'>"
            f"{'' if k == OFF_KEY else f'{p:+.2f}'}</td>"
            f"<td style='color:{'#4ade80' if pp < 0.05 else '#94a3b8'}'>"
            f"{'' if k == OFF_KEY else f'{pp:.3f}'}</td>"
            f"<td>{grids['nb'].get(k, 0)}</td>"
            f"<td>{grids['mean'].get(k, float('nan')):+.1f}</td>"
            f"<td>{grids['median'].get(k, float('nan')):+.1f}</td>"
            f"<td>{grids['vote'].get(k, 0)}</td>"
            f"<td>{grids['worst'].get(k, float('nan')):+.1f}</td>"
            f"<td>{grids['sells'].get(k, float('nan')):.2f}</td>"
            f"<td>{grids['buys'].get(k, float('nan')):.0f}</td></tr>")

    skip_html = ("<p class='note'>Skipped: "
                 + ", ".join(f"{s} ({w})" for s, w in sorted(skipped)) + "</p>"
                 ) if skipped else ""

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>P/E sell gate sweep</title><style>
body{{font-family:sans-serif;background:#0b1220;color:#e2e8f0;padding:20px}}
table{{border-collapse:collapse;font-size:13px;margin:12px 0}}
th,td{{border:1px solid #1e293b;padding:5px 10px;text-align:center}}
th{{background:#111c30;color:#94a3b8}}
.note{{color:#94a3b8;font-size:13px;line-height:1.7;max-width:980px}}
code{{color:#e2e8f0}}
</style></head><body>
<h2>P/E sell gate &mdash; SELL_MIN_PELOG</h2>
<p class="note">{n_syms} symbols, {len(QS)} thresholds plus OFF, {elapsed/60:.1f} min.
Blocks a sell while <code>ln(P/E / median P/E over {pe_w} bars)</code> is at or
below the threshold &mdash; while the P/E is <i>not</i> stretched. Higher blocks
more.<br>
Every figure is paired per symbol against <b>OFF</b>, which is what config has.
OFF runs on the same start index as the gated cells, so it is not judged on extra
bars.<br>
<b>Read the prior, not the table.</b> This is the same shape of gate as
SELL_MIN_ZDEV, which lost on all 66 of its cells. The one real difference is that
z_dev is computed from price alone while this can see earnings.</p>
{skip_html}
<table><thead><tr>
<th>threshold</th><th>paired vs OFF</th><th>sign-test p</th><th>nb (max 2)</th>
<th>mean</th><th>median</th><th>cells beaten</th><th>worst symbol</th>
<th>sells</th><th>buys</th>
</tr></thead><tbody>{rows}</tbody></table>
<p class="note">Green rows beat OFF with p&lt;0.05 and a positive paired median.
With {len(QS)} cells about one reaches p&lt;0.05 by chance, so check <b>nb</b>:
an isolated winner between two losers is noise, two agreeing neighbours is a
plateau. Watch <b>sells</b> too &mdash; a cell that wins by never selling has not
found anything, it has just switched the arm off.</p>
</body></html>"""


def _report(per_symbol, skipped, elapsed):
    per_symbol = apply_exclusions(per_symbol)
    if not per_symbol:
        print("every symbol was excluded"); return
    grids = aggregate(per_symbol)
    pr, pp, nb = grids["paired"], grids["pairp"], grids["nb"]

    print(f"\nOFF (reference)   mean {grids['mean'][OFF_KEY]:+.2f}  "
          f"median {grids['median'][OFF_KEY]:+.2f}  "
          f"sells {grids['sells'][OFF_KEY]:.2f}  buys {grids['buys'][OFF_KEY]:.0f}")

    print(f"\n{'threshold':>10}{'P/E vs med':>12}{'paired':>9}{'p':>8}{'nb':>4}"
          f"{'mean':>8}{'median':>8}{'vote':>6}{'worst':>8}{'sells':>7}")
    for q in QS:
        k = _key(q)
        print(f"{q:>10.2f}{(math.exp(q)-1)*100:>11.0f}%{pr[k]:+9.2f}{pp[k]:8.3f}"
              f"{nb[k]:4d}{grids['mean'][k]:8.1f}{grids['median'][k]:8.1f}"
              f"{grids['vote'][k]:6d}{grids['worst'][k]:8.1f}{grids['sells'][k]:7.2f}")

    good = sorted(((pr[_key(q)], q) for q in QS
                   if pr[_key(q)] > 0 and pp[_key(q)] < 0.05), reverse=True)
    print(f"\ncells beating OFF with p<0.05: {len(good)}/{len(QS)}")
    if good:
        for v, q in good:
            print(f"  {q:+.2f}  paired {v:+.2f}  p {pp[_key(q)]:.3f}  "
                  f"nb {nb[_key(q)]}  sells {grids['sells'][_key(q)]:.2f}")
        solid = [q for _, q in good if nb[_key(q)] >= 2]
        print(f"  with both neighbours agreeing: {len(solid)}"
              f"{' — ' + ', '.join(f'{q:+.2f}' for q in solid) if solid else ' (isolated cells only)'}")
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
    print(f"Sweeping {len(QS)} thresholds + off over {len(syms)} symbols "
          f"at PE_MEDIAN_WINDOW={getattr(config, 'PE_MEDIAN_WINDOW', 500)}")
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
