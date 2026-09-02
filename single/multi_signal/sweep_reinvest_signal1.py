"""
Sweep the reinvest slope gate: REINVEST_SIGNAL1_WINDOW x REINVEST_MIN_SIGNAL1.

Mirror of sweep_sell_signal1.py for the other arm. The sell side is held at its config
values throughout; only the reinvest gate moves.

OPPOSITE POLARITY TO THE SELL GATE

  Both arms read the same signal1 slope and compare it the same way, but they
  want opposite things from it:

      sell      BLOCKED while slope >= min_signal1   trend intact, let it run
      reinvest  ALLOWED only once slope >= min_signal1   wait for the turn

  So raising the threshold makes the sell arm sell MORE and the reinvest arm
  reinvest LESS. k is signed the same way in both sweeps — higher k is a higher
  slope threshold — but it means "looser" in one grid and "stricter" in the other.
  Read the reinvest count column before interpreting any cell.

WHAT LIMITS THIS GATE

  It guards check() only. The timeout path in considerReinvest is deliberately
  left as an unconditional release valve, so with REINVEST_TIMEOUT_DAYS = 400 the
  reserve comes back out on its own eventually no matter what this gate does. A
  strict setting delays reinvestment; it cannot prevent it. Expect a smaller
  surface than the sell sweep's.

THE THRESHOLD IS SCALED BY THE WINDOW

  Same quantity, same law as the sell gate — the slope's spread shrinks as the
  window grows, p95 = 3.991 * w^-0.494 (single/multi_signal/dispersion.py), close
  enough to 4/sqrt(w). So the swept quantity is k in

      REINVEST_MIN_SIGNAL1 = k / sqrt(window)

  and a column is roughly constant strictness at every window. Live is
  REINVEST_SIGNAL1_WINDOW = 100 with REINVEST_MIN_SIGNAL1 = 0.05, i.e. k = +0.5.

  Note the sign, and that it means the opposite of what it means for the sell
  gate. k negative lets reinvestment through on most days, since most days have a
  slope above a negative threshold; k positive holds the reserve back until the
  slope is clearly up. The live +0.5 is therefore on the strict side.

READING IT

  Same as every other sweep here. Mean beside the round-robin vote, both taken
  per symbol against the same symbol at another cell, and the reinvest count as
  the mechanism check. A contiguous region, not the best of 340 cells.

Usage:
    python single/multi_signal/sweep_reinvest_signal1.py            # all symbols
    python single/multi_signal/sweep_reinvest_signal1.py FPT STB    # a subset
    python single/multi_signal/sweep_reinvest_signal1.py --rescore
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

WINDOWS = list(range(10, 201, 10))                        # 20
KS      = [round(-4.0 + 0.5 * i, 1) for i in range(17)]   # -4.0 .. 4.0

OUT  = Path(__file__).parent / "sweep_reinvest_signal1.html"
RAW  = Path(__file__).parent / "sweep_reinvest_signal1_raw.json"
PROG = Path(__file__).parent / "sweep_reinvest_signal1_progress.html"


def _threshold(k: float, window: int) -> float:
    return k / math.sqrt(window)


def _key(w, k):
    return f"{w}|{k}"


def eval_symbol(sym: str):
    """Returns (sym, {key: (diff, reinvests, sells)}, note)."""
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

        # The sell side stays on its configured window and threshold. Letting it
        # follow the sweep is the mistake sweep_sell_signal1 made in the other
        # direction, and it makes a cell answer two questions at once.
        s3 = sig(1000, "signal3_sharpe") if config.MIN_SIGNAL3 is not None else {}
        s1 = (sig(config.SELL_SIGNAL1_WINDOW, "signal1_slope")
              if config.SELL_MIN_SIGNAL1 is not None else {})
        z = {}
        if config.SELL_MIN_ZDEV is not None:
            zd = db.load_zdev(sym, 1000, config.SELL_ZDEV_WINDOW)
            if zd.empty:
                return sym, None, f"no z_dev at stat_window={config.SELL_ZDEV_WINDOW}"
            for dt, v in zd["z_dev"].items():
                i = d2i.get(pd.Timestamp(dt))
                if i is not None and v is not None:
                    z[i] = float(v)

        # The swept maps, one per window, reused across every k.
        ri_by_w = {w: sig(w, "signal1_slope") for w in WINDOWS}

        # One start index for every cell, taken over the LONGEST swept window so
        # no cell is judged on more bars than its neighbour. All of them are well
        # under the 1000 the sell arm needs anyway.
        start_idx = max([1000, max(WINDOWS) - 1]
                        + [min(m) for m in (s1, s3, z) if m])
        eval_bars = len(df) - start_idx
        if config.MIN_EVAL_BARS and eval_bars < config.MIN_EVAL_BARS:
            return sym, None, f"only {eval_bars} bars after warmup"

        b0, s0, r0 = make_interval_strategies()
        base = run_estimate(sym, df, config.INTERVAL_MONEY, b0, s0, r0, crc,
                            start_index=start_idx)["allRatioGrowth"]

        out = {}
        for w in WINDOWS:
            ri_map = ri_by_w[w]
            for k in KS:
                buy, sell, rei = make_median_strategies(
                    signal3_map=s3, signal1_map=s1,
                    reinvest_signal1_map=ri_map, zdev_map=z,
                    reinvest_min_signal1=_threshold(k, w))
                r = run_estimate(sym, df, config.INTERVAL_MONEY, buy, sell, rei,
                                 crc, start_index=start_idx)
                out[_key(w, k)] = (round(r["allRatioGrowth"] - base, 4),
                                   r["totalReinvest"], r["totalSells"])
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


METRICS = {
    "mean":      ("Mean diff",    "%", +1),
    "vote":      ("Cells beaten", "",  +1),
    "median":    ("Median diff",  "%", +1),
    "win":       ("Win rate",     "%", +1),
    "worst":     ("Worst symbol", "%", +1),
    "reinvests": ("Reinvests",    "",  0),
    "sells":     ("Sells",        "",  0),
}


def aggregate(per_symbol: dict) -> dict:
    keys = [_key(w, k) for w in WINDOWS for k in KS]
    syms = [s for s in per_symbol if all(kk in per_symbol[s] for kk in keys)]
    grids = {m: {} for m in METRICS}
    if not syms:
        return grids
    m = np.array([[per_symbol[s][kk][0] for kk in keys] for s in syms])
    for i, kk in enumerate(keys):
        col = m[:, i][:, None]
        grids["vote"][kk] = int(((col - m > 1e-9).sum(axis=0)
                                 > (m - col > 1e-9).sum(axis=0)).sum())
        vals = sorted(m[:, i].tolist())
        grids["mean"][kk] = st.mean(vals)
        grids["median"][kk] = st.median(vals)
        grids["win"][kk] = 100 * sum(1 for v in vals if v > 0) / len(vals)
        grids["worst"][kk] = vals[0]
        grids["reinvests"][kk] = st.mean([per_symbol[s][kk][1] for s in syms])
        grids["sells"][kk] = st.mean([per_symbol[s][kk][2] for s in syms])
    return grids


def save_raw(per_symbol, skipped, elapsed):
    RAW.write_text(json.dumps({
        "meta": {
            # Positional layout of every cell tuple. Two orders grew up across these
            # sweeps and they differ only by position, so a reader that assumes the
            # wrong one reports buys as reinvests and says nothing.
            "fields": ["diff", "reinvests", "sells"],
            "windows": WINDOWS, "ks": KS, "elapsed": elapsed,
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
<meta http-equiv="refresh" content="3"><title>reinvest signal1 sweep</title><style>
body{{font-family:sans-serif;background:#0b1220;color:#e2e8f0;padding:24px}}
.bar{{background:#1e293b;border-radius:6px;height:22px;width:520px;overflow:hidden}}
.fill{{background:#22c55e;height:100%;width:{pct:.1f}%}}
.k{{color:#64748b}} .v{{font-weight:700}}</style></head><body>
<h2>reinvest signal1 sweep &mdash; {'running' if done < total else 'done'}</h2>
<div class="bar"><div class="fill"></div></div>
<p><span class="v">{done} / {total}</span> symbols <span class="k">({pct:.0f}%)</span></p>
<p><span class="k">grid</span> <span class="v">{len(WINDOWS)}&times;{len(KS)}
= {len(WINDOWS)*len(KS)}</span> cells per symbol</p>
<p><span class="k">elapsed</span> <span class="v">{el/60:.1f} min</span>&nbsp;&nbsp;
<span class="k">eta</span> <span class="v">
{('%.1f min' % (eta/60)) if done and done < total else '&mdash;'}</span></p>
<p class="k">{note}</p></body></html>""", encoding="utf-8")


def build_html(grids, n_syms, skipped, elapsed):
    live_w = config.REINVEST_SIGNAL1_WINDOW
    live_k = ((config.REINVEST_MIN_SIGNAL1 * math.sqrt(live_w))
              if config.REINVEST_MIN_SIGNAL1 is not None else None)

    rows = ""
    for m, (label, unit, d) in METRICS.items():
        g = grids.get(m) or {}
        if not g or d == 0:
            continue
        bk, bv = max(g.items(), key=lambda kv: kv[1])
        w, k = bk.split("|")
        rows += (f"<tr><td style='text-align:left'>{label}</td>"
                 f"<td><b>w={w}, k={k}</b></td>"
                 f"<td>REINVEST_MIN_SIGNAL1 = {_threshold(float(k), int(w)):.3f}</td>"
                 f"<td style='color:#4ade80'>{bv:+.2f}{unit}</td></tr>")

    skip_html = ("<p class='note'>Skipped: "
                 + ", ".join(f"{s} ({w})" for s, w in sorted(skipped)) + "</p>"
                 ) if skipped else ""

    data = {m: {k: (round(v, 3) if isinstance(v, float) else v)
                for k, v in (grids.get(m) or {}).items()} for m in METRICS}
    opts = "".join(f"<option value='{m}'{' selected' if m == 'mean' else ''}>{lbl}</option>"
                   for m, (lbl, _, _) in METRICS.items())

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>reinvest signal1 sweep</title><style>
body{{font-family:sans-serif;background:#0b1220;color:#e2e8f0;padding:20px}}
table{{border-collapse:collapse;font-size:12px;margin:10px 0}}
th,td{{border:1px solid #1e293b;padding:5px 8px;text-align:center}}
th{{background:#111c30;color:#94a3b8}}
.note{{color:#94a3b8;font-size:13px;line-height:1.7;max-width:960px}}
select{{background:#111c30;color:#e2e8f0;border:1px solid #334155;padding:6px 10px;
  border-radius:6px;font-size:14px}}
.card{{background:#0f172a;border:1px solid #1e293b;border-radius:8px;
  padding:12px 16px;margin:12px 0;display:inline-block}}
.wrap{{overflow-x:auto}}
</style></head><body>
<h2>Reinvest slope gate: window &times; threshold</h2>
<p class="note">{n_syms} symbols, {len(WINDOWS)}&times;{len(KS)} =
{len(WINDOWS)*len(KS)} cells, {elapsed/60:.1f} min. The sell side is held at its
config values; only the reinvest gate moves. Threshold is
<code>k/&radic;window</code>.
<br><b>Polarity is the opposite of the sell gate:</b> reinvest is ALLOWED only
once the slope reaches the threshold, so a higher k reinvests LESS. Check the
reinvest count before reading anything else.
<br>This gate guards <code>check()</code> only — the {config.REINVEST_TIMEOUT_DAYS}-day
timeout still releases the reserve regardless, so a strict setting delays
reinvestment rather than preventing it.
<br>Live: <b>w={live_w}, REINVEST_MIN_SIGNAL1={config.REINVEST_MIN_SIGNAL1}</b>
{f'(k &asymp; {live_k:.2f})' if live_k is not None else '(gate off)'}.</p>
{skip_html}
<div class="card"><b>What each metric prefers</b>
<table><thead><tr><th>metric</th><th>best cell</th><th>threshold</th>
<th>value</th></tr></thead><tbody>{rows}</tbody></table>
<span class="note">Mean follows the largest symbol; vote gives every symbol one
vote and is blind to size.</span></div>

<p><b>Heat map:</b> <select id="metric">{opts}</select></p>
<div class="wrap"><table id="grid"></table></div>
<p class="note"><b>Read the plateau, not the best cell.</b> The best of
{len(WINDOWS)*len(KS)} cells looks good whether or not any edge exists.</p>

<script>
const DATA = {json.dumps(data)};
const WS = {json.dumps(WINDOWS)}, KS = {json.dumps(KS)};
const KK = {json.dumps([str(k) for k in KS])};
function render() {{
  const m = document.getElementById('metric').value;
  const g = DATA[m];
  const vals = Object.values(g).filter(v => v !== null && v !== undefined);
  if (!vals.length) return;
  const lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
  let h = '<thead><tr><th>w</th>';
  KS.forEach(k => {{ h += '<th>k=' + k + '</th>'; }});
  h += '</tr></thead><tbody>';
  WS.forEach(function(w) {{
    h += "<tr><th style='text-align:right'>" + w + '</th>';
    KS.forEach(function(k, j) {{
      // Keys are built in Python and shipped as strings: JS renders -4.0 as "-4"
      // and would miss every whole-numbered k.
      const v = g[w + '|' + KK[j]];
      if (v === null || v === undefined) {{
        h += "<td style='color:#475569'>&mdash;</td>"; return;
      }}
      const f = hi === lo ? 0.5 : (v - lo) / (hi - lo);
      const bg = f >= 0.5
        ? 'rgba(34,197,94,' + (0.10 + 0.62 * (f - 0.5) * 2).toFixed(2) + ')'
        : 'rgba(239,68,68,' + (0.10 + 0.62 * (0.5 - f) * 2).toFixed(2) + ')';
      const txt = (m === 'vote') ? v.toFixed(0)
                : (m === 'reinvests' || m === 'sells') ? v.toFixed(1)
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
    OUT.write_text(build_html(grids, len(per_symbol), skipped, elapsed),
                   encoding="utf-8")

    g = grids["mean"]
    print(f"\nmean diff, {len(per_symbol)} symbols")
    print(f"{'w':>5} " + " ".join(f"{k:>6g}" for k in KS))
    for w in WINDOWS:
        print(f"{w:>5} " + " ".join(
            f"{g.get(_key(w,k), float('nan')):6.0f}" for k in KS))

    print("\nwhat each metric prefers:")
    for m, (label, unit, d) in METRICS.items():
        gg = grids.get(m) or {}
        if not gg or d == 0:
            continue
        bk, bv = max(gg.items(), key=lambda kv: kv[1])
        w, k = bk.split("|")
        print(f"  {label:<14} w={w:<5} k={k:<6} "
              f"REINVEST_MIN_SIGNAL1={_threshold(float(k), int(w)):+.3f}  "
              f"-> {bv:+.2f}{unit}")

    lw = config.REINVEST_SIGNAL1_WINDOW
    if config.REINVEST_MIN_SIGNAL1 is not None and lw in WINDOWS:
        lk = min(KS, key=lambda k: abs(_threshold(k, lw) - config.REINVEST_MIN_SIGNAL1))
        kk = _key(lw, lk)
        if kk in g:
            print(f"\nnearest cell to live (w={lw}, "
                  f"REINVEST_MIN_SIGNAL1={config.REINVEST_MIN_SIGNAL1}): k={lk} -> "
                  f"mean {g[kk]:+.1f}, vote {grids['vote'][kk]}, "
                  f"reinvests {grids['reinvests'][kk]:.1f}")
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

    if config.PERCENT_REINVEST is None:
        print("PERCENT_REINVEST is None — the reinvest arm is switched off, so "
              "this gate does nothing. Nothing to sweep.")
        return

    syms = [s.upper() for s in args] or db.list_symbols()
    print(f"Sweeping {len(WINDOWS)}x{len(KS)} = {len(WINDOWS)*len(KS)} cells "
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
