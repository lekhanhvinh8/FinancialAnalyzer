"""
breadth_signals round-trips, and NaN stays NaN.

Run with:  python -m breadth.test_db
"""

import sys

import numpy as np
import pandas as pd

import database as db
from breadth.signals import BreadthSeries, load_from_db, save_to_db, variant

UNI, WIN, SLOPE = "__test__", 7, 3


def main() -> int:
    fails = []

    def check(c, m):
        if not c:
            fails.append(m)

    dates = [pd.Timestamp("2020-01-0%d" % d) for d in (1, 2, 3)]
    b = BreadthSeries(
        dates=dates,
        values={"median_prem": np.array([1.5, np.nan, -3.25]),   # -> base
                "prem_trim":   np.array([2.0, 2.5, -1.0]),       # -> trim5-95
                "mean_slope":  np.array([0.1, 0.2, 0.3])},       # -> slope3
        counts=np.array([40.0, 41.0, 42.0]),
        row_of={d: i for i, d in enumerate(dates)},
    )

    # A SIGNAL IS NAMED BY WHAT IT READS. median_prem reads neither the slope
    # window nor the z_dev one, so it must not be filed under a name that
    # mentions them -- the bug this test was written for.
    check(variant("median_prem", SLOPE) == "base",
          f"median_prem phai la 'base', duoc {variant('median_prem', SLOPE)}")
    check(variant("prem_trim", SLOPE) == "trim5-95", "prem_trim sai ten")
    check(variant("mean_slope", SLOPE) == f"slope{SLOPE}", "mean_slope sai ten")

    for v in ("base", "trim5-95"):
        db.delete_breadth(UNI, WIN, v)
    info = save_to_db(b, UNI, WIN, SLOPE)
    # mean_slope is computed but NOT stored, so two variants and 6 rows, not
    # three and 9. Nothing reads it back from the database; storing it kept a
    # variant alive in a store that nothing addressed.
    check(sorted(info) == ["base", "trim5-95"],
          f"phai tach lam 2 variant, duoc {sorted(info)}")
    check(sum(r["saved"] for r in info.values()) == 6,
          f"phai ghi 2x3 = 6 dong, ghi {sum(r['saved'] for r in info.values())}")

    # Read back: the three variants reassemble into one series.
    got = load_from_db(UNI, WIN, SLOPE)
    check(got is not None, "khong doc lai duoc")
    if got:
        check([str(d)[:10] for d in got.dates] == ["2020-01-01", "2020-01-02",
                                                   "2020-01-03"], "ngay sai")
        check(list(got.counts) == [40, 41, 42], f"n_symbols sai: {got.counts}")
        check(got.at("median_prem", 0) == 1.5, "gia tri sai")
        # NaN must survive as "no data", not become 0.
        check(got.at("median_prem", 1) is None,
              f"NaN phai ve None, duoc {got.at('median_prem', 1)}")
        check(got.at("prem_trim", 2) == -1.0, "prem_trim sai")
        check("mean_slope" not in got.values,
              "mean_slope khong duoc luu vao DB")

    # Re-saving overwrites rather than duplicating.
    save_to_db(b, UNI, WIN, SLOPE)
    check(len(db.load_breadth(UNI, WIN, "base")) == 3, "ghi lai phai de len")

    # MOVING A PARAMETER MOVES ONLY WHAT READS IT. Nothing stored today reads
    # the slope window, so changing it must not create a variant at all -- 2829
    # identical rows used to be rewritten under a new name every time an
    # unrelated window moved.
    save_to_db(b, UNI, WIN, SLOPE + 1)
    v = db.breadth_variants()
    mine = set(v[v["universe"] == UNI]["variant"])
    check(mine == {"base", "trim5-95"},
          f"doi slope khong duoc de ra variant moi, co: {sorted(mine)}")
    base_rows = db.load_breadth(UNI, WIN, "base")
    check(len(base_rows) == 3 and "median_prem" in base_rows,
          "doi slope khong duoc dong toi median_prem")

    # Asking for a config that was never written is empty, not an error.
    check(load_from_db(UNI, 999, SLOPE) is None,
          "config chua co phai tra ve None")

    for vv in ("base", "trim5-95"):
        db.delete_breadth(UNI, WIN, vv)
    check(db.load_breadth(UNI, WIN, "base").empty, "xoa khong sach")

    if fails:
        print(f"LOI ({len(fails)}):")
        for f in fails:
            print("  -", f)
        return 1
    print("OK — ten variant theo tung tin hieu, ghi/doc/de-len/xoa, va NaN van la NaN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
