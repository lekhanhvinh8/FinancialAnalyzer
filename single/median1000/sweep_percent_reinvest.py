"""
Sweep PERCENT_REINVEST — the reinvest arm's price condition.

One parameter. The timeout stays at its configured 400 days and the slope gate
stays wherever config leaves it (currently off), so this measures the price
condition on its own. Combinations come later, once each parameter has been read
in isolation.

WHY THIS ONE MATTERS MORE THAN THE SLOPE GATE DID

  Capital that passes through the reinvest arm, as a share of all capital
  deployed, over 52 symbols: mean 91.4%, median 94.0%. Every symbol uses it.

  That is not obvious from the trade counts — ~3.5 reinvests against ~81 buys.
  The reason is that a blocked buy does not vanish: BuyMedian1000Strategy pushes
  the interval into totalReserveCapital, and the only way out of the reserve is
  the reinvest arm. Add the proceeds of every sell and almost all money ends up
  passing through this one condition. A share above 100% for some symbols is the
  same capital recycled several times.

  The slope gate that was just switched off moved the reinvest count by 0.4 across
  its whole grid. This parameter decides when 94% of the money gets deployed.

READ THE SIGN

  The condition is (price - median)/median * 100 < PERCENT_REINVEST, the same
  form and the same sign as PERCENT_BUY, against the same fixed 1000-day median.
  So the number is a ceiling measured ABOVE the median and larger is MORE
  permissive:

      -25   redeploy only 25% below the median          rare
       10   redeploy up to 10% above it                 current
      160   redeploy unless the price has tripled       almost always
      None  never redeploy; the reserve only ever leaves via the timeout

  No k/sqrt(w) normalisation here, unlike the two slope sweeps: the reinvest arm
  has no window of its own, the median is always the 1000-day one, so a raw
  percentage means one thing throughout. The grid is placed off the measured
  spread of price-to-median distance at w=1000 (dispersion.py): p5 -25, p25 -2,
  p50 +17, p75 +52, p95 +156. The live 10 sits near the 45th percentile.

WHAT THE TIMEOUT DOES TO THIS

  REINVEST_TIMEOUT_DAYS = 400 releases the reserve unconditionally once 400 days
  have passed with no sell and no reinvest, and REINVEST_TIMEOUT_PERCENT = 999
  means no price condition applies when it fires. So a strict setting here delays
  redeployment rather than preventing it, and the strict end of the grid converges
  on "the timeout does everything". Watch the reinvest count column: if it barely
  moves, that is what is happening.

  The None row is the exception and is worth having for that reason — it removes
  the arm entirely, timeout included, so the reserve never comes back at all.

WHAT IT FOUND: 10 IS ALREADY THE PEAK

  52 symbols, 14 settings, 2.7 min. The live value wins the mean (+45.8), the
  median (+21.4) and the win rate (79%) at once, and the median curve is cleanly
  unimodal around it:

      -25   -15    -5    +5   +10   +20   +35   +50   +80  +160   None
     13.1  16.7  17.0  17.9  21.4  20.8  19.4  14.5   6.9   7.7   -0.8

  Only the round-robin vote prefers something else, -15, and paired symbol by
  symbol that preference is 24/45 with a median difference of 0.00 and p=0.383 —
  a coin flip, nothing there.

  +5 is the one real rival: 27/41 symbols do better there than at +10, p=0.030.
  But they do better by 0.43 median points while the mean drops 6.34 — many
  symbols improve slightly, a few get much worse. Statistically real, economically
  not worth the trade.

  Above +50 the surface collapses, and the mechanism shows in the counts:
  reinvests run 4.4 -> 22.9 and sells 4.3 -> 11.8. Redeploying constantly means
  holding more shares, which triggers more sells. That is churn, not edge.

  The strongest result is the None row. Removing the arm costs 78 mean points and
  17.7 median, with only 13 of 52 symbols better off. It confirms the 94% capital
  share from the other direction: blocked buys accumulate in the reserve and this
  is the only way out.

  Safe region is wide — anything from -5 to +35 gives a median of 16 to 21 — so
  this is not a parameter that needs to be right to the point.

Usage:
    python single/median1000/sweep_percent_reinvest.py             # all symbols
    python single/median1000/sweep_percent_reinvest.py FPT STB     # a subset
    python single/median1000/sweep_percent_reinvest.py --rescore
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
from single.median1000 import config
from single.median1000.factory import make_median_strategies, make_interval_strategies

# Placed off the measured spread at w=1000, see the header. None last: it is the
# only value that removes the arm rather than tightening it.
GRID = [-25, -15, -10, -5, 0, 5, 10, 20, 35, 50, 80, 120, 160, None]

OUT  = Path(__file__).parent / "sweep_percent_reinvest.html"
RAW  = Path(__file__).parent / "sweep_percent_reinvest_raw.json"
PROG = Path(__file__).parent / "sweep_percent_reinvest_progress.html"


def _key(v):
    return "none" if v is None else str(v)


def _label(v):
    return "None (arm off)" if v is None else f"{v:+d}%"


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
                zdev_map=z, percent_reinvest=v)
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
    live_key = _key(config.PERCENT_REINVEST)
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
<h2>PERCENT_REINVEST sweep &mdash; {'running' if done < total else 'done'}</h2>
<div class="bar"><div class="fill"></div></div>
<p><span class="v">{done} / {total}</span> symbols <span class="k">({pct:.0f}%)</span></p>
<p><span class="k">grid</span> <span class="v">{len(GRID)}</span> settings per symbol</p>
<p><span class="k">elapsed</span> <span class="v">{el/60:.1f} min</span>&nbsp;&nbsp;
<span class="k">eta</span> <span class="v">
{('%.1f min' % (eta/60)) if done and done < total else '&mdash;'}</span></p>
<p class="k">{note}</p></body></html>""", encoding="utf-8")


def build_html(rows, n_syms, skipped, elapsed, per_symbol=None):
    live = _key(config.PERCENT_REINVEST)
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
<title>PERCENT_REINVEST sweep</title><style>
body{{font-family:sans-serif;background:#0b1220;color:#e2e8f0;padding:20px}}
table{{border-collapse:collapse;font-size:13px;margin:14px 0}}
th,td{{border:1px solid #1e293b;padding:6px 12px}}
th{{background:#111c30;color:#94a3b8;text-align:right}}
th:first-child,td:first-child{{text-align:left}}
.note{{color:#94a3b8;font-size:13px;line-height:1.7;max-width:940px}}
</style></head><body>
<h2>PERCENT_REINVEST sweep</h2>
<p class="note">{n_syms} symbols, {len(GRID)} settings, {elapsed/60:.1f} min. One
parameter only — the {config.REINVEST_TIMEOUT_DAYS}-day timeout and the slope
gate stay at their configured values.<br>
The condition is <code>(price&nbsp;&minus;&nbsp;median)/median&nbsp;&times;&nbsp;100
&lt; PERCENT_REINVEST</code> against the fixed 1000-day median, same sign as
PERCENT_BUY, so larger is <b>more permissive</b>. <code>None</code> removes the
arm entirely — the reserve then never comes back, not even on the timeout.<br>
This arm carries <b>94% of all capital deployed</b> (median over 52 symbols): a
blocked buy goes into the reserve, and the reserve only leaves through here.</p>
{skip_html}
<table><thead><tr><th>PERCENT_REINVEST</th><th>mean</th><th>median</th><th>win</th>
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
    print(f"{'PERCENT_REINVEST':>17} {'mean':>8} {'median':>8} {'win':>6} {'vote':>5} "
          f"{'worst':>8} | {'vs live':>8} {'up':>6} {'p':>6} | "
          f"{'reinv':>6} {'buys':>5} {'sells':>6}")
    for v in GRID:
        k = _key(v)
        if k not in rows:
            continue
        r = rows[k]
        star = "  <- live" if k == _key(config.PERCENT_REINVEST) else ""
        pair = "     —  " if k == _key(config.PERCENT_REINVEST) else f"{r['pair']:+8.2f}"
        pp   = "      " if k == _key(config.PERCENT_REINVEST) else f"{r['pair_p']:6.3f}"
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
