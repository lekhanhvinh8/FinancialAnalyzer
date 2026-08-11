"""
Sweep the signal1 sell filter: SELL_SIGNAL1_WINDOW x SELL_MIN_SIGNAL1.

signal1 blocks ~61% of all sell-eligible days — more than the other two filters
combined — and has never been tuned. This maps the surface.

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

  Per-symbol diffs are saved to sweep_signal1_raw.json, so switching score costs
  seconds instead of another full sweep:

      python sweep_signal1.py --rescore          # median
      python sweep_signal1.py --rescore --mean   # mean

  Look for a plateau, not the maximum. Taking the best of ~180 cells will find a
  good-looking number whether or not any edge exists; a contiguous region that
  stays good is evidence, an isolated spike beside bad neighbours is noise.

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


def aggregate(per_symbol: dict, score: str):
    """score: 'median' or 'mean'. Returns (grid_score, grid_winrate)."""
    fn = st.median if score == "median" else st.mean
    grid, win = {}, {}
    for w in WINDOWS:
        for k in KS:
            vals = [d[(w, k)] for d in per_symbol.values() if (w, k) in d]
            if vals:
                grid[(w, k)] = fn(vals)
                win[(w, k)] = 100 * sum(1 for v in vals if v > 0) / len(vals)
    return grid, win


def save_raw(per_symbol: dict, skipped: list, path: Path):
    """JSON keys must be strings, so (window, k) is encoded as 'window|k'."""
    path.write_text(json.dumps({
        "meta": {
            "windows": WINDOWS, "ks": KS,
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
    return per_symbol, [tuple(x) for x in raw["skipped"]]


def _cell_color(v, lo, hi):
    if v is None:
        return "#1e293b", "#64748b"
    if v >= 0:
        f = 0 if hi <= 0 else min(1.0, v / hi)
        return f"rgba(34,197,94,{0.12 + 0.55*f:.2f})", "#dcfce7"
    f = 0 if lo >= 0 else min(1.0, v / lo)
    return f"rgba(239,68,68,{0.12 + 0.55*f:.2f})", "#fee2e2"


def build_html(grid_med, grid_win, n_syms, elapsed, skipped, score="median"):
    meds = [v for v in grid_med.values() if v is not None]
    lo, hi = (min(meds), max(meds)) if meds else (0, 0)
    best = max(grid_med.items(), key=lambda kv: (kv[1] is not None, kv[1]))

    head = "".join(f"<th>k={k:g}<br><span style='color:#64748b;font-weight:400'>"
                   f"{_threshold(k,100):.2f} @w100</span></th>" for k in KS)
    body = ""
    for w in WINDOWS:
        body += f"<tr><th style='text-align:right'>{w}</th>"
        for k in KS:
            v = grid_med.get((w, k))
            bg, fg = _cell_color(v, lo, hi)
            wr = grid_win.get((w, k))
            mark = " ★" if (w, k) == best[0] else ""
            body += (f"<td style='background:{bg};color:{fg}'>"
                     f"{'—' if v is None else f'{v:+.2f}%'}{mark}"
                     f"<br><span style='font-size:10px;color:#94a3b8'>"
                     f"{'' if wr is None else f'{wr:.0f}% win'}</span></td>")
        body += "</tr>"

    skip_html = ""
    if skipped:
        skip_html = ("<p style='color:#64748b;font-size:12px'>Skipped: " +
                     ", ".join(f"{s} ({why})" for s, why in sorted(skipped)) + "</p>")

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>signal1 sweep</title><style>
body{{font-family:sans-serif;background:#0b1220;color:#e2e8f0;padding:20px}}
table{{border-collapse:collapse;font-size:12px}}
th,td{{border:1px solid #1e293b;padding:5px 8px;text-align:center}}
th{{background:#111c30;color:#94a3b8;font-weight:600}}
.note{{color:#94a3b8;font-size:13px;line-height:1.7;max-width:900px}}
</style></head><body>
<h2>signal1 sell filter — window x k sweep</h2>
<p class="note">Cell = <b>mean per-symbol diff</b> (Median1000 − BuyInterval) over
{n_syms} symbols; small text = win rate. Threshold is <code>k/&radic;window</code>,
so a column is roughly constant strictness across windows
(k=-4 blocks ~95% of sell-eligible days, k=0 about 55%, k=+4 about 5%). Current live config is
<b>window {config.SELL_SIGNAL1_WINDOW}, min_signal1 {config.SELL_MIN_SIGNAL1}</b>
(k&nbsp;&asymp;&nbsp;{config.SELL_MIN_SIGNAL1*math.sqrt(config.SELL_SIGNAL1_WINDOW):.2f}).
<br><b>Read the plateau, not the ★.</b> The best of ~{len(WINDOWS)*len(KS)} cells looks
good by construction; a contiguous good region is evidence, a lone spike is noise.</p>
{skip_html}
<table><thead><tr><th>window</th>{head}</tr></thead><tbody>{body}</tbody></table>
<p class="note">Best cell: window {best[0][0]}, k={best[0][1]:g}
(min_signal1 = {_threshold(*best[0][::-1]) if False else _threshold(best[0][1], best[0][0]):.3f})
&rarr; mean diff {best[1]:+.2f}%. Swept in {elapsed/60:.1f} min.</p>
</body></html>"""


def _report(per_symbol, skipped, score, elapsed):
    grid, win = aggregate(per_symbol, score)
    OUT.write_text(build_html(grid, win, len(per_symbol), elapsed, skipped, score),
                   encoding="utf-8")
    print(f"\nscore = {score.upper()} per-symbol diff, {len(per_symbol)} symbols")
    print(f"{'w':>5} " + " ".join(f"k={k:<5g}" for k in KS))
    for w in WINDOWS:
        print(f"{w:>5} " + " ".join(
            f"{grid.get((w,k), float('nan')):+7.2f}" for k in KS))
    best = max(grid.items(), key=lambda kv: kv[1])
    print(f"\nbest: window {best[0][0]}, k={best[0][1]:g} "
          f"(min_signal1={_threshold(best[0][1], best[0][0]):.3f}) -> {best[1]:+.2f}%")
    print(f"report -> {OUT}")


def main():
    args  = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    score = "mean" if "--mean" in flags else "median"

    # Re-score an existing run without recomputing anything.
    if "--rescore" in flags:
        if not RAW.exists():
            print(f"no raw data at {RAW} — run the sweep first"); return
        per_symbol, skipped = load_raw(RAW)
        print(f"re-scoring {len(per_symbol)} symbols from {RAW.name} as {score}")
        _report(per_symbol, skipped, score, 0.0)
        return

    syms = [s.upper() for s in args] or db.list_symbols()
    print(f"Sweeping {len(WINDOWS)}x{len(KS)} = {len(WINDOWS)*len(KS)} combos "
          f"over {len(syms)} symbols")
    t0 = time.time()

    per_symbol, skipped = {}, []
    with ProcessPoolExecutor() as ex:
        for i, (sym, res, note) in enumerate(ex.map(eval_symbol, syms), 1):
            if res is None:
                skipped.append((sym, note))
                print(f"[{i}/{len(syms)}] {sym} skipped — {note}", flush=True)
            else:
                per_symbol[sym] = res
                print(f"[{i}/{len(syms)}] {sym} ok", flush=True)

    if not per_symbol:
        print("nothing to report"); return

    # Written before aggregating, so a crash in the reporting code cannot destroy
    # an hour of computation.
    save_raw(per_symbol, skipped, RAW)
    print(f"raw -> {RAW}")

    elapsed = time.time() - t0
    _report(per_symbol, skipped, score, elapsed)
    print(f"({elapsed/60:.1f} min)   re-score with: "
          f"python {Path(__file__).name} --rescore [--mean]")


if __name__ == "__main__":
    main()
