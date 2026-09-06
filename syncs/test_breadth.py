"""
The breadth sync's freshness rule, asserted on a throwaway universe.

Run with:  python -m syncs.test_breadth

WHAT IS WORTH TESTING HERE

  Not the arithmetic -- core/test_breadth_calc.py covers the round trip, and the
  numbers were checked against an independent recomputation from raw prices.

  What can rot silently is the FRESHNESS RULE. A sync that wrongly believes it
  is current writes nothing and says nothing, which is exactly how
  breadth_signals came to sit sixteen trading days behind the price table while
  every run kept reporting success. So each way the answer can go stale gets an
  assertion:

      a price series is revised   -> not current
      a price series grows        -> not current
      a symbol joins the universe -> not current
      nothing moved               -> current, and the rebuild is skipped

  The third is the one a per-symbol "resume from last date" rule would miss, and
  it is why this step has no incremental path.
"""

import sys

import numpy as np
import pandas as pd

import database as db
import syncs.breadth as sb


def main() -> int:
    fails = []

    def check(cond, msg):
        if not cond:
            fails.append(msg)

    # A universe of our own, so nothing here touches the real one.
    A, B, C = "__T_A__", "__T_B__", "__T_C__"
    dates = pd.date_range("2020-01-01", periods=40, freq="D")

    def put(sym, n, base=100.0):
        # DatetimeIndex + a close column, which is what save_daily_prices takes.
        df = pd.DataFrame({"close": base + np.arange(n, dtype=float)},
                          index=dates[:n])
        db.save_daily_prices(sym, df)

    put(A, 30)
    put(B, 30, base=50.0)

    # fingerprint is a pure function of the inputs, so the rule can be tested
    # without running the 4-minute rebuild.
    f1 = sb.fingerprint([A, B], sb.WINDOW)
    check(sb.fingerprint([A, B], sb.WINDOW) == f1, "cung dau vao phai cho cung fingerprint")
    check(sb.fingerprint([B, A], sb.WINDOW) == f1, "thu tu ma khong duoc lam doi fingerprint")

    # ── a series grows ──────────────────────────────────────────────────────
    put(A, 35)
    f2 = sb.fingerprint([A, B], sb.WINDOW)
    check(f2 != f1, "them phien moi phai lam doi fingerprint")

    # ── a series is revised in place (a corporate action, re-adjusted) ──────
    db.save_daily_prices(A, pd.DataFrame(
        {"close": 100.0 + np.arange(35, dtype=float) * 2}, index=dates[:35]))
    f3 = sb.fingerprint([A, B], sb.WINDOW)
    check(f3 != f2, "sua lai lich su phai lam doi fingerprint, du so phien khong doi")

    # ── a symbol joins the universe ─────────────────────────────────────────
    # The case a per-symbol "resume from the last stored date" rule cannot see:
    # C's own rows are new, but its arrival moves every basket row from its
    # listing date on.
    put(C, 20, base=70.0)
    f4 = sb.fingerprint([A, B, C], sb.WINDOW)
    check(f4 != f3, "them mot ma vao ro phai lam doi fingerprint")

    # ── the skip path ───────────────────────────────────────────────────────
    # Stored fingerprint matching the inputs means current; anything else does
    # not. Written under the test universe name so the real row is untouched.
    real_variant = sb._fp_variant()
    saved = db.load_sync_fingerprint("breadth", "__T_UNI__", real_variant)
    db.save_sync_fingerprint("breadth", "__T_UNI__", real_variant, f4)
    got = db.load_sync_fingerprint("breadth", "__T_UNI__", real_variant)
    check(got == f4, f"fingerprint doc lai phai giong, duoc {got}")
    check(db.load_sync_fingerprint("breadth", "__T_UNI__", "khong-co") is None,
          "variant chua co phai tra ve None")

    # ── what the sync writes is only what is STORED ─────────────────────────
    from core.breadth_calc import STORED, SIGNALS, variant
    check(set(STORED) < set(SIGNALS), "STORED phai la tap con that su cua SIGNALS")
    check("mean_slope" not in STORED, "mean_slope khong duoc luu")
    check({variant(s) for s in STORED} == {"base", "trim5-95"},
          f"chi hai variant duoc ghi, dang co {sorted({variant(s) for s in STORED})}")

    # ── a basket's NAME describes the basket ────────────────────────────────
    # The old name lied: rows computed without VIC and VIX were filed under
    # "all", so asking the database for the market returned a basket missing two
    # of the largest companies on it. A name that cannot say what it holds is
    # how that goes unnoticed for as long as it did.
    from core.breadth_calc import universe_key
    check(universe_key("all") == "all", "khong loai ai thi ten giu nguyen")
    check(universe_key("all", ["VIC", "VIX"]) == "all-VIC-VIX", "ten phai ke ma bi loai")
    check(universe_key("all", ["VIX", "VIC"]) == "all-VIC-VIX",
          "thu tu ma bi loai khong duoc lam doi ten")
    check(universe_key("vn30", ["VIC"]) == "vn30-VIC", "phai chay voi ro bat ky")

    # Every basket the sync maintains has a distinct name, and every name is
    # derived rather than typed -- two baskets sharing a name would overwrite
    # each other silently, which is the failure this whole rename fixes.
    bs = sb.baskets()
    check(len(bs) == len(sb.BASKETS),
          f"{len(sb.BASKETS)} ro nhung chi {len(bs)} ten -> co ten trung")
    check("all" in bs, f"phai co ro 'all', dang co: {sorted(bs)}")
    for name, syms in bs.items():
        check(len(syms) > 0, f"ro {name} rong")
        check(name == "all" or len(syms) < len(bs["all"]),
              f"ro {name} phai nho hon 'all'")

    # skip= leaves symbols out of the basket without a second load.
    import inspect
    from core.breadth_calc import compute as _compute
    check("skip" in inspect.signature(_compute).parameters,
          "compute() phai nhan skip= de mot lan nap phuc vu nhieu ro")

    # ── the sync must not import a strategy ─────────────────────────────────
    from pathlib import Path
    src = (Path(__file__).parent / "breadth.py").read_text(encoding="utf-8")
    for pkg in ("breadth.", "single.", "portfolio."):
        check(f"from {pkg}" not in src and f"import {pkg}" not in src,
              f"syncs/breadth.py import {pkg} -- tang du lieu khong duoc biet chien luoc")

    # ── clean up ────────────────────────────────────────────────────────────
    if saved is None:
        with db._conn() as con:
            con.execute("DELETE FROM sync_fingerprint WHERE symbol = '__T_UNI__'")
    else:
        db.save_sync_fingerprint("breadth", "__T_UNI__", real_variant, saved)
    with db._conn() as con:
        con.execute("DELETE FROM daily_prices WHERE symbol IN (?, ?, ?)", (A, B, C))
        con.execute("DELETE FROM symbols WHERE symbol IN (?, ?, ?)", (A, B, C))

    if fails:
        print(f"LOI ({len(fails)}):")
        for f in fails:
            print("  -", f)
        return 1
    print(f"OK — fingerprint doi dung 3 truong hop, {len(sb.BASKETS)} ro co ten "
          f"tu mo ta, va chi ghi tin hieu trong STORED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
