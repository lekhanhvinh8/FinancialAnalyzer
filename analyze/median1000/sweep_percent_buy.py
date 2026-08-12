"""
Sweep PERCENT_BUY — the buy arm's only condition, and the one never tuned.

WHY THIS ONE

  On the 52-symbol run, per-symbol diff correlates +0.31 with the number of buys
  and only +0.12 with the number of sells. Five of the six symbols that buy least
  often are among the worst results, and LPB alone — 16 buys in 1200 bars, 1.3%
  of them — is -256 of the -873 total loss. The three sell gates have absorbed
  most of the tuning effort so far and the buy arm none of it.

READ THE SIGN BEFORE READING THE GRID

  The condition is (price - median)/median * 100 < PERCENT_BUY, so the number is
  a ceiling measured ABOVE the 1000-day median, and larger is MORE permissive:

      PERCENT_BUY = -20    buy only when 20% BELOW the median      selective
      PERCENT_BUY =  60    buy unless more than 60% above it       current
      PERCENT_BUY = 300    buy unless the price has quadrupled     ~always
      PERCENT_BUY = None   buy every interval                      no buy condition

  The None row is NOT a zero anchor, and it is worth saying why since it looks
  like one. It switches off the buy condition only; the sell and reinvest arms
  are still Median1000. So it measures "DCA in, strategy out" — a useful row, and
  the honest upper end of the permissive direction, but not the interval arm.
  The all-arms check (every PERCENT_* at None, diff must be 0.00) belongs to
  run_all, not here.

  Read that row apart from the rest for a second reason. Every other setting
  uses BuyMedian1000Strategy, which stands down on a bar the sell arm fires;
  None replaces it with BuyIntervalStrategy, which has no such guard because
  "no buy condition" has to mean exactly that. So None sells ~19 times against
  ~5 everywhere else, and part of its number is same-bar churn rather than the
  threshold being permissive.

SCORING

  Same lesson as sweep_signal1: no single statistic answers this. Read the mean
  beside the vote, and check where the buy count lands — a cell can win on mean
  by buying almost never on one lucky symbol.

      mean   size of the effect, and hostage to the largest symbol
      vote   round robin, one vote per symbol, blind to size
      buys   mean buys per symbol, the mechanism behind the number

  Differences are per symbol against the same symbol at another setting; a
  difference of two aggregates would compare different symbols.

Usage:
    python analyze/median1000/sweep_percent_buy.py            # all symbols
    python analyze/median1000/sweep_percent_buy.py FPT LPB    # a subset
    python analyze/median1000/sweep_percent_buy.py --rescore  # re-read the raw JSON
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

# Values are a ceiling above the median (see the header); None last because it
# is the permissive extreme. Negative means "only buy below the median".
GRID = [-40, -30, -20, -10, 0, 10, 20, 30, 40, 50, 60, 70, 80,
        100, 120, 150, 200, 300, None]

OUT  = Path(__file__).parent / "sweep_percent_buy.html"
RAW  = Path(__file__).parent / "sweep_percent_buy_raw.json"
PROG = Path(__file__).parent / "sweep_percent_buy_progress.html"


def _key(v):
    """JSON object keys must be strings, and None has to survive the round trip."""
    return "none" if v is None else str(v)


def _label(v):
    return "None (no buy cond.)" if v is None else f"{v:+d}%"


def eval_symbol(sym: str):
    """Returns (sym, {key: (diff, buys, sells)}, note)."""
    try:
        df = load_symbol_df(sym)
        if len(df) < 1010:
            return sym, None, f"only {len(df)} rows"
        crc = db.load_range_stats(sym, df, range_days=1000)
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

        # Only load what the live config actually gates on, and let those inputs
        # set the start index — the same rule run_all follows, so the two agree
        # on which bars a symbol is judged over.
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

        starts = [1000] + [min(m) for m in (s1, s3, ri, z) if m]
        start_idx = max(starts)
        eval_bars = len(df) - start_idx
        if config.MIN_EVAL_BARS and eval_bars < config.MIN_EVAL_BARS:
            return sym, None, f"only {eval_bars} bars after warmup"

        # The interval arm does not depend on PERCENT_BUY, so it is computed once.
        b0, s0, r0 = make_interval_strategies()
        base = run_estimate(sym, df, config.INTERVAL_MONEY, b0, s0, r0, crc,
                            start_index=start_idx)["allRatioGrowth"]

        out = {}
        for v in GRID:
            buy, sell, rei = make_median_strategies(
                signal3_map=s3, signal1_map=s1, reinvest_signal1_map=ri,
                zdev_map=z, percent_buy=v)
            r = run_estimate(sym, df, config.INTERVAL_MONEY, buy, sell, rei, crc,
                             start_index=start_idx)
            out[_key(v)] = (round(r["allRatioGrowth"] - base, 4),
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


def _vote(per_symbol: dict, keys: list) -> dict:
    """
    Round robin: each setting plays every other, one vote per symbol, scored by
    how many it beats on a majority of the symbols that separate them. Immune to
    a single dominant symbol, and blind to size — read it beside the mean.
    """
    syms = [s for s in per_symbol if all(k in per_symbol[s] for k in keys)]
    if len(syms) < 3:
        return {}
    m = np.array([[per_symbol[s][k][0] for k in keys] for s in syms])
    beaten = {}
    for i, k in enumerate(keys):
        col = m[:, i][:, None]
        beaten[k] = int(((col - m > 1e-9).sum(axis=0)
                         > (m - col > 1e-9).sum(axis=0)).sum())
    return beaten


def aggregate(per_symbol: dict) -> dict:
    keys = [_key(v) for v in GRID]
    votes = _vote(per_symbol, keys)
    rows = {}
    for k in keys:
        vals = sorted(d[k][0] for d in per_symbol.values() if k in d)
        if not vals:
            continue
        n = len(vals)
        wins = sum(1 for v in vals if v > 0)
        dec = sum(1 for v in vals if abs(v) > 1e-9)
        p = (sum(math.comb(dec, i) for i in range(wins, dec + 1)) / 2 ** dec
             if dec else 1.0)
        rows[k] = {
            "median": st.median(vals), "mean": st.mean(vals),
            "win": 100 * wins / n, "p": p, "worst": vals[0],
            "vote": votes.get(k, 0),
            "buys": st.mean([d[k][1] for d in per_symbol.values() if k in d]),
            "sells": st.mean([d[k][2] for d in per_symbol.values() if k in d]),
        }
    return rows


def save_raw(per_symbol, skipped, elapsed):
    RAW.write_text(json.dumps({
        "meta": {"grid": [_key(v) for v in GRID], "elapsed": elapsed,
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
<meta http-equiv="refresh" content="3"><title>percent_buy sweep</title><style>
body{{font-family:sans-serif;background:#0b1220;color:#e2e8f0;padding:24px}}
.bar{{background:#1e293b;border-radius:6px;height:22px;width:520px;overflow:hidden}}
.fill{{background:#22c55e;height:100%;width:{pct:.1f}%}}
.k{{color:#64748b}} .v{{font-weight:700}}</style></head><body>
<h2>PERCENT_BUY sweep &mdash; {'running' if done < total else 'done'}</h2>
<div class="bar"><div class="fill"></div></div>
<p><span class="v">{done} / {total}</span> symbols <span class="k">({pct:.0f}%)</span></p>
<p><span class="k">grid</span> <span class="v">{len(GRID)}</span> settings per symbol</p>
<p><span class="k">elapsed</span> <span class="v">{el/60:.1f} min</span>&nbsp;&nbsp;
<span class="k">eta</span> <span class="v">
{('%.1f min' % (eta/60)) if done and done < total else '—'}</span></p>
<p class="k">{note}</p></body></html>""", encoding="utf-8")


def build_html(rows, per_symbol, skipped, elapsed):
    keys = [k for k in (_key(v) for v in GRID) if k in rows]
    best = {m: (max if m != "p" else min)(rows[k][m] for k in keys)
            for m in ("mean", "median", "win", "vote", "worst", "p")}
    live = _key(config.PERCENT_BUY)

    body = ""
    for v in GRID:
        k = _key(v)
        if k not in rows:
            continue
        r = rows[k]
        mark = " &larr; live" if k == live else ""
        anchor = (" <span style='color:#64748b'>buy every interval; "
                  "sell/reinvest still on</span>" if v is None else "")
        hl = "background:#1e293b;" if k == live else ""
        def cell(m, txt):
            c = "#4ade80" if r[m] == best[m] else "#e2e8f0"
            return f"<td style='text-align:right;color:{c}'>{txt}</td>"
        body += (
            f"<tr style='{hl}'><td><b>{_label(v)}</b>{mark}{anchor}</td>"
            + cell("mean", f"{r['mean']:+.1f}%")
            + cell("median", f"{r['median']:+.1f}%")
            + cell("win", f"{r['win']:.0f}%")
            + cell("vote", f"{r['vote']}")
            + cell("worst", f"{r['worst']:+.0f}%")
            + cell("p", f"{r['p']:.3f}")
            + f"<td style='text-align:right;color:#94a3b8'>{r['buys']:.0f}</td>"
            + f"<td style='text-align:right;color:#94a3b8'>{r['sells']:.1f}</td></tr>")

    skip_html = ("<p class='note'>Skipped: "
                 + ", ".join(f"{s} ({w})" for s, w in sorted(skipped)) + "</p>"
                 ) if skipped else ""

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>PERCENT_BUY sweep</title><style>
body{{font-family:sans-serif;background:#0b1220;color:#e2e8f0;padding:20px}}
table{{border-collapse:collapse;font-size:13px;margin:14px 0}}
th,td{{border:1px solid #1e293b;padding:6px 12px}}
th{{background:#111c30;color:#94a3b8;text-align:right}}
th:first-child,td:first-child{{text-align:left}}
.note{{color:#94a3b8;font-size:13px;line-height:1.7;max-width:900px}}
</style></head><body>
<h2>PERCENT_BUY sweep</h2>
<p class="note">{len(per_symbol)} symbols, {len(GRID)} settings, {elapsed/60:.1f} min.
The condition is <code>(price&nbsp;&minus;&nbsp;median)/median&nbsp;&times;&nbsp;100
&lt; PERCENT_BUY</code>, so the number is a ceiling <b>above</b> the 1000-day
median and larger is <b>more permissive</b>. <code>None</code> removes the buy
condition only &mdash; sell and reinvest stay on, so that row is
&ldquo;DCA in, strategy out&rdquo;, not the comparison arm.</p>
{skip_html}
<table><thead><tr><th>PERCENT_BUY</th><th>mean</th><th>median</th><th>win</th>
<th>vote</th><th>worst</th><th>p</th><th>buys</th><th>sells</th></tr></thead>
<tbody>{body}</tbody></table>
<p class="note">Green marks the best cell in each column. <b>mean</b> is hostage
to the largest symbol, <b>vote</b> is one per symbol and blind to size — a
setting that wins only one of them is telling you which way it is biased.
<b>buys</b> is the mechanism: read it before believing any of the rest.</p>
</body></html>"""


def _report(per_symbol, skipped, elapsed):
    per_symbol = apply_exclusions(per_symbol)
    if not per_symbol:
        print("every symbol was excluded"); return
    rows = aggregate(per_symbol)
    OUT.write_text(build_html(rows, per_symbol, skipped, elapsed), encoding="utf-8")

    print(f"\n{len(per_symbol)} symbols\n")
    print(f"{'PERCENT_BUY':>12} {'mean':>8} {'median':>8} {'win':>6} "
          f"{'vote':>5} {'worst':>8} {'buys':>6} {'sells':>6}")
    for v in GRID:
        k = _key(v)
        if k not in rows:
            continue
        r = rows[k]
        print(f"{_label(v):>12} {r['mean']:+8.1f} {r['median']:+8.1f} "
              f"{r['win']:5.0f}% {r['vote']:5d} {r['worst']:+8.0f} "
              f"{r['buys']:6.0f} {r['sells']:6.1f}")

    live = rows.get(_key(config.PERCENT_BUY))
    if live:
        by_mean = max(rows.items(), key=lambda kv: kv[1]["mean"])
        by_vote = max(rows.items(), key=lambda kv: kv[1]["vote"])
        print(f"\nlive PERCENT_BUY={config.PERCENT_BUY}: "
              f"mean {live['mean']:+.1f}, vote {live['vote']}")
        print(f"best mean: {by_mean[0]} ({by_mean[1]['mean']:+.1f})   "
              f"best vote: {by_vote[0]} ({by_vote[1]['vote']})")
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
    print(f"Sweeping {len(GRID)} settings over {len(syms)} symbols")
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
    print(f"({elapsed/60:.1f} min)   re-score with: python {Path(__file__).name} --rescore")


if __name__ == "__main__":
    main()
