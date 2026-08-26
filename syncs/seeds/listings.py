"""
Dates before which a symbol's stored price series is not real.

WHY THIS FILE HAS TO EXIST

  The price source returns history for VHM going back to November 2011. Vinhomes
  did not list until 17 May 2018, and the pre-listing block is not an early
  quotation — it is filler. 1,412 rows carrying 71 distinct prices, one of them
  held flat at 14,300 for 855 consecutive days. No traded instrument does that.

  Deleting the rows is not enough on its own, because the SOURCE returns them:
  the next sync would put every one of them back. The floor has to live
  somewhere the sync path reads, which is what this is.

WHAT IT IS NOT

  Not a general date filter, and not a place to trim data somebody dislikes. An
  entry here is a claim that the rows below it are FICTITIOUS, and it needs the
  evidence to say so — a listing date that the real series agrees with, and a
  pre-listing block that fails a basic test of being a price at all.

  Prefer fixing the collector where the collector is wrong. This is for the case
  where the upstream data is wrong and there is nowhere else to put the
  correction.
"""

# symbol -> first date on which its price series is real (ISO, inclusive).
LISTED_FROM = {
    # Vinhomes listed on HOSE 17/05/2018, and the stored series jumps from
    # 8,410 to 30,990 across that boundary — the two sides are not one series.
    "VHM": "2018-05-17",
}


def listing_floor(symbol: str):
    """First real date for `symbol`, or None if it has no recorded floor."""
    return LISTED_FROM.get(str(symbol).upper())


def trim_to_listing(symbol: str, df):
    """
    Drop rows dated before the symbol's floor.

    Takes and returns a DataFrame indexed by date. A symbol with no floor is
    returned untouched, which is every symbol but the few listed above.
    """
    floor = listing_floor(symbol)
    if floor is None or df is None or df.empty:
        return df
    keep = df.index >= floor
    dropped = int((~keep).sum())
    if dropped:
        print(f"  [listings] {symbol}: bo {dropped} dong truoc {floor} "
              f"(du lieu truoc niem yet)")
    return df[keep]
