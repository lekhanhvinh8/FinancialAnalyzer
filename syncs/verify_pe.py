"""
Independent check of the stored P/E (pe_ratios) for stocks and indices.

Two checks, each catching a different kind of error:

  data       Profit quarters missing between a stock's first and last quarter,
             and quarters where the DB disagrees with the raw CafeF file. Raw
             is not automatically right — CafeF has served a cumulative
             half-year figure as a quarter — so this only lists them.

  recompute  Rebuilds P/E with its own code — nothing from syncs/calculate.py —
             from the DB's price, share and profit rows, and compares it with
             pe_ratios on sample dates (the last trading day of every quarter
             and of every mid-quarter month, plus the latest date). Catches
             formula errors. TTM here demands four consecutive quarters: a
             missing quarter makes TTM missing instead of summing whatever four
             rows happen to be there.

    python syncs/verify_pe.py                # everything
    python syncs/verify_pe.py FPT VN30       # just these symbols

No external comparison: the free vnstock tier has no usable P/E history.
KBS's ratio table labels its columns wrongly (its "2026-Q2" EPS for BSR is an
older period's) and VCI's stops at 2018.

Report only; it writes nothing.
"""

import sys, json, sqlite3, bisect
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

from database import DB_PATH   # the path only — every read below is plain SQL

RAW_DIR = ROOT / "data" / "raw" / "cafef"

# Stored symbol -> (index_members id, members left out)
INDICES = {
    "VN30":      ("vn30",      set()),
    "VN30EXVIC": ("vn30",      {"VIC"}),
    "VNDIAMOND": ("vndiamond", set()),
    "VNFINLEAD": ("vnfinlead", set()),
}

REL_TOL = 0.005   # recompute: same definition, only rounding may differ
SHOW    = 5       # mismatching dates printed per symbol


# ── Data, read directly ───────────────────────────────────────────────────────

def _diff(a, b):
    """Relative gap; inf when only one side exists, None when neither does."""
    if a is None or b is None:
        return None if a is b else float("inf")
    return abs(a - b) / abs(b)


def _q_end(y: int, q: int) -> str:
    return {1: f"{y}-03-31", 2: f"{y}-06-30", 3: f"{y}-09-30", 4: f"{y}-12-31"}[q]


def _prev(y: int, q: int) -> tuple[int, int]:
    return (y, q - 1) if q > 1 else (y - 1, 4)


def _next(y: int, q: int) -> tuple[int, int]:
    return (y, q + 1) if q < 4 else (y + 1, 1)


def _first_nonzero(*vals):
    return next((float(v) for v in vals if v is not None and v == v and v != 0), None)


def raw_profit(sym: str) -> dict:
    """{(year, quarter): profit} straight from the CafeF JSON, 14 -> 13 -> 10."""
    path = RAW_DIR / f"{sym}_KQKD.json"
    if not path.exists():
        return {}
    sections = json.loads(path.read_text(encoding="utf-8"))["value"]["data"]
    out = {}
    for q in sections[0]["data"] if sections else []:
        v = {it["code"]: it.get("value") for it in q["data"]}
        p = _first_nonzero(v.get("KQKD_14"), v.get("KQKD_13"), v.get("KQKD_10"))
        if p is not None:
            out[(int(q["year"]), int(q["quater"]))] = p
    return out


class Stock:
    """Everything one stock's P/E needs, with point-in-time lookups."""

    def __init__(self, con, sym: str):
        self.sym = sym
        self.prices = dict(con.execute(
            "SELECT date, close FROM daily_prices WHERE symbol=?", (sym,)))

        rows = con.execute(
            "SELECT year, quarter, shares, kqkd_14, kqkd_13, kqkd_10 "
            "FROM quarterly_fundamentals WHERE symbol=? ORDER BY year, quarter", (sym,)).fetchall()
        shares = [(_q_end(y, q), s) for y, q, s, *_ in rows if s]
        self.share_dates  = [d for d, _ in shares]
        self.share_values = [s for _, s in shares]
        # Today's count, used on every date when present: prices are adjusted
        # onto today's share basis (see syncs/calculate.py).
        cur = con.execute("SELECT shares FROM share_snapshots WHERE symbol=?"
                          " ORDER BY as_of DESC LIMIT 1", (sym,)).fetchone()
        self.current_shares = cur[0] if cur else None

        self.profit = {(y, q): p for y, q, _, *k in rows
                       if (p := _first_nonzero(*k)) is not None}
        self.quarters = sorted(self.profit)
        self.q_dates  = [_q_end(y, q) for y, q in self.quarters]

        # (quarter, raw, db). A quarter only the DB has is a manual patch
        # (data/raw/exception), so only quarters the raw file has are compared.
        self.raw_vs_db = [(k, v, self.profit.get(k)) for k, v in sorted(raw_profit(sym).items())
                          if _diff(self.profit.get(k), v) > 1e-6]

    def gaps(self) -> list:
        out = []
        if self.quarters:
            yq = self.quarters[0]
            while yq < self.quarters[-1]:
                if yq not in self.profit:
                    out.append(yq)
                yq = _next(*yq)
        return out

    def ttm(self, d: str):
        """(ttm, note): four consecutive quarters ending at the latest one by d."""
        i = bisect.bisect_right(self.q_dates, d) - 1
        if i < 0:
            return None, "no quarter yet"
        window = [self.quarters[i]]
        for _ in range(3):
            window.append(_prev(*window[-1]))
        missing = sorted(k for k in window if k not in self.profit)
        if missing:
            return None, "missing " + ", ".join(f"{y}Q{q}" for y, q in missing)
        return sum(self.profit[k] for k in window), ""

    def shares(self, d: str):
        if self.current_shares is not None:
            return self.current_shares
        if not self.share_values:
            return None
        i = bisect.bisect_right(self.share_dates, d) - 1
        return self.share_values[max(i, 0)]   # before the first quarter: earliest known

    def values(self, d: str):
        """(price, shares, ttm, note) on d; any of the first three may be None."""
        ttm, note = self.ttm(d)
        return self.prices.get(d), self.shares(d), ttm, note

    def pe(self, d: str):
        price, shares, ttm, note = self.values(d)
        if ttm is not None and ttm <= 0:
            return None, "TTM <= 0"
        if price is None or shares is None or ttm is None:
            return None, note
        return price * shares / ttm, ""


def members_on(con, index_id: str, d: str) -> list[str]:
    return [r[0] for r in con.execute(
        "SELECT member_symbol FROM index_members WHERE index_symbol=? AND date_added<=? "
        "AND (date_removed IS NULL OR date_removed>?)", (index_id, d, d))]


def index_pe(con, stocks: dict, sym: str, d: str):
    """(pe, member_count) — the same aggregate rule as the stored series."""
    index_id, excluded = INDICES[sym]
    members = [m for m in members_on(con, index_id, d) if m not in excluded]
    mcap = profit = 0.0
    count = 0
    for m in members:
        if m not in stocks:
            continue
        price, shares, ttm, _ = stocks[m].values(d)
        if price is None or shares is None or ttm is None or ttm <= 0:
            continue
        mcap += price * shares
        profit += ttm
        count += 1
    if count == 0 or count * 2 < len(members):
        return None, count
    return mcap / profit, count


def sample_dates(con) -> list[str]:
    """Last trading day of each quarter-end and mid-quarter month, plus the latest."""
    dates = [r[0] for r in con.execute(
        "SELECT DISTINCT p.date FROM daily_prices p JOIN symbols s ON s.symbol=p.symbol "
        "WHERE s.symbol_type='stock' ORDER BY p.date")]
    last_in_month = {}
    for d in dates:
        last_in_month[d[:7]] = d
    picked = {d for ym, d in last_in_month.items() if int(ym[5:]) in (2, 3, 5, 6, 8, 9, 11, 12)}
    return sorted(picked | {dates[-1]})


def stored(con, sym: str) -> dict:
    return {d: (pe, n) for d, pe, n in con.execute(
        "SELECT date, pe_ratio, member_count FROM pe_ratios WHERE symbol=?", (sym,))}


def _banner(text: str) -> None:
    print(f"\n{'=' * 70}\n{text}\n{'=' * 70}")


# ── Check 1: data ─────────────────────────────────────────────────────────────

def check_data(stocks: dict, targets: list[str]) -> None:
    _banner("DATA — missing profit quarters, and DB vs raw CafeF")
    syms = [t for t in targets if t in stocks]

    by_quarter = {}
    for sym in syms:
        for yq in stocks[sym].gaps():
            by_quarter.setdefault(yq, []).append(sym)
    print(f"\nMissing quarters (between each stock's first and last): "
          f"{sum(map(len, by_quarter.values()))}")
    for (y, q), who in sorted(by_quarter.items()):
        print(f"  {y}Q{q} {len(who):>3}  {' '.join(who)}")

    print("\nDB ≠ raw CafeF file (billion VND):")
    f = lambda v: f"{v / 1e9:12,.1f}" if v is not None else f"{'—':>12}"
    n = 0
    for sym in syms:
        for (y, q), raw, dbv in stocks[sym].raw_vs_db:
            print(f"  {sym:<6}{y}Q{q}  raw{f(raw)}   db{f(dbv)}")
            n += 1
    print(f"  {n} quarter(s)" if n else "  none")


# ── Check 2: recompute ────────────────────────────────────────────────────────

def check_recompute(con, stocks: dict, targets: list[str], dates: list[str]) -> None:
    _banner(f"RECOMPUTE — {len(dates)} sample dates, tolerance {REL_TOL:.1%}")
    f = lambda v: f"{v:10.2f}" if v is not None else f"{'—':>10}"
    bad_symbols = 0
    for sym in targets:
        have = stored(con, sym)
        bad = []
        for d in dates:
            if sym in INDICES:
                mine, n = index_pe(con, stocks, sym, d)
                theirs, their_n = have.get(d, (None, None))
                note = "" if their_n in (None, n) else f"members {n} vs {their_n}"
            else:
                if d not in stocks[sym].prices:
                    continue
                mine, note = stocks[sym].pe(d)
                theirs = have.get(d, (None, None))[0]
            diff = _diff(mine, theirs)
            if diff is not None and diff > REL_TOL:
                bad.append((d, theirs, mine, diff, note))
        if not bad:
            continue

        bad_symbols += 1
        print(f"\n{sym}: {len(bad)} date(s) off")
        print(f"  {'date':<12}{'stored':>10}{'recomputed':>12}{'diff':>9}  note")
        for d, theirs, mine, diff, note in bad[:SHOW]:
            dtxt = "missing" if diff == float("inf") else f"{diff:.1%}"
            print(f"  {d:<12}{f(theirs)}  {f(mine)}{dtxt:>9}  {note}")
        if len(bad) > SHOW:
            print(f"  … {len(bad) - SHOW} more")
    print(f"\nRecompute: {bad_symbols} of {len(targets)} symbol(s) disagree with pe_ratios.")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]

    con = sqlite3.connect(DB_PATH)
    all_stocks = [r[0] for r in con.execute(
        "SELECT symbol FROM symbols WHERE symbol_type='stock' ORDER BY symbol")]
    stocks  = {s: Stock(con, s) for s in all_stocks}
    targets = [a.upper() for a in args] or all_stocks + list(INDICES)

    unknown = [t for t in targets if t not in stocks and t not in INDICES]
    if unknown:
        sys.exit(f"Unknown symbol(s): {', '.join(unknown)}")

    check_data(stocks, targets)
    check_recompute(con, stocks, targets, sample_dates(con))


if __name__ == "__main__":
    main()
