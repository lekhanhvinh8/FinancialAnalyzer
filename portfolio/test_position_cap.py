"""
The concentration cap: eligibility, sizing, and the arithmetic that joins them.

WHY THIS IS TESTED AND THE OTHER RULES ARE NOT

  A broken rule signature raises. A broken position cap does not: it silently
  sizes purchases wrongly and the run completes, prints a number, and looks
  exactly like a run that worked. The only way to know the ceiling held is to
  assert on it.

  So this checks the PROPERTY the cap exists to guarantee -- that no buy leaves a
  position above the ceiling -- rather than the particular arithmetic used to get
  there.

Run with:  python -m portfolio.test_position_cap
"""

import sys

from portfolio.allocator import EqualSplitAllocator, QuotaAllocator
from portfolio.engine import (apply_cooldown, apply_position_cap,
                              position_headroom)
from portfolio.models import Candidate, Wallet


def _wallet(holdings: dict, prices: dict, cash=0.0, reserve=0.0) -> Wallet:
    w = Wallet()
    w.contribution = cash
    w.reserve = reserve
    for sym, value in holdings.items():
        p = w.position(sym)
        p.shares = value / prices[sym]
        p.basis = p.basis_current = value
    return w


def _cands(*syms):
    return [Candidate(symbol=s, index=0, price=10_000.0, score=0.0) for s in syms]


def main() -> int:
    fails = []

    def check(cond, msg):
        if not cond:
            fails.append(msg)

    PRICES = {"A": 10_000.0, "B": 10_000.0, "C": 10_000.0, "D": 10_000.0}

    # ── headroom arithmetic ─────────────────────────────────────────────────
    # Portfolio 1,000: A worth 300, cash 700. At 10% the ceiling is 100, so A is
    # already 200 over and B may take the full 100.
    w = _wallet({"A": 300.0}, PRICES, cash=700.0)
    room = position_headroom(w, _cands("A", "B"), PRICES, 10.0, w.contribution)
    check(room["A"] == 0.0, f"A het room phai la 0, duoc {room['A']}")
    check(abs(room["B"] - 100.0) < 1e-6, f"B phai co 100, duoc {room['B']}")

    # Cash counts in the denominator; without it the total would be 300 and the
    # answers would differ.
    kept, room = apply_position_cap(w, _cands("A", "B"), PRICES, 10.0, w.contribution)
    check([c.symbol for c in kept] == ["B"], f"chi B duoc giu, duoc {[c.symbol for c in kept]}")

    # Off means off.
    kept, room = apply_position_cap(w, _cands("A", "B"), PRICES, 0.0, w.contribution)
    check(len(kept) == 2 and room is None, "max_pct=0 phai tat han")

    # An empty wallet still admits everyone: the total is the cash.
    w0 = _wallet({}, PRICES, cash=8_000_000.0)
    r0 = position_headroom(w0, _cands("A"), PRICES, 10.0, w0.contribution)
    check(abs(r0["A"] - 800_000.0) < 1e-6,
          f"vi rong 8tr, tran 10% phai la 800k, duoc {r0['A']}")

    # ── equal split respects the ceiling and refills the others ─────────────
    alloc = EqualSplitAllocator(top_k=4)
    limits = {"A": 10.0, "B": 1e9, "C": 1e9, "D": 1e9}
    got = dict((c.symbol, v) for c, v in alloc.allocate(400.0, _cands("A", "B", "C", "D"), limits))
    check(abs(got.get("A", 0) - 10.0) < 1e-6, f"A phai bi chan o 10, duoc {got.get('A')}")
    check(abs(sum(got.values()) - 400.0) < 1e-6,
          f"phai tieu het 400, tieu {sum(got.values())}")
    others = [v for s, v in got.items() if s != "A"]
    check(max(others) - min(others) < 1e-6, "ba ma con lai phai chia deu phan du")

    # Everything capped: spend only what the ceilings allow, not more.
    got = dict((c.symbol, v) for c, v in
               alloc.allocate(400.0, _cands("A", "B"), {"A": 10.0, "B": 20.0}))
    check(abs(sum(got.values()) - 30.0) < 1e-6,
          f"tran tong 30, tieu {sum(got.values())}")

    # No limits at all behaves exactly as before.
    got = dict((c.symbol, v) for c, v in alloc.allocate(400.0, _cands("A", "B"), None))
    check(abs(got["A"] - 200.0) < 1e-6 and abs(got["B"] - 200.0) < 1e-6,
          "khong co limits thi phai chia deu nhu cu")

    # ── quota allocator ─────────────────────────────────────────────────────
    q = QuotaAllocator(quota_pct=20.0, min_split=20.0, top_k=5)
    got = dict((c.symbol, v) for c, v in
               q.allocate(100.0, _cands("A", "B", "C"), {"A": 5.0, "B": 1e9, "C": 1e9}))
    check(abs(got.get("A", 0) - 5.0) < 1e-6, f"quota: A bi chan o 5, duoc {got.get('A')}")
    check(abs(got.get("B", 0) - 20.0) < 1e-6,
          f"quota: B van lay dung quota 20, duoc {got.get('B')} (khong duoc phong len)")

    # Below min_split the pot goes to the best name that can hold it, not to a
    # blocked one.
    got = q.allocate(10.0, _cands("A", "B"), {"A": 0.0, "B": 1e9})
    check(len(got) == 1 and got[0][0].symbol == "B" and abs(got[0][1] - 10.0) < 1e-6,
          f"duoi min_split phai roi sang B, duoc {[(c.symbol, v) for c, v in got]}")

    # ── the property that matters ───────────────────────────────────────────
    # Whatever the split, no position ends the day above the ceiling.
    for cash in (1_000.0, 50_000.0, 8_000_000.0):
        for held in ({}, {"A": 500.0}, {"A": 5_000.0, "B": 100.0}):
            w = _wallet(held, PRICES, cash=cash)
            cands = _cands("A", "B", "C")
            kept, room = apply_position_cap(w, cands, PRICES, 10.0, w.contribution)
            total = sum(p.shares * PRICES[p.symbol] for p in w.positions.values()) + cash
            ceiling = total * 0.10
            for c, amt in EqualSplitAllocator(top_k=3).allocate(cash, kept, room):
                pos = w.positions.get(c.symbol)
                before = pos.shares * PRICES[c.symbol] if pos else 0.0
                if before + amt > ceiling + 1e-6:
                    fails.append(
                        f"vuot tran: {c.symbol} {before:.0f}+{amt:.0f} > {ceiling:.0f} "
                        f"(cash {cash:.0f}, held {held})")

    # ── cooldown ────────────────────────────────────────────────────────────
    # It only ever removes names, and it must remove the RIGHT ones: a symbol
    # never acted on (index -1) is always eligible, one acted on exactly `bars`
    # ago is eligible again, one bar short is not.
    w = Wallet()
    w.position("A").last_buy_index = 100
    w.position("B").last_buy_index = 50
    # C untouched: last_buy_index stays -1.
    cands = [Candidate(symbol=s, index=150, price=1.0, score=0.0)
             for s in ("A", "B", "C")]

    check([c.symbol for c in apply_cooldown(w, cands, 0, "last_buy_index")]
          == ["A", "B", "C"], "cooldown=0 phai tat han")
    check([c.symbol for c in apply_cooldown(w, cands, 50, "last_buy_index")]
          == ["A", "B", "C"], "dung 50 bar truoc phai duoc mua lai (>=)")
    check([c.symbol for c in apply_cooldown(w, cands, 51, "last_buy_index")]
          == ["B", "C"], "thieu 1 bar thi A phai bi loai")
    check([c.symbol for c in apply_cooldown(w, cands, 101, "last_buy_index")]
          == ["C"], "chi C (chua mua bao gio) con lai")

    # The two arms read different fields and must not see each other's history.
    w2 = Wallet()
    w2.position("A").last_reinvest_index = 149
    c2 = [Candidate(symbol="A", index=150, price=1.0, score=0.0)]
    check(len(apply_cooldown(w2, c2, 100, "last_buy_index")) == 1,
          "cooldown mua khong duoc doc lich su reinvest")
    check(len(apply_cooldown(w2, c2, 100, "last_reinvest_index")) == 0,
          "cooldown reinvest phai doc dung truong cua no")

    if fails:
        print(f"LOI ({len(fails)}):")
        for f in fails:
            print("  -", f)
        return 1
    print("OK — headroom, hai allocator, cooldown, va bat bien "
          "'khong lenh nao vuot tran'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
