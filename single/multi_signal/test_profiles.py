"""
What each named profile MEANS, asserted rather than left to config.py.

Run with:  python -m single.multi_signal.test_profiles

WHY THIS TEST EXISTS

  A profile is an overlay on config.py, so any parameter it does not name is
  inherited. That is convenient and it silently rots: change the shipped default
  and every profile that was relying on the old value now means something else,
  with nothing failing and no line in any report saying so.

  It happened three times in one afternoon, each time unnoticed until a number
  looked wrong:

    "price" was an empty overlay meaning "config.py as it stands". The default
    switched on a breadth sell gate, and a no-argument run -- which applied
    "price" -- then quietly undid the setting the file had just turned on. 52
    symbols, zero difference, no warning.

    "both" means "the symbol AND the market on every arm". When the default's
    buy and reinvest arms moved to the basket, "both" inherited that and became
    a byte-identical copy of the default: two names, one configuration.

    "price_nogates" is a control meaning "price with three gates off". It
    inherited the same way and became "the default with three gates off", which
    is a different experiment with the same name -- the worst kind, because its
    number stays plausible.

  So each profile now states which arms read the price, which read the basket,
  and which read both, and this test pins that down. A profile may add
  parameters freely; it may not quietly change what it is.
"""

import importlib
import sys

from single.multi_signal import config
from single.multi_signal.profiles import PROFILES, apply

# (price condition on?, breadth gate on?) per arm -- the identity of a profile,
# independent of the exact thresholds, which sweeps are free to move.
#   P = reads this symbol's price   B = reads the basket   PB = both   -- = neither
EXPECTED = {
    "price":         {"buy": "P",  "sell": "P",  "reinvest": "P"},
    "breadth":       {"buy": "B",  "sell": "B",  "reinvest": "B"},
    "both":          {"buy": "PB", "sell": "PB", "reinvest": "PB"},
    "both_or":       {"buy": "PB", "sell": "PB", "reinvest": "PB"},
    "price_nogates": {"buy": "P",  "sell": "P",  "reinvest": "P"},
}

# The shipped default is a profile in all but name, so it is pinned too. Its
# buy and reinvest arms run on the basket alone; its sell arm reads both.
EXPECTED_DEFAULT = {"buy": "B", "sell": "PB", "reinvest": "B"}

# Cong loc, tach rieng khoi ba arm: chung khong quyet dinh arm nao doc gi, nhung
# bat/tat mot cai la doi han hanh vi. MIN_SIGNAL3 tung bi tat o config va ba
# profile thua ke gia tri do ma khong ai nhan ra.
GATES = {
    "price":         {"MIN_SIGNAL3": True},
    "breadth":       {"MIN_SIGNAL3": False},
    "both":          {"MIN_SIGNAL3": True},
    "both_or":       {"MIN_SIGNAL3": True},
    "price_nogates": {"MIN_SIGNAL3": False},
}
GATES_DEFAULT = {"MIN_SIGNAL3": True}

ARMS = {
    "buy":      (("PERCENT_BUY",), "BUY_MAX_BREADTH"),
    "sell":     (("PERCENT_SELL", "PERCENT_SELL_BOTTOM"), "SELL_MIN_BREADTH"),
    "reinvest": (("PERCENT_REINVEST", "PERCENT_REINVEST_TOP"), "REINVEST_MAX_BREADTH"),
}


def _shape(cfg) -> dict:
    out = {}
    for arm, (price_keys, breadth_key) in ARMS.items():
        p = any(getattr(cfg, k, None) is not None for k in price_keys)
        b = getattr(cfg, breadth_key, None) is not None
        out[arm] = ("PB" if p and b else "P" if p else "B" if b else "--")
    return out


def main() -> int:
    fails = []

    def check(cond, msg):
        if not cond:
            fails.append(msg)

    def _gates(cfg):
        return {k: getattr(cfg, k, None) is not None for k in GATES_DEFAULT}

    importlib.reload(config)
    got = _shape(config)
    check(got == EXPECTED_DEFAULT,
          f"mac dinh (khong profile): mong {EXPECTED_DEFAULT}, duoc {got}")
    g = _gates(config)
    check(g == GATES_DEFAULT, f"cong cua mac dinh: mong {GATES_DEFAULT}, duoc {g}")

    for name, want in EXPECTED.items():
        importlib.reload(config)
        apply(config, name)
        got = _shape(config)
        check(got == want, f"profile {name}: mong {want}, duoc {got}")
        g = _gates(config)
        check(g == GATES[name],
              f"profile {name} cong loc: mong {GATES[name]}, duoc {g}")

    # Every profile that exists must be pinned here, or a new one could be added
    # and drift without this test noticing.
    check(set(PROFILES) == set(EXPECTED),
          f"profile chua duoc chot: {sorted(set(PROFILES) - set(EXPECTED))}, "
          f"chot thua: {sorted(set(EXPECTED) - set(PROFILES))}")

    # No two profiles may resolve to the same configuration -- that is how
    # "both" became a copy of the default without anyone noticing.
    seen = {}
    for name in PROFILES:
        importlib.reload(config)
        apply(config, name)
        key = tuple(sorted((k, repr(getattr(config, k)))
                           for k in dir(config)
                           if k.isupper() and not k.startswith("_") and k != "PROFILE"))
        if key in seen:
            fails.append(f"profile {name} giong het {seen[key]} — hai ten, mot cau hinh")
        seen[key] = name

    importlib.reload(config)   # leave the module as it was found

    if fails:
        print(f"LOI ({len(fails)}):")
        for f in fails:
            print("  -", f)
        return 1
    print(f"OK — {len(EXPECTED)} profile va mac dinh giu dung y nghia va dung "
          f"cong loc, khong hai cai nao trung nhau")
    return 0


if __name__ == "__main__":
    sys.exit(main())
