"""
Sweep all symbols in the DB with the Median1000 strategy.

Outputs (in analyze/median1000/charts/):
  - <symbol>_backtest.html       per-symbol backtest chart
  - run_all_progress.html        live progress (auto-refreshes every 3s)
  - report_all.html              final comparison table

Usage:
    python analyze/median1000/run_all.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import time
import traceback
from datetime import datetime
import pandas as pd
import database as db
from analyze.runner import load_symbol_df, run_estimate
from analyze.strategies.buy import BuyMedian1000Strategy, BuyIntervalStrategy
from analyze.strategies.sell import SellMedian1000Strategy, SellStrategy
from analyze.strategies.reinvest import ReInvestMedian1000Strategy, ReinvestStrategy
from export.chart import save_backtest_chart
from progress import RunAllProgress
from analyze.median1000 import config

CHARTS_DIR = Path(__file__).parent / "charts"


def make_median_strategies(signal3_map: dict | None = None, signal1_map: dict | None = None,
                           reinvest_signal1_map: dict | None = None, zdev_map: dict | None = None):
    gate  = config.REINVEST_MIN_SIGNAL1 is not None
    zgate = config.SELL_MIN_ZDEV is not None
    return (
        BuyMedian1000Strategy(percentBuy=config.PERCENT_BUY,               use_pe=config.USE_PE),
        SellMedian1000Strategy(percentSell=config.PERCENT_SELL,             use_pe=config.USE_PE,
                               signal3_map=signal3_map or {}, min_signal3=config.MIN_SIGNAL3,
                               signal1_map=signal1_map or {}, min_signal1=config.SELL_MIN_SIGNAL1,
                               zdev_map=(zdev_map or {}) if zgate else {},
                               min_zdev=config.SELL_MIN_ZDEV or 0.0),
        ReInvestMedian1000Strategy(percentReinvest=config.PERCENT_REINVEST, use_pe=config.USE_PE,
                                   timeoutDays=config.REINVEST_TIMEOUT_DAYS,
                                   timeoutPercent=config.REINVEST_TIMEOUT_PERCENT,
                                   signal1_map=(reinvest_signal1_map or {}) if gate else {},
                                   min_signal1=config.REINVEST_MIN_SIGNAL1 or 0.0),
    )

def make_interval_strategies():
    return (
        BuyIntervalStrategy(),
        SellStrategy(),
        ReinvestStrategy(),
    )


def process_symbol(symbol: str, prog: RunAllProgress, run_ts: str = "",
                   run_dir: Path | None = None) -> tuple[dict | None, str | None]:
    """Returns (row, skip_reason). Exactly one is non-None."""
    t0 = time.time()
    prog.begin(symbol)
    try:
        df = load_symbol_df(symbol)
        if len(df) < 1010:
            prog.end_err(symbol, f"skipped — only {len(df)} rows")
            return None, f"only {len(df)} rows"

        cal_range_close = db.load_range_stats(symbol, df)
        if cal_range_close is None:
            prog.end_err(symbol, "no range_stats in DB")
            return None, "no range_stats in DB"

        date_to_idx = {pd.Timestamp(row["time"]): i for i, row in df.iterrows()}

        # Build signal3 map: {row_index → signal3_sharpe} for window=1000
        sig3_df = db.load_trend_signals(symbol, window_days=1000)
        signal3_map: dict = {}
        if not sig3_df.empty:
            for date, s3 in sig3_df["signal3_sharpe"].items():
                idx = date_to_idx.get(pd.Timestamp(date))
                if idx is not None:
                    signal3_map[idx] = float(s3)

        # Build signal1 map: {row_index → signal1_slope} for short-term window
        sig1_df = db.load_trend_signals(symbol, window_days=config.SELL_SIGNAL1_WINDOW)
        signal1_map: dict = {}
        if not sig1_df.empty:
            for date, s1 in sig1_df["signal1_slope"].items():
                idx = date_to_idx.get(pd.Timestamp(date))
                if idx is not None:
                    signal1_map[idx] = float(s1)

        # Reinvest slope map — reuse signal1_map when the window matches, else load it
        if config.REINVEST_SIGNAL1_WINDOW == config.SELL_SIGNAL1_WINDOW:
            reinvest_signal1_map = signal1_map
        else:
            reinvest_signal1_map = {}
            ri_df = db.load_trend_signals(symbol, window_days=config.REINVEST_SIGNAL1_WINDOW)
            if not ri_df.empty:
                for date, s1 in ri_df["signal1_slope"].items():
                    idx = date_to_idx.get(pd.Timestamp(date))
                    if idx is not None:
                        reinvest_signal1_map[idx] = float(s1)

        # z_dev map for the sell filter — {row_index: z_dev} at the configured stat window
        zdev_map: dict = {}
        if config.SELL_MIN_ZDEV is not None:
            zd = db.load_zdev(symbol, 1000, config.SELL_ZDEV_WINDOW)
            for date, z in zd["z_dev"].items() if not zd.empty else []:
                idx = date_to_idx.get(pd.Timestamp(date))
                if idx is not None and z is not None:
                    zdev_map[idx] = float(z)

        # Start once EVERY input the strategies read is available — the latest
        # first-appearance wins. Before that point the early period would be running
        # a different strategy than the later one, because whichever inputs are still
        # missing simply do not filter. Adding a signal means adding a line here;
        # nothing else needs to know the arithmetic.
        #
        # Applied to BOTH arms. Moving only the treatment's start would hand the
        # interval arm extra years of compounding and invalidate the comparison.
        first_idx = {
            "median1000":       1000,   # the index > 1000 guard inside the strategies
            "signal1":          min(signal1_map)          if signal1_map          else None,
            "signal3":          min(signal3_map)          if signal3_map          else None,
            "reinvest_signal1": min(reinvest_signal1_map) if reinvest_signal1_map else None,
            "zdev":             min(zdev_map)             if zdev_map             else None,
        }
        if config.SELL_MIN_ZDEV is not None and not zdev_map:
            prog.end_err(symbol, f"no z_dev at stat_window={config.SELL_ZDEV_WINDOW}")
            return None, f"no z_dev at stat_window={config.SELL_ZDEV_WINDOW}"
        available = {k: v for k, v in first_idx.items() if v is not None}
        start_idx = max(available.values())
        binding   = max(available, key=available.get)

        eval_bars = len(df) - start_idx
        if config.MIN_EVAL_BARS and eval_bars < config.MIN_EVAL_BARS:
            msg = f"only {eval_bars} bars after warmup (start {start_idx}, bound by {binding})"
            prog.end_err(symbol, msg)
            return None, msg

        buy1, sell1, ri1 = make_median_strategies(signal3_map, signal1_map,
                                                  reinvest_signal1_map, zdev_map)
        r1 = run_estimate(symbol, df, config.INTERVAL_MONEY, buy1, sell1, ri1,
                          cal_range_close, start_index=start_idx)

        buy2, sell2, ri2 = make_interval_strategies()
        r2 = run_estimate(symbol, df, config.INTERVAL_MONEY, buy2, sell2, ri2,
                          cal_range_close, start_index=start_idx)

        out_dir = run_dir if run_dir is not None else CHARTS_DIR
        chart_path = out_dir / f"{symbol.lower()}_backtest.html"
        save_backtest_chart(
            df,
            r1["buyedInfos"], r1["sellInfos"], r1["reinvestInfos"],
            path=str(chart_path),
            index=symbol.lower(),
            buy_strategy=buy1, sell_strategy=sell1, reinvest_strategy=ri1,
            cal_range_close=cal_range_close,
            result=r1,
            compare_result=r2,
            start_index=start_idx,
        )

        # Current state of the three conditions at the latest bar — the same
        # check() calls the backtest chart uses to paint its condition zones.
        # Note reinvest.check() covers only the price path; the timeout fallback
        # lives in considerReinvest and is not reflected here.
        last = len(df) - 1
        close_last = float(df["close"].iloc[last]) * 1000
        pe_last = df["pe_ratio"].iloc[last] if "pe_ratio" in df.columns else None
        if pe_last is not None and pe_last != pe_last:   # NaN
            pe_last = None
        def _chk(strategy):
            try:
                return bool(strategy.check(last, close_last, pe_last, cal_range_close))
            except Exception:
                return False
        now_flags = (_chk(buy1), _chk(sell1), _chk(ri1))

        dur = time.time() - t0
        mg  = float(round(r1["allRatioGrowth"], 2))
        ig  = float(round(r2["allRatioGrowth"], 2))
        prog.end_ok(
            symbol, dur,
            median_growth=mg,
            buys=r1["totalBuys"], sells=r1["totalSells"], reinvests=r1["totalReinvest"],
            interval_growth=ig,
            chart=chart_path.name,
        )
        return {
            "symbol":            symbol,
            "median_growth_%":   mg,
            "median_buys":       r1["totalBuys"],
            "median_sells":      r1["totalSells"],
            "median_reinvests":  r1["totalReinvest"],
            "interval_growth_%": ig,
            "chart":             chart_path.name,
            "now_flags":         now_flags,
        }, None

    except Exception:
        err = traceback.format_exc().strip().splitlines()[-1]
        prog.end_err(symbol, err)
        print(f"  {symbol}: ERROR — {err}")
        return None, err


def build_report(rows: list[dict], out_path: Path,
                 skipped: list[tuple[str, str]] | None = None):
    df = pd.DataFrame(rows)
    df["diff_%"] = df["median_growth_%"] - df["interval_growth_%"]
    df = df.sort_values("diff_%", ascending=False)

    # Same (buy, sell, reinvest) -> colour/label map the backtest chart uses for
    # its condition zones, so a row here and the chart agree on wording.
    NOW_COMBO = {
        (False, False, False): ("#64748b", "—"),
        (True,  False, False): ("#22c55e", "Buy"),
        (False, True,  False): ("#ef4444", "Sell"),
        (False, False, True):  ("#f97316", "Reinvest"),
        (True,  False, True):  ("#14b8a6", "Buy + Reinvest"),
        (True,  True,  False): ("#eab308", "Buy + Sell"),
        (False, True,  True):  ("#ec4899", "Sell + Reinvest"),
        (True,  True,  True):  ("#94a3b8", "All"),
    }

    WIN_GREEN  = "background:#14532d;color:#bbf7d0"
    LOSE_RED   = "background:#7f1d1d;color:#fca5a5"
    DRAW_GRAY  = "background:#1e293b;color:#94a3b8"

    def winner_styles(m, i):
        if m > i:   return WIN_GREEN, LOSE_RED
        if i > m:   return LOSE_RED,  WIN_GREEN
        return DRAW_GRAY, DRAW_GRAY

    # Every uppercase name in config.py, read at render time. Introspected rather
    # than listed so a parameter added later cannot silently go unreported — the
    # whole point is that a saved report says what produced it.
    cfg = {k: getattr(config, k) for k in dir(config)
           if k.isupper() and not k.startswith("_")}
    cfg_cells = "".join(
        f"<div><span style='color:#64748b'>{k}</span> "
        f"<span style='color:#e2e8f0;font-weight:600'>{v}</span></div>"
        for k, v in sorted(cfg.items())
    )
    config_html = (
        "<div style='margin:10px 0;padding:10px 14px;background:#0f172a;"
        "border:1px solid #1e293b;border-radius:8px;font-size:12px'>"
        "<div style='color:#94a3b8;font-weight:700;margin-bottom:6px'>"
        "Configuration used for this run</div>"
        "<div style='display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));"
        f"gap:2px 18px'>{cfg_cells}</div></div>"
    )

    skipped = skipped or []
    skipped_note = f", {len(skipped)} skipped" if skipped else ""
    skipped_html = ""
    if skipped:
        items = "".join(
            f"<div><span style='color:#e2e8f0;font-weight:600'>{sym}</span> "
            f"<span style='color:#64748b'>— {why}</span></div>"
            for sym, why in sorted(skipped)
        )
        skipped_html = (
            "<div style='margin:10px 0;padding:10px 14px;background:#0f172a;"
            "border:1px solid #1e293b;border-radius:8px;font-size:12px'>"
            f"<div style='color:#94a3b8;font-weight:700;margin-bottom:6px'>"
            f"Skipped ({len(skipped)}) — excluded from every figure below</div>"
            "<div style='display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));"
            f"gap:2px 18px'>{items}</div></div>"
        )

    rows_html = ""
    data_json  = []
    for _, row in df.iterrows():
        m, i = row["median_growth_%"], row["interval_growth_%"]
        ms, is_ = winner_styles(m, i)
        diff = m - i
        diff_color = "#4ade80" if diff >= 0 else "#f87171"
        diff_sign  = "+" if diff >= 0 else ""
        sym = row["symbol"]
        now_color, now_label = NOW_COMBO.get(
            tuple(row.get("now_flags") or (False, False, False)), ("#64748b", "?"))
        rows_html += (
            f'<tr data-sym="{sym}">'
            f'<td><label style="display:flex;align-items:center;gap:6px;cursor:pointer">'
            f'<input type="checkbox" class="sym-toggle" data-sym="{sym}" checked '
            f'style="cursor:pointer;accent-color:#60a5fa">{sym}</label></td>'
            f"<td style='{ms};text-align:right'>{m:.2f}%</td>"
            f"<td style='{is_};text-align:right'>{i:.2f}%</td>"
            f"<td style='text-align:right;color:{diff_color};font-weight:600'>{diff_sign}{diff:.2f}%</td>"
            f"<td style='text-align:right'>{int(row['median_buys'])}</td>"
            f"<td style='text-align:right'>{int(row['median_sells'])}</td>"
            f"<td style='text-align:right'>{int(row['median_reinvests'])}</td>"
            f"<td style='text-align:center;color:{now_color};font-weight:600'>{now_label}</td>"
            f"<td style='text-align:center'><a href='{row['chart']}' target='_blank'>open</a></td>"
            f"</tr>\n"
        )
        # "s" = sells, used by the activity row in the summary
        data_json.append({"sym": sym, "m": round(m, 4), "i": round(i, 4),
                          "s": int(row["median_sells"])})

    import json
    data_js = json.dumps(data_json)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Median1000 Backtest — All Symbols</title>
<style>
  body {{ font-family: sans-serif; background: #111; color: #ddd; padding: 20px; }}
  h1 {{ font-size: 1.4rem; margin-bottom: 12px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
  th {{ background: #1e293b; color: #94a3b8; padding: 8px 12px; text-align: left;
        position: sticky; top: 0; z-index: 1; }}
  td {{ padding: 6px 12px; border-bottom: 1px solid #1e293b; }}
  tr:hover td {{ background: rgba(255,255,255,0.04); }}
  tr.excluded td {{ opacity: 0.35; }}
  a {{ color: #60a5fa; }}
  #summary {{ margin-top:28px;background:#0f172a;border:1px solid #1e293b;
    border-radius:10px;padding:20px 24px;font-size:13px;line-height:2; }}
  #summary .s-title {{ font-size:15px;font-weight:700;color:#f1f5f9;margin-bottom:10px; }}
  #summary table {{ font-size:13px; }}
  #summary td:first-child {{ color:#64748b;padding-right:24px; }}
</style>
</head>
<body>
<h1>Median1000 Backtest — All Symbols</h1>
<p style="color:#64748b;font-size:12px">
  {len(rows)} symbols reported{skipped_note} &nbsp;|&nbsp;
  vs BuyInterval (no sell/reinvest), both arms starting at the same bar &nbsp;|&nbsp;
  Sorted by Diff (Median1000 − Interval) descending. &nbsp;|&nbsp;
  <span style="color:#94a3b8">Uncheck a row to exclude it from summary.</span>
</p>
{config_html}
{skipped_html}
<table>
<thead><tr>
  <th>Symbol</th>
  <th>Median1000</th><th>BuyInterval</th><th>Diff</th>
  <th>Buys</th><th>Sells</th><th>Reinvests</th>
  <th>Signal now</th><th>Chart</th>
</tr></thead>
<tbody>
{rows_html}
</tbody>
</table>

<div id="summary">
  <div class="s-title">Summary</div>
  <table style="border-collapse:collapse;width:100%">
    <tr><td>Symbols compared</td><td id="s-n" style="font-weight:600"></td></tr>
    <tr><td>Median1000 wins</td><td id="s-mw" style="color:#4ade80;font-weight:600"></td></tr>
    <tr><td>BuyInterval wins</td><td id="s-iw" style="color:#f87171;font-weight:600"></td></tr>
    <tr><td>Draws</td><td id="s-dr" style="color:#94a3b8"></td></tr>
    <tr><td colspan="2"><hr style="border-color:#1e293b;margin:6px 0"></td></tr>
    <tr><td>Avg growth — Median1000 / Interval</td><td id="s-avg"></td></tr>
    <tr><td>Median growth — Median1000 / Interval</td><td id="s-med"></td></tr>
    <tr><td><b>Median per-symbol diff</b></td><td id="s-mdiff"></td></tr>
    <tr><td colspan="2"><hr style="border-color:#1e293b;margin:6px 0"></td></tr>
    <tr><td>Win rate (sign test)</td><td id="s-sign"></td></tr>
    <tr><td>Avg win / avg loss</td><td id="s-wl"></td></tr>
    <tr><td>Diff spread — p25 / p50 / p75</td><td id="s-quart"></td></tr>
    <tr><td>Gains concentration — top 1 / top 3</td><td id="s-conc"></td></tr>
    <tr><td>Net diff — all / excluding best</td><td id="s-net"></td></tr>
    <tr><td>Activity — avg sells, never sold</td><td id="s-act"></td></tr>
    <tr><td colspan="2"><hr style="border-color:#1e293b;margin:6px 0"></td></tr>
    <tr><td colspan="2"><hr style="border-color:#1e293b;margin:6px 0"></td></tr>
    <tr><td>Best Median1000</td><td id="s-mbest" style="color:#4ade80"></td></tr>
    <tr><td>Best BuyInterval</td><td id="s-ibest" style="color:#4ade80"></td></tr>
    <tr><td>Worst Median1000</td><td id="s-mworst" style="color:#f87171"></td></tr>
  </table>
</div>

<script>
const ALL_DATA = {data_js};
const excluded = new Set();

function median(arr) {{
  const s = [...arr].sort((a,b) => a-b);
  const m = Math.floor(s.length/2);
  return s.length % 2 ? s[m] : (s[m-1]+s[m])/2;
}}

function fmt(v) {{
  return (v >= 0 ? '+' : '') + v.toFixed(2) + '%';
}}

function updateSummary() {{
  const active = ALL_DATA.filter(d => !excluded.has(d.sym));
  if (!active.length) return;
  const n  = active.length;
  const ms = active.map(d => d.m);
  const is_ = active.map(d => d.i);
  const mw = active.filter(d => d.m > d.i).length;
  const iw = active.filter(d => d.i > d.m).length;
  const dr = n - mw - iw;
  const mAvg = ms.reduce((a,b)=>a+b,0)/n;
  const iAvg = is_.reduce((a,b)=>a+b,0)/n;
  const mMed = median(ms);
  const iMed = median(is_);
  const diff = mAvg - iAvg;
  const diffColor = diff >= 0 ? '#4ade80' : '#f87171';

  const mBest = active.reduce((a,b) => b.m > a.m ? b : a);
  const iBest = active.reduce((a,b) => b.i > a.i ? b : a);
  const mWorst = active.reduce((a,b) => b.m < a.m ? b : a);

  document.getElementById('s-n').textContent = n;
  document.getElementById('s-mw').innerHTML = mw + ' <span style="color:#64748b;font-weight:400">(' + Math.round(mw/n*100) + '%)</span>';
  document.getElementById('s-iw').innerHTML = iw + ' <span style="color:#64748b;font-weight:400">(' + Math.round(iw/n*100) + '%)</span>';
  document.getElementById('s-dr').textContent = dr;
  document.getElementById('s-avg').innerHTML =
    '<span style="color:#60a5fa">' + mAvg.toFixed(2) + '%</span> &nbsp;/&nbsp; ' +
    '<span style="color:#94a3b8">' + iAvg.toFixed(2) + '%</span> &nbsp;' +
    '<span style="color:' + diffColor + ';font-weight:600">(' + fmt(diff) + ')</span>';
  document.getElementById('s-med').innerHTML =
    '<span style="color:#60a5fa">' + mMed.toFixed(2) + '%</span> &nbsp;/&nbsp; ' +
    '<span style="color:#94a3b8">' + iMed.toFixed(2) + '%</span>';
  // Median of the per-symbol differences, NOT median(m) - median(i). The two are
  // not the same: the symbol at the middle of one distribution is not the symbol
  // at the middle of the other, so a difference of medians describes no actual
  // symbol. On the 45-symbol run they read +1.42% and +8.42% respectively.
  const diffs  = active.map(d => d.m - d.i).sort((a,b)=>a-b);
  const mdiff  = median(diffs);
  document.getElementById('s-mdiff').innerHTML =
    '<span style="color:' + (mdiff>=0?'#4ade80':'#f87171') + ';font-weight:700">' + fmt(mdiff) + '</span>' +
    ' <span style="color:#64748b;font-weight:400">(median of per-symbol diffs — not the difference of the two medians above)</span>';

  // Sign test over decided symbols only; exact draws carry no directional info.
  const dec = diffs.filter(v => Math.abs(v) > 1e-9);
  const wins = dec.filter(v => v > 0).length;
  let p = 1;
  if (dec.length) {{
    let c = 0;
    const lg = k => {{ let r = 0; for (let j = 2; j <= k; j++) r += Math.log(j); return r; }};
    for (let k = wins; k <= dec.length; k++)
      c += Math.exp(lg(dec.length) - lg(k) - lg(dec.length - k) - dec.length * Math.LN2);
    p = c;
  }}
  document.getElementById('s-sign').innerHTML =
    wins + '/' + dec.length + ' <span style="color:#64748b">(' +
    (dec.length ? Math.round(100*wins/dec.length) : 0) + '%)</span> &nbsp; ' +
    '<span style="color:' + (p<0.05?'#4ade80':'#94a3b8') + '">p = ' + p.toFixed(4) + '</span>';

  const wArr = dec.filter(v=>v>0), lArr = dec.filter(v=>v<0);
  const avg = a => a.length ? a.reduce((x,y)=>x+y,0)/a.length : 0;
  document.getElementById('s-wl').innerHTML =
    '<span style="color:#4ade80">' + fmt(avg(wArr)) + '</span> &nbsp;/&nbsp; ' +
    '<span style="color:#f87171">' + fmt(avg(lArr)) + '</span>' +
    (lArr.length ? ' <span style="color:#64748b">(' + Math.abs(avg(wArr)/avg(lArr)).toFixed(2) + 'x)</span>' : '');

  const q = f => diffs[Math.min(diffs.length-1, Math.max(0, Math.floor(f*(diffs.length-1))))];
  document.getElementById('s-quart').innerHTML =
    '<span style="color:#94a3b8">' + fmt(q(0.25)) + ' &nbsp;/&nbsp; ' + fmt(q(0.50)) +
    ' &nbsp;/&nbsp; ' + fmt(q(0.75)) + '</span>';

  const totW = wArr.reduce((a,b)=>a+b,0);
  const sortedW = wArr.slice().sort((a,b)=>b-a);
  const top1 = totW ? 100*sortedW[0]/totW : 0;
  const top3 = totW ? 100*sortedW.slice(0,3).reduce((a,b)=>a+b,0)/totW : 0;
  document.getElementById('s-conc').innerHTML =
    '<span style="color:' + (top1>25?'#fbbf24':'#94a3b8') + '">' + top1.toFixed(0) + '%</span>' +
    ' &nbsp;/&nbsp; <span style="color:' + (top3>50?'#fbbf24':'#94a3b8') + '">' + top3.toFixed(0) + '%</span>' +
    ' <span style="color:#64748b">of total gains</span>';

  const netAll  = diffs.reduce((a,b)=>a+b,0);
  const bestSym = active.reduce((a,b) => (b.m-b.i) > (a.m-a.i) ? b : a);
  document.getElementById('s-net').innerHTML =
    fmt(netAll) + ' &nbsp;-> &nbsp;' + fmt(netAll - (bestSym.m - bestSym.i)) +
    ' <span style="color:#64748b">(excl. ' + bestSym.sym + ')</span>';

  const noSell = active.filter(d => d.s === 0).length;
  const flat   = active.filter(d => Math.abs(d.m - d.i) < 1e-9).length;
  document.getElementById('s-act').innerHTML =
    (active.reduce((a,b)=>a+b.s,0)/n).toFixed(1) + ' sells &nbsp;|&nbsp; ' +
    '<span style="color:' + (noSell > n/4 ? '#fbbf24' : '#94a3b8') + '">' + noSell + '/' + n +
    ' never sold</span>' + (flat ? ' <span style="color:#64748b">(' + flat + ' identical to interval)</span>' : '');

  document.getElementById('s-mbest').innerHTML = '<b>' + mBest.sym + '</b> &nbsp;' + mBest.m.toFixed(2) + '%';
  document.getElementById('s-ibest').innerHTML = '<b>' + iBest.sym + '</b> &nbsp;' + iBest.i.toFixed(2) + '%';
  document.getElementById('s-mworst').innerHTML = '<b>' + mWorst.sym + '</b> &nbsp;' + mWorst.m.toFixed(2) + '%';
}}

document.querySelectorAll('.sym-toggle').forEach(cb => {{
  cb.addEventListener('change', () => {{
    const sym = cb.dataset.sym;
    const row = document.querySelector('tr[data-sym="' + sym + '"]');
    if (cb.checked) {{ excluded.delete(sym); row.classList.remove('excluded'); }}
    else            {{ excluded.add(sym);    row.classList.add('excluded'); }}
    updateSummary();
  }});
}});

updateSummary();
</script>
</body>
</html>"""

    out_path.write_text(html, encoding="utf-8")
    print(f"Report -> {out_path}")


if __name__ == "__main__":
    db.init_db()
    CHARTS_DIR.mkdir(exist_ok=True)

    symbols = [s.upper() for s in sys.argv[1:]] if len(sys.argv) > 1 else db.list_symbols()

    run_ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = CHARTS_DIR / run_ts
    run_dir.mkdir(exist_ok=True)

    print(f"Processing {len(symbols)} symbols: {', '.join(symbols)}")
    print(f"Output    -> {run_dir}")
    print(f"Progress  -> {run_dir}/run_all_progress.html\n")

    prog = RunAllProgress(symbols, out=str(run_dir / "run_all_progress.html"))

    report_rows, skipped = [], []
    for i, sym in enumerate(symbols, 1):
        print(f"[{i}/{len(symbols)}] {sym}", end=" ... ", flush=True)
        row, skip_reason = process_symbol(sym, prog, run_ts="", run_dir=run_dir)
        if row:
            report_rows.append(row)
            print(f"median={row['median_growth_%']:.1f}%  interval={row['interval_growth_%']:.1f}%")
        else:
            skipped.append((sym, skip_reason or "unknown"))
            print(f"skipped — {skip_reason}")

    prog.finish()

    if report_rows:
        build_report(report_rows, run_dir / "report_all.html", skipped)

    print("\nDone.")
