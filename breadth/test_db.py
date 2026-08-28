"""
breadth_signals round-trips, and NaN stays NaN.

Run with:  python -m breadth.test_db
"""

import sys

import numpy as np
import pandas as pd

import database as db
from breadth.signals import BreadthSeries, load_from_db, save_to_db, variant

UNI, WIN, SLOPE, ZS = "__test__", 7, 3, 5


def main() -> int:
    fails = []

    def check(c, m):
        if not c:
            fails.append(m)

    dates = [pd.Timestamp("2020-01-0%d" % d) for d in (1, 2, 3)]
    b = BreadthSeries(
        dates=dates,
        values={"median_prem": np.array([1.5, np.nan, -3.25]),
                "prem_trim": np.array([2.0, 2.5, -1.0])},
        counts=np.array([40.0, 41.0, 42.0]),
        row_of={d: i for i, d in enumerate(dates)},
    )

    db.delete_breadth(UNI, WIN, variant(SLOPE, ZS))
    info = save_to_db(b, UNI, WIN, SLOPE, ZS)
    check(info["saved"] == 6, f"phai ghi 2x3 = 6 dong, ghi {info['saved']}")

    got = load_from_db(UNI, WIN, SLOPE, ZS)
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

    # Re-saving must overwrite, not duplicate: the primary key carries the whole
    # config, so a second run of the same settings replaces the first.
    save_to_db(b, UNI, WIN, SLOPE, ZS)
    df = db.load_breadth(UNI, WIN, variant(SLOPE, ZS))
    check(len(df) == 3, f"ghi lai phai de len, co {len(df)} ngay")

    # A different variant is a different row set, not an overwrite.
    save_to_db(b, UNI, WIN, SLOPE + 1, ZS)
    v = db.breadth_variants()
    mine = v[v["universe"] == UNI]
    check(len(mine) == 2, f"2 variant phai tach nhau, thay {len(mine)}")

    # Asking for a config that was never written is empty, not an error.
    check(load_from_db(UNI, 999, SLOPE, ZS) is None,
          "config chua co phai tra ve None")

    db.delete_breadth(UNI, WIN, variant(SLOPE, ZS))
    db.delete_breadth(UNI, WIN, variant(SLOPE + 1, ZS))
    check(db.load_breadth(UNI, WIN, variant(SLOPE, ZS)).empty, "xoa khong sach")

    if fails:
        print(f"LOI ({len(fails)}):")
        for f in fails:
            print("  -", f)
        return 1
    print("OK — ghi/doc/de-len/tach-variant/xoa, va NaN van la NaN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
