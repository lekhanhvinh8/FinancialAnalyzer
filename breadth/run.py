"""
CLI for the breadth method.

    python -m breadth.run                     # the shipped config
    python -m breadth.run --universe=vn30     # breadth over VN30 members only
    python -m breadth.run --sell=0.25         # switch the timing arm on

Prints the plan, the comparison against plain DCA into the same instrument, and
a decade-by-decade view of what the pace actually did.
"""

import sys
import time
from pathlib import Path

# The console here is cp1252 and the output is Vietnamese. Reconfiguring beats
# rewriting the strings in English, which is what the first two attempts at this
# did elsewhere in the project.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from breadth import config
from breadth.engine import run_backtest
from core.breadth_calc import (cache_path, compute, fingerprint,
                               load as load_cache, save as save_cache)
from breadth.strategy import build_baseline, build_plan
from breadth import chart as chartmod
from breadth import report_html
from core.market import Market
from core.progress import RunProgress
from core.universe import resolve


CHARTS = Path(__file__).resolve().parent / "charts"


def main(argv) -> int:
    for a in argv:
        if a.startswith("--universe="):
            config.UNIVERSE = a.split("=", 1)[1]
        elif a.startswith("--sell="):
            v = a.split("=", 1)[1]
            config.SELL_BELOW_PCT = None if v.lower() == "none" else float(v)
        elif a.startswith("--window="):
            config.WINDOW = int(a.split("=", 1)[1])

    plan = build_plan(config)
    base = build_baseline(config)
    print(plan.describe())
    print()

    universe = resolve(config.UNIVERSE, config.EXCLUDE, extra=[config.SYMBOL])
    print(f"Universe: {len(universe)} ma (do breadth), giao dich {config.SYMBOL}")

    prog = RunProgress(CHARTS / "progress.html", [
        ("load", f"Nap du lieu {len(universe)} ma", len(universe)),
        ("breadth", "Tinh breadth", None),
        ("backtest", "Chay backtest", None),
        ("report", "Dung bao cao", None),
    ])
    print(f"Progress -> {CHARTS / 'progress.html'}", flush=True)

    # Breadth is a pure function of the market and the two windows, so it caches
    # safely. The load it avoids is eight minutes; the compute it avoids is one
    # second. --fresh forces the long way round.
    cpath = cache_path(Path(__file__).resolve().parent,
                       config.UNIVERSE, config.WINDOW,
                       f"{config.SLOPE_WINDOW}sqt")
    # The cache is keyed on the prices it was built from, not only on its path:
    # a run that reuses a cache built before the last price sync is measuring
    # yesterday's market.
    fp = fingerprint(universe, config.WINDOW)
    breadth = None if "--fresh" in argv else load_cache(cpath, fp)
    if breadth is not None:
        print(f"Breadth: {len(breadth)} ngay (cache)")
        market = None

    t0 = time.time()
    n = {"i": 0}
    if breadth is not None:
        prog.end("load", "dung cache")
        prog.end("breadth", f"{len(breadth)} ngay (cache)")
        return _report(config, plan, base, breadth, None, prog)

    prog.begin("load")

    def on_symbol(symbol, ok, reason):
        n["i"] += 1
        prog.step("load", symbol, ok=ok, detail="" if ok else str(reason))
        if n["i"] % 10 == 0 or not ok:
            done = time.time() - t0
            print(f"  {n['i']:>3}/{len(universe)}  {symbol:<7}"
                  f"{'ok' if ok else 'bo qua: ' + str(reason):<28}{done:>5.0f}s",
                  flush=True)

    market = Market.load(universe, plan.windows(), min_rows=config.MIN_ROWS,
                         on_symbol=on_symbol, slope_windows=plan.slope_windows())
    print(f"\n{market.summary()}   ({time.time() - t0:.0f}s)\n", flush=True)

    t1 = time.time()
    breadth = compute(market, config.WINDOW, config.SLOPE_WINDOW)
    print(f"Breadth: {len(breadth)} ngay  ({time.time() - t1:.1f}s)")
    save_cache(breadth, cpath, fp)
    print(f"Cache -> {cpath}")
    # DOES NOT WRITE breadth_signals. syncs/breadth.py owns that table, like
    # every other table in the database. This used to write it, and the write
    # sat behind the cache check above -- so a cache hit returned early, the run
    # reported success, and the table silently fell sixteen trading days behind
    # the prices it is derived from.
    #
    # Run `python sync.py --breadth` to refresh it. That step skips itself when
    # no input series changed, so calling it is cheap.
    prog.end("breadth", f"{len(breadth)} ngay")
    return _report(config, plan, base, breadth, market, prog)


def _report(config, plan, base, breadth, market, prog) -> int:
    from breadth.market_stub import PriceMarket
    if market is None:
        # Same warmup core.data would give it, so the two paths agree.
        market = PriceMarket.for_symbol(config.SYMBOL, breadth.dates,
                                        warmup=max(plan.windows()) - 1)
    plan.attach(breadth)
    base.attach(breadth)

    prog.begin("backtest")
    result = run_backtest(market, breadth, plan, config.CONTRIBUTION,
                          deposit_rate=config.DEPOSIT_RATE, track=True)
    bench = run_backtest(market, breadth, base, config.CONTRIBUTION,
                         deposit_rate=config.DEPOSIT_RATE, track=True)

    # The other premium statistic, same thresholds. Both go on the chart so the
    # two sets of decisions can be compared where they were made.
    was = config.USE_TRIM_MEAN
    config.USE_TRIM_MEAN = not was
    alt_plan = build_plan(config)
    config.USE_TRIM_MEAN = was
    alt_plan.attach(breadth)
    alt = run_backtest(market, breadth, alt_plan, config.CONTRIBUTION,
                       deposit_rate=config.DEPOSIT_RATE, track=True)
    alt_label = "prem_trim" if not was else "prem_median"

    w = 22
    print(f"\n{'':<{w}}{plan.name[:18]:>18}{base.name[:20]:>20}")
    print("-" * (w + 38))
    for label, key, fmt in (
        ("months", "months", "{:>16,.0f}"),
        ("buys", "buys", "{:>16,.0f}"),
        ("sells", "sells", "{:>16,.0f}"),
        ("invested", "invested", "{:>16,.0f}"),
        ("final value", "value", "{:>16,.0f}"),
        ("  holdings", "holdings", "{:>16,.0f}"),
        ("  reserve", "reserve", "{:>16,.0f}"),
        ("  interest", "interest", "{:>16,.0f}"),
        ("shares", "shares", "{:>16,.1f}"),
    ):
        print(f"{label:<{w}}{fmt.format(result[key]):>18}"
              f"{fmt.format(bench[key]):>20}")
    print("-" * (w + 38))
    print(f"{'growth':<{w}}{result['growth_%']:>17.2f}%{bench['growth_%']:>19.2f}%")
    print(f"{'difference':<{w}}{result['growth_%'] - bench['growth_%']:>17.2f}%")

    print(f"\n{'so sanh hai thong ke':<24}{'tang truong':>12}{'mua':>7}"
          f"{'tai':>6}{'ban':>6}")
    print("-" * 55)
    used = "prem_trim" if was else "prem_median"
    for lab, r in ((used + " (dang dung)", result), (alt_label, alt)):
        print(f"{lab:<24}{r['growth_%']:>11.2f}%{r['buys']:>7}"
              f"{r.get('reinvests', 0):>6}{r['sells']:>6}")

    # What the pace actually did, which is the only way to tell a rule that
    # fired from one that never got the chance.
    print(f"\n{'nam':<6}{'below_pct tb':>14}{'so ngay manh':>14}"
          f"{'so ngay yeu':>13}{'n tb':>7}")
    print("-" * 54)
    from collections import defaultdict
    by_year = defaultdict(list)
    for i, d in enumerate(breadth.dates):
        by_year[d.year].append(i)
    for year in sorted(by_year):
        idx = by_year[year]
        vals = [breadth.at("below_pct", i) for i in idx]
        vals = [v for v in vals if v is not None]
        ok = [i for i in idx if breadth.counts[i] >= plan.min_symbols]
        strong = sum(1 for i in ok if plan.fires(plan.buy_when, i))
        weak = sum(1 for i in ok
                   if not plan.fires(plan.buy_when, i)
                   and not plan.fires(plan.hold_when, i))
        avg = sum(vals) / len(vals) if vals else float("nan")
        nbar = sum(breadth.counts[i] for i in idx) / len(idx)
        print(f"{year:<6}{avg:>13.2f} {strong:>13} {weak:>12} {nbar:>6.0f}")

    prog.begin("report")
    ch = chartmod.build(result, config, CHARTS, breadth, plan,
                        alt=(alt_label, alt))
    print(f"\nChart  -> {ch}")
    rep = report_html.build(result, bench, plan, config, breadth,
                            CHARTS / "report.html", chart_name=ch.name,
                            bench_name=base.name)
    print(f"Report -> {rep}")
    prog.end("report", rep.name)
    prog.finish({
        "Tang truong": f"{result['growth_%']:.2f}%",
        "DCA": f"{bench['growth_%']:.2f}%",
        "Chenh lech": f"{result['growth_%'] - bench['growth_%']:+.2f}%",
    }, report="report.html")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
