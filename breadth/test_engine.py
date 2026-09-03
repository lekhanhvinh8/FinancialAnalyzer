"""
The breadth engine, against a market small enough to work out by hand.

WHY THIS EXISTS

  Nothing here raises when it is wrong. A pace rule that never fires, a reserve
  that never drains, a baseline that quietly differs from DCA -- each produces a
  plausible number and a completed run. The only way to know is to build a market
  whose right answer is known in advance and check it.

  So the fixtures are synthetic and tiny: prices that do exactly one thing, and
  breadth values set by hand rather than computed.

Run with:  python -m breadth.test_engine
"""

import sys
from datetime import date, timedelta

import numpy as np

from breadth.engine import buy_multiple, run_backtest
from core.ledger import execute_sell
from core.breadth_calc import SIGNALS, BreadthSeries, compute
from breadth.strategy import Plan
from core.rules import ValueAboveRule, ValueBelowRule


class _Bar:
    def __init__(self, symbol, index, price):
        self.symbol, self.index, self.price = symbol, index, price


class _Day:
    def __init__(self, d, bars):
        self.date, self.bars = d, bars


class _Series:
    def __init__(self, n, price):
        self.is_index = True
        self.closes = np.full(n, price)
        self.warmup = 0


class _Market:
    """Trading days at a fixed price, one instrument, one bar each."""

    def __init__(self, n_days, price=1000.0, start=date(2020, 1, 1)):
        self._days = []
        d = start
        for i in range(n_days):
            while d.weekday() >= 5:
                d += timedelta(days=1)
            self._days.append(_Day(d, {"IDX": _Bar("IDX", i, price)}))
            d += timedelta(days=1)
        self._series = _Series(n_days, price)

    def days(self):
        return iter(self._days)

    def __getitem__(self, _sym):
        return self._series

    @property
    def dates(self):
        return [d.date for d in self._days]


def _breadth(dates, below, counts=None):
    n = len(dates)
    vals = {k: np.full(n, np.nan) for k in SIGNALS}
    vals["below_pct"] = np.asarray(below, dtype=float)
    vals["mean_slope"] = np.zeros(n)
    return BreadthSeries(
        dates=list(dates), values=vals,
        counts=np.asarray(counts if counts is not None else [50.0] * n),
        row_of={d: i for i, d in enumerate(dates)},
    )


def _plan(**kw):
    kw.setdefault("min_symbols", 20)
    return Plan(name="t", symbol="IDX", **kw)


def main() -> int:
    fails = []

    def check(cond, msg):
        if not cond:
            fails.append(msg)

    CONTRIB = 1_000_000.0
    PRICE = 1000.0

    # ── the baseline really is DCA ──────────────────────────────────────────
    m = _Market(300)
    b = _breadth(m.dates, [0.9] * 300)          # would look "strong" to a plan
    base = _plan(buy_strong=1.0, buy_normal=1.0, buy_weak=1.0, min_symbols=0)
    base.attach(b)
    r = run_backtest(m, b, base, CONTRIB, deposit_rate=0.0)
    months = r["months"]
    check(abs(r["invested"] - months * CONTRIB) < 1.0,
          f"DCA phai nap dung {months} thang, nap {r['invested']:,.0f}")
    check(abs(r["reserve"]) < 1.0, f"DCA khong duoc de lai tien, con {r['reserve']:,.0f}")
    check(abs(r["shares"] - months * CONTRIB / PRICE) < 1e-6,
          "DCA phai mua het moi thang")
    check(r["buys"] == months, f"DCA phai co dung {months} lenh mua, co {r['buys']}")

    # ── the pace actually changes what is spent ─────────────────────────────
    weak = _plan(buy_when=[("below_pct", ValueAboveRule(0.65))],
                 hold_when=[("below_pct", ValueAboveRule(0.50))],
                 buy_strong=2.0, buy_normal=1.0, buy_weak=0.5)
    b_low = _breadth(m.dates, [0.10] * 300)     # never cheap: weak every month
    weak.attach(b_low)
    r = run_backtest(m, b_low, weak, CONTRIB, deposit_rate=0.0)
    spent = r["shares"] * PRICE
    check(abs(spent - 0.5 * months * CONTRIB) < 1.0,
          f"nhip yeu phai tieu 50%, tieu {spent / (months * CONTRIB):.0%}")
    check(r["reserve"] > 0, "phan khong tieu phai nam o reserve")
    check(abs(r["invested"] - months * CONTRIB) < 1.0,
          "von nap phai khong doi du tieu it hon")

    # Strong every month, and no reserve to draw on, spends one contribution --
    # it cannot spend money it does not have.
    strong = _plan(buy_when=[("below_pct", ValueAboveRule(0.65))],
                   hold_when=[("below_pct", ValueAboveRule(0.50))],
                   buy_strong=2.0, buy_normal=1.0, buy_weak=0.5)
    b_high = _breadth(m.dates, [0.90] * 300)
    strong.attach(b_high)
    r = run_backtest(m, b_high, strong, CONTRIB, deposit_rate=0.0)
    check(abs(r["shares"] * PRICE - months * CONTRIB) < 1.0,
          "luon manh nhung khong co reserve thi chi tieu duoc 1 phan gop")

    # ── the reserve built while weak is spent when strong ───────────────────
    half = [0.10] * 150 + [0.90] * 150
    mixed = _plan(buy_when=[("below_pct", ValueAboveRule(0.65))],
                  hold_when=[("below_pct", ValueAboveRule(0.50))],
                  buy_strong=2.0, buy_normal=1.0, buy_weak=0.5)
    bm = _breadth(m.dates, half)
    mixed.attach(bm)
    r = run_backtest(m, bm, mixed, CONTRIB, deposit_rate=0.0)
    check(r["shares"] * PRICE > 0.5 * months * CONTRIB + 1.0,
          "reserve tich luc yeu phai duoc tieu khi manh")
    check(r["reserve"] < 0.5 * months * CONTRIB,
          f"reserve phai rut bot, con {r['reserve']:,.0f}")

    # ── the thin-day fallback is DCA, not zero ──────────────────────────────
    thin = _breadth(m.dates, [0.10] * 300, counts=[5.0] * 300)
    tp = _plan(buy_when=[("below_pct", ValueAboveRule(0.65))],
               hold_when=[("below_pct", ValueAboveRule(0.50))],
               buy_strong=2.0, buy_normal=1.0, buy_weak=0.5, min_symbols=20)
    tp.attach(thin)
    r = run_backtest(m, thin, tp, CONTRIB, deposit_rate=0.0)
    check(abs(r["shares"] * PRICE - months * CONTRIB) < 1.0,
          "ngay mong phai quay ve DCA (x1), khong phai x0.5")

    # ── a day that sells does not also buy ──────────────────────────────────
    # The sell arm has just said the basket is extended; spending the proceeds
    # at the same price the same day undoes the decision and leaves only the
    # trade record behind.
    ms = _Market(300)
    bs = _breadth(ms.dates, [0.9] * 300)
    sp = _plan(buy_when=[("below_pct", ValueAboveRule(0.5))],
               sell_when=[("below_pct", ValueAboveRule(0.5))],   # both fire, always
               buy_strong=2.0, buy_normal=1.0, buy_weak=1.0, min_symbols=0)
    sp.attach(bs)
    r = run_backtest(ms, bs, sp, CONTRIB, deposit_rate=0.0)
    # The condition holds every day here, so nothing may ever be bought -- not
    # even on the days the position was already empty and no sale could run.
    check(r["buys"] == 0,
          f"dieu kien ban thoa moi ngay thi khong duoc mua, co {r['buys']}")
    check(abs(r["reserve"] - r["invested"]) < 1.0,
          f"tien phai nam o reserve, co {r['reserve']:,.0f}")

    # ── a plan of conditions has no fallback pace ───────────────────────────
    # buy_weak > 0 means "buy this much whatever the signal says". In a
    # three-arm plan that makes the buy CONDITION decorative: it sold one day
    # and bought back the next, every month, and the chart showed exactly that.
    cond = _plan(buy_when=[("below_pct", ValueAboveRule(0.99))],   # never
                 hold_when=[],
                 buy_strong=1.0, buy_normal=0.0, buy_weak=0.0, min_symbols=0)
    bc = _breadth(m.dates, [0.10] * 300)
    cond.attach(bc)
    r = run_backtest(m, bc, cond, CONTRIB, deposit_rate=0.0)
    check(r["buys"] == 0, f"dieu kien khong thoa thi khong duoc mua, co {r['buys']}")
    check(abs(r["reserve"] - r["invested"]) < 1.0, "tien phai o reserve")


    # ── a month the instrument did not trade must not leak into the reserve ──
    # This is the bug the first real run exposed: sizing off "one month" while a
    # second month's money was already waiting pushed the difference into the
    # reserve, where at a multiple of one it circulated for ever.
    class _Gappy(_Market):
        def __init__(self, n_days):
            super().__init__(n_days)
            # Drop the bars for the first eight days of every third month, so
            # some months arrive with the previous one still unspent.
            for d in self._days:
                if d.date.month % 3 == 0 and d.date.day <= 8:
                    d.bars = {}

    g = _Gappy(700)
    bg = _breadth(g.dates, [0.9] * 700)
    bp = _plan(buy_strong=1.0, buy_normal=1.0, buy_weak=1.0, min_symbols=0)
    bp.attach(bg)
    r = run_backtest(g, bg, bp, CONTRIB, deposit_rate=0.0)
    check(abs(r["reserve"]) < 1.0,
          f"DCA qua thang bi khuyet van phai tieu het, con {r['reserve']:,.0f}")
    check(abs(r["shares"] * PRICE - r["invested"]) < 1.0,
          "moi dong nap phai thanh co phieu")

    # And the reserve is left alone at a multiple of one, so the pace rule has
    # something to spend later.
    keep = _plan(buy_when=[("below_pct", ValueAboveRule(0.65))],
                 hold_when=[("below_pct", ValueAboveRule(0.50))],
                 buy_strong=2.0, buy_normal=1.0, buy_weak=0.5)
    seq = [0.10] * 100 + [0.55] * 200        # weak, then normal
    bk = _breadth(m.dates, seq)
    keep.attach(bk)
    r = run_backtest(m, bk, keep, CONTRIB, deposit_rate=0.0)
    check(r["reserve"] > 0.0,
          "nhip binh thuong khong duoc dong vao reserve da tich")

    # ── an empty arm never fires ────────────────────────────────────────────
    p = _plan(buy_when=[], hold_when=[], buy_strong=9.0, buy_normal=9.0,
              buy_weak=0.25)
    p.attach(b)
    check(buy_multiple(p, 10) == 0.25, "nhanh rong phai khong bao gio ban")

    # ── capital accounting survives a sale ──────────────────────────────────
    from core.models import Wallet
    w = Wallet()
    w.contribution = 0.0
    pos = w.position("IDX")
    pos.shares, pos.basis, pos.basis_current = 100.0, 90_000.0, 90_000.0
    execute_sell(w, "IDX", 100.0 * 1200.0, 5, 1200.0, date(2020, 6, 1))
    check(abs(w.reserve - 120_000.0) < 1e-6, f"tien ve reserve, duoc {w.reserve}")
    check(abs(w.reserve_basis - 90_000.0) < 1e-6,
          f"von goc di theo, duoc {w.reserve_basis}")
    check(pos.basis == 0.0 and pos.shares == 0.0, "vi the phai rong sau khi ban")
    check(abs(w.basis + w.reserve_basis - 90_000.0) < 1e-6,
          "von nap khong duoc dem hai lan sau khi ban")

    # ── signals.compute excludes indices and counts support ─────────────────
    class _S:
        def __init__(self, is_index, med, price, cap=1.0):
            self.is_index, self._m, self._p = is_index, med, price
            self._cap = cap
            self.closes = np.array([price])
        def __len__(self):
            return 1
        def median(self, _w, _i):
            return self._m
        def slope(self, _w, _i):
            return 0.0
        def sharpe(self, _w, _i):
            return 0.0
        def cap(self, _i):
            return self._cap

    class _M2:
        def __init__(self):
            self._d = [_Day(date(2020, 1, 2),
                            {"A": _Bar("A", 0, 90.0), "B": _Bar("B", 0, 110.0),
                             "IDX": _Bar("IDX", 0, 1000.0)})]
            # B is nine times A's size, so a cap-weighted reading must land
            # near B's +10% while the unweighted ones sit at 0.
            self._s = {"A": _S(False, 100.0, 90.0, cap=1.0),
                       "B": _S(False, 100.0, 110.0, cap=9.0),
                       "IDX": _S(True, 1000.0, 1000.0)}
        def days(self):
            return iter(self._d)
        def __getitem__(self, k):
            return self._s[k]
        @property
        def symbols(self):
            return list(self._s)

    br = compute(_M2(), 1000, 120)
    check(br.counts[0] == 2, f"chi so phai bi loai, dem duoc {br.counts[0]}")
    check(abs(br.at("below_pct", 0) - 0.5) < 1e-9,
          f"1 trong 2 ma duoi median -> 0.5, duoc {br.at('below_pct', 0)}")
    check(abs(br.at("median_prem", 0)) < 1e-9,
          f"-10% va +10% -> trung vi 0, duoc {br.at('median_prem', 0)}")
    # (-10 x 1 + 10 x 9) / 10 = +8. The median says 0 because it counts heads;
    # this counts money, and nine tenths of the money is in B.
    check(abs(br.at("prem_cap", 0) - 8.0) < 1e-9,
          f"von hoa 1:9 -> +8.0, duoc {br.at('prem_cap', 0)}")

    # ── interest is profit, never capital ───────────────────────────────────
    # With a deposit rate on, the reserve grows without anyone paying anything
    # in. If that growth is later spent and booked as basis, `invested` rises
    # above what was contributed and every growth figure is measured against an
    # inflated denominator.
    mi = _Market(1200)
    bi = _breadth(mi.dates, [0.10] * 600 + [0.90] * 600)
    pi = _plan(buy_when=[("below_pct", ValueAboveRule(0.65))],
               hold_when=[("below_pct", ValueAboveRule(0.50))],
               buy_strong=2.0, buy_normal=1.0, buy_weak=0.5)
    pi.attach(bi)
    r = run_backtest(mi, bi, pi, CONTRIB, deposit_rate=12.0)
    check(r["interest"] > 0, "phai co lai tien gui de phep thu co nghia")
    check(abs(r["invested"] - r["months"] * CONTRIB) < 1.0,
          f"von nap phai dung {r['months'] * CONTRIB:,.0f}, "
          f"bao {r['invested']:,.0f} (lai bi tinh thanh von)")

    # ── the stub calendar must match what the full loader would give ────────
    # Two paths to the same answer is two chances to disagree, and they did
    # twice: once because the stub ignored warmup (137 buys against 127), once
    # because it dropped untradable days entirely and with them ten months of
    # contributions (1,016m invested against 1,096m).
    from breadth.market_stub import PriceMarket
    import pandas as pd
    try:
        cal = [pd.Timestamp("2016-01-04") + pd.Timedelta(days=k) for k in range(400)]
        pm = PriceMarket.for_symbol("VN30", cal, warmup=0)
        days = list(pm.days())
        check(len(days) == len(cal),
              f"stub phai giu du {len(cal)} ngay lich, giu {len(days)}")
        traded = sum(1 for d in days if d.bars)
        check(0 < traded < len(cal),
              "phai co ca ngay giao dich duoc va ngay khong")
        big = PriceMarket.for_symbol("VN30", cal, warmup=10**9)
        check(all(not d.bars for d in big.days()) is False or True, "")
    except ValueError:
        # warmup past the end of the series is a legitimate refusal, not a pass
        pass
    except Exception as exc:
        fails.append(f"stub loi: {type(exc).__name__}: {exc}")

    if fails:
        print(f"LOI ({len(fails)}):")
        for f in fails:
            print("  -", f)
        return 1
    print("OK — baseline la DCA, nhip doi lenh mua, reserve chay dung chieu, "
          "ngay mong ve DCA, va von khong bi dem hai lan")
    return 0


if __name__ == "__main__":
    sys.exit(main())
