"""
Sync the breadth_signals table: the whole basket reduced to one row per day.

WHY THIS STEP LOOKS DIFFERENT FROM THE OTHER SEVEN

  Every other step is per symbol. This one is CROSS-SECTIONAL: one row is a
  statistic over every symbol trading that day, so there is no "sync FPT's
  breadth". It runs once, after the per-symbol steps, and it needs those steps
  to have finished -- the premium a symbol contributes is read from its
  range_stats.

  That also means the output changes RETROACTIVELY in a way no per-symbol step
  does. A symbol listing in 2018 joins the cross-section from its listing date
  on, which moves every row from 2018 onwards even though nothing about the
  older symbols changed. So "resume from the last stored date" is not a correct
  incremental rule here, and this step does not offer one.

FINGERPRINTED, LIKE zdev, AND FOR THE SAME REASON

  Prices are re-fetched from 2012 and INSERT OR REPLACE'd on every run, so a
  corporate action can rewrite years of history behind our back. Asking the
  output table what it holds cannot see that; asking the INPUT can.

  The fingerprint hashes, for every symbol in the universe, its symbol name and
  a hash of its close series. That covers all three ways the answer can change:

      a series was revised   -> that symbol's hash changes
      a series grew          -> that symbol's hash changes
      the universe changed   -> the list of names changes

  Match means every input is byte-identical to the run that produced what is
  stored, so there is nothing to do. No match means rebuild.

  NO APPEND-ONLY PATH, deliberately. zdev has one because its output for a date
  depends on that symbol alone, so appended dates touch only appended rows. Here
  a new symbol rewrites history, and separating "only dates were appended to
  every symbol and no symbol is new" from the general case would be a second
  code path guarding a computation that costs twelve seconds once the market is
  loaded. The load is the cost, and an incremental path would still have to
  load.

WHAT IS LOADED

  Only what the STORED signals read: the 1000-bar window, and no slope windows.
  mean_slope is computed for breadth/'s own strategy and never stored, so
  loading the slope series here would spend three minutes on a column this step
  discards. That is the difference between a 261-second load and a 450-second
  one, measured.
"""

import database as db
from core.breadth_calc import (STORED, compute, fingerprint,
                               save_to_db, variant)
from core.market import Market
from core.universe import resolve

# The configuration that decides the numbers. Kept here rather than imported
# from breadth/config.py: syncs/ may not import a method, and these are the
# database's settings, not a strategy's.
UNIVERSE = "all"
WINDOW = 1000
EXCLUDE = ["VIX", "VIC"]
MIN_ROWS = 0

# slope_window reaches compute() but no STORED signal reads it, so it cannot
# change what is written. Passed as the value breadth/config.py uses so the two
# agree if a slope signal is ever stored.
SLOPE_WINDOW = 120

_KIND = "breadth"


def _fingerprint_variant() -> str:
    """One fingerprint row per configuration that changes the output."""
    return f"{UNIVERSE}_w{WINDOW}"


def is_breadth_current(symbols: list[str] | None = None) -> bool:
    """True when the stored fingerprint matches the inputs as they stand now."""
    syms = symbols if symbols is not None else resolve(UNIVERSE, EXCLUDE)
    stored = db.load_sync_fingerprint(_KIND, UNIVERSE, _fingerprint_variant())
    return stored is not None and stored == fingerprint(syms, WINDOW)


def sync_breadth(override: bool = False, quiet: bool = False) -> dict:
    """
    Recompute the basket signals and write them, unless the inputs are unchanged.

    override : rebuild whatever the fingerprint says -- which is what a change
               to core/breadth_calc.py needs, since the hash tracks the input
               and cannot see a new formula.

    Returns {"status": "skipped"|"rebuilt", ...}.
    """
    symbols = resolve(UNIVERSE, EXCLUDE)
    fp = fingerprint(symbols, WINDOW)
    stored = db.load_sync_fingerprint(_KIND, UNIVERSE, _fingerprint_variant())

    if not override and stored == fp:
        if not quiet:
            print(f"  [breadth] up to date ({len(symbols)} symbols)")
        return {"status": "skipped", "symbols": len(symbols)}

    if not quiet:
        why = ("forced" if override else
               "first run" if stored is None else "inputs changed")
        print(f"  [breadth] rebuilding — {why} ({len(symbols)} symbols)")

    market = Market.load(symbols, {WINDOW}, min_rows=MIN_ROWS)
    series = compute(market, WINDOW, SLOPE_WINDOW)

    # override=True on the write: a rebuild replaces what was there. Every date
    # is rewritten, not only new ones, because a changed input can move any row.
    written = save_to_db(series, UNIVERSE, WINDOW, override=True)
    rows = sum(r["saved"] for r in written.values())

    # Stored only after a successful write, so a crash halfway leaves the
    # fingerprint stale and the next run rebuilds rather than trusting a
    # partial table.
    db.save_sync_fingerprint(_KIND, UNIVERSE, _fingerprint_variant(), fp)

    if not quiet:
        for v, r in sorted(written.items()):
            print(f"  [breadth] {v}: {r['saved']:,} rows "
                  f"({r['signals']} signals x {r['dates']} dates)")
    return {"status": "rebuilt", "symbols": len(symbols), "rows": rows,
            "dates": len(series.dates), "last_date": str(series.dates[-1])[:10],
            "variants": sorted(written), "stored_signals": len(STORED)}
