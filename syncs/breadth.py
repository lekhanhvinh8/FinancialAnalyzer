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

MORE THAN ONE BASKET, AND WHY THE NAMES MATTER

  breadth_signals has always been keyed by `universe`, and only ever held one
  value. That one was called "all" while actually being every stock MINUS VIC
  and VIX -- so a reader asking the database for the market got a basket missing
  two of the largest companies on it, with nothing in the name to say so.

  BASKETS below is the list, and core.breadth_calc.universe_key builds each name
  from what the basket is: "all" is every stock, "all-VIC-VIX" is every stock
  without those two. Adding a basket is one entry here.

  One LOAD serves them all. Loading the market is four minutes and computing one
  basket is twelve seconds, so the second basket is nearly free -- compute()
  takes a `skip` set rather than being handed a smaller market.

FINGERPRINTED, LIKE zdev, AND FOR THE SAME REASON

  Prices are re-fetched from 2012 and INSERT OR REPLACE'd on every run, so a
  corporate action can rewrite years of history behind our back. Asking the
  output table what it holds cannot see that; asking the INPUT can.

  The fingerprint hashes, for every symbol in the basket, its name and a hash of
  its close series. That covers all three ways the answer can change:

      a series was revised   -> that symbol's hash changes
      a series grew          -> that symbol's hash changes
      the basket changed     -> the list of names changes

  One fingerprint per basket, so a new basket rebuilds only itself.

  NO APPEND-ONLY PATH, deliberately. zdev has one because its output for a date
  depends on that symbol alone, so appended dates touch only appended rows. Here
  a new symbol rewrites history, and separating "only dates were appended to
  every symbol and no symbol is new" from the general case would be a second
  code path guarding a computation that costs twelve seconds once the market is
  loaded.

WHAT IS LOADED

  Only what the STORED signals read: the 1000-bar window, and no slope windows.
  mean_slope is computed for breadth/'s own strategy and never stored, so
  loading the slope series here would spend three minutes on a column this step
  discards. That is the difference between a 261-second load and a 450-second
  one, measured.
"""

import database as db
from core.breadth_calc import (STORED, compute, fingerprint, save_to_db,
                               universe_key, variant)
from core.market import Market
from core.universe import resolve

# The configuration that decides the numbers. Kept here rather than imported
# from breadth/config.py: syncs/ may not import a method, and these are the
# database's settings, not a strategy's.
WINDOW = 1000
MIN_ROWS = 0

# Every basket that gets stored, as (spec, excluded). The name each is filed
# under comes from universe_key, so it always describes the basket.
#
#   all           every stock in the database
#   all-VIC-VIX   the same, without the two symbols single/multi_signal keeps
#                 out of its RESULT aggregates. That exclusion has a reason --
#                 VIX was ~30% of total gains, VIC the mirror on the loss side --
#                 but the reason is about averaging results, not about measuring
#                 a market, and it was copied here without one of its own. Both
#                 are stored so the choice is a config setting rather than a
#                 property of the data.
#
# Adding another is one line: ("vn30", ()) would measure breadth over the large
# caps only.
BASKETS = [
    ("all", ()),
    ("all", ("VIC", "VIX")),
]

SLOPE_WINDOW = 120   # reaches compute(); no STORED signal reads it

_KIND = "breadth"


def _fp_variant() -> str:
    """One fingerprint row per window; the basket is the `symbol` column."""
    return f"w{WINDOW}"


def baskets() -> dict:
    """{universe key: [symbols]} for every basket this step maintains."""
    return {universe_key(spec, exc): sorted(resolve(spec, exc))
            for spec, exc in BASKETS}


def is_breadth_current(key: str = None) -> bool:
    """True when every basket (or the named one) matches what is stored."""
    for name, syms in baskets().items():
        if key is not None and name != key:
            continue
        stored = db.load_sync_fingerprint(_KIND, name, _fp_variant())
        if stored is None or stored != fingerprint(syms, WINDOW):
            return False
    return True


def sync_breadth(override: bool = False, quiet: bool = False) -> dict:
    """
    Recompute each basket's signals and write them, skipping any whose inputs
    are unchanged.

    override : rebuild whatever the fingerprints say -- which is what a change
               to core/breadth_calc.py needs, since the hash tracks the input
               and cannot see a new formula.

    Returns {"status": ..., "baskets": {name: {...}}}.
    """
    want = baskets()
    todo, fps = {}, {}
    for name, syms in want.items():
        fps[name] = fingerprint(syms, WINDOW)
        stored = db.load_sync_fingerprint(_KIND, name, _fp_variant())
        if override or stored != fps[name]:
            todo[name] = (syms, "forced" if override else
                          "first run" if stored is None else "inputs changed")

    if not todo:
        if not quiet:
            print(f"  [breadth] up to date ({len(want)} baskets: "
                  f"{', '.join(want)})")
        return {"status": "skipped", "baskets": {}}

    # One load covering every basket that needs rebuilding; each basket then
    # skips what is not in it.
    every = sorted({s for syms, _ in todo.values() for s in syms})
    if not quiet:
        for name, (syms, why) in sorted(todo.items()):
            print(f"  [breadth] rebuilding {name} — {why} ({len(syms)} symbols)")
        print(f"  [breadth] loading {len(every)} symbols once for "
              f"{len(todo)} basket(s)")
    market = Market.load(every, {WINDOW}, min_rows=MIN_ROWS)

    out = {}
    for name, (syms, _) in sorted(todo.items()):
        series = compute(market, WINDOW, SLOPE_WINDOW,
                         skip=set(every) - set(syms))
        # override=True on the write: a rebuild replaces what was there. Every
        # date is rewritten, not only new ones, because a changed input can move
        # any row.
        written = save_to_db(series, name, WINDOW, override=True)
        # Stored only after a successful write, so a crash halfway leaves the
        # fingerprint stale and the next run rebuilds rather than trusting a
        # partial table.
        db.save_sync_fingerprint(_KIND, name, _fp_variant(), fps[name])
        rows = sum(r["saved"] for r in written.values())
        out[name] = {"symbols": len(syms), "rows": rows,
                     "dates": len(series.dates),
                     "last_date": str(series.dates[-1])[:10],
                     "variants": sorted(written)}
        if not quiet:
            for v, r in sorted(written.items()):
                print(f"  [breadth] {name}/{v}: {r['saved']:,} rows "
                      f"({r['signals']} signals x {r['dates']} dates)")
    return {"status": "rebuilt", "baskets": out, "stored_signals": len(STORED)}
