"""
Run one portfolio backtest against the equal-weight DCA baseline.

Usage:
    python -m portfolio.run                     # UNIVERSE from config
    python -m portfolio.run FPT HPG STB VNM     # an explicit universe
    python -m portfolio.run --universe=vn30
    python -m portfolio.run --top-k=5
    python -m portfolio.run --scorer=drawdown --top-k=8

Both plans run over ONE Market, so warmup, eligibility and the tradable calendar
are identical by construction rather than by agreement — the only difference
between the two runs is what strategy.py says.
"""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# A Windows console defaults to cp1252, which cannot encode most of what this
# program prints — Vietnamese labels, the box-drawing in a describe() string,
# an em dash in a skip reason. Without this a run dies on a PRINT STATEMENT
# after minutes of work, which has now happened three times in this package's
# short life. errors="replace" rather than "strict": a mangled character in a
# progress line is not a reason to lose the run.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from portfolio import config
from portfolio.engine import run_backtest
from core.market import Market
from core.progress import RunProgress
from portfolio.report import compare
from portfolio.overlay_chart import build_overlay
from portfolio.report_html import build_report
from portfolio.symbol_chart import build_all as build_symbol_charts
from portfolio.strategy import build_baseline, build_plan
from core.universe import resolve


def _bar(n: int, total: int, width: int = 18) -> str:
    """A text progress bar. Plain ASCII so it survives a cp1252 console."""
    filled = int(width * n / total) if total else width
    return "[" + "#" * filled + "." * (width - filled) + "]"


def main(argv) -> int:
    symbols = [a.upper() for a in argv if not a.startswith("--")]
    for a in argv:
        if a.startswith("--universe="):
            config.UNIVERSE = a.split("=", 1)[1]
        elif a.startswith("--top-k="):
            v = a.split("=", 1)[1]
            config.TOP_K = None if v.lower() in ("none", "all") else int(v)
        elif a.startswith("--scorer="):
            config.SCORER = a.split("=", 1)[1]
        elif a.startswith("--leftover="):
            config.LEFTOVER = a.split("=", 1)[1]
    if symbols:
        config.UNIVERSE = symbols

    plan = build_plan(config)
    baseline = build_baseline(config)

    print(plan.describe())
    print(f"  leftover  : {config.LEFTOVER}")
    print(f"  fallback  : {plan.fallback_symbol or chr(45)}")
    print(f"  benchmark : {baseline.name}")
    if plan.allocator.top_k is None:
        print("  NOTE      : top_k is None, so the ranking is inert - "
              "every candidate gets the same money")
    print()

    benchmark = getattr(config, "BENCHMARK", None)
    universe = resolve(config.UNIVERSE, config.EXCLUDE,
                       extra=[benchmark] if benchmark else [])
    print(f"Universe: {len(universe)} symbols"
          + (f"  (gom ca benchmark {benchmark})" if benchmark else ""))

    # Progress matters here because loading dominates the wall clock — minutes
    # against a backtest that takes under a second — and without a counter the
    # symbol list just scrolls with no way to tell a slow run from a stuck one.
    charts_dir = Path(__file__).resolve().parent / "charts"
    total = len(universe)
    n_est = total  # charts are capped by traded symbols; refined after the run
    prog = RunProgress(charts_dir / "progress.html", [
        ("load", f"Nạp dữ liệu {total} mã", total),
        ("backtest", "Chạy backtest", None),
        ("charts", "Dựng biểu đồ mã", None),
    ])
    print(f"Progress -> {charts_dir / 'progress.html'}", flush=True)

    t0 = time.time()
    state = {"n": 0}

    def on_symbol(symbol, ok, reason):
        state["n"] += 1
        n = state["n"]
        done = time.time() - t0
        # ETA from the average so far. Crude, and honest about it: symbols do
        # not take the same time, but over fifty of them the average is close
        # enough to answer "another minute or another ten".
        eta = done / n * (total - n)
        bar = _bar(n, total)
        status = "ok" if ok else f"bo qua: {reason}"
        print(f"  {bar} {n:>3}/{total}  {symbol:<7}{status:<34}"
              f"{done:>5.0f}s  con ~{eta:>4.0f}s", flush=True)
        prog.step("load", symbol, ok=ok, detail="" if ok else str(reason))

    # Both plans share the Market, so it must carry every window either reads.
    prog.begin("load")
    print(f"\n[1/3] Nap du lieu {total} ma "
          f"(cua so {sorted(plan.windows() | baseline.windows())}"
          + (f", slope {sorted(plan.slope_windows())}" if plan.slope_windows() else "")
          + ")", flush=True)
    market = Market.load(universe, plan.windows() | baseline.windows(),
                         min_rows=config.MIN_ROWS, on_symbol=on_symbol,
                         slope_windows=plan.slope_windows()
                                       | baseline.slope_windows())
    load_s = time.time() - t0
    print(f"\n{market.summary()}   ({load_s:.1f}s to load)\n")

    prog.end("load", market.summary())
    prog.begin("backtest")
    print("[2/3] Chay backtest", flush=True)
    # track=True records the month-end equity curve, which only the HTML report
    # reads. A sweep leaves it off.
    t1 = time.time()
    result = run_backtest(market, plan, config.CONTRIBUTION,
                          deposit_rate=config.DEPOSIT_RATE,
                          leftover=config.LEFTOVER, track=True)
    t2 = time.time()
    base = run_backtest(market, baseline, config.CONTRIBUTION,
                        deposit_rate=config.DEPOSIT_RATE,
                        leftover=config.LEFTOVER, track=True)
    print(f"plan {t2 - t1:.1f}s | baseline {time.time() - t2:.1f}s\n")

    prog.end("backtest",
             f"{result['growth_%']:.2f}% vs {base['growth_%']:.2f}%")
    print(compare(result, base, plan_name=plan.name,
                  baseline_name=baseline.name))

    n_charts = len([p for p in result["wallet"].positions.values() if p.trades])
    print(f"\n[3/3] Dung {n_charts} bieu do ma "
          f"(~30s/ma, chay song song)", flush=True)
    prog.begin("charts")
    prog._phase("charts")["total"] = n_charts
    t3 = time.time()
    charts = build_symbol_charts(result, market, plan, config, charts_dir,
                                 on_chart=lambda sym, ok, err:
                                     prog.step("charts", sym, ok=ok, detail=err or ""))
    print(f"  xong {len(charts)} bieu do trong {time.time() - t3:.0f}s")

    prog.end("charts")
    overlay = build_overlay(result, market, config,
                            charts_dir / "overlay.html", charts=charts)
    print(f"Overlay -> {overlay}")

    out = charts_dir / "report.html"
    build_report(result, base, plan, baseline, config, market, out,
                 load_seconds=load_s, charts=charts)
    prog.finish({
        "Tăng trưởng": f"{result['growth_%']:.2f}%",
        "Benchmark": f"{base['growth_%']:.2f}%",
        "Chênh lệch": f"{result['growth_%'] - base['growth_%']:+.2f}%",
        "Mã nắm giữ": result["symbols_held"],
        "Lệnh mua": f"{result['buys']:,}",
        "Lệnh bán": f"{result['sells']:,}",
    }, report="report.html")
    print(f"\nReport -> {out}")
    if "--no-open" not in argv:
        try:
            os.startfile(out)
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
