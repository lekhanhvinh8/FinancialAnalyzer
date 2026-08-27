# Portfolio method — where this strand stopped, and why

Closed 2026-08-27. The code stays; the parameter search does not continue.

## The conclusion

**The strategy is value investing — buy good companies when the price has fallen
deeply — and this database cannot identify "good".**

The price half works. A symbol's distance below its own 1000-bar median is
computed from prices, prices are the one thing here that is clean and daily, and
the condition does what it says.

The quality half was never implemented. Market capitalisation stood in for it,
and market cap is not a quality measure — it is a size measure, and a flawed one
without free float. Every result below is a search over how hard to lean on a
proxy that was standing in for the thing that actually matters.

## Why market cap is the wrong stand-in

**It is not adjusted for free float.** Total capitalisation counts every share,
including those that never trade — state holdings, founder stakes, strategic
blocks locked by agreement. In this market that is not a rounding error: several
VN30 names are majority state-owned, so their investable size is a fraction of
their headline size. Ranking by total cap therefore ranks partly by *who is not
selling*, which has nothing to do with whether the business is good or the price
is fair.

**And size is not quality even when measured correctly.** A large company can be
large and deteriorating. HAG was in the upper third of the basket by size in 2015
and lost half its value while the market multiplied; it kept qualifying on the
way down because a falling price is exactly what the buy condition looks for.

Identifying "good" needs the things this database does not carry: return on
equity through a full cycle, debt service capacity, earnings that reconcile to
cash, ownership and governance. Free float is the smallest missing piece and
already blocks the current proxy.

## What was measured

All figures on the repaired data (see the VHM entry below). DCA into VN30
returns **95.75%** over the same 137 months and the same contributions.

| Configuration | Growth | Note |
|---|---|---|
| No size floor, cooldown 10, no position cap | **145.29%** | best measured |
| Size floor top 50% | 126.06% | |
| Size floor top 20% | 64.00% | below the benchmark |
| + position cap 10% | 108.31% | recovers most of the loss |
| + cooldown 100 on both arms | 92.02% | below the benchmark again |
| + index exempt from the cap | 106.39% | but see below |

The last row is the trap. It beats the benchmark by 10.64 points while holding
**68.01% of the portfolio in VN30**, which contributes **+68.94 of the +106.39**.
Two thirds of the result is the benchmark held directly. A fallback that can
absorb any amount lets a rule be too strict without the headline showing it.

## What was learned that outlives the parameters

**Data quality dominates parameter tuning.** VHM carried 1,412 rows of
fabricated pre-listing history — 71 distinct prices, one held flat for 855
days — and the source returns it, so deleting it was not enough and a floor had
to go into the sync path. It was worth **21 points**, larger than any parameter
change measured here. Every sweep table in `config.py` predates the repair and
is marked accordingly.

**A ranking cannot enforce a floor.** Size in the score is measured against the
day's *candidates*, and the price test has already narrowed those to names that
are falling — so "large for this pool" routinely meant small for the market. HAG
passed at universe percentile 0.12 while ranking 0.67 inside a pool of four.
Only a filter measured against the whole basket refuses that, which is why
`CapRankAboveRule` gained a `basis`.

**A cooldown promotes as much as it restrains.** It runs after the ranking and
only removes names, but removing the top of a list promotes everything under it.
HAG once took 102m while ranked tenth of ten, because the four above it were all
inside the cooldown window.

**A position cap has an arithmetic floor.** A 10% ceiling needs ten
simultaneously eligible names to stay fully invested. Combined with a size floor
admitting eleven names and a 100-bar cooldown removing each for five months, the
plan holds cash by construction — 431m of reserve and 34m of deposit interest in
the cooldown-100 run.

**The buy condition structurally excludes steady compounders.** HCM is the best
performer in the basket at +2083% and was never bought once. A stock that rises
steadily for a decade is rarely below its own 1000-bar median, and no amount of
ranking fixes that — it fails the rule, not the sort.

## Caveats that were never resolved

- **Survivorship bias.** `UNIVERSE = "all"` is what is worth collecting today, so
  names that delisted or collapsed were never available to buy. Every figure here
  is an upper bound.
- **P/E lookahead.** `syncs/calculate.py` stamps fundamentals at quarter end
  rather than publication date. `USE_PE` is off in this package, but
  `single/`'s `SELL_MIN_PELOG` reads it.
- **No transaction costs.** The best configuration makes 671 buys; the cost model
  would not be a rounding error.
- **One start date.** Every number is a single observation. Nothing here
  distinguishes a 5-point difference from noise; the filter row of the dense
  sweep varied 6.5 points on a parameter that does almost nothing.

## If this is picked up again

Get free float first, then a quality screen. Re-measuring the existing knobs
against a better proxy is worth more than any further search over these ones —
the search above is a search over the wrong variable, and it has been run far
enough to say so.

The infrastructure is finished and tested: two-stage filters with a selectable
basis, blended ranking, position caps, per-arm cooldowns, the overlay chart, and
`test_rules.py` / `test_position_cap.py` / `syncs/test_listings.py`.
