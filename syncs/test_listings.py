"""
The pre-listing floor is applied where the sync path actually reads it.

WHY A TEST AND NOT JUST THE DICT

  The source returns the fictitious rows, so deleting them from the database
  fixes nothing on its own — the next sync writes them straight back. The whole
  correction rests on trim_to_listing being called inside _sync_one BEFORE the
  frame is used for anything.

  A dict that nobody calls looks exactly like a dict that everybody calls, so
  this checks the wiring, not the data: that prices.py imports it, that the call
  sits ahead of the first read of the frame, and that the trim itself keeps the
  boundary date and drops what precedes it.

Run with:  python -m syncs.test_listings
"""

import inspect
import sys

import pandas as pd

from syncs import prices
from syncs.seeds.listings import LISTED_FROM, listing_floor, trim_to_listing


def main() -> int:
    fails = []

    # ── the trim itself ──────────────────────────────────────────────────────
    idx = pd.to_datetime(["2011-11-10", "2017-07-13", "2018-05-16",
                          "2018-05-17", "2020-01-02"])
    df = pd.DataFrame({"close": [8410, 8410, 8410, 30990, 25000]}, index=idx)

    kept = trim_to_listing("VHM", df)
    if list(kept.index.strftime("%Y-%m-%d")) != ["2018-05-17", "2020-01-02"]:
        fails.append(f"VHM: giu sai {list(kept.index.strftime('%Y-%m-%d'))}")

    # Inclusive on the floor: the listing day is real and must survive.
    if "2018-05-17" not in set(kept.index.strftime("%Y-%m-%d")):
        fails.append("VHM: ngay niem yet bi cat, phai giu lai")

    # A symbol with no floor is untouched — that is every symbol but the few
    # listed, and getting it wrong would silently truncate the whole basket.
    if len(trim_to_listing("FPT", df)) != len(df):
        fails.append("FPT: bi cat du khong co floor")
    if listing_floor("FPT") is not None:
        fails.append("FPT: khong duoc co floor")

    if trim_to_listing("VHM", pd.DataFrame()) is not None:
        empty = trim_to_listing("VHM", pd.DataFrame())
        if empty is None or not empty.empty:
            fails.append("khung rong phai tra ve khung rong")

    # ── the wiring ───────────────────────────────────────────────────────────
    src = inspect.getsource(prices._sync_one)
    if "trim_to_listing" not in src:
        fails.append("prices._sync_one khong goi trim_to_listing")
    else:
        call = src.index("trim_to_listing(sym")
        # Everything that consumes the frame must come after the trim. If any of
        # these ran first it would be reading the fictitious rows.
        for marker in ("df.empty", "load_daily_prices", "detect_adjustment"):
            at = src.find(marker)
            if 0 <= at < call:
                fails.append(f"prices._sync_one doc `{marker}` TRUOC khi trim")

    for sym, floor in LISTED_FROM.items():
        if not (len(floor) == 10 and floor[4] == floor[7] == "-"):
            fails.append(f"{sym}: floor '{floor}' khong phai ISO date")

    if fails:
        print(f"LOI ({len(fails)}):")
        for f in fails:
            print("  -", f)
        return 1
    print(f"OK — {len(LISTED_FROM)} floor, trim dung bien, va prices.py goi no truoc "
          f"moi cho doc khung")
    return 0


if __name__ == "__main__":
    sys.exit(main())
