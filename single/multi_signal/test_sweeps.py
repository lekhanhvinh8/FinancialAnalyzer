"""
The sweep grids are data, so check the data: every cell names real config
keys, every grid has a live cell, and the override context puts config back.

Run with:  python -m single.multi_signal.test_sweeps

No database needed. Whether a cell gives the same numbers as the old
hand-written scripts was checked once, by running both on the same symbols
(see SWEEPS.md); this guards what can silently rot afterwards -- a renamed
config key, which would make a cell set an attribute nothing reads.
"""

import sys

from single.multi_signal import config
from single.multi_signal.sweep_runner import overrides, paths
from single.multi_signal.sweep_specs import SPECS


def main() -> int:
    fails = []

    def check(cond, msg):
        if not cond:
            fails.append(msg)

    known = {k for k in dir(config) if k.isupper()}
    for name, spec in SPECS.items():
        check(spec.cells.get("live") == {}, f"{name}: no empty live cell")
        for key, cell in spec.cells.items():
            for k in cell:
                check(k in known, f"{name}/{key}: {k} is not a config key")
        for key, c in spec.coords.items():
            check(len(c) == len(spec.axes), f"{name}/{key}: coords do not match axes")
        check(len(set(spec.cells)) == len(spec.cells), f"{name}: duplicate keys")

    before = config.PERCENT_SELL
    with overrides({"PERCENT_SELL": 12345, "NOT_A_KEY": 1}):
        check(config.PERCENT_SELL == 12345, "override not applied")
    check(config.PERCENT_SELL == before, "override not restored")
    check(not hasattr(config, "NOT_A_KEY"), "added key not removed")

    a = paths("x", "breadth", {"PERCENT_SELL": 55})[0].name
    b = paths("x", "breadth", {"PERCENT_SELL": None})[0].name
    check(a != b, "two different --set values write the same file")

    if fails:
        print(f"LOI ({len(fails)}):")
        for f in fails:
            print("  -", f)
        return 1
    print(f"OK — {len(SPECS)} sweep, moi o chi dung khoa config co that, "
          f"override tra config ve nguyen trang")
    return 0


if __name__ == "__main__":
    sys.exit(main())
