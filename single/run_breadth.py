"""
The breadth strategy on one symbol, or on a list.

    python -m single.run_breadth              # VN30
    python -m single.run_breadth FPT HPG      # named symbols
    python -m single.run_breadth --all        # every stock, in parallel
    python -m single.run_breadth --all --workers=4
    python -m single.run_breadth --all        # every stock in the database

Buy while the basket is not expensive, sell when it is broadly extended AND this
symbol's own momentum has stopped, reinvest only when the basket is genuinely
cheap. Compared against plain interval buying on the same symbol, which is the
question this has to answer: does reading the market beat ignoring it.

Needs breadth_signals in the database -- run `python -m breadth.run --fresh`
first if it is empty.
"""

import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import pandas as pd

import database as db
from breadth.chart import add_signal_line
from export.chart import save_backtest_chart
from progress import RunAllProgress
from single.breadth_map import build_breadth_map, describe
from single.runner import load_symbol_df, run_estimate
from single.strategies.buy import BuyBreadthStrategy, BuyIntervalStrategy
from single.strategies.reinvest import ReInvestBreadthStrategy, ReinvestStrategy
from single.strategies.sell import SellBreadthStrategy, SellStrategy

CHARTS = Path(__file__).resolve().parent / "charts_breadth"

# ── the strategy ─────────────────────────────────────────────────────────────
BUY_MAX_BREADTH = 60.0        # mua khi median_prem <= 60
SELL_MIN_BREADTH = 70.0       # ban khi median_prem > 70 ...
SELL_SIGNAL1_WINDOW = 120     # ... va da cua chinh ma da dung
SELL_MAX_SIGNAL1 = 0.228
REINVEST_MAX_BREADTH = 10.0   # reinvest khi median_prem <= 10
REINVEST_PERCENT = 100.0

INTERVAL_MONEY = 8_000_000
START_INDEX = 1000            # warmup, matching the 1000-bar reference


def _slope_map(symbol, df, window):
    date_to_idx = {pd.Timestamp(t): i for i, t in enumerate(df["time"])}
    sig = db.load_trend_signals(symbol, window_days=window)
    out = {}
    if not sig.empty:
        for date, v in sig["signal1_slope"].items():
            i = date_to_idx.get(pd.Timestamp(date))
            if i is not None:
                out[i] = float(v)
    return out


def run_one(symbol: str, chart: bool = True, out_dir: Path = None) -> dict:
    df = load_symbol_df(symbol)
    cal = db.load_range_stats(symbol, df, range_days={1000})

    breadth = build_breadth_map(df)
    if not breadth:
        raise SystemExit(
            "breadth_signals trong. Chay `python -m breadth.run --fresh` truoc.")
    slopes = _slope_map(symbol, df, SELL_SIGNAL1_WINDOW)

    buy = BuyBreadthStrategy(breadth_map=breadth, max_breadth=BUY_MAX_BREADTH)
    sell = SellBreadthStrategy(breadth_map=breadth, min_breadth=SELL_MIN_BREADTH,
                               signal1_map=slopes, max_signal1=SELL_MAX_SIGNAL1)
    rei = ReInvestBreadthStrategy(breadth_map=breadth,
                                  max_breadth=REINVEST_MAX_BREADTH,
                                  percent=REINVEST_PERCENT)

    got = run_estimate(symbol, df, INTERVAL_MONEY, buy, sell, rei, cal,
                       start_index=START_INDEX)
    base = run_estimate(symbol, df, INTERVAL_MONEY, BuyIntervalStrategy(),
                        SellStrategy(), ReinvestStrategy(), cal,
                        start_index=START_INDEX)

    if chart:
        out = out_dir or CHARTS
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"{symbol.lower()}_breadth.html"
        save_backtest_chart(
            df, got["buyedInfos"], got["sellInfos"], got["reinvestInfos"],
            path=str(path),
            title=f"{symbol} — breadth strategy",
            index=symbol.lower(), cal_range_close=cal,
            buy_strategy=buy, sell_strategy=sell, reinvest_strategy=rei,
            result=got, compare_result=base, start_index=START_INDEX,
            sig1_window=SELL_SIGNAL1_WINDOW)

        # The line the decisions were made on. Without it the chart shows three
        # sells with nothing on it that explains them -- the reason lives in the
        # basket, not in this symbol's price.
        x = [str(t)[:10] for t in df["time"]]
        add_signal_line(
            path, x, {"median_prem": [breadth.get(i) for i in range(len(x))]},
            [(BUY_MAX_BREADTH, "mua"), (SELL_MIN_BREADTH, "ban"),
             (REINVEST_MAX_BREADTH, "reinvest")],
            axis_title="median_prem")

    return {"symbol": symbol, "breadth": describe(breadth),
            "plan": got, "base": base}


def process_symbol(symbol: str, out_dir: Path):
    """
    One symbol in a worker process. Returns plain data, never a progress object:
    RunAllProgress is not picklable and the parent owns it, exactly as
    median1000/run_all.py arranges it.
    """
    t0 = time.time()
    try:
        r = run_one(symbol, out_dir=out_dir)
    except Exception as exc:
        return symbol, None, f"{type(exc).__name__}: {exc}", time.time() - t0
    p, b = r["plan"], r["base"]
    return symbol, {
        "symbol": symbol,
        "growth_%": p["allRatioGrowth"],
        "interval_growth_%": b["allRatioGrowth"],
        "diff_%": p["allRatioGrowth"] - b["allRatioGrowth"],
        "buys": p["totalBuys"], "sells": p["totalSells"],
        "reinvests": p["totalReinvest"],
        "chart": f"{symbol.lower()}_breadth.html",
    }, None, time.time() - t0


def build_report(rows: list, path: Path, skipped: list) -> Path:
    """
    One table, sorted by how much the strategy beat interval buying.

    A SIGN TEST, NOT AN AVERAGE. The sells fire on the same few market-wide days
    for every symbol, so the rows are not independent observations and a mean of
    them would claim precision that is not there. How many symbols it beat is
    the honest summary.
    """
    rows = sorted(rows, key=lambda r: -r["diff_%"])
    wins = sum(1 for r in rows if r["diff_%"] > 0)
    body = "".join(
        f'<tr><td><a href="{r["chart"]}">{r["symbol"]}</a></td>'
        f'<td class="n">{r["growth_%"]:.2f}%</td>'
        f'<td class="n">{r["interval_growth_%"]:.2f}%</td>'
        f'<td class="n {"pos" if r["diff_%"] > 0 else "neg"}">{r["diff_%"]:+.2f}%</td>'
        f'<td class="n">{r["buys"]}</td><td class="n">{r["sells"]}</td>'
        f'<td class="n">{r["reinvests"]}</td></tr>' for r in rows)
    skip = "".join(f"<li>{s} — {why}</li>" for s, why in skipped)

    path.write_text(f"""<!doctype html><meta charset="utf-8">
<title>breadth strategy — {len(rows)} mã</title>
<style>
body{{font:15px/1.6 system-ui,sans-serif;max-width:900px;margin:32px auto;padding:0 16px;
background:#0E141C;color:#E4EBF4}}
table{{width:100%;border-collapse:collapse;font-size:13.5px}}
th{{text-align:right;color:#7386A0;font-weight:500;border-bottom:1px solid #2B3949;padding:6px}}
th:first-child{{text-align:left}}
td{{padding:3px 6px;border-bottom:1px solid #1C2734}}
td.n{{text-align:right;font-family:ui-monospace,monospace}}
a{{color:#6E9BFF;text-decoration:none}} .pos{{color:#5FCC9C}} .neg{{color:#F0857D}}
h1{{font-size:20px}} .sub{{color:#A3B2C6;font-size:13.5px}}
</style>
<h1>Breadth strategy</h1>
<p class="sub">mua &le; {BUY_MAX_BREADTH:g} &middot; bán &gt; {SELL_MIN_BREADTH:g}
kèm slope[{SELL_SIGNAL1_WINDOW}] &lt; {SELL_MAX_SIGNAL1} &middot;
reinvest &le; {REINVEST_MAX_BREADTH:g} &middot; dựng {datetime.now():%Y-%m-%d %H:%M}</p>
<p class="sub"><b>Thắng {wins}/{len(rows)} mã ({wins / len(rows):.0%})</b> so với mua đều.
Các lệnh bán rơi vào cùng vài ngày toàn thị trường ở mọi mã, nên đây là
{len(rows)} góc nhìn của một quyết định, không phải {len(rows)} quan sát độc lập.</p>
<table><thead><tr><th>Mã</th><th>Breadth</th><th>Mua đều</th><th>Chênh</th>
<th>Mua</th><th>Bán</th><th>Tái đt</th></tr></thead><tbody>{body}</tbody></table>
{f"<p class='sub'>Bỏ qua {len(skipped)}:</p><ul class='sub'>{skip}</ul>" if skip else ""}
""", encoding="utf-8")
    return path


def main(argv) -> int:
    args = [a for a in argv if not a.startswith("--")]
    flags = [a for a in argv if a.startswith("--")]
    workers = next((int(f.split("=", 1)[1]) for f in flags
                    if f.startswith("--workers=")), None)

    if "--all" in flags:
        from core.universe import resolve
        symbols = resolve("all", ["VIX", "VIC"], extra=["VN30"])
    else:
        symbols = [a.upper() for a in args] or ["VN30"]
    print(f"mua <= {BUY_MAX_BREADTH:g} | ban > {SELL_MIN_BREADTH:g} "
          f"va slope[{SELL_SIGNAL1_WINDOW}] < {SELL_MAX_SIGNAL1} | "
          f"reinvest <= {REINVEST_MAX_BREADTH:g}")

    # A fresh directory per run, like median1000/run_all.py: a rerun must not
    # overwrite the charts a previous one is being read from.
    CHARTS.mkdir(parents=True, exist_ok=True)
    run_dir = CHARTS / datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir.mkdir(exist_ok=True)
    print(f"Output   -> {run_dir}")
    print(f"Progress -> {run_dir / 'run_breadth_progress.html'}\n", flush=True)

    prog = RunAllProgress(symbols, out=str(run_dir / "run_breadth_progress.html"))
    t0 = time.time()
    rows, skipped, done = [], [], 0

    with ProcessPoolExecutor(max_workers=workers) as ex:
        n_slots = ex._max_workers
        futures = {ex.submit(process_symbol, sym, run_dir): sym for sym in symbols}

        # The pool runs submissions FIFO, so the first n_slots are the ones
        # actually in flight. Tracked here rather than reported by the workers,
        # which would need a Manager queue just to say "I started".
        for sym in symbols[:n_slots]:
            prog.begin(sym)
        next_start = n_slots

        # as_completed, not map: map yields in submission order, so one slow
        # symbol holds back every result behind it and the page moves in bursts.
        for fut in as_completed(futures):
            sym, row, why, dur = fut.result()
            done += 1
            if row:
                rows.append(row)
                prog.end_ok(sym, dur, median_growth=row["growth_%"],
                            buys=row["buys"], sells=row["sells"],
                            reinvests=row["reinvests"],
                            interval_growth=row["interval_growth_%"],
                            chart=row["chart"])
                print(f"[{done}/{len(symbols)}] {sym:<7}"
                      f"{row['growth_%']:>9.2f}%{row['interval_growth_%']:>11.2f}%"
                      f"{row['diff_%']:>9.2f}%", flush=True)
            else:
                skipped.append((sym, why or "unknown"))
                prog.end_err(sym, why or "unknown")
                print(f"[{done}/{len(symbols)}] {sym:<7}bo qua — {why}", flush=True)
            if next_start < len(symbols):
                prog.begin(symbols[next_start])
                next_start += 1

    prog.finish()
    if rows:
        rep = build_report(rows, run_dir / "report_all.html", skipped)
        wins = sum(1 for r in rows if r["diff_%"] > 0)
        print(f"\nthang {wins}/{len(rows)} ma ({wins / len(rows):.0%})")
        print(f"Report -> {rep}")
    print(f"Done in {(time.time() - t0) / 60:.1f} min tren {n_slots} workers.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
