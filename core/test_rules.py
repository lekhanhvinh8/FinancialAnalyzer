"""
Every Rule accepts the call the engine actually makes.

WHY THIS FILE EXISTS

  Rule.applies grew a third parameter, `pool_rank`. The base class was updated
  and five subclasses that override applies were not, so the whole package
  imported cleanly, every rule described itself correctly, and the first
  backtest died on SymbolIn.applies() takes 3 positional arguments but 4 were
  given.

  Nothing short of CALLING the method would have caught that. A smoke test that
  only builds a plan and prints describe() passes on the broken code, which is
  what happened.

  So this walks every concrete Rule subclass, instantiates it and calls
  applies() both ways. It is deliberately mechanical: the point is coverage of
  the SIGNATURE, not of the logic, and a subclass added later is picked up
  without anyone remembering to list it here.

Run with:  python -m core.test_rules
"""

import inspect
import sys

import numpy as np

from core import rules as R
from core.data import SymbolSeries, WindowStats


def _series() -> SymbolSeries:
    n = 40
    closes = np.linspace(10_000, 20_000, n)
    s = SymbolSeries(
        symbol="TST",
        dates=list(range(n)),
        closes=closes,
        pes=np.full(n, 12.0),
        caps=np.full(n, 5e12),
        cap_pct=np.full(n, 0.6),
    )
    s.stats[10] = WindowStats(
        window=10,
        median=closes.copy(), mean=closes.copy(),
        top=closes * 1.2, bottom=closes * 0.8,
        p25=closes * 0.9, p75=closes * 1.1,
    )
    s.slopes[10] = np.full(n, 0.05)
    return s


# One instance per concrete subclass. Composites need a child, so they get one.
def _instances() -> list:
    leaf = R.PremiumBelowRule(window=10, max_premium=10)
    made = {
        R.NeverRule: R.NeverRule(),
        R.AlwaysRule: R.AlwaysRule(),
        R.PremiumBelowRule: leaf,
        R.PremiumAboveRule: R.PremiumAboveRule(window=10, min_premium=10),
        R.SlopeBelowRule: R.SlopeBelowRule(window=10, max_slope=0.2),
        R.CapRankAboveRule: R.CapRankAboveRule(0.5),
        R.SymbolIn: R.SymbolIn({"TST"}),
        R.ValueAboveRule: R.ValueAboveRule(0.0),
        R.ValueBelowRule: R.ValueBelowRule(1e9),
        R.AllOf: R.AllOf([leaf, R.CapRankAboveRule(0.5)]),
        R.AnyOf: R.AnyOf([leaf]),
        R.Not: R.Not(leaf),
    }
    # Anything added to rules.py later must appear above, or this fails.
    found = {v for _n, v in inspect.getmembers(R, inspect.isclass)
             if issubclass(v, R.Rule) and v is not R.Rule}
    missing = found - set(made)
    if missing:
        raise AssertionError(
            "khong co instance cho: " + ", ".join(sorted(c.__name__ for c in missing)))
    return sorted(made.items(), key=lambda kv: kv[0].__name__)


def main() -> int:
    s = _series()
    fails = []
    for cls, rule in _instances():
        name = cls.__name__
        for label, args in (("2 tham so", (s, 20)),
                            ("3 tham so", (s, 20, 0.7))):
            try:
                v = rule.applies(*args)
                if not isinstance(v, bool):
                    fails.append(f"{name} ({label}): tra ve {type(v).__name__}, "
                                 f"khong phai bool")
            except Exception as exc:
                fails.append(f"{name} ({label}): {type(exc).__name__}: {exc}")

        # Every rule must also describe itself and answer symbol_only().
        try:
            assert isinstance(rule.describe(), str)
            rule.symbol_only()
            rule.windows()
            rule.slope_windows()
        except Exception as exc:
            fails.append(f"{name} (phu tro): {type(exc).__name__}: {exc}")

    # pool_rank must actually change the answer for the one rule that reads it,
    # otherwise the parameter is being accepted and ignored.
    pool = R.CapRankAboveRule(0.5, "pool")
    if pool.applies(s, 20, 0.9) is not True or pool.applies(s, 20, 0.1) is not False:
        fails.append("CapRankAboveRule(basis='pool') khong doc pool_rank")
    uni = R.CapRankAboveRule(0.5, "universe")
    if uni.applies(s, 20, 0.1) is not True:
        fails.append("CapRankAboveRule(basis='universe') lai doc pool_rank")

    n = len(_instances())
    if fails:
        print(f"LOI ({len(fails)}):")
        for f in fails:
            print("  -", f)
        return 1
    print(f"OK — {n} lop Rule, ca hai cach goi, va pool_rank co tac dung")
    return 0


if __name__ == "__main__":
    sys.exit(main())
