"""
Sweep REINVEST_TIMEOUT_DAYS — the reserve's release valve.

One parameter. REINVEST_TIMEOUT_PERCENT stays at 999, so the release stays
unconditional: this measures WHEN the valve opens, not what price it demands.
Everything else is at its configured value.

WHAT THE VALVE ACTUALLY DOES

    if (timeoutDays > 0
        and (lastSellIndex == 0     or index - lastSellIndex     >= timeoutDays)
        and (lastReinvestIndex == 0 or index - lastReinvestIndex >= timeoutDays)):
            release the whole reserve

  Two consequences that are easy to miss.

  lastSellIndex == 0 means "has never sold", which makes the condition true. So
  the FIRST release fires as soon as there is anything in the reserve, on any
  setting above zero — it is not waiting for a timeout at all. Setting this to 0
  removes that free first release along with everything else.

  And it competes with REINVEST_TIMEOUT_DAYS. A short timeout releases the reserve
  before the price condition ever gets to speak; a long one, or zero, leaves the
  price condition doing all the work. So this sweep answers the question the
  REINVEST_TIMEOUT_DAYS sweep could not: how much of that arm's behaviour was the
  condition and how much was the valve. That one held this at 400 throughout.

THE GRID

  Evaluated history is ~2800 bars, about eleven years, so:

      0     off. No valve, and no free first release either.
      20    roughly monthly
      90    roughly quarterly
      400   current, about 1.6 years
      1200  about five years
      2800  fires once at the start and never again

  Spaced logarithmically because the effect is proportional — the step from 20 to
  40 halves the release rate, the step from 1800 to 2800 barely moves it.

  0 is the off value here, not None. None is not meaningful for this parameter
  and the factory would pass it straight through into a `> 0` comparison.

WHAT IT FOUND: ONLY ONE WAY TO GET THIS WRONG

  52 symbols, 14 settings. Nothing beats live; every cell is 0.00 or negative
  against it, and the best p is 0.220.

      setting    vs live       p    reinv   sells
      0 (off)      +0.00   0.667      2.1     1.9
      20 d        -17.20   1.000     27.3    12.1
      40 d         -7.33   0.997     15.8     7.3
      90 d         -1.23   0.944      8.7     4.5
      190 d        +0.00   0.860      5.5     3.1
      400 d          —       —        4.0     2.3   live
      1200 d       +0.00   0.439      2.8     2.2
      2800 d       +0.00   0.220      2.6     2.2

  Short is the only real mistake. At 20 days the arm loses 17 points against
  live on 13/49 symbols, and the counts say why: reinvests run to 27.3 and sells
  to 12.1. Releasing the reserve constantly means holding more shares, which
  triggers more sells — the same churn the PERCENT_REINVEST sweep found at its
  permissive end.

  From 190 days up the valve stops mattering. The paired median is exactly 0.00
  at every setting even though the release count keeps falling from 5.5 to 2.6,
  and past 1200 the rows are identical because the valve fires once at the start
  and never again.

  Switching it off entirely is also indistinguishable from live: 23/48 symbols,
  paired median 0.00, p=0.667, with half as many releases. Left at 400 anyway —
  the valve is insurance against a regime where the price condition stops firing,
  and it currently costs nothing. Dropping something free to save a line is not
  worth it.

  One warning from the aggregate column, which is why the vs column exists. The
  aggregate median peaks exactly at 400 (+20.0) with 15.8 and 12.1 either side,
  which reads like a fine-tuned optimum. Paired, both neighbours are 0.00. That
  peak is noise.

Usage:
    python single/multi_signal/sweep_reinvest_timeout.py             # all symbols
    python single/multi_signal/sweep_reinvest_timeout.py FPT STB     # a subset
    python single/multi_signal/sweep_reinvest_timeout.py --rescore
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
from single.multi_signal import config
from single.multi_signal.factory import make_median_strategies, make_interval_strategies

# Log-spaced, see the header. 0 first because it is the off value: no valve at
# all, which also removes the free first release the other settings get.
GRID = [0, 20, 40, 60, 90, 130, 190, 270, 400, 550, 800, 1200, 1800, 2800]

OUT  = Path(__file__).parent / "sweep_reinvest_timeout.html"
RAW  = Path(__file__).parent / "sweep_reinvest_timeout_raw.json"
PROG = Path(__file__).parent / "sweep_reinvest_timeout_progress.html"


def _key(v):
    return str(v)


def _label(v):
    return "0 (no valve)" if v == 0 else f"{v} d"


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
                zdev_map=z, reinvest_timeout_days=v)
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
    live_key = _key(config.REINVEST_TIMEOUT_DAYS)
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
<h2>REINVEST_TIMEOUT_DAYS sweep &mdash; {'running' if done < total else 'done'}</h2>
<div class="bar"><div class="fill"></div></div>
<p><span class="v">{done} / {total}</span> symbols <span class="k">({pct:.0f}%)</span></p>
<p><span class="k">grid</span> <span class="v">{len(GRID)}</span> settings per symbol</p>
<p><span class="k">elapsed</span> <span class="v">{el/60:.1f} min</span>&nbsp;&nbsp;
<span class="k">eta</span> <span class="v">
{('%.1f min' % (eta/60)) if done and done < total else '&mdash;'}</span></p>
<p class="k">{note}</p></body></html>""", encoding="utf-8")


def build_html(rows, n_syms, skipped, elapsed, per_symbol=None):
    live = _key(config.REINVEST_TIMEOUT_DAYS)
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
<title>REINVEST_TIMEOUT_DAYS sweep</title><style>
body{{font-family:sans-serif;background:#0b1220;color:#e2e8f0;padding:20px}}
table{{border-collapse:collapse;font-size:13px;margin:14px 0}}
th,td{{border:1px solid #1e293b;padding:6px 12px}}
th{{background:#111c30;color:#94a3b8;text-align:right}}
th:first-child,td:first-child{{text-align:left}}
.note{{color:#94a3b8;font-size:13px;line-height:1.7;max-width:940px}}
</style></head><body>
<h2>REINVEST_TIMEOUT_DAYS sweep</h2>
<p class="note">{n_syms} symbols, {len(GRID)} settings, {elapsed/60:.1f} min. One
parameter only — REINVEST_TIMEOUT_PERCENT stays at {config.REINVEST_TIMEOUT_PERCENT},
so the release is unconditional and this measures <b>when</b> the valve opens.<br>
The valve also fires the very first time there is anything in the reserve, on any
setting above zero, because "has never sold" satisfies its condition. <b>0</b>
removes the valve and that free first release together.<br>
It competes with PERCENT_REINVEST: a short timeout empties the reserve before the
price condition can act, a long one leaves the condition doing the work. Watch
<b>reinv</b> for which is happening.</p>
{skip_html}
<table><thead><tr><th>REINVEST_TIMEOUT_DAYS</th><th>mean</th><th>median</th><th>win</th>
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
    print(f"{'REINVEST_TIMEOUT_DAYS':>17} {'mean':>8} {'median':>8} {'win':>6} {'vote':>5} "
          f"{'worst':>8} | {'vs live':>8} {'up':>6} {'p':>6} | "
          f"{'reinv':>6} {'buys':>5} {'sells':>6}")
    for v in GRID:
        k = _key(v)
        if k not in rows:
            continue
        r = rows[k]
        star = "  <- live" if k == _key(config.REINVEST_TIMEOUT_DAYS) else ""
        pair = "     —  " if k == _key(config.REINVEST_TIMEOUT_DAYS) else f"{r['pair']:+8.2f}"
        pp   = "      " if k == _key(config.REINVEST_TIMEOUT_DAYS) else f"{r['pair_p']:6.3f}"
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
