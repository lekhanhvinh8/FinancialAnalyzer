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

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from portfolio import config
from portfolio.engine import run_backtest
from portfolio.market import Market
from portfolio.report import compare
from portfolio.strategy import build_baseline, build_plan
from portfolio.universe import resolve


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

    t0 = time.time()

    def on_symbol(symbol, ok, reason):
        print(f"  {symbol:<6} {'ok' if ok else 'skip: ' + str(reason)}", flush=True)

    # Both plans share the Market, so it must carry every window either reads.
    market = Market.load(universe, plan.windows() | baseline.windows(),
                         min_rows=config.MIN_ROWS, on_symbol=on_symbol)
    print(f"\n{market.summary()}   ({time.time() - t0:.1f}s to load)\n")

    t1 = time.time()
    result = run_backtest(market, plan, config.CONTRIBUTION,
                          deposit_rate=config.DEPOSIT_RATE,
                          leftover=config.LEFTOVER)
    t2 = time.time()
    base = run_backtest(market, baseline, config.CONTRIBUTION,
                        deposit_rate=config.DEPOSIT_RATE,
                        leftover=config.LEFTOVER)
    print(f"plan {t2 - t1:.1f}s | baseline {time.time() - t2:.1f}s\n")

    print(compare(result, base))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
