"""
Sweep MIN_SIGNAL3 — the last sell gate nobody has ever measured.

One parameter. Everything else stays at its configured value, so this measures
the Sharpe gate on its own.

WHY IT WAS NEVER MEASURED

  The only number ever attached to it, mean -2.50, was signal3 AND z_dev together
  layered on signal1. z_dev has been off since 73b7ce6, so that figure says
  nothing about this gate alone. It is the one remaining sell filter running on
  an untested value.

WHAT IT DOES

  Blocks a sell while the 1000-day Sharpe is at or above the threshold — the
  reading being "stable, trending regime, let it run". Same polarity as the
  signal1 sell gate: a HIGHER threshold blocks fewer days and therefore sells
  MORE.

NO WINDOW NORMALISATION NEEDED

  The gate always reads signal3 at window 1000; there is no MIN_SIGNAL3_WINDOW to
  sweep, so one window means one scale and the raw threshold is comparable
  throughout. That is why this grid is plain numbers rather than the k/sqrt(w) of
  the two slope sweeps.

  Sharpe does narrow sharply with the window — p95 = 124.6 * w^-0.654, R^2 =
  0.9971 (analyze/median1000/dispersion.py) — which would matter if the window
  were ever swept, and is the reason to add MIN_SIGNAL3_WINDOW before trying that.

THE GRID

  Placed off the measured distribution at w=1000:

      p5      p25     p50     p75     p95
      -0.339  +0.077  +0.423  +0.759  +1.360

  The live 1.1 sits between p75 and p95, blocking roughly 11% of sell-eligible
  days. The grid runs from below p5, where nearly every day is blocked and the arm
  almost never sells, to well past p95 where the gate is inert — plus None, which
  removes it outright. The inert end and None should agree; if they do not,
  something is wrong.

WHAT IT FOUND: 1.1 STANDS, AND THE SHAPE MATTERS MORE THAN THE VALUE

  Nothing beats live; every cell is 0.00 or negative against it. The sanity check
  passes too — 2.0, 2.5 and 3.5 converge exactly on None, which is what an inert
  gate should do.

      setting   vs live       p   sells   worst
      -0.50      -16.09   1.000     0.0     -29
      +0.30       -7.54   0.999     0.5     -34
      +0.45       +0.00   0.832     1.0     -35
      +0.75       +0.00   0.356     1.9     -83
      +1.10          —       —      2.3     -91   live
      +1.30       +0.00   0.999     2.4    -228
      None        +0.00   0.952     2.6    -225

  Below +0.45 it is destructive: nearly every day blocked, the arm stops selling
  altogether, -16.1 paired. From +0.45 to +1.1 the surface is flat, so the precise
  value inside that band is not doing work. Above +1.1 the tail gives way — the
  worst symbol falls from -91 to -228.

  The gate is worth keeping, modestly. Off costs mean -6.04 and a net -314 (+148
  gained, -462 lost), -3.39 even without the largest mover. 34 of 52 symbols are
  untouched. It mainly protects LPB, -91 with it and -225 without; HPG -141 and
  FPT -102 also depend on it, while GMD gains +126 from its removal.

Usage:
    python analyze/median1000/sweep_min_signal3.py             # all symbols
    python analyze/median1000/sweep_min_signal3.py FPT STB     # a subset
    python analyze/median1000/sweep_min_signal3.py --rescore
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

# Placed off the measured Sharpe distribution at w=1000, see the header. None
# last: it is the only value that removes the gate rather than loosening it.
GRID = [-0.5, -0.25, 0.0, 0.15, 0.3, 0.45, 0.6, 0.75,
        0.9, 1.1, 1.3, 1.6, 2.0, 2.5, 3.5, None]

OUT  = Path(__file__).parent / "sweep_min_signal3.html"
RAW  = Path(__file__).parent / "sweep_min_signal3_raw.json"
PROG = Path(__file__).parent / "sweep_min_signal3_progress.html"


def _key(v):
    return "none" if v is None else str(v)


def _label(v):
    return "None (gate off)" if v is None else f"{v:+.2f}"


def eval_symbol(sym: str):
    """Returns (sym, {key: (diff, reinvests, buys, sells)}, note)."""
    try:
        df = load_symbol_df(sym)
        if len(df) < 1010:
            return sym, None, f"only {len(df)} rows"
        buy_w = getattr(config, "BUY_MEDIAN_WINDOW", 1000)
        crc = db.load_range_stats(sym, df, range_days={1000, buy_w})
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

        # Everything except the swept parameter comes from config and stays put.
        # Always loaded: this is the swept quantity, so it must be available even
        # when config currently has the gate off. The other maps stay conditional.
        s3 = sig(1000, "signal3_sharpe")
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

        start_idx = max([1000, buy_w] + [min(m) for m in (s1, s3, ri, z) if m])
        eval_bars = len(df) - start_idx
        if config.MIN_EVAL_BARS and eval_bars < config.MIN_EVAL_BARS:
            return sym, None, f"only {eval_bars} bars after warmup"

        b0, s0, r0 = make_interval_strategies()
        base = run_estimate(sym, df, config.INTERVAL_MONEY, b0, s0, r0, crc,
                            start_index=start_idx)["allRatioGrowth"]

        out = {}
        for v in GRID:
            buy, sell, rei = make_median_strategies(
                signal3_map=s3, signal1_map=s1, reinvest_signal1_map=ri,
                zdev_map=z, min_signal3=v)
            r = run_estimate(sym, df, config.INTERVAL_MONEY, buy, sell, rei, crc,
                             start_index=start_idx)
            out[_key(v)] = (round(r["allRatioGrowth"] - base, 4),
                            r["totalReinvest"], r["totalBuys"], r["totalSells"])
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
    """Round robin, one vote per symbol: immune to a single dominant symbol and
    blind to size. Read beside the mean, never instead of it."""
    syms = [s for s in per_symbol if all(k in per_symbol[s] for k in keys)]
    if len(syms) < 3:
        return {}
    m = np.array([[per_symbol[s][k][0] for k in keys] for s in syms])
    return {k: int(((m[:, i][:, None] - m > 1e-9).sum(axis=0)
                    > (m - m[:, i][:, None] > 1e-9).sum(axis=0)).sum())
            for i, k in enumerate(keys)}


def _paired(per_symbol: dict, k: str, live_key: str) -> dict:
    """Per-symbol difference against the live cell — the only valid comparison
    between two settings. Returns the median of those differences, how many
    symbols improved, and the sign-test p."""
    if k == live_key:
        return {"pair": 0.0, "pair_up": "", "pair_p": 1.0}
    d = [v[k][0] - v[live_key][0]
         for v in per_symbol.values() if k in v and live_key in v]
    if not d:
        return {"pair": float("nan"), "pair_up": "", "pair_p": 1.0}
    up = sum(1 for x in d if x > 1e-9)
    dec = sum(1 for x in d if abs(x) > 1e-9)
    p = (sum(math.comb(dec, i) for i in range(up, dec + 1)) / 2 ** dec
         if dec else 1.0)
    return {"pair": st.median(d), "pair_up": f"{up}/{dec}", "pair_p": p}


def aggregate(per_symbol: dict) -> dict:
    """
    Every column here is an aggregate OVER symbols at one setting. Two of them
    cannot be subtracted from each other: the symbol sitting at the median of one
    column is a different symbol from the one at the median of another, because
    changing the threshold reorders the ranking. On this sweep that mistake read
    +5.51 in favour of a cell that is in fact worse for 33 of 48 symbols.

    So the paired comparison against the live setting is computed here and shown
    as its own column, rather than left for the reader to derive by subtracting.
    """
    keys = [_key(v) for v in GRID]
    votes = _vote(per_symbol, keys)
    live_key = _key(config.MIN_SIGNAL3)
    rows = {}
    for k in keys:
        vals = sorted(d[k][0] for d in per_symbol.values() if k in d)
        if not vals:
            continue
        n = len(vals)
        wins = sum(1 for v in vals if v > 0)
        dec = sum(1 for v in vals if abs(v) > 1e-9)
        rows[k] = {
            "mean": st.mean(vals), "median": st.median(vals),
            "win": 100 * wins / n, "worst": vals[0], "vote": votes.get(k, 0),
            "p": (sum(math.comb(dec, i) for i in range(wins, dec + 1)) / 2 ** dec
                  if dec else 1.0),
            **_paired(per_symbol, k, live_key),
            "reinv": st.mean([d[k][1] for d in per_symbol.values() if k in d]),
            "buys":  st.mean([d[k][2] for d in per_symbol.values() if k in d]),
            "sells": st.mean([d[k][3] for d in per_symbol.values() if k in d]),
        }
    return rows


def save_raw(per_symbol, skipped, elapsed):
    RAW.write_text(json.dumps({
        "meta": {
            # Positional layout of every cell tuple. Two orders grew up across these
            # sweeps and they differ only by position, so a reader that assumes the
            # wrong one reports buys as reinvests and says nothing.
            "fields": ["diff", "reinvests", "buys", "sells"],
            "grid": [_key(v) for v in GRID], "elapsed": elapsed,
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
<meta http-equiv="refresh" content="3"><title>percent_reinvest sweep</title><style>
body{{font-family:sans-serif;background:#0b1220;color:#e2e8f0;padding:24px}}
.bar{{background:#1e293b;border-radius:6px;height:22px;width:520px;overflow:hidden}}
.fill{{background:#22c55e;height:100%;width:{pct:.1f}%}}
.k{{color:#64748b}} .v{{font-weight:700}}</style></head><body>
<h2>MIN_SIGNAL3 sweep &mdash; {'running' if done < total else 'done'}</h2>
<div class="bar"><div class="fill"></div></div>
<p><span class="v">{done} / {total}</span> symbols <span class="k">({pct:.0f}%)</span></p>
<p><span class="k">grid</span> <span class="v">{len(GRID)}</span> settings per symbol</p>
<p><span class="k">elapsed</span> <span class="v">{el/60:.1f} min</span>&nbsp;&nbsp;
<span class="k">eta</span> <span class="v">
{('%.1f min' % (eta/60)) if done and done < total else '&mdash;'}</span></p>
<p class="k">{note}</p></body></html>""", encoding="utf-8")


def build_html(rows, n_syms, skipped, elapsed, per_symbol=None):
    live = _key(config.MIN_SIGNAL3)
    best = {m: (max if m != "p" else min)(rows[k][m] for k in rows)
            for m in ("mean", "median", "win", "vote", "worst", "p")}

    syms  = sorted(per_symbol or {})
    keys  = [_key(v) for v in GRID if _key(v) in rows]
    diffs = {k: [per_symbol[s][k][0] for s in syms] for k in keys} \
            if syms else {}

    body = ""
    for v in GRID:
        k = _key(v)
        if k not in rows:
            continue
        r = rows[k]
        mark = " &larr; live" if k == live else ""
        hl = "background:#1e293b;" if k == live else ""
        def cell(m, txt):
            c = "#4ade80" if r[m] == best[m] else "#e2e8f0"
            return f"<td style='text-align:right;color:{c}'>{txt}</td>"
        body += (
            f"<tr data-row='{k}' style='{hl}'>"
            f"<td><b>{_label(v)}</b>{mark}</td>"
            + cell("mean", f"{r['mean']:+.1f}%") + cell("median", f"{r['median']:+.1f}%")
            + cell("win", f"{r['win']:.0f}%") + cell("vote", f"{r['vote']}")
            + cell("worst", f"{r['worst']:+.0f}%")
            + (f"<td data-vs='{k}' style='border-left:2px solid #334155;"
               f"text-align:right'></td>"
               f"<td data-vsmeta='{k}' style='text-align:right;color:#94a3b8'></td>")
            + f"<td style='text-align:right;color:#94a3b8'>{r['reinv']:.1f}</td>"
            + f"<td style='text-align:right;color:#94a3b8'>{r['buys']:.0f}</td>"
            + f"<td style='text-align:right;color:#94a3b8'>{r['sells']:.1f}</td></tr>")

    skip_html = ("<p class='note'>Skipped: "
                 + ", ".join(f"{s} ({w})" for s, w in sorted(skipped)) + "</p>"
                 ) if skipped else ""

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>MIN_SIGNAL3 sweep</title><style>
body{{font-family:sans-serif;background:#0b1220;color:#e2e8f0;padding:20px}}
table{{border-collapse:collapse;font-size:13px;margin:14px 0}}
th,td{{border:1px solid #1e293b;padding:6px 12px}}
th{{background:#111c30;color:#94a3b8;text-align:right}}
th:first-child,td:first-child{{text-align:left}}
.note{{color:#94a3b8;font-size:13px;line-height:1.7;max-width:940px}}
</style></head><body>
<h2>MIN_SIGNAL3 sweep</h2>
<p class="note">{n_syms} symbols, {len(GRID)} settings, {elapsed/60:.1f} min. One
parameter only; every other gate and condition stays at its configured value.<br>
The gate blocks a sell while the 1000-day Sharpe is at or above the threshold, so
a <b>higher</b> value blocks fewer days and sells <b>more</b> — same polarity as
the signal1 sell gate.<br>
Grid placed off the measured Sharpe distribution at w=1000: p5 &minus;0.34, p25
+0.08, p50 +0.42, p75 +0.76, p95 +1.36. The live 1.10 blocks roughly 11% of
sell-eligible days. No k/&radic;w here — the gate always reads window 1000, so
one scale throughout.<br>
The top of the grid should converge on <b>None</b>; if it does not, something is
wrong.</p>
{skip_html}
<table><thead><tr><th>MIN_SIGNAL3</th><th>mean</th><th>median</th><th>win</th>
<th>vote</th><th>worst</th><th style='border-left:2px solid #334155'>vs <span id='refLabel'>live</span></th>
<th>up / p</th><th>reinv</th><th>buys</th><th>sells</th>
</tr></thead><tbody>{body}</tbody></table>
<p class="note"><b>Click any row to make it the reference</b> — the vs
column recomputes against it from the per-symbol numbers. That is the only way to
compare two settings: subtracting two vs values would be
median(A&minus;ref)&nbsp;&minus;&nbsp;median(B&minus;ref), the same mistake one
level up.<br>
<b>median</b>, <b>win</b> and <b>worst</b> must never be subtracted between rows.
The symbol at the median of one column is a different symbol from the one at the
median of another, because changing the threshold reorders the ranking — on this
grid that mistake reads +5.51 for a cell that is worse for 33 of 48 symbols.
<b>mean</b> is the exception and may be subtracted: it is linear, so
mean(A)&minus;mean(B) is exactly mean(A&minus;B). <b>vote</b> is already a
pairwise round robin.<br>Green marks the best cell in each column. <b>mean</b> is hostage
to the largest symbol, <b>vote</b> gives each symbol one vote and is blind to
size. <b>reinv</b> is the mechanism check: if it barely moves across the grid,
the timeout is doing the work and this parameter only shifts timing.</p>

<script>
// DIFFS[key] = that setting's per-symbol diff, symbols in one fixed order.
// Shipped so the reference row can change in the browser. Subtracting two
// already-computed vs values would be median(A-ref) - median(B-ref), which is a
// difference of two medians again — the same mistake one level up. The only way
// to compare two settings is to go back to the per-symbol numbers.
const DIFFS = {json.dumps(diffs)};
const KEYS  = {json.dumps(keys)};
let   REF   = {json.dumps(live)};

function med(a) {{
  const s = [...a].sort((x, y) => x - y), m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}}
function lchoose(n, k) {{
  let r = 0;
  for (let i = 1; i <= k; i++) r += Math.log(n - k + i) - Math.log(i);
  return r;
}}
function signP(up, dec) {{
  let c = 0;
  for (let k = up; k <= dec; k++) c += Math.exp(lchoose(dec, k) - dec * Math.LN2);
  return Math.min(1, c);
}}

function recompute() {{
  const ref = DIFFS[REF];
  if (!ref) return;
  document.getElementById('refLabel').textContent =
    REF === 'none' ? 'None' : REF + '%';
  KEYS.forEach(function(k) {{
    const cell = document.querySelector('td[data-vs="' + k + '"]');
    const meta = document.querySelector('td[data-vsmeta="' + k + '"]');
    if (!cell) return;
    if (k === REF) {{
      cell.innerHTML = '&mdash;'; cell.style.color = '#64748b';
      meta.textContent = 'reference'; return;
    }}
    const d   = DIFFS[k].map((v, i) => v - ref[i]);
    const up  = d.filter(x => x > 1e-9).length;
    const dec = d.filter(x => Math.abs(x) > 1e-9).length;
    const p   = dec ? signP(up, dec) : 1;
    const m   = med(d);
    cell.textContent = (m >= 0 ? '+' : '') + m.toFixed(2);
    cell.style.color = (m > 0 && p < 0.05) ? '#4ade80'
                     : (m < 0 && p > 0.95) ? '#f87171' : '#e2e8f0';
    meta.textContent = up + '/' + dec + '  p=' + p.toFixed(3);
  }});
  document.querySelectorAll('tr[data-row]').forEach(function(tr) {{
    tr.style.outline = tr.dataset.row === REF ? '2px solid #60a5fa' : '';
  }});
}}
document.querySelectorAll('tr[data-row]').forEach(function(tr) {{
  tr.style.cursor = 'pointer';
  tr.addEventListener('click', function() {{ REF = tr.dataset.row; recompute(); }});
}});
recompute();
</script>
</body></html>"""


def _report(per_symbol, skipped, elapsed):
    per_symbol = apply_exclusions(per_symbol)
    if not per_symbol:
        print("every symbol was excluded"); return
    rows = aggregate(per_symbol)
    OUT.write_text(build_html(rows, len(per_symbol), skipped, elapsed,
                              per_symbol), encoding="utf-8")

    print(f"\n{len(per_symbol)} symbols\n")
    print("columns left of the bar are aggregates at one setting and must NOT be\n"
          "subtracted from each other; vs-live is the paired comparison.\n")
    print(f"{'MIN_SIGNAL3':>17} {'mean':>8} {'median':>8} {'win':>6} {'vote':>5} "
          f"{'worst':>8} | {'vs live':>8} {'up':>6} {'p':>6} | "
          f"{'reinv':>6} {'buys':>5} {'sells':>6}")
    for v in GRID:
        k = _key(v)
        if k not in rows:
            continue
        r = rows[k]
        star = "  <- live" if k == _key(config.MIN_SIGNAL3) else ""
        pair = "     —  " if k == _key(config.MIN_SIGNAL3) else f"{r['pair']:+8.2f}"
        pp   = "      " if k == _key(config.MIN_SIGNAL3) else f"{r['pair_p']:6.3f}"
        print(f"{_label(v):>17} {r['mean']:+8.1f} {r['median']:+8.1f} "
              f"{r['win']:5.0f}% {r['vote']:5d} {r['worst']:+8.0f} | {pair} "
              f"{r['pair_up']:>6} {pp} | "
              f"{r['reinv']:6.1f} {r['buys']:5.0f} {r['sells']:6.1f}{star}")

    by_mean = max(rows.items(), key=lambda kv: kv[1]["mean"])
    by_vote = max(rows.items(), key=lambda kv: kv[1]["vote"])
    print(f"\nbest mean: {by_mean[0]} ({by_mean[1]['mean']:+.1f})   "
          f"best vote: {by_vote[0]} ({by_vote[1]['vote']})")
    rs = [r["reinv"] for r in rows.values()]
    print(f"reinvest count spans {min(rs):.1f} to {max(rs):.1f} — "
          f"{'the timeout is doing the work' if max(rs)-min(rs) < 1 else 'the condition bites'}")
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
    print(f"({elapsed/60:.1f} min)   re-score with: "
          f"python {Path(__file__).name} --rescore")


if __name__ == "__main__":
    main()
