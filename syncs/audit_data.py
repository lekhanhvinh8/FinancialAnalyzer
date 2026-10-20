"""
Audit the stored data against its sources and against itself, and optionally
repair what it finds.

Four checks, each catching a different way an incremental sync goes stale:

  prices   The source back-adjusts its whole history on a bonus issue, split or
           stock dividend. Our rows do not move, so the series breaks by a
           constant factor at the ex-date. sync_prices catches this at the
           moment it happens; a break that is already buried under newer rows
           is invisible to it and only shows up here.

  shares   fill_merge protects a stored quarter, so a balance sheet the source
           later revises is never picked up.

  profit   An incremental sync only adds quarters after the latest one, so a
           quarter CafeF filled in late, or a value it served as 0 before it
           had the real figure, stays missing. Compared against the raw JSON
           the last fetch saved, plus the quarters sync derived from full-year
           figures (data/raw/exception/derived_quarterly_profit.csv) — offline.
           A source row is used only where it agrees with what is stored; see
           syncs.profit.merge_profit.

  derived  pe_ratios stores price x shares as of when it ran. Repair the prices
           or restate the shares without recomputing it and the two drift
           apart. Offline — no API, and it is the only check that sees a repair
           that was left half-finished.

    python syncs/audit_data.py                  # report everything, touch nothing
    python syncs/audit_data.py --offline        # derived check only, no API
    python syncs/audit_data.py VHM MBB          # just these symbols
    python syncs/audit_data.py --fix            # repair what it found

Reporting is the default. --fix writes to the DB.
"""

import sys, os, time
from datetime import date as _date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# This runs for tens of minutes and prints as it goes. Redirected to a file
# Python would block-buffer it, so the log stays empty until the run ends —
# exactly when it stops being useful to watch.
try:
    sys.stdout.reconfigure(line_buffering=True)
except AttributeError:
    pass

import pandas as pd

import database as db
from syncs import calculate
from syncs import profit
from syncs.sources import vnstock, cafef
from syncs._helpers import PRICE_START, call_with_retry
from syncs.prices import detect_adjustment, _ADJ_TOLERANCE
from syncs.shares import _SHARES_EPS

# pe_ratios is a product of price x shares, so it should reproduce them exactly.
# Anything past rounding means it was computed against data that has since moved.
_DERIVED_TOL = 0.001

_SLEEP   = 5
_INDICES = ["vn30", "vndiamond", "vnfinlead"]



# ── Checks ────────────────────────────────────────────────────────────────────

def check_prices(sym, today):
    """Returns (factor, broken_from) when the stored series is on an old scale."""
    existing = db.load_daily_prices(sym)
    if existing.empty:
        return None
    fresh  = call_with_retry(vnstock.get_prices, sym, PRICE_START, today, label=sym)
    factor = detect_adjustment(fresh, existing)
    if factor is None:
        return None

    joined = existing.join(fresh, how="inner", lsuffix="_db", rsuffix="_api").sort_index()
    ratio  = joined["close_db"] / joined["close_api"]
    agreed = ratio[(ratio - 1).abs() <= _ADJ_TOLERANCE]
    since  = agreed.index.min().date().isoformat() if not agreed.empty else None
    return factor, since


def check_shares(sym):
    """Returns the quarters where the stored count no longer matches the source."""
    stored = db.load_shares(sym)
    if stored.empty:
        return []
    fresh = call_with_retry(vnstock.get_shares, sym, label=sym)
    if fresh is None or fresh.empty:
        return []

    have = {(int(r.year), int(r.quarter)): float(r.shares) for _, r in stored.iterrows()}
    bad  = []
    for _, r in fresh.iterrows():
        key = (int(r.year), int(r.quarter))
        if key not in have:
            continue  # a quarter we simply have not stored yet — sync handles it
        old, new = have[key], float(r.shares)
        if old > 0 and abs(new / old - 1) > _SHARES_EPS:
            bad.append((key, old, new))
    return bad


def check_profit(sym):
    """Returns (rows the raw file and the derived ledger can fill, [(quarter, reason) refused])."""
    raw     = cafef.load_raw_net_profit(sym, profit.RAW_DIR)
    derived = profit.load_derived(sym)
    if not raw.empty:   # a quarter the raw file has needs no derived stand-in
        have    = set(zip(raw.year, raw.quarter))
        derived = derived[[k not in have for k in zip(derived.year, derived.quarter)]]
    parts = [df[["year", "quarter", *profit._KQKD_COLS]] for df in (raw, derived) if not df.empty]
    if not parts:
        return pd.DataFrame(), []
    return profit.merge_profit(pd.concat(parts, ignore_index=True), db.load_net_profit(sym))


def check_derived(sym):
    """
    Returns (earliest_bad_date, n_dates) where pe_ratios disagrees with what
    price x shares says today.
    """
    pe = db.load_pe_ratios(sym)
    if pe.empty or "total_market_cap" not in pe:
        return None
    prices = db.load_daily_prices(sym)
    if prices.empty:
        return None
    fd = calculate._build_fundamental_daily(sym, prices.index)
    if fd is None:
        return None

    expected = (prices["close"] * fd["shares"]).dropna()
    stored   = pe["total_market_cap"].dropna()
    common   = expected.index.intersection(stored.index)
    common   = common[expected[common] > 0]
    if len(common) == 0:
        return None

    rel = (stored[common] / expected[common] - 1).abs()
    bad = rel[rel > _DERIVED_TOL]
    if bad.empty:
        return None
    return bad.index.min().date().isoformat(), len(bad)


def check_index(index):
    """
    Recompute the aggregate and return the earliest date it no longer lands on
    the stored value, with the worst disagreement found.

    Summing the stored member rows would be cheaper and wrong: the aggregate
    takes point-in-time membership and drops any member whose TTM profit is
    not positive, so a plain sum over today's member list disagrees with a
    correct aggregate by whatever those two rules exclude.
    """
    index_sym = index.upper()
    agg = db.load_pe_ratios(index_sym)
    if agg.empty:
        return None

    fresh = calculate.calc_pe_history(index=index, emit_members=False)
    if fresh.empty:
        return None
    now = {r["date"]: r["total_market_cap"] for _, r in fresh.iterrows()}

    # The whole series, not a recent window. A member whose prices were
    # re-adjusted moves its index across every date it was ever in, and a
    # window that has already been repaired hides exactly that: the tail agrees
    # while all the history behind it is still wrong. Recomputing is the only
    # way to know an aggregate is right, so the check costs what the repair
    # costs — which is why this is the audit and not something sync does.
    worst, earliest = 0.0, None
    for ts, row in agg.iterrows():
        day = ts.date().isoformat()
        stored = row["total_market_cap"]
        if day not in now or stored != stored or stored <= 0:
            continue
        fresh_mcap = now[day]
        if fresh_mcap is None or fresh_mcap != fresh_mcap or fresh_mcap <= 0:
            # We hold an aggregate for a date that no longer earns one.
            rel = 1.0
        else:
            rel = abs(stored / float(fresh_mcap) - 1)
        if rel > _DERIVED_TOL:
            earliest = earliest or day
            worst    = max(worst, rel)

    return (earliest, worst) if earliest else None


# ── Repair ────────────────────────────────────────────────────────────────────

def repair(findings, index_hits):
    """Run the sync steps each finding calls for. Writes to the DB."""
    from syncs import (sync_prices, sync_shares, sync_pe, sync_range_stats,
                       sync_trend_signals, sync_zdev)

    for sym, f in findings.items():
        print(f"\n{'='*60}\nRepairing {sym}\n{'='*60}")

        rebuilt_prices = bool(f.get("price"))
        if rebuilt_prices:
            sync_prices(symbols=[sym], override=True)
        if f.get("shares"):
            sync_shares(symbols=[sym], override=True)
        if f.get("profit") is not None:
            profit.save(sym, f["profit"])

        # A price re-adjustment moved the scale under every date, so there is
        # no point to resume from. Anything else spoils a tail: take the
        # earliest date any finding points at.
        if rebuilt_prices:
            since = None
        else:
            since = f.get("since")
            for (y, q), _, _ in f.get("shares", []):
                since = _earliest(since, _quarter_end_str(y, q))

        sync_pe(symbols=[sym], from_date=since)
        sync_range_stats(symbols=[sym], start=since, override=True)

        if rebuilt_prices:
            # Both read prices only — a share restatement leaves them alone.
            sync_trend_signals(symbols=[sym], start=None, override=True)
            sync_zdev(symbols=[sym])

    for index, target in index_hits.items():
        print(f"\n{'='*60}\nRepairing index {index.upper()}\n{'='*60}")
        since = None if target is True else target
        sync_pe(index=index, from_date=since)
        sync_range_stats(index=index, start=since, override=True)


def _quarter_end_str(year, quarter):
    return calculate._quarter_end(year, quarter).date().isoformat()


def _earliest(a, b):
    return b if a is None else min(a, b)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    flags   = {a for a in sys.argv[1:] if a.startswith("--")}
    args    = [a.upper() for a in sys.argv[1:] if not a.startswith("--")]
    offline = "--offline" in flags
    do_fix  = "--fix" in flags
    today   = _date.today().isoformat()
    stocks  = args or db.list_symbols(symbol_type="stock")

    mode = "offline" if offline else "source + offline"
    print(f"Auditing {len(stocks)} symbols ({mode})"
          + ("" if offline else f", ~{_SLEEP}s apart") + " …\n")

    findings, failed = {}, []

    for i, sym in enumerate(stocks, 1):
        f, notes = {}, []

        if not offline:
            try:
                res = check_prices(sym, today)
                if res:
                    f["price"], f["since"] = res[0], None
                    notes.append(f"prices {res[0]:.4g}x"
                                 + (f" from {res[1]}" if res[1] else " (whole series)"))
            except Exception as e:
                failed.append(sym); notes.append(f"price fetch failed: {str(e)[:60]}")

            try:
                bad = check_shares(sym)
                if bad:
                    f["shares"] = bad
                    notes.append("shares " + ", ".join(
                        f"{y}Q{q} {old/1e9:.3f}→{new/1e9:.3f}b" for (y, q), old, new in bad))
            except Exception as e:
                notes.append(f"shares fetch failed: {str(e)[:60]}")

        rows, refused = check_profit(sym)
        if not rows.empty:
            f["profit"] = rows
            first = rows.sort_values(["year", "quarter"]).iloc[0]
            f["since"] = _earliest(f.get("since"), _quarter_end_str(int(first.year), int(first.quarter)))
            notes.append(f"profit {len(rows)} quarter(s) to fill from raw, from "
                         f"{int(first.year)}Q{int(first.quarter)}")
        if refused:
            notes.append("profit refused " + ", ".join(f"{y}Q{q}" for (y, q), _ in refused))

        res = check_derived(sym)
        if res:
            f["since"] = _earliest(f.get("since"), res[0])
            f["derived"] = res
            notes.append(f"pe_ratios off on {res[1]} dates from {res[0]}")

        if f:
            findings[sym] = f
        print(f"  [{i:2d}/{len(stocks)}] {sym:5s} " + ("; ".join(notes) if notes else "ok"))

        if not offline and i < len(stocks):
            time.sleep(_SLEEP)

    # Which indices does this drag along?
    index_hits = {}
    for index in _INDICES:
        members = set(db.load_index_members(index)["symbol"].unique())
        hit     = members & set(findings)
        full    = any(findings[s].get("price") for s in hit)
        since   = min((findings[s]["since"] for s in hit
                       if findings[s].get("since")), default=None)
        own = check_index(index)
        if full or since or own:
            index_hits[index] = True if full else _earliest(since, own[0] if own else None)
            detail = ("member prices re-adjusted" if full else
                      f"aggregate off by up to {own[1]:.2%} from {own[0]}" if own else
                      f"member data restated from {since}")
            print(f"  index {index.upper():10s} {detail}")

    print(f"\n{'='*60}")
    print(f"symbols checked {len(stocks)}   with findings {len(findings)}"
          f"   indices affected {len(index_hits)}   fetch failures {len(failed)}")
    if failed:
        print(f"could not fetch: {' '.join(failed)} — rerun for these")

    if not findings and not index_hits:
        print("\nNothing to repair.")
        return

    if not do_fix:
        print("\nRerun with --fix to repair, or do it by hand:")
        price_syms = sorted(s for s, f in findings.items() if f.get("price"))
        if price_syms:
            print(f"  python sync.py {' '.join(price_syms)} --prices --force")
        if any("profit" in f for f in findings.values()):
            print("  (profit fills come from the raw files — only --fix writes them)")
        if findings:
            print(f"  python sync.py {' '.join(sorted(findings))} --pe --range-stats --force")
        if index_hits:
            # No CLI flag reaches an index P/E without also touching its
            # members, and lowercase is what selects the index series itself.
            print(f"  python sync.py {' '.join(index_hits)} --pe --range-stats --force")
        return

    print("\n--fix given — writing to the DB.\n")
    repair(findings, index_hits)
    print("\nRepair done. Rerun the audit to confirm.")


if __name__ == "__main__":
    main()
