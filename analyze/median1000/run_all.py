"""
Sweep all symbols in the DB with the Median1000 strategy.

Outputs (in analyze/median1000/charts/):
  - backtest_<symbol>.html       per-symbol backtest chart
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


def make_median_strategies():
    return (
        BuyMedian1000Strategy(percentBuy=config.PERCENT_BUY,               use_pe=config.USE_PE),
        SellMedian1000Strategy(percentSell=config.PERCENT_SELL,             use_pe=config.USE_PE),
        ReInvestMedian1000Strategy(percentReinvest=config.PERCENT_REINVEST, use_pe=config.USE_PE,
                                   timeoutDays=config.REINVEST_TIMEOUT_DAYS,
                                   timeoutPercent=config.REINVEST_TIMEOUT_PERCENT),
    )

def make_interval_strategies():
    return (
        BuyIntervalStrategy(),
        SellStrategy(),
        ReinvestStrategy(),
    )


def process_symbol(symbol: str, prog: RunAllProgress) -> dict | None:
    t0 = time.time()
    prog.begin(symbol)
    try:
        df = load_symbol_df(symbol)
        if len(df) < 1010:
            prog.end_err(symbol, f"skipped — only {len(df)} rows")
            return None

        cal_range_close = db.load_range_stats(symbol, df)
        if cal_range_close is None:
            prog.end_err(symbol, "no range_stats in DB")
            return None

        buy1, sell1, ri1 = make_median_strategies()
        r1 = run_estimate(symbol, df, config.INTERVAL_MONEY, buy1, sell1, ri1, cal_range_close)

        buy2, sell2, ri2 = make_interval_strategies()
        r2 = run_estimate(symbol, df, config.INTERVAL_MONEY, buy2, sell2, ri2, cal_range_close)

        chart_path = CHARTS_DIR / f"backtest_{symbol.lower()}.html"
        save_backtest_chart(
            df,
            r1["buyedInfos"], r1["sellInfos"], r1["reinvestInfos"],
            path=str(chart_path),
            index=symbol.lower(),
            buy_strategy=buy1, sell_strategy=sell1, reinvest_strategy=ri1,
            cal_range_close=cal_range_close,
            result=r1,
            compare_result=r2,
        )

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
        }

    except Exception:
        err = traceback.format_exc().strip().splitlines()[-1]
        prog.end_err(symbol, err)
        print(f"  {symbol}: ERROR — {err}")
        return None


def build_report(rows: list[dict], out_path: Path):
    df = pd.DataFrame(rows).sort_values("median_growth_%", ascending=False)

    WIN_GREEN  = "background:#14532d;color:#bbf7d0"
    LOSE_RED   = "background:#7f1d1d;color:#fca5a5"
    DRAW_GRAY  = "background:#1e293b;color:#94a3b8"

    def winner_styles(m, i):
        if m > i:   return WIN_GREEN, LOSE_RED
        if i > m:   return LOSE_RED,  WIN_GREEN
        return DRAW_GRAY, DRAW_GRAY

    rows_html = ""
    for _, row in df.iterrows():
        m, i = row["median_growth_%"], row["interval_growth_%"]
        ms, is_ = winner_styles(m, i)
        diff = m - i
        diff_color = "#4ade80" if diff >= 0 else "#f87171"
        diff_sign  = "+" if diff >= 0 else ""
        rows_html += (
            f"<tr>"
            f"<td>{row['symbol']}</td>"
            f"<td style='{ms};text-align:right'>{m:.2f}%</td>"
            f"<td style='{is_};text-align:right'>{i:.2f}%</td>"
            f"<td style='text-align:right;color:{diff_color};font-weight:600'>{diff_sign}{diff:.2f}%</td>"
            f"<td style='text-align:right'>{int(row['median_buys'])}</td>"
            f"<td style='text-align:right'>{int(row['median_sells'])}</td>"
            f"<td style='text-align:right'>{int(row['median_reinvests'])}</td>"
            f"<td style='text-align:center'><a href='{row['chart']}' target='_blank'>open</a></td>"
            f"</tr>\n"
        )

    # ── Summary ───────────────────────────────────────────────────────────────
    n          = len(df)
    m_wins     = int((df["median_growth_%"] > df["interval_growth_%"]).sum())
    i_wins     = int((df["interval_growth_%"] > df["median_growth_%"]).sum())
    draws      = n - m_wins - i_wins
    m_avg      = df["median_growth_%"].mean()
    i_avg      = df["interval_growth_%"].mean()
    m_med      = df["median_growth_%"].median()
    i_med      = df["interval_growth_%"].median()
    m_best_row = df.loc[df["median_growth_%"].idxmax()]
    i_best_row = df.loc[df["interval_growth_%"].idxmax()]
    m_worst    = df.loc[df["median_growth_%"].idxmin(), "symbol"]
    avg_diff   = m_avg - i_avg

    avg_diff_sign  = "+" if avg_diff >= 0 else ""
    avg_diff_color = "#4ade80" if avg_diff >= 0 else "#f87171"

    summary_html = f"""
<div style="margin-top:28px;background:#0f172a;border:1px solid #1e293b;
  border-radius:10px;padding:20px 24px;font-size:13px;line-height:2">
  <div style="font-size:15px;font-weight:700;color:#f1f5f9;margin-bottom:10px">Summary</div>
  <table style="border-collapse:collapse;width:100%">
    <tr>
      <td style="color:#64748b;padding-right:24px">Symbols compared</td>
      <td style="font-weight:600">{n}</td>
    </tr>
    <tr>
      <td style="color:#64748b">Median1000 wins</td>
      <td style="color:#4ade80;font-weight:600">{m_wins} &nbsp;<span style="color:#64748b;font-weight:400">({m_wins/n*100:.0f}%)</span></td>
    </tr>
    <tr>
      <td style="color:#64748b">BuyInterval wins</td>
      <td style="color:#f87171;font-weight:600">{i_wins} &nbsp;<span style="color:#64748b;font-weight:400">({i_wins/n*100:.0f}%)</span></td>
    </tr>
    <tr>
      <td style="color:#64748b">Draws</td>
      <td style="color:#94a3b8">{draws}</td>
    </tr>
    <tr><td colspan="2"><hr style="border-color:#1e293b;margin:6px 0"></td></tr>
    <tr>
      <td style="color:#64748b">Avg growth — Median1000 / Interval</td>
      <td><span style="color:#60a5fa">{m_avg:.2f}%</span> &nbsp;/&nbsp; <span style="color:#94a3b8">{i_avg:.2f}%</span>
        &nbsp;<span style="color:{avg_diff_color};font-weight:600">({avg_diff_sign}{avg_diff:.2f}%)</span></td>
    </tr>
    <tr>
      <td style="color:#64748b">Median growth — Median1000 / Interval</td>
      <td><span style="color:#60a5fa">{m_med:.2f}%</span> &nbsp;/&nbsp; <span style="color:#94a3b8">{i_med:.2f}%</span></td>
    </tr>
    <tr><td colspan="2"><hr style="border-color:#1e293b;margin:6px 0"></td></tr>
    <tr>
      <td style="color:#64748b">Best Median1000</td>
      <td style="color:#4ade80"><b>{m_best_row['symbol']}</b> &nbsp;{m_best_row['median_growth_%']:.2f}%</td>
    </tr>
    <tr>
      <td style="color:#64748b">Best BuyInterval</td>
      <td style="color:#4ade80"><b>{i_best_row['symbol']}</b> &nbsp;{i_best_row['interval_growth_%']:.2f}%</td>
    </tr>
    <tr>
      <td style="color:#64748b">Worst Median1000</td>
      <td style="color:#f87171"><b>{m_worst}</b> &nbsp;{df.loc[df['median_growth_%'].idxmin(), 'median_growth_%']:.2f}%</td>
    </tr>
  </table>
</div>"""

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
  a {{ color: #60a5fa; }}
</style>
</head>
<body>
<h1>Median1000 Backtest — All Symbols</h1>
<p style="color:#64748b;font-size:12px">
  Interval money: {config.INTERVAL_MONEY:,} VND &nbsp;|&nbsp;
  Buy when &lt; median − {config.PERCENT_BUY}% &nbsp;|&nbsp;
  Sell when &gt; median + {config.PERCENT_SELL}% &nbsp;|&nbsp;
  Reinvest when &lt; median − {config.PERCENT_REINVEST}% &nbsp;|&nbsp;
  vs BuyInterval (no sell/reinvest) &nbsp;|&nbsp;
  Sorted by Median1000 growth descending.
</p>
<table>
<thead><tr>
  <th>Symbol</th>
  <th>Median1000</th><th>BuyInterval</th><th>Diff</th>
  <th>Buys</th><th>Sells</th><th>Reinvests</th>
  <th>Chart</th>
</tr></thead>
<tbody>
{rows_html}
</tbody>
</table>
{summary_html}
</body>
</html>"""

    out_path.write_text(html, encoding="utf-8")
    print(f"Report -> {out_path}")


if __name__ == "__main__":
    db.init_db()
    CHARTS_DIR.mkdir(exist_ok=True)

    symbols = [s.upper() for s in sys.argv[1:]] if len(sys.argv) > 1 else db.list_symbols()
    print(f"Processing {len(symbols)} symbols: {', '.join(symbols)}")
    print(f"Progress -> {CHARTS_DIR}/run_all_progress.html\n")

    prog = RunAllProgress(symbols, out=str(CHARTS_DIR / "run_all_progress.html"))

    report_rows = []
    for i, sym in enumerate(symbols, 1):
        print(f"[{i}/{len(symbols)}] {sym}", end=" ... ", flush=True)
        row = process_symbol(sym, prog)
        if row:
            report_rows.append(row)
            print(f"median={row['median_growth_%']:.1f}%  interval={row['interval_growth_%']:.1f}%")
        else:
            print("skipped/error")

    prog.finish()

    if report_rows:
        build_report(report_rows, CHARTS_DIR / "report_all.html")

    print("\nDone.")
