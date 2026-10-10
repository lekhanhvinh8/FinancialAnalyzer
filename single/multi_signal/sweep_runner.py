"""
One runner for every parameter sweep. The grids live in sweep_specs.py; what
each one found lives in SWEEPS.md.

    python -m single.multi_signal.sweep_runner --list
    python -m single.multi_signal.sweep_runner percent_sell
    python -m single.multi_signal.sweep_runner percent_sell FPT HPG --workers=4
    python -m single.multi_signal.sweep_runner breadth_sell --profile=breadth
    python -m single.multi_signal.sweep_runner breadth_sell --set=PERCENT_SELL=None
    python -m single.multi_signal.sweep_runner breadth_sell --profile=none   # config.py alone
    python -m single.multi_signal.sweep_runner percent_sell --rescore

Output goes to single/multi_signal/charts/sweeps/ (git-ignored):
sweep_<name>[_<tag>].html, _raw.json and _progress.html. The tag spells out
--profile and --set, so two different measurements never overwrite each other.

A CELL IS "run_all WITH THESE CONFIG VALUES"

  Each cell is a dict of config overrides. The worker applies them, asks
  inputs.SymbolInputs for exactly what run_all would load under that config,
  and builds the strategies with make_median_strategies() reading config. There
  is no second definition of any strategy or input here, which is what the
  seventeen hand-written sweeps this replaces got wrong more than once.

  Every symbol runs every cell from ONE start index -- the latest any cell
  needs -- and against one DCA baseline, so cells differ only in the setting.

  The "live" cell carries no overrides: it is the configuration as run (config
  plus --profile and --set). Paired comparisons default to it.
"""

import json
import math
import statistics as st
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import contextmanager
from pathlib import Path

import numpy as np

import database as db
from single.runner import run_estimate
from single.multi_signal import config
from single.multi_signal.factory import make_median_strategies, make_interval_strategies
from single.multi_signal.inputs import SymbolInputs, windows_for
from single.multi_signal.sweep_matrix import matrix_html

OUT_DIR = Path(__file__).parent / "charts" / "sweeps"
FIELDS = ["diff", "reinvests", "buys", "sells"]


# ── Config overrides ──────────────────────────────────────────────────────────

@contextmanager
def overrides(values: dict):
    """Set config attributes for the duration, then put every one back."""
    missing = object()
    saved = {k: getattr(config, k, missing) for k in values}
    try:
        for k, v in values.items():
            setattr(config, k, v)
        yield
    finally:
        for k, v in saved.items():
            if v is missing:
                delattr(config, k)
            else:
                setattr(config, k, v)


def base_overrides(profile: str | None, sets: dict) -> dict:
    from single.multi_signal.profiles import PROFILES
    out = dict(PROFILES[profile]) if profile else {}
    out.update(sets)
    return out


# ── One symbol, every cell ────────────────────────────────────────────────────

def eval_symbol(sym: str, spec_name: str, base: dict):
    """Returns (sym, {cell_key: (diff, reinvests, buys, sells)}, skip_reason)."""
    from single.multi_signal.sweep_specs import SPECS
    spec = SPECS[spec_name]
    try:
        with overrides(base):
            inp = SymbolInputs(sym)
            if len(inp.df) < 1010:
                return sym, None, f"only {len(inp.df)} rows"

            windows = set()
            for c in spec.cells.values():
                with overrides(c):
                    windows |= windows_for(config)
            if not inp.load_range_stats(windows):
                return sym, None, "no range_stats"

            prepared, start_idx = [], 0
            for key, c in spec.cells.items():
                with overrides(c):
                    maps, first, why = inp.maps(config)
                if why:
                    return sym, None, f"{key}: {why}"
                prepared.append((key, c, maps))
                start_idx = max(start_idx, max(first.values()))

            eval_bars = len(inp.df) - start_idx
            if config.MIN_EVAL_BARS and eval_bars < config.MIN_EVAL_BARS:
                return sym, None, f"only {eval_bars} bars after warmup"

            b0, s0, r0 = make_interval_strategies()
            dca = run_estimate(sym, inp.df, config.INTERVAL_MONEY, b0, s0, r0,
                               inp.crc, start_index=start_idx)["allRatioGrowth"]

            out = {}
            for key, c, maps in prepared:
                with overrides(c):
                    buy, sell, rei = make_median_strategies(**maps)
                    r = run_estimate(sym, inp.df, config.INTERVAL_MONEY, buy, sell,
                                     rei, inp.crc, start_index=start_idx)
                out[key] = (round(r["allRatioGrowth"] - dca, 4), r["totalReinvest"],
                            r["totalBuys"], r["totalSells"])
        return sym, out, None
    except Exception as e:
        return sym, None, f"{type(e).__name__}: {e}"


# ── Statistics ────────────────────────────────────────────────────────────────

def sign_p(up: int, dec: int) -> float:
    """One-sided sign test: P(at least `up` of `dec` improve | coin flip)."""
    return sum(math.comb(dec, i) for i in range(up, dec + 1)) / 2 ** dec if dec else 1.0


def paired(per: dict, a: str, b: str) -> dict:
    """Per-symbol a minus b -- the only valid comparison between two cells."""
    d = [v[a][0] - v[b][0] for v in per.values() if a in v and b in v]
    if not d:
        return {"pair": float("nan"), "up": 0, "dec": 0, "p": 1.0}
    up = sum(1 for x in d if x > 1e-9)
    dec = sum(1 for x in d if abs(x) > 1e-9)
    return {"pair": st.median(d), "up": up, "dec": dec, "p": sign_p(up, dec)}


def votes(per: dict, keys: list) -> dict:
    """Round robin, one vote per symbol: blind to size, immune to one symbol."""
    syms = [s for s in per if all(k in per[s] for k in keys)]
    if len(syms) < 3:
        return {}
    m = np.array([[per[s][k][0] for k in keys] for s in syms])
    return {k: int(((m[:, i][:, None] - m > 1e-9).sum(axis=0)
                    > (m - m[:, i][:, None] > 1e-9).sum(axis=0)).sum())
            for i, k in enumerate(keys)}


def aggregate(per: dict, keys: list) -> dict:
    """
    Columns are aggregates OVER symbols at one cell, and must never be
    subtracted between cells -- the symbol at the median of one column is a
    different symbol from the one at the median of another. The paired column
    against "live" is computed here so nobody has to derive it by subtraction.
    """
    v = votes(per, keys)
    rows = {}
    for k in keys:
        vals = sorted(d[k][0] for d in per.values() if k in d)
        if not vals:
            continue
        wins = sum(1 for x in vals if x > 1e-9)
        dec = sum(1 for x in vals if abs(x) > 1e-9)
        rows[k] = {
            "mean": st.mean(vals), "median": st.median(vals),
            "win": 100 * wins / len(vals), "worst": vals[0], "vote": v.get(k, 0),
            "p": sign_p(wins, dec), **paired(per, k, "live"),
            "reinv": st.mean(d[k][1] for d in per.values() if k in d),
            "buys": st.mean(d[k][2] for d in per.values() if k in d),
            "sells": st.mean(d[k][3] for d in per.values() if k in d),
        }
    return rows


def drop_excluded(per: dict) -> dict:
    drop = {s.upper() for s in getattr(config, "EXCLUDE_SYMBOLS", [])}
    return {s: d for s, d in per.items() if s.upper() not in drop}


# ── Files ─────────────────────────────────────────────────────────────────────

def _fmt(v) -> str:
    return "None" if v is None else f"{v:g}" if isinstance(v, (int, float)) else str(v)


def paths(name: str, profile: str | None, sets: dict):
    bits = ([profile] if profile else []) + [f"{k}{_fmt(v)}" for k, v in sorted(sets.items())]
    tag = ("_" + "_".join(bits).replace(".", "")) if bits else ""
    base = OUT_DIR / f"sweep_{name}{tag}"
    return (Path(f"{base}.html"), Path(f"{base}_raw.json"), Path(f"{base}_progress.html"))


def save_raw(path, spec, per, skipped, elapsed, base):
    path.write_text(json.dumps({
        "meta": {"fields": FIELDS, "grid": list(spec.cells), "axes": spec.axes,
                 "coords": {k: list(c) for k, c in spec.coords.items()},
                 "elapsed": elapsed, "base": base,
                 "config": {c: getattr(config, c) for c in dir(config)
                            if c.isupper() and not c.startswith("_")}},
        "skipped": skipped, "results": per,
    }, default=str), encoding="utf-8")


def load_raw(path):
    raw = json.loads(path.read_text(encoding="utf-8"))
    per = {s: {k: tuple(v) for k, v in d.items()} for s, d in raw["results"].items()}
    return per, [tuple(x) for x in raw["skipped"]], raw["meta"].get("elapsed", 0.0)


def write_progress(path, title, done, total, started, note=""):
    el = time.time() - started
    pct = 100 * done / total if total else 0
    eta = (el / done * (total - done)) if done else 0
    path.write_text(f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<meta http-equiv="refresh" content="3"><title>{title}</title><style>
body{{font-family:sans-serif;background:#0b1220;color:#e2e8f0;padding:24px}}
.bar{{background:#1e293b;border-radius:6px;height:22px;width:520px;overflow:hidden}}
.fill{{background:#22c55e;height:100%;width:{pct:.1f}%}} .k{{color:#64748b}}</style>
</head><body><h2>{title} &mdash; {'running' if done < total else 'done'}</h2>
<div class="bar"><div class="fill"></div></div>
<p><b>{done} / {total}</b> symbols <span class="k">({pct:.0f}%)</span></p>
<p><span class="k">elapsed</span> <b>{el/60:.1f} min</b> &nbsp;
<span class="k">eta</span> <b>{('%.1f min' % (eta/60)) if done and done < total else '&mdash;'}</b></p>
<p class="k">{note}</p></body></html>""", encoding="utf-8")


# ── Report ────────────────────────────────────────────────────────────────────

CSS = """
body{font-family:sans-serif;background:#0b1220;color:#e2e8f0;padding:20px}
table{border-collapse:collapse;font-size:13px;margin:14px 0}
th,td{border:1px solid #1e293b;padding:5px 10px}
th{background:#111c30;color:#94a3b8;text-align:right}
th:first-child,td:first-child{text-align:left}
td{text-align:right} .note{color:#94a3b8;font-size:13px;line-height:1.7;max-width:980px}
table.hm td{min-width:58px;font-size:12px}
"""

JS = """
function med(a){const s=[...a].sort((x,y)=>x-y),m=s.length>>1;return s.length%2?s[m]:(s[m-1]+s[m])/2;}
function lch(n,k){let r=0;for(let i=1;i<=k;i++)r+=Math.log(n-k+i)-Math.log(i);return r;}
function signP(up,dec){let c=0;for(let k=up;k<=dec;k++)c+=Math.exp(lch(dec,k)-dec*Math.LN2);return Math.min(1,c);}
function recompute(){
  const ref=DIFFS[REF]; if(!ref)return;
  document.getElementById('refLabel').textContent=REF;
  KEYS.forEach(function(k){
    const cell=document.querySelector('td[data-vs="'+k+'"]'),meta=document.querySelector('td[data-vsmeta="'+k+'"]');
    if(!cell)return;
    if(k===REF){cell.innerHTML='&mdash;';cell.style.color='#64748b';meta.textContent='reference';return;}
    const d=DIFFS[k].map((v,i)=>v-ref[i]).filter(x=>x===x);
    const up=d.filter(x=>x>1e-9).length,dec=d.filter(x=>Math.abs(x)>1e-9).length,p=dec?signP(up,dec):1,m=med(d);
    cell.textContent=(m>=0?'+':'')+m.toFixed(2);
    cell.style.color=(m>0&&p<0.05)?'#4ade80':(m<0&&p>0.95)?'#f87171':'#e2e8f0';
    meta.textContent=up+'/'+dec+'  p='+p.toFixed(3);
  });
  document.querySelectorAll('tr[data-row]').forEach(function(tr){tr.style.outline=tr.dataset.row===REF?'2px solid #60a5fa':'';});
}
document.querySelectorAll('tr[data-row]').forEach(function(tr){tr.style.cursor='pointer';
  tr.addEventListener('click',function(){REF=tr.dataset.row;recompute();});});
recompute();
"""


def _heat(r) -> str:
    """One heatmap cell: paired median vs live, coloured when significant."""
    if r is None:
        return "<td style='color:#334155'>&middot;</td>"
    if r["dec"] == 0 and r["up"] == 0 and r["pair"] == 0:
        return "<td style='color:#64748b'>0.00</td>"
    c = ("#14532d" if r["pair"] > 0 and r["p"] < 0.05 else
         "#7f1d1d" if r["pair"] < 0 and sign_p(r["dec"] - r["up"], r["dec"]) < 0.05 else
         "transparent")
    return (f"<td style='background:{c}' title='{r['up']}/{r['dec']} p={r['p']:.3f}'>"
            f"{r['pair']:+.2f}</td>")


def heatmaps(spec, rows) -> str:
    """Paired median vs live laid out on the grid: rows x cols, a panel per
    value of the first axis when there are three."""
    if len(spec.axes) < 2:
        return ""
    ax = spec.axes
    vals = [list(dict.fromkeys(c[i] for c in spec.coords.values())) for i in range(len(ax))]
    by = {tuple(c): k for k, c in spec.coords.items()}
    panels = [()] if len(ax) == 2 else [(p,) for p in vals[0]]
    ri, ci = len(ax) - 2, len(ax) - 1
    html = ("<h3>Paired median vs live, laid out on the grid</h3><p class=note>"
            "Green / red: the cell beats / loses to live at p&lt;0.05 by sign test. "
            "Hover for symbols up / changed. Read regions, not single cells: a grid "
            f"of {len(spec.cells)} cells produces about {0.05 * len(spec.cells):.0f} "
            "significant cells by chance alone.</p>")
    for p in panels:
        title = f"<p><b>{ax[0]} = {_fmt(p[0])}</b></p>" if p else ""
        head = "".join(f"<th>{_fmt(v)}</th>" for v in vals[ci])
        body = ""
        for rv in vals[ri]:
            body += f"<tr><td><b>{_fmt(rv)}</b></td>" + "".join(
                _heat(rows.get(by.get(p + (rv, cv)))) for cv in vals[ci]) + "</tr>"
        html += (f"{title}<table class=hm><tr><th>{ax[ri]} \\ {ax[ci]}</th>{head}</tr>"
                 f"{body}</table>")
    return html


def build_html(spec, rows, per, skipped, elapsed, base) -> str:
    keys = [k for k in spec.cells if k in rows]
    best = {m: (max if m != "p" else min)(rows[k][m] for k in keys)
            for m in ("mean", "median", "win", "vote", "worst", "p")}
    syms = sorted(per)
    diffs = {k: [per[s][k][0] if k in per[s] else float("nan") for s in syms] for k in keys}

    def cell(r, m, txt):
        return f"<td style='color:{'#4ade80' if r[m] == best[m] else '#e2e8f0'}'>{txt}</td>"

    body = ""
    for k in keys:
        r = rows[k]
        body += (f"<tr data-row='{k}'><td><b>{spec.labels.get(k, k)}</b></td>"
                 + cell(r, "mean", f"{r['mean']:+.1f}") + cell(r, "median", f"{r['median']:+.1f}")
                 + cell(r, "win", f"{r['win']:.0f}%") + cell(r, "p", f"{r['p']:.3f}")
                 + cell(r, "vote", f"{r['vote']}") + cell(r, "worst", f"{r['worst']:+.0f}")
                 + f"<td data-vs='{k}' style='border-left:2px solid #334155'></td>"
                 + f"<td data-vsmeta='{k}' style='color:#94a3b8'></td>"
                 + f"<td style='color:#94a3b8'>{r['reinv']:.1f}</td>"
                 + f"<td style='color:#94a3b8'>{r['buys']:.0f}</td>"
                 + f"<td style='color:#94a3b8'>{r['sells']:.1f}</td></tr>")
    skip = ("<p class=note>Skipped: " + ", ".join(f"{s} ({w})" for s, w in sorted(skipped))
            + "</p>") if skipped else ""
    base_txt = ", ".join(f"{k}={_fmt(v)}" for k, v in base.items()) or "config.py as written"
    matrix = matrix_html(per, keys) if len(keys) <= 80 else ""
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>sweep {spec.name}</title><style>{CSS}</style></head><body>
<h2>{spec.title}</h2>
<p class=note>{len(per)} symbols, {len(spec.cells)} cells, {elapsed/60:.1f} min.
Every number is the per-symbol growth difference against DCA, in points.
Base configuration: <code>{base_txt}</code>.<br>{spec.note}</p>{skip}
<table><thead><tr><th>cell</th><th>mean</th><th>median</th><th>beats DCA</th>
<th>p</th><th>vote</th><th>worst</th>
<th style='border-left:2px solid #334155'>vs <span id='refLabel'>live</span></th>
<th>up / p</th><th>reinv</th><th>buys</th><th>sells</th></tr></thead>
<tbody>{body}</tbody></table>
<p class=note><b>Click a row to make it the reference</b>; the vs column recomputes
from the per-symbol numbers. That is the only valid comparison between two cells:
mean may be subtracted between rows, median / beats DCA / worst may not.
p is the sign test that a symbol beats DCA. Green marks the best cell per column.</p>
{heatmaps(spec, rows)}
<script>const DIFFS={json.dumps(diffs).replace("NaN", "null")};
const KEYS={json.dumps(keys)}; let REF="live";{JS}</script>
{matrix}
</body></html>"""


def report(spec, per, skipped, elapsed, base, out):
    per = drop_excluded(per)
    if not per:
        print("every symbol was excluded")
        return
    keys = list(spec.cells)
    rows = aggregate(per, keys)
    out.write_text(build_html(spec, rows, per, skipped, elapsed, base), encoding="utf-8")
    w = max(len(spec.labels.get(k, k)) for k in keys)
    print(f"\n{len(per)} symbols, paired column is against 'live'\n")
    print(f"{'cell':>{w}} {'mean':>8} {'median':>8} {'beats':>6} {'worst':>8} | "
          f"{'vs live':>8} {'up':>7} {'p':>6} | {'reinv':>5} {'buys':>5} {'sells':>5}")
    for k in keys:
        if k not in rows:
            continue
        r = rows[k]
        pair = "      —" if k == "live" else f"{r['pair']:+8.2f}"
        print(f"{spec.labels.get(k, k):>{w}} {r['mean']:+8.1f} {r['median']:+8.1f} "
              f"{r['win']:5.0f}% {r['worst']:+8.0f} | {pair} {r['up']:>3}/{r['dec']:<3} "
              f"{r['p']:6.3f} | {r['reinv']:5.1f} {r['buys']:5.0f} {r['sells']:5.1f}")
    print(f"\nreport -> {out}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_value(s: str):
    if s == "None":
        return None
    for t in (int, float):
        try:
            return t(s)
        except ValueError:
            pass
    return s


def run(name, syms, profile=None, sets=None, workers=None):
    from single.multi_signal.sweep_specs import SPECS
    spec = SPECS[name]
    profile = profile if profile is not None else spec.profile
    sets = sets or {}
    base = base_overrides(profile, sets)
    out, raw, prog = paths(name, profile, sets)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    syms = syms or db.list_symbols()
    print(f"sweep {name}: {len(spec.cells)} cells x {len(syms)} symbols, base {base or '-'}")
    print(f"progress -> {prog}")
    t0, per, skipped, done = time.time(), {}, [], 0
    write_progress(prog, f"sweep {name}", 0, len(syms), t0, "starting workers…")
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(eval_symbol, s, name, base): s for s in syms}
        for fut in as_completed(futures):
            sym, res, note = fut.result()
            done += 1
            if res is None:
                skipped.append((sym, note))
                print(f"[{done}/{len(syms)}] {sym} skipped — {note}", flush=True)
            else:
                per[sym] = res
                print(f"[{done}/{len(syms)}] {sym} ok", flush=True)
            write_progress(prog, f"sweep {name}", done, len(syms), t0, f"last: {sym}")
    if not per:
        print("nothing to report")
        return None
    elapsed = time.time() - t0
    save_raw(raw, spec, per, skipped, elapsed, base)
    with overrides(base):
        report(spec, per, skipped, elapsed, base, out)
    print(f"raw -> {raw}   ({elapsed/60:.1f} min)")
    return per


def main():
    from single.multi_signal.sweep_specs import SPECS
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    if "--list" in flags or not args:
        for n, s in SPECS.items():
            print(f"  {n:<20} {len(s.cells):>4} cells  {s.title}")
        return
    name, syms = args[0], [s.upper() for s in args[1:]]
    if name not in SPECS:
        raise SystemExit(f"no sweep named {name}; --list shows them")
    profile = next((f.split("=", 1)[1] for f in flags if f.startswith("--profile=")), None)
    workers = next((int(f.split("=", 1)[1]) for f in flags if f.startswith("--workers=")), None)
    sets = {}
    for f in flags:
        if f.startswith("--set="):
            k, v = f[len("--set="):].split("=", 1)
            sets[k] = _parse_value(v)
    if profile == "none":
        profile = ""
    if "--rescore" in flags:
        spec = SPECS[name]
        prof = profile if profile is not None else spec.profile
        out, raw, _ = paths(name, prof, sets)
        if not raw.exists():
            raise SystemExit(f"no raw data at {raw}")
        per, skipped, elapsed = load_raw(raw)
        base = base_overrides(prof, sets)
        with overrides(base):
            report(spec, per, skipped, elapsed, base, out)
        return
    run(name, syms, profile, sets, workers)


if __name__ == "__main__":
    main()
