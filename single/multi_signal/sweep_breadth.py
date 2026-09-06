"""
Sweep one breadth threshold at a time: BUY_MAX_BREADTH, SELL_MIN_BREADTH or
REINVEST_MAX_BREADTH, on whichever line BREADTH_SIGNAL names.

    python -m single.multi_signal.sweep_breadth --arm=sell
    python -m single.multi_signal.sweep_breadth --arm=buy --signal=prem_trim_cap
    python -m single.multi_signal.sweep_breadth --arm=reinvest FPT STB
    python -m single.multi_signal.sweep_breadth --arm=sell --rescore

ONE FILE, THREE ARMS, rather than three copies of a 550-line sweep. The sixteen
sweeps beside this one are copies of each other and the cost shows: the same
statistical mistake had to be fixed in each, and their headers disagree about
what the metrics mean. The three breadth thresholds differ only in which
parameter a cell sets and which way the comparison runs, so ARMS holds that and
everything else is shared.

WHAT IS HELD FIXED

  The profile is applied first (default "breadth"), then the swept arm's
  threshold is overridden per cell. The other two arms keep their profile
  values, so this measures ONE parameter against a working configuration -- not
  a grid where everything moves at once.

  BREADTH_SIGNAL is a sweep input because the three lines sit on different
  scales: 60 is the 86th percentile of prem_median and the 78th of prem_trim_cap. A
  threshold quoted without the line it was measured on means nothing.

THE REFERENCE ROW IS THE PROFILE'S OWN VALUE

  and "none" (gate off) is an ordinary row in the grid, so the reader can see
  what the gate is worth at all before asking what its best setting is.

READING THE COLUMNS -- the rules the other sweeps learned the hard way

  median, win and worst are aggregates OVER symbols at one setting and must
  never be subtracted between rows: the symbol at the median of one column is a
  different symbol from the one at the median of another. mean is the exception,
  being linear. vote is a pairwise round robin, one vote per symbol, immune to a
  single dominant name. The paired column does the comparison correctly and is
  re-referenced by clicking a row.

  A PLATEAU IS THE POINT. A single best cell surrounded by worse ones is a fit
  to this history; a run of neighbouring cells that all beat the reference is a
  setting that might survive out of sample. Read the shape of the column, not
  its maximum.
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
from single.multi_signal.profiles import apply as apply_profile

# ── what differs between the three arms ─────────────────────────────────────
# The grids are placed off the measured distribution of the line rather than on
# round numbers: prem_trim_cap runs 10 to 16 points above prem_median, so 40/50/60
# would sit in a different part of the distribution for each signal. Wide enough
# that the ends are clearly wrong, which is how a plateau becomes visible AS a
# plateau rather than as the top of a slope.
ARMS = {
    "buy": {
        "param": "BUY_MAX_BREADTH", "kw": "buy_max_breadth",
        "grid": [10, 20, 30, 40, 50, 55, 60, 65, 70, 75, 80, 90, None],
        "sense": "mua khi ro &le; nguong, nen NHO hon la CHAT hon",
    },
    "sell": {
        "param": "SELL_MIN_BREADTH", "kw": "sell_min_breadth",
        # Extended past 100 after the first run put its best cell on the grid
        # edge, which says nothing about whether the edge is a peak or a slope.
        # prem_trim_cap tops out at 124.8, so 120 still fires occasionally and 130
        # never does -- the grid now contains its own "off" end.
        "grid": [40, 50, 60, 70, 75, 80, 85, 90, 95, 100, 105, 110, 120, 130, None],
        "sense": "ban khi ro &gt; nguong, nen LON hon la CHAT hon",
    },
    "reinvest": {
        "param": "REINVEST_MAX_BREADTH", "kw": "reinvest_max_breadth",
        "grid": [-10, 0, 5, 10, 15, 20, 30, 40, 50, 60, None],
        "sense": "reinvest khi ro &le; nguong, nen NHO hon la CHAT hon",
    },
    # NOT A BREADTH THRESHOLD, and here anyway. The reinvest sweep showed the
    # gate controls nothing -- reinvests held at 3.3-3.5 per symbol across a
    # fivefold change in the threshold -- because this valve releases the reserve
    # whatever the gate says. So this is the parameter that was actually
    # deciding, and it belongs in the same tool rather than in a copy of it.
    #
    # 0 disables the valve, which is the row that isolates the breadth gate.
    "timeout": {
        "param": "REINVEST_TIMEOUT_DAYS", "kw": "reinvest_timeout_days",
        "grid": [0, 60, 120, 200, 300, 400, 500, 700, 1000, 1500],
        "sense": "thoi han xa reserve, NHO hon la xa SOM hon; 0 = tat van",
    },
}

ARM = "sell"          # replaced by --arm in main(), before any worker starts
PROFILE = "breadth"
SIGNAL = None         # None -> whatever config says
# --set=PARAM=VALUE, applied after the profile. Sweeping three thresholds one at
# a time only works if each later sweep runs against the values the earlier ones
# chose; without this the second sweep measures its parameter against a
# configuration already known to be worse, and the third against two.
OVERRIDES = {}


def _apply_all(arm=None, profile=None, signal=None, overrides=None):
    """
    Set this process's sweep settings, then overlay them onto config.

    TAKES ARGUMENTS BECAUSE A WORKER IS A FRESH PROCESS. It re-imports this
    module, so ARM, SIGNAL and OVERRIDES come back as their defaults and
    whatever main() assigned in the parent never arrives. The first run of this
    file swept the sell arm on prem_median while the report said buy on
    prem_trim_cap: every number was real, every label was wrong, and the two sweeps
    were byte-identical -- which is the only reason it was caught.
    """
    global ARM, PROFILE, SIGNAL, OVERRIDES
    if arm is not None:
        ARM = arm
    if profile is not None:
        PROFILE = profile
    if signal is not None:
        SIGNAL = signal
    if overrides is not None:
        OVERRIDES = dict(overrides)
    apply_profile(config, PROFILE)
    if SIGNAL:
        config.BREADTH_SIGNAL = SIGNAL
    for k, v in OVERRIDES.items():
        setattr(config, k, v)


def _paths(arm):
    d = Path(__file__).parent
    return (d / f"sweep_breadth_{arm}.html",
            d / f"sweep_breadth_{arm}_raw.json",
            d / f"sweep_breadth_{arm}_progress.html")


def _key(v):
    return "none" if v is None else f"{v:g}"


def _label(v):
    return "None (tat cong)" if v is None else f"{v:g}"


def _grid():
    return ARMS[ARM]["grid"]


def _live():
    return getattr(config, ARMS[ARM]["param"], None)


def eval_symbol(sym: str, arm: str, profile: str, signal, overrides: dict):
    """Returns (sym, {key: (diff, reinvests, buys, sells)}, note)."""
    _apply_all(arm, profile, signal, overrides)
    try:
        df = load_symbol_df(sym)
        if len(df) < 1010:
            return sym, None, f"only {len(df)} rows"

        buy_w = getattr(config, "BUY_MEDIAN_WINDOW", 1000)
        sell_w = getattr(config, "SELL_MEDIAN_WINDOW", 1000)
        crc = db.load_range_stats(symbol=sym, df=df, range_days={1000, buy_w, sell_w})
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

        # Only the gates the profile actually leaves on. A gate that is off is
        # not loaded, so its warmup cannot push the start index for something
        # nobody is applying.
        s3 = sig(1000, "signal3_sharpe") if config.MIN_SIGNAL3 is not None else {}
        s1 = (sig(config.SELL_SIGNAL1_WINDOW, "signal1_slope")
              if config.SELL_MIN_SIGNAL1 is not None else {})
        ri = (s1 if (s1 and config.REINVEST_SIGNAL1_WINDOW == config.SELL_SIGNAL1_WINDOW)
              else (sig(config.REINVEST_SIGNAL1_WINDOW, "signal1_slope")
                    if config.REINVEST_MIN_SIGNAL1 is not None else {}))

        from single.multi_signal.breadth_map import build_breadth_map
        bm = build_breadth_map(df)
        if not bm:
            return sym, None, f"no breadth for {config.BREADTH_SIGNAL}"

        # The breadth line's own warmup counts: before it starts every gate
        # reading it is shut, and bars where no arm can act are not evaluation.
        start_idx = max([1000, buy_w, sell_w, min(bm)]
                        + [min(m) for m in (s1, s3, ri) if m])
        eval_bars = len(df) - start_idx
        if config.MIN_EVAL_BARS and eval_bars < config.MIN_EVAL_BARS:
            return sym, None, f"only {eval_bars} bars after warmup"

        b0, s0, r0 = make_interval_strategies()
        base = run_estimate(sym, df, config.INTERVAL_MONEY, b0, s0, r0, crc,
                            start_index=start_idx)["allRatioGrowth"]

        kw = ARMS[ARM]["kw"]

        def cell(v):
            buy, sell, rei = make_median_strategies(
                signal3_map=s3, signal1_map=s1, reinvest_signal1_map=ri,
                breadth_map=bm, **{kw: v})
            r = run_estimate(sym, df, config.INTERVAL_MONEY, buy, sell, rei, crc,
                             start_index=start_idx)
            # (diff, reinvests, buys, sells) -- the order every sweep here uses.
            return (round(r["allRatioGrowth"] - base, 4), r["totalReinvest"],
                    r["totalBuys"], r["totalSells"])

        return sym, {_key(v): cell(v) for v in _grid()}, None
    except Exception as e:
        return sym, None, f"{type(e).__name__}: {e}"


def _vote(per_symbol: dict, keys) -> dict:
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
    """Per-symbol difference against the reference cell -- the only valid
    comparison between two settings. Median of those differences, how many
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
    keys = [_key(v) for v in _grid()]
    votes = _vote(per_symbol, keys)
    live_key = _key(_live())
    if live_key not in keys:
        live_key = keys[0]
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
            "buys": st.mean([d[k][2] for d in per_symbol.values() if k in d]),
            "sells": st.mean([d[k][3] for d in per_symbol.values() if k in d]),
        }
    return rows


def save_raw(per_symbol, skipped, elapsed):
    _, RAW, _ = _paths(ARM)
    RAW.write_text(json.dumps({
        "meta": {"fields": ["diff", "reinvests", "buys", "sells"],
                 "arm": ARM, "profile": PROFILE,
                 "signal": SIGNAL or config.BREADTH_SIGNAL,
                 "overrides": {k: v for k, v in OVERRIDES.items()},
                 "grid": [_key(v) for v in _grid()], "elapsed": elapsed,
                 "config": {c: getattr(config, c) for c in dir(config)
                            if c.isupper() and not c.startswith("_")}},
        "skipped": skipped, "results": per_symbol,
    }), encoding="utf-8")


def load_raw():
    _, RAW, _ = _paths(ARM)
    raw = json.loads(RAW.read_text(encoding="utf-8"))
    per = {s: {k: tuple(v) for k, v in d.items()} for s, d in raw["results"].items()}
    return per, [tuple(x) for x in raw["skipped"]], raw["meta"].get("elapsed", 0.0)


def write_progress(done, total, started, note=""):
    _, _, PROG = _paths(ARM)
    el = time.time() - started
    pct = 100 * done / total if total else 0
    eta = (el / done * (total - done)) if done else 0
    name = ARMS[ARM]["param"]
    eta_txt = ("%.1f min" % (eta / 60)) if done and done < total else "&mdash;"
    PROG.write_text(f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<meta http-equiv="refresh" content="3"><title>{name} sweep</title><style>
body{{font-family:sans-serif;background:#0b1220;color:#e2e8f0;padding:24px}}
.bar{{background:#1e293b;border-radius:6px;height:22px;width:520px;overflow:hidden}}
.fill{{background:#22c55e;height:100%;width:{pct:.1f}%}}
.k{{color:#64748b}} .v{{font-weight:700}}</style></head><body>
<h2>{name} sweep &mdash; {'running' if done < total else 'done'}</h2>
<div class="bar"><div class="fill"></div></div>
<p><span class="v">{done} / {total}</span> symbols <span class="k">({pct:.0f}%)</span></p>
<p><span class="k">signal</span> <span class="v">{SIGNAL or config.BREADTH_SIGNAL}</span>
&nbsp;&nbsp;<span class="k">profile</span> <span class="v">{PROFILE}</span>
&nbsp;&nbsp;<span class="k">grid</span> <span class="v">{len(_grid())}</span> settings</p>
<p><span class="k">elapsed</span> <span class="v">{el/60:.1f} min</span>&nbsp;&nbsp;
<span class="k">eta</span> <span class="v">{eta_txt}</span></p>
<p class="k">{note}</p></body></html>""", encoding="utf-8")


def build_html(rows, n_syms, skipped, elapsed, per_symbol=None):
    name = ARMS[ARM]["param"]
    live = _key(_live())
    best = {m: (max if m != "p" else min)(rows[k][m] for k in rows)
            for m in ("mean", "median", "win", "vote", "worst", "p")}

    syms = sorted(per_symbol or {})
    keys = [_key(v) for v in _grid() if _key(v) in rows]
    diffs = {k: [per_symbol[s][k][0] for s in syms] for k in keys} if syms else {}

    body = ""
    for v in _grid():
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
<title>{name} sweep</title><style>
body{{font-family:sans-serif;background:#0b1220;color:#e2e8f0;padding:20px}}
table{{border-collapse:collapse;font-size:13px;margin:14px 0}}
th,td{{border:1px solid #1e293b;padding:6px 12px}}
th{{background:#111c30;color:#94a3b8;text-align:right}}
th:first-child,td:first-child{{text-align:left}}
tbody tr{{cursor:pointer}} tbody tr:hover{{background:#16203a}}
.note{{color:#94a3b8;font-size:13px;line-height:1.7;max-width:940px}}
</style></head><body>
<h2>{name} sweep &mdash; {SIGNAL or config.BREADTH_SIGNAL}</h2>
<p class="note">{n_syms} symbols, {len(_grid())} settings, {elapsed/60:.1f} min,
profile <b>{PROFILE}</b>, line <b>{SIGNAL or config.BREADTH_SIGNAL}</b>.
One parameter only &mdash; the other two breadth thresholds and every gate stay
at their profile values{(", except " + ", ".join(f"{k}={v}" for k, v in OVERRIDES.items())) if OVERRIDES else ""}.<br>
{ARMS[ARM]['sense']}. <code>None</code> switches this gate off.<br>
<b>A plateau is the point.</b> A single best cell with worse neighbours is a fit
to this history. A run of adjacent cells that all beat the reference is a setting
that might survive out of sample.</p>
{skip_html}
<table><thead><tr><th>{name}</th><th>mean</th><th>median</th><th>win</th>
<th>vote</th><th>worst</th>
<th style='border-left:2px solid #334155'>vs <span id='refLabel'>{live}</span></th>
<th>up / p</th><th>reinv</th><th>buys</th><th>sells</th>
</tr></thead><tbody>{body}</tbody></table>
<p class="note"><b>Click any row to make it the reference</b> &mdash; the vs
column recomputes against it from the per-symbol numbers. That is the only way to
compare two settings: subtracting two vs values would be
median(A&minus;ref)&nbsp;&minus;&nbsp;median(B&minus;ref), the same mistake one
level up.<br>
<b>median</b>, <b>win</b> and <b>worst</b> must never be subtracted between rows:
the symbol at the median of one column is a different symbol from the one at the
median of another. <b>mean</b> is the exception and may be subtracted &mdash; it
is linear. <b>vote</b> is a pairwise round robin, one vote per symbol.<br>
Green marks the best cell in each column. <b>mean</b> is hostage to the largest
symbol, <b>vote</b> is blind to size. <b>buys</b> / <b>sells</b> are the mechanism
check: if they barely move across the grid, this threshold is not what decides.</p>
<script>
const D = {json.dumps(diffs)};
function med(a){{const b=[...a].sort((x,y)=>x-y);const n=b.length;
  return n?(n%2?b[(n-1)/2]:(b[n/2-1]+b[n/2])/2):NaN;}}
function comb(n,k){{let r=1;for(let i=0;i<k;i++)r=r*(n-i)/(i+1);return r;}}
function render(ref){{
  document.getElementById('refLabel').textContent = ref;
  for (const k of Object.keys(D)) {{
    const c = document.querySelector('[data-vs="' + k + '"]');
    const m = document.querySelector('[data-vsmeta="' + k + '"]');
    if (!c) continue;
    if (k === ref) {{ c.textContent = '\\u2014'; c.style.color = '#64748b';
                      m.textContent = ''; continue; }}
    const d = D[k].map(function(v, i) {{ return v - D[ref][i]; }});
    const mm = med(d);
    let up = 0, dec = 0;
    for (const x of d) {{ if (Math.abs(x) > 1e-9) {{ dec++; if (x > 0) up++; }} }}
    let p = 1;
    if (dec) {{ let s = 0; for (let i = up; i <= dec; i++) s += comb(dec, i);
                p = s / Math.pow(2, dec); }}
    c.textContent = (mm >= 0 ? '+' : '') + mm.toFixed(1) + '%';
    c.style.color = mm > 0 ? '#4ade80' : (mm < 0 ? '#f87171' : '#e2e8f0');
    m.textContent = dec ? (up + '/' + dec + '  p=' + p.toFixed(3)) : '';
  }}
}}
document.querySelectorAll('tbody tr').forEach(function(tr) {{
  tr.onclick = function() {{ render(tr.dataset.row); }};
}});
render({json.dumps(live)});
</script></body></html>"""


def _report(per_symbol, skipped, elapsed):
    OUT, _, _ = _paths(ARM)
    rows = aggregate(per_symbol)
    name = ARMS[ARM]["param"]
    live = _key(_live())
    print(f"\n{name}  ({SIGNAL or config.BREADTH_SIGNAL}, profile {PROFILE}, "
          f"{len(per_symbol)} symbols)")
    print(f"{'setting':>16}{'mean':>9}{'median':>9}{'win':>7}{'vote':>6}"
          f"{'vs live':>10}{'up/dec':>9}{'p':>8}{'buys':>7}{'sells':>7}")
    for v in _grid():
        k = _key(v)
        if k not in rows:
            continue
        r = rows[k]
        star = " <" if k == live else ""
        print(f"{_label(v):>16}{r['mean']:>+9.1f}{r['median']:>+9.1f}"
              f"{r['win']:>6.0f}%{r['vote']:>6}{r['pair']:>+10.1f}"
              f"{r['pair_up']:>9}{r['pair_p']:>8.3f}{r['buys']:>7.0f}"
              f"{r['sells']:>7.1f}{star}")
    OUT.write_text(build_html(rows, len(per_symbol), skipped, elapsed, per_symbol),
                   encoding="utf-8")
    print(f"\nreport -> {OUT}")


def main():
    global ARM, PROFILE, SIGNAL
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]

    KNOWN = ("--arm=", "--profile=", "--signal=", "--set=", "--rescore")
    unknown = [f for f in flags if not f.startswith(KNOWN)]
    if unknown:
        raise SystemExit(
            f"co la: {' '.join(unknown)}\n"
            "dung:  --arm=buy|sell|reinvest [--signal=NAME] [--profile=NAME] "
            "[--set=PARAM=VALUE] [--rescore] [MA ...]")

    ARM = next((f.split("=", 1)[1] for f in flags if f.startswith("--arm=")), ARM)
    if ARM not in ARMS:
        raise SystemExit(f"--arm phai la: {', '.join(ARMS)}")
    PROFILE = next((f.split("=", 1)[1] for f in flags
                    if f.startswith("--profile=")), PROFILE)
    SIGNAL = next((f.split("=", 1)[1] for f in flags
                   if f.startswith("--signal=")), SIGNAL)
    for f in flags:
        if f.startswith("--set="):
            k, _, v = f[len("--set="):].partition("=")
            OVERRIDES[k] = None if v.lower() == "none" else float(v)
    if OVERRIDES:
        print("Override -> " + ", ".join(f"{k}={v}" for k, v in OVERRIDES.items()))

    _apply_all()
    OUT, RAW, PROG = _paths(ARM)

    if "--rescore" in flags:
        if not RAW.exists():
            print(f"no raw data at {RAW} -- run the sweep first")
            return
        per, skipped, elapsed = load_raw()
        print(f"re-scoring {len(per)} symbols from {RAW.name}")
        _report(per, skipped, elapsed)
        return

    syms = [s.upper() for s in args] or db.list_symbols()
    print(f"Arm      -> {ARM} ({ARMS[ARM]['param']}), live = {_live()}")
    print(f"Signal   -> {SIGNAL or config.BREADTH_SIGNAL}, profile {PROFILE}")
    print(f"Sweeping {len(_grid())} settings over {len(syms)} symbols")
    t0 = time.time()
    per_symbol, skipped, done = {}, [], 0
    write_progress(0, len(syms), t0, "starting workers...")
    print(f"progress -> {PROG}")

    with ProcessPoolExecutor() as ex:
        futures = {ex.submit(eval_symbol, s, ARM, PROFILE, SIGNAL,
                             dict(OVERRIDES)): s for s in syms}
        for fut in as_completed(futures):
            sym, res, note = fut.result()
            done += 1
            if res is None:
                skipped.append((sym, note))
                print(f"[{done}/{len(syms)}] {sym} skipped -- {note}", flush=True)
            else:
                per_symbol[sym] = res
                print(f"[{done}/{len(syms)}] {sym} ok", flush=True)
            write_progress(done, len(syms), t0, f"last: {sym}")

    if not per_symbol:
        print("nothing to report")
        return
    elapsed = time.time() - t0
    save_raw(per_symbol, skipped, elapsed)
    print(f"raw -> {RAW}")
    _report(per_symbol, skipped, elapsed)
    print(f"({elapsed/60:.1f} min)   re-score with: "
          f"python -m single.multi_signal.sweep_breadth --arm={ARM} --rescore")


if __name__ == "__main__":
    main()
