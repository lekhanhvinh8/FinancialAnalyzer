# Sweeps — what each one measured

Every parameter sweep runs through one runner now:

```bash
python -m single.multi_signal.sweep_runner --list          # every grid
python -m single.multi_signal.sweep_runner percent_sell    # run one
```

The grids are in `sweep_specs.py`, the runner in `sweep_runner.py`, and results
go to `charts/sweeps/` (git-ignored).

The sections below are the findings the original hand-written scripts carried in
their docstrings, moved here verbatim when those 17 scripts were replaced
(last commit with them: `5ececf8`). **Every number below was measured on the
configuration of its day**, which is not config.py as it stands today — each
section says what it was run against. To check one, re-run its grid with the
`--profile` / `--set=KEY=VALUE` the section names; the runner reports every
cell paired against `live`.

One known difference: the old scripts never loaded the breadth map. That made
no difference while the breadth gates were off, and makes their buy arm never
buy once a breadth gate is on — so no old number taken after the gates were
switched on in config.py should be trusted. The new runner loads exactly what
`run_all` loads.

## breadth_buy, breadth_sell, breadth_reinvest, breadth_timeout

Was `sweep_breadth.py`.

```text
Sweep one breadth threshold at a time: BUY_MAX_BREADTH, SELL_MIN_BREADTH or
REINVEST_MAX_BREADTH, on whichever line BREADTH_SIGNAL names.

    python -m single.multi_signal.sweep_breadth --arm=sell
    python -m single.multi_signal.sweep_breadth --arm=buy --signal=prem_trim_cap
    python -m single.multi_signal.sweep_breadth --arm=reinvest FPT STB
    python -m single.multi_signal.sweep_breadth --arm=sell --rescore

ONE FILE, THREE ARMS, rather than three copies of a 550-line sweep. The sixteen
sweeps beside this one are copies of each other and the cost shows: the same
statistical mistake had to be fixed in each, and their headers disagree about
what the metrics mean. The three breadth thresholds differ only in which
parameter a cell sets and which way the comparison runs, so ARMS holds that and
everything else is shared.

WHAT IS HELD FIXED

  The profile is applied first (default "breadth"), then the swept arm's
  threshold is overridden per cell. The other two arms keep their profile
  values, so this measures ONE parameter against a working configuration -- not
  a grid where everything moves at once.

  BREADTH_SIGNAL is a sweep input because the three lines sit on different
  scales: 60 is the 86th percentile of prem_median and the 78th of prem_trim_cap. A
  threshold quoted without the line it was measured on means nothing.

THE REFERENCE ROW IS THE PROFILE'S OWN VALUE

  and "none" (gate off) is an ordinary row in the grid, so the reader can see
  what the gate is worth at all before asking what its best setting is.

READING THE COLUMNS -- the rules the other sweeps learned the hard way

  median, win and worst are aggregates OVER symbols at one setting and must
  never be subtracted between rows: the symbol at the median of one column is a
  different symbol from the one at the median of another. mean is the exception,
  being linear. vote is a pairwise round robin, one vote per symbol, immune to a
  single dominant name. The paired column does the comparison correctly and is
  re-referenced by clicking a row.

  A PLATEAU IS THE POINT. A single best cell surrounded by worse ones is a fit
  to this history; a run of neighbouring cells that all beat the reference is a
  setting that might survive out of sample. Read the shape of the column, not
  its maximum.
```

## buy_window

Was `sweep_buy_window.py`.

```text
Sweep the buy arm's median window against its threshold: BUY_MEDIAN_WINDOW x q.

The buy arm compared the price to a 1000-day median because that number was
hardcoded, never because it was tested. Sell and reinvest stay on 1000 here; only
the buy arm moves.

WHY q AND NOT PERCENT_BUY

  A fixed percentage is not the same condition at different windows. The price's
  distance from its own median widens as the window grows — measured over 59
  symbols and 182,522 observations per window (single/multi_signal/dispersion.py):

      p95 = 1.290 * w^0.698      R^2 = 0.9991      w in 20..1000

  so PERCENT_BUY = 60 is above the entire distribution at w=50 and blocks nothing,
  sits at the 95th percentile at w=250, and blocks about a fifth of days at
  w=1000. A rectangular grid of raw percentages would spend most of its cells on
  "always buys" and "never buys".

  The swept quantity is therefore

      PERCENT_BUY = q * 1.290 * w^0.698

  so a column means roughly one thing at every window: q = 1.0 is the 95th
  percentile of that window's own deviation, q = 0.5 is around the 80th, q = 0
  is "only buy below the median". The live setting, w=1000 with PERCENT_BUY=60,
  is q = 0.37.

  Two known limits, both from dispersion.py:
  - This normalises SCALE, and the centre moves too — the median deviation runs
    from +0.4 at w=50 to +16.8 at w=1000. Columns match well in the upper tail,
    where a buy ceiling actually binds, and drift in the lower half.
  - The constant is fitted on the full history. It decides which cells are worth
    testing, not what the strategy does; the winning cell is a plain fixed pair.

WHAT IT FOUND: THE WINDOW BARELY MATTERS, AND 1000 IS ALREADY FINE

  52 symbols, 500 cells, 30.7 min. Region in the top 10% of BOTH mean and vote:
  w = 500..1000, q = 0.2..0.6, 39 cells.

      w     q    PERCENT_BUY   mean   vote   neighbours in region
    820   0.4           55.8   41.1    471   7/8   interior
    780   0.4           53.9   41.0    467   7/8
   1000   0.4           64.1   40.9    488   2/5   live

  Nothing to change. The live setting is inside the region and 0.2 mean points
  off the best of 500 cells, which is noise. Two independent sweeps now agree.

  The window is close to irrelevant: taking the best cell in each row, the mean
  spans 36.5 to 41.1 across a 50x change in window length. The threshold is what
  moves the result — every one of the top ten cells is q=0.4.

  Its 2/5 neighbours is a grid artefact, not an edge in the surface. w=1000 is
  the last row so it only has five neighbours; the rows below it read 40.6, 40.8,
  40.9, so nothing is falling away.

  The worst symbol sits between -275 and -250 in every cell in the grid. LPB is
  out of reach of this parameter as well.

WHY THE GRID STOPS AT 1000

  The sell arm needs 1000 bars of warmup whatever the buy arm does, so any buy
  window at or below 1000 leaves the start index exactly where it is. Every cell
  then sees the same symbols over the same bars and the whole grid is comparable
  for free. Going above 1000 would move the start, cost symbols, and force a
  fixed start at the longest window.

  That follow-up is NOT needed: the surface is flat at the top, w=740 through
  1000 reading 40.1, 41.1, 40.6, 40.8, 40.9. It would only be worth running if
  the top rows were still climbing.

READING IT

  Same as the other sweeps: mean beside the vote, and check the buy count before
  believing either. Differences are per symbol against the same symbol at another
  cell; a difference of two aggregates would be comparing different symbols.

Usage:
    python single/multi_signal/sweep_buy_window.py             # all symbols
    python single/multi_signal/sweep_buy_window.py FPT STB     # a subset
    python single/multi_signal/sweep_buy_window.py --rescore
```

## min_signal3

Was `sweep_min_signal3.py`.

```text
Sweep MIN_SIGNAL3 — the last sell gate nobody has ever measured.

One parameter. Everything else stays at its configured value, so this measures
the Sharpe gate on its own.

WHY IT WAS NEVER MEASURED

  The only number ever attached to it, mean -2.50, was signal3 AND z_dev together
  layered on signal1. z_dev has been off since 73b7ce6, so that figure says
  nothing about this gate alone. It is the one remaining sell filter running on
  an untested value.

WHAT IT DOES

  Blocks a sell while the 1000-day Sharpe is at or above the threshold — the
  reading being "stable, trending regime, let it run". Same polarity as the
  signal1 sell gate: a HIGHER threshold blocks fewer days and therefore sells
  MORE.

NO WINDOW NORMALISATION NEEDED

  The gate always reads signal3 at window 1000; there is no MIN_SIGNAL3_WINDOW to
  sweep, so one window means one scale and the raw threshold is comparable
  throughout. That is why this grid is plain numbers rather than the k/sqrt(w) of
  the two slope sweeps.

  Sharpe does narrow sharply with the window — p95 = 124.6 * w^-0.654, R^2 =
  0.9971 (single/multi_signal/dispersion.py) — which would matter if the window
  were ever swept, and is the reason to add MIN_SIGNAL3_WINDOW before trying that.

THE GRID

  Placed off the measured distribution at w=1000:

      p5      p25     p50     p75     p95
      -0.339  +0.077  +0.423  +0.759  +1.360

  The live 1.1 sits between p75 and p95, blocking roughly 11% of sell-eligible
  days. The grid runs from below p5, where nearly every day is blocked and the arm
  almost never sells, to well past p95 where the gate is inert — plus None, which
  removes it outright. The inert end and None should agree; if they do not,
  something is wrong.

WHAT IT FOUND: 1.1 STANDS, AND THE SHAPE MATTERS MORE THAN THE VALUE

  Nothing beats live; every cell is 0.00 or negative against it. The sanity check
  passes too — 2.0, 2.5 and 3.5 converge exactly on None, which is what an inert
  gate should do.

      setting   vs live       p   sells   worst
      -0.50      -16.09   1.000     0.0     -29
      +0.30       -7.54   0.999     0.5     -34
      +0.45       +0.00   0.832     1.0     -35
      +0.75       +0.00   0.356     1.9     -83
      +1.10          —       —      2.3     -91   live
      +1.30       +0.00   0.999     2.4    -228
      None        +0.00   0.952     2.6    -225

  Below +0.45 it is destructive: nearly every day blocked, the arm stops selling
  altogether, -16.1 paired. From +0.45 to +1.1 the surface is flat, so the precise
  value inside that band is not doing work. Above +1.1 the tail gives way — the
  worst symbol falls from -91 to -228.

  The gate is worth keeping, modestly. Off costs mean -6.04 and a net -314 (+148
  gained, -462 lost), -3.39 even without the largest mover. 34 of 52 symbols are
  untouched. It mainly protects LPB, -91 with it and -225 without; HPG -141 and
  FPT -102 also depend on it, while GMD gains +126 from its removal.

Usage:
    python single/multi_signal/sweep_min_signal3.py             # all symbols
    python single/multi_signal/sweep_min_signal3.py FPT STB     # a subset
    python single/multi_signal/sweep_min_signal3.py --rescore
```

## pelog

Was `sweep_pelog.py`.

```text
Sweep the P/E sell gate: SELL_MIN_PELOG.

Blocks a sell while ln(P/E / its own PE_MEDIAN_WINDOW median) is at or below the
threshold — that is, while the P/E is NOT stretched. A higher threshold blocks
more. The gate is off in config, so the reference every cell is paired against is
the OFF cell, not a live setting.

WHY THIS GATE EXISTS

  The price condition cannot tell "expensive" from "the business grew into the
  price". On a compounder the difference is the whole result. FPT ends 85.03
  points behind buying at every interval, on four sells where the price was far
  above its median and the P/E was barely above its own:

      sell date     price vs median    ln(P/E / median), w=500
      2015-11-03         +77.5%                 0.181
      2018-01-29         +82.0%                 0.021
      2022-01-19        +125.3%                 0.262
      2025-04-18         +77.7%                -0.077

  Over FPT's whole history the price condition fires on 926 days and this one on
  217. A threshold of 0.262 blocks all four sells.

THIS IS Z_DEV'S SHAPE, AND Z_DEV LOST 0/66

  Same polarity, same stated purpose. z_dev's comment in sell.py even claims the
  same interpretation — "a low z_dev says the price is only above its trailing
  median because the business grew into it". That claim was never true of z_dev,
  whose formula is a z-score of ln(price / median price) and contains no earnings
  at all. This one does. That is the entire difference, and it is the reason to
  try again rather than a reason to expect success.

  Read this sweep against that prior, not against the FPT table above.

WHY A LEVEL AND NOT A Z-SCORE

  The obvious alternative is the z-score of the same log ratio, which is far more
  uniform across symbols: setting one threshold so the median symbol fires on 5%
  of days, the z-score form has every symbol between 1.5% and 8.4%, while this
  form has 17 symbols near 0% and 9 above 20%.

  Taken alone that argues for the z-score. Two things argue against it. This
  repo's own record is that level measures work here and z-scores do not —
  PERCENT_SELL is a level and it pays, SELL_MIN_ZDEV is a z-score and it does
  not — and the unevenness of the level form is the unevenness the live
  PERCENT_SELL already runs with, 17 quiet symbols against its 18. A z-score also
  answers a different question: it asks whether the P/E is unusual against its
  recent behaviour, not whether it is high, and a P/E drifting steadily to an
  all-time high reads as perfectly normal to it. FPT on 2022-01-19 is +65.7% over
  its median and -3.03 in z units.

  The z-score form is measured and kept as the fallback if this one finds
  nothing.

THE GRID

  Placed off the measured distribution at w=500 (dispersion.py pelog):

      p5      p25     p50     p75     p95
      -0.774  -0.188  +0.012  +0.231  +0.910

  It runs from below p5, where the gate is inert, to past p95, where the arm
  almost never sells — plus None, which removes it outright. Denser between 0.0
  and 0.4, which is where the FPT sells sit and where a useful setting would be.

  The threshold does not transfer across PE_MEDIAN_WINDOW: p95 = 0.094 * w^0.360,
  so this grid is only valid at 500.

EVERY CELL SHARES ONE START INDEX

  Including the OFF cell. The gate needs a full window of real P/E observations
  behind it (see build_pelog_map in factory.py), which for 31 of 59 symbols starts
  later than the price does. Judging OFF on more bars than the others would make
  the comparison meaningless, so OFF pays the same warmup it is being compared
  against. This is the mistake that invalidated a whole sweep in 9c81db9.

WHAT IT FOUND: THE GATE WORKS ON THE SYMBOLS IT WAS BUILT FOR AND LOSES ANYWAY

  52 symbols, 16 thresholds plus OFF, 4.2 min. Reference is the gate off: mean
  +36.03, median +20.14, 2.10 sells per symbol.

  Not one threshold beats it, and 13 of the 16 have a paired median of exactly
  0.00. The strict end is the only place with a large effect and it is the wrong
  one — sells fall from 2.10 to 0.27 and the mean from 36.0 to 7.8.

  What makes this one worth reading rather than filing is that the mechanism is
  not in doubt. At a threshold of 0.30 it does exactly what it was built to do:

      FPT   -85.0 -> +3.2      its four sells go to zero
      LPB   +116               the worst symbol in the run, untouched by anything
      DPM   +108               else ever tried, including all 70 cells of
      GMD    +96               sweep_sell_reinvest
      CTG    +93

  And the same cell costs more than it earns: 19 symbols up, 21 down, paired
  median 0.00, with HPG -340, VND -197, SHB -138. FPT's rescue is itself the
  warning — it comes from taking its sell count from 4 to 0.

  THE THIRD TIME THE SAME THING HAPPENED

      attempt                              FPT / GMD        portfolio
      SELL_MIN_ZDEV                            -            0 of 66 cells
      PERCENT_SELL x PERCENT_REINVEST      +91 / +428       15 up, 34 down
      SELL_MIN_PELOG                       +88 /  +96       19 up, 21 down

  Three unrelated mechanisms, one result. Restraining the sell arm rescues the
  few symbols it misfires on and charges the many it works on. The finding is not
  about P/E; it is that the sell arm is net positive across the portfolio and
  every attempt so far has paid the majority to save the minority.

  This does not say the FPT problem is imaginary — it is measured and it is 85
  points. It says the fix cannot be a portfolio-wide threshold, because no such
  threshold can tell a compounder from an oscillator. See sell.py, where this is
  recorded for whoever considers a fourth gate.

Usage:
    python single/multi_signal/sweep_pelog.py             # all symbols
    python single/multi_signal/sweep_pelog.py FPT GMD     # a subset
    python single/multi_signal/sweep_pelog.py --rescore
```

## percent_reinvest

Was `sweep_percent_reinvest.py`.

```text
Sweep PERCENT_REINVEST — the reinvest arm's price condition.

One parameter. The timeout stays at its configured 400 days and the slope gate
stays wherever config leaves it (currently off), so this measures the price
condition on its own. Combinations come later, once each parameter has been read
in isolation.

WHY THIS ONE MATTERS MORE THAN THE SLOPE GATE DID

  Capital that passes through the reinvest arm, as a share of all capital
  deployed, over 52 symbols: mean 91.4%, median 94.0%. Every symbol uses it.

  That is not obvious from the trade counts — ~3.5 reinvests against ~81 buys.
  The reason is that a blocked buy does not vanish: BuyMedian1000Strategy pushes
  the interval into totalReserveCapital, and the only way out of the reserve is
  the reinvest arm. Add the proceeds of every sell and almost all money ends up
  passing through this one condition. A share above 100% for some symbols is the
  same capital recycled several times.

  The slope gate that was just switched off moved the reinvest count by 0.4 across
  its whole grid. This parameter decides when 94% of the money gets deployed.

READ THE SIGN

  The condition is (price - median)/median * 100 < PERCENT_REINVEST, the same
  form and the same sign as PERCENT_BUY, against the same fixed 1000-day median.
  So the number is a ceiling measured ABOVE the median and larger is MORE
  permissive:

      -25   redeploy only 25% below the median          rare
       10   redeploy up to 10% above it                 current
      160   redeploy unless the price has tripled       almost always
      None  never redeploy; the reserve only ever leaves via the timeout

  No k/sqrt(w) normalisation here, unlike the two slope sweeps: the reinvest arm
  has no window of its own, the median is always the 1000-day one, so a raw
  percentage means one thing throughout. The grid is placed off the measured
  spread of price-to-median distance at w=1000 (dispersion.py): p5 -25, p25 -2,
  p50 +17, p75 +52, p95 +156. The live 10 sits near the 45th percentile.

WHAT THE TIMEOUT DOES TO THIS

  REINVEST_TIMEOUT_DAYS = 400 releases the reserve unconditionally once 400 days
  have passed with no sell and no reinvest, and REINVEST_TIMEOUT_PERCENT = 999
  means no price condition applies when it fires. So a strict setting here delays
  redeployment rather than preventing it, and the strict end of the grid converges
  on "the timeout does everything". Watch the reinvest count column: if it barely
  moves, that is what is happening.

  The None row is the exception and is worth having for that reason — it removes
  the arm entirely, timeout included, so the reserve never comes back at all.

WHAT IT FOUND: 10 IS ALREADY THE PEAK

  52 symbols, 14 settings, 2.7 min. The live value wins the mean (+45.8), the
  median (+21.4) and the win rate (79%) at once, and the median curve is cleanly
  unimodal around it:

      -25   -15    -5    +5   +10   +20   +35   +50   +80  +160   None
     13.1  16.7  17.0  17.9  21.4  20.8  19.4  14.5   6.9   7.7   -0.8

  Only the round-robin vote prefers something else, -15, and paired symbol by
  symbol that preference is 24/45 with a median difference of 0.00 and p=0.383 —
  a coin flip, nothing there.

  +5 is the one real rival: 27/41 symbols do better there than at +10, p=0.030.
  But they do better by 0.43 median points while the mean drops 6.34 — many
  symbols improve slightly, a few get much worse. Statistically real, economically
  not worth the trade.

  Above +50 the surface collapses, and the mechanism shows in the counts:
  reinvests run 4.4 -> 22.9 and sells 4.3 -> 11.8. Redeploying constantly means
  holding more shares, which triggers more sells. That is churn, not edge.

  The strongest result is the None row. Removing the arm costs 78 mean points and
  17.7 median, with only 13 of 52 symbols better off. It confirms the 94% capital
  share from the other direction: blocked buys accumulate in the reserve and this
  is the only way out.

  Safe region is wide — anything from -5 to +35 gives a median of 16 to 21 — so
  this is not a parameter that needs to be right to the point.

Usage:
    python single/multi_signal/sweep_percent_reinvest.py             # all symbols
    python single/multi_signal/sweep_percent_reinvest.py FPT STB     # a subset
    python single/multi_signal/sweep_percent_reinvest.py --rescore
```

## percent_sell

Was `sweep_percent_sell.py`.

```text
Sweep PERCENT_SELL — the sell arm's price condition.

One parameter. The three sell gates (signal1, signal3, z_dev) and everything else
stay at their configured values, so this measures the price condition on its own.

THE SIGN IS THE OPPOSITE OF THE OTHER TWO PERCENT_*

  The condition is (price - median)/median * 100 > PERCENT_SELL, against the
  fixed 1000-day median. The comparison runs the other way from the buy and
  reinvest arms, so the same number means the opposite thing:

      buy       pct <  PERCENT_BUY        larger = MORE permissive
      reinvest  pct <  PERCENT_REINVEST   larger = MORE permissive
      sell      pct >  PERCENT_SELL       larger = STRICTER, sells less

  So reading down this grid, higher rows sell more:

        0   sell whenever the price is above its median at all
       60   sell once it is 60% above           current
      300   sell only after a quadruple          almost never
      None  never sell; the arm is removed

  Off the measured spread at w=1000 (dispersion.py): p5 -25, p25 -2, p50 +17,
  p75 +52, p95 +156. The live 60 sits near the 77th percentile, so it fires on
  roughly the top fifth of days by price-to-median distance.

  No k/sqrt(w) normalisation: the sell arm has no window of its own, the median
  is always the 1000-day one, so a raw percentage means one thing throughout.

WHAT TO WATCH BELOW 60

  PERCENT_BUY is 60, and the buy condition is pct < 60 while sell is pct > this.
  Once this drops below 60 the two overlap, and the churn guard added in d2ffc39
  starts firing: the buy arm stands down on any bar the sell arm fires, rather
  than liquidating and re-entering the same day. Expect the buys column to fall
  through that part of the grid — that is the guard working, not a bug.

WHAT IT FOUND: 60 SELLS TOO EAGERLY, 65-80 IS BETTER

  52 symbols, 14 settings. This is the first parameter where the sweep argues for
  a change, and it is the vs-live column that says so — the aggregate columns
  point the wrong way.

  Refining the grid between 60 and 110 gives a contiguous significant region:

      value   improved   paired median   p
        65      35/43         +2.27    0.000
        70      32/45         +3.28    0.003
        75      31/45         +5.25    0.008
        80      29/45         +7.68    0.036
        85      28/45         +1.94    0.068
        90      25/45         +0.00    0.276

  Four consecutive settings clear the sign test with a positive paired median.
  Past 85 the effect is gone. Inside the region the paired median rises while
  significance weakens — a real trade-off, no single cell dominates.

  The mechanism is that the strategy was selling too early: sells fall 4.3 -> 2.3
  and the worst symbol improves from -238 to -101. Three gates were added to this
  arm to restrain selling; it turns out the price condition itself was the thing
  to loosen.

  Unlike the other sweeps here the evidence is BROAD rather than concentrated —
  29 to 35 of ~45 symbols improve, and the paired median is genuinely positive.
  The mean is still one-symbol business (HPG is +425 at 75; removing it takes the
  mean negative), so quote the median and the count, not the mean.

RE-RUN AFTER THE 2026-08-18 PRICE REPAIR — THE REGION SURVIVED INTACT

  Nine symbols had their whole price history rewritten that day (VHM was stored
  at 2.001x the source, MBB 1.202x, SSI 1.251x, and six more). Every number
  above was measured before that, so the sweep was re-run against the repaired
  data to see what still stood.

  Nothing moved. Recomputing both runs' raw files the same way, paired against
  the same "60" column:

      value    before                 after
        65     35/45  +1.92  0.000    35/45  +1.90  0.000
        70     33/47  +3.21  0.004    33/47  +3.21  0.004
        75     33/47  +6.26  0.004    33/47  +6.25  0.004
        80     31/47  +9.09  0.020    31/47  +8.98  0.020
        85     30/47  +3.48  0.039    30/47  +3.42  0.039

  Not one cell changed how many symbols improved, and no p moved in three
  decimals. The reason is worth keeping, because it says which results a data
  repair can and cannot invalidate: the vs-live column is a difference between
  two settings for the SAME symbol, and the error shifted every setting of a
  symbol by the same amount, so it cancels. VHM shifted -160.0093 at 60 and
  -160.0093 at 75 — identical to four decimals — leaving its paired delta at
  +0.1292 in both runs.

  It cancels because the error was near enough a uniform rescale, and the arm
  reads (price - median)/median, which a rescale leaves alone. What DID move is
  anything measured against buy-and-hold: VHM's report_all diff went from
  +132.37 to -36.28, since buy-and-hold is start-to-end and the break was
  suppressing it. So a paired sweep survives an error of this shape; an
  aggregate against buy-and-hold does not, and an error that changed the SHAPE
  of a series would not cancel in either.

  Live is 75 now, so the vs-live column re-based there and points at 80-85:
  +1.63 (29/35, p=0.000) and +1.84 (29/37, p=0.000). Still significant, an
  order of magnitude smaller than the +6.26 that moved it from 60 to 75. Read
  that as the top of the region, not as a reason to move again.

  The footer still reads "best mean: 55", as it did before the repair. It is
  the aggregate trap this file's aggregate() warns about, and it is worth
  spelling out once: going 75 -> 55 helps 20 symbols by +104 on average and
  hurts 28 by -46, netting +804 — of which HCM alone is +1003. Take HCM out and
  the net is -199. The paired median is -1.56 at p=0.903.

Usage:
    python single/multi_signal/sweep_percent_sell.py             # all symbols
    python single/multi_signal/sweep_percent_sell.py FPT STB     # a subset
    python single/multi_signal/sweep_percent_sell.py --rescore
```

## reinvest_2d

Was `sweep_reinvest_2d.py`.

```text
Sweep the two reinvest price triggers against each other:
PERCENT_REINVEST x PERCENT_REINVEST_TOP.

Both have been measured alone and both came out a tie against the other. This asks
the one thing neither could: do they COMPLEMENT each other? The arm ORs them, so a
pair can in principle cover symbols that neither covers by itself.

WHY THERE IS A REASON TO EXPECT IT

  They are good on different symbols, which is the only situation where an OR is
  worth anything.

    PERCENT_REINVEST = 10   asks "is the price back near its usual level". It is
                            what carries the typical symbol: median +20.14 against
                            the top trigger's +22.04, and it wins the 35-way round
                            robin on 23 head-to-heads.
    PERCENT_REINVEST_TOP    asks "has the price fallen far from its peak". Its
                            aggregate lead is three symbols wide — VND +430,
                            HPG +265, HAG +240 — and its worst symbol is -121
                            against the median trigger's family at -155.7.

  One is broad and shallow, the other narrow and deep, and they fire on different
  days by construction: the days the top trigger adds are days the price is still
  at least 10% ABOVE its median, which is exactly where the median trigger is
  silent.

WHAT "COMPLEMENTARY" HAS TO MEAN HERE

  Not "the cell scores well" — a pair can score well because one of its halves is
  carrying it, and reading the heat map alone would call that success. It has to
  beat what either half does ALONE.

  So every pair is also compared against its own row's None column and its own
  column's None row, and scored against whichever of those two is BETTER. Beating
  the weaker half proves nothing. That table sits beside the heat map and is the
  one to read first.

THE GRID

      PERCENT_REINVEST      None, -10, 0, 5, 10, 20, 35
                            None is the trigger off, which turns the row into
                            "top trigger only". 10 is live. The 1D sweep found
                            -5..+35 all within a few points, so the row spans that
                            band rather than hunting a new optimum.
      PERCENT_REINVEST_TOP  None, -30 .. -70
                            None turns the column into "median trigger only". The
                            1D sweep put everything useful between -30 and -70,
                            with -50 the best cell.

  Live (10, None) is a cell in this grid, so it is the reference every other cell
  is paired against, and the None row and None column give the two "alone" arms
  the synergy table needs. Neither axis moves the warmup.

  The timeout stays on everywhere except (None, None), where the factory falls
  back to the base class and the valve goes with it — that one cell is a floor,
  not a candidate.

Usage:
    python single/multi_signal/sweep_reinvest_2d.py             # all symbols
    python single/multi_signal/sweep_reinvest_2d.py FPT GMD     # a subset
    python single/multi_signal/sweep_reinvest_2d.py --rescore
```

## reinvest_signal1

Was `sweep_reinvest_signal1.py`.

```text
Sweep the reinvest slope gate: REINVEST_SIGNAL1_WINDOW x REINVEST_MIN_SIGNAL1.

Mirror of sweep_sell_signal1.py for the other arm. The sell side is held at its config
values throughout; only the reinvest gate moves.

OPPOSITE POLARITY TO THE SELL GATE

  Both arms read the same signal1 slope and compare it the same way, but they
  want opposite things from it:

      sell      BLOCKED while slope >= min_signal1   trend intact, let it run
      reinvest  ALLOWED only once slope >= min_signal1   wait for the turn

  So raising the threshold makes the sell arm sell MORE and the reinvest arm
  reinvest LESS. k is signed the same way in both sweeps — higher k is a higher
  slope threshold — but it means "looser" in one grid and "stricter" in the other.
  Read the reinvest count column before interpreting any cell.

WHAT LIMITS THIS GATE

  It guards check() only. The timeout path in considerReinvest is deliberately
  left as an unconditional release valve, so with REINVEST_TIMEOUT_DAYS = 400 the
  reserve comes back out on its own eventually no matter what this gate does. A
  strict setting delays reinvestment; it cannot prevent it. Expect a smaller
  surface than the sell sweep's.

THE THRESHOLD IS SCALED BY THE WINDOW

  Same quantity, same law as the sell gate — the slope's spread shrinks as the
  window grows, p95 = 3.991 * w^-0.494 (single/multi_signal/dispersion.py), close
  enough to 4/sqrt(w). So the swept quantity is k in

      REINVEST_MIN_SIGNAL1 = k / sqrt(window)

  and a column is roughly constant strictness at every window. Live is
  REINVEST_SIGNAL1_WINDOW = 100 with REINVEST_MIN_SIGNAL1 = 0.05, i.e. k = +0.5.

  Note the sign, and that it means the opposite of what it means for the sell
  gate. k negative lets reinvestment through on most days, since most days have a
  slope above a negative threshold; k positive holds the reserve back until the
  slope is clearly up. The live +0.5 is therefore on the strict side.

READING IT

  Same as every other sweep here. Mean beside the round-robin vote, both taken
  per symbol against the same symbol at another cell, and the reinvest count as
  the mechanism check. A contiguous region, not the best of 340 cells.

Usage:
    python single/multi_signal/sweep_reinvest_signal1.py            # all symbols
    python single/multi_signal/sweep_reinvest_signal1.py FPT STB    # a subset
    python single/multi_signal/sweep_reinvest_signal1.py --rescore
```

## reinvest_timeout

Was `sweep_reinvest_timeout.py`.

```text
Sweep REINVEST_TIMEOUT_DAYS — the reserve's release valve.

One parameter. REINVEST_TIMEOUT_PERCENT stays at 999, so the release stays
unconditional: this measures WHEN the valve opens, not what price it demands.
Everything else is at its configured value.

WHAT THE VALVE ACTUALLY DOES

    if (timeoutDays > 0
        and (lastSellIndex == 0     or index - lastSellIndex     >= timeoutDays)
        and (lastReinvestIndex == 0 or index - lastReinvestIndex >= timeoutDays)):
            release the whole reserve

  Two consequences that are easy to miss.

  lastSellIndex == 0 means "has never sold", which makes the condition true. So
  the FIRST release fires as soon as there is anything in the reserve, on any
  setting above zero — it is not waiting for a timeout at all. Setting this to 0
  removes that free first release along with everything else.

  And it competes with REINVEST_TIMEOUT_DAYS. A short timeout releases the reserve
  before the price condition ever gets to speak; a long one, or zero, leaves the
  price condition doing all the work. So this sweep answers the question the
  REINVEST_TIMEOUT_DAYS sweep could not: how much of that arm's behaviour was the
  condition and how much was the valve. That one held this at 400 throughout.

THE GRID

  Evaluated history is ~2800 bars, about eleven years, so:

      0     off. No valve, and no free first release either.
      20    roughly monthly
      90    roughly quarterly
      400   current, about 1.6 years
      1200  about five years
      2800  fires once at the start and never again

  Spaced logarithmically because the effect is proportional — the step from 20 to
  40 halves the release rate, the step from 1800 to 2800 barely moves it.

  0 is the off value here, not None. None is not meaningful for this parameter
  and the factory would pass it straight through into a `> 0` comparison.

WHAT IT FOUND: ONLY ONE WAY TO GET THIS WRONG

  52 symbols, 14 settings. Nothing beats live; every cell is 0.00 or negative
  against it, and the best p is 0.220.

      setting    vs live       p    reinv   sells
      0 (off)      +0.00   0.667      2.1     1.9
      20 d        -17.20   1.000     27.3    12.1
      40 d         -7.33   0.997     15.8     7.3
      90 d         -1.23   0.944      8.7     4.5
      190 d        +0.00   0.860      5.5     3.1
      400 d          —       —        4.0     2.3   live
      1200 d       +0.00   0.439      2.8     2.2
      2800 d       +0.00   0.220      2.6     2.2

  Short is the only real mistake. At 20 days the arm loses 17 points against
  live on 13/49 symbols, and the counts say why: reinvests run to 27.3 and sells
  to 12.1. Releasing the reserve constantly means holding more shares, which
  triggers more sells — the same churn the PERCENT_REINVEST sweep found at its
  permissive end.

  From 190 days up the valve stops mattering. The paired median is exactly 0.00
  at every setting even though the release count keeps falling from 5.5 to 2.6,
  and past 1200 the rows are identical because the valve fires once at the start
  and never again.

  Switching it off entirely is also indistinguishable from live: 23/48 symbols,
  paired median 0.00, p=0.667, with half as many releases. Left at 400 anyway —
  the valve is insurance against a regime where the price condition stops firing,
  and it currently costs nothing. Dropping something free to save a line is not
  worth it.

  One warning from the aggregate column, which is why the vs column exists. The
  aggregate median peaks exactly at 400 (+20.0) with 15.8 and 12.1 either side,
  which reads like a fine-tuned optimum. Paired, both neighbours are 0.00. That
  peak is noise.

Usage:
    python single/multi_signal/sweep_reinvest_timeout.py             # all symbols
    python single/multi_signal/sweep_reinvest_timeout.py FPT STB     # a subset
    python single/multi_signal/sweep_reinvest_timeout.py --rescore
```

## reinvest_top

Was `sweep_reinvest_top.py`.

```text
Sweep the second reinvest trigger: PERCENT_REINVEST_TOP.

Redeploy the reserve once the price has fallen this far from the 1000-bar HIGH.
In the strategy it is AND'd with the existing test against the median; in this
sweep the median test is switched OFF in every cell, so the top condition is
judged on its own and PERCENT_REINVEST never enters a figure.

  THIS SWEEP PREDATES THE AND. It ran when the two were OR'd, and every figure
  below is still valid because the median test is off in every cell — with one
  condition live the join does not apply. What changed is what it implies about
  the SHIPPED config, where PERCENT_REINVEST is 10: adding a top threshold there
  now REMOVES reinvests rather than adding them.

SIGN

  Same comparison direction as PERCENT_REINVEST — redeploy while dev is BELOW the
  threshold — but measured against the top, where dev is always <= 0. So the
  threshold is negative and -30 reads as "at least 30% off the high". One rule for
  both triggers, one formula, opposite signs because the reference points sit on
  opposite sides of the price.

WHY THIS MIGHT WORK WHERE WIDENING PERCENT_REINVEST DID NOT

  The dead zone is the underlying problem. After a sell at +75% over the median
  the price must fall 65 points before the money may return, and on a compounder
  it never does, so the 400-bar timeout ends up buying back higher than it sold —
  five of seven re-entries across FPT and GMD, at +20% to +53% above the sell.

  Widening PERCENT_REINVEST was the obvious fix and it lost, 15 symbols up against
  34 down, because it lets money back in UNCONDITIONALLY: on a symbol whose price
  simply stayed high, it redeploys into strength. A drawdown condition is
  selective — it opens only after a real fall from the peak.

  Measured on those same seven re-entries, bars until each condition first permits
  a buy-back, against the timeout's 400:

      sell            dev vs top   median<=10   top<=-30   top<=-40
      FPT 2015-11-03      0.0%        1101        1101       2583
      FPT 2018-01-29     -2.9%         538         538       2020
      FPT 2022-01-19    -11.7%        1022         204       1026
      FPT 2025-04-18    -27.7%         215         112        219
      GMD 2017-03-07      0.0%         332         286        726
      GMD 2021-06-17      0.0%         950         355        951
      GMD 2023-02-03     -8.9%         543         542        544

  At -30, four of the seven happen on the price condition rather than the clock,
  and far sooner: 204 bars instead of 1022, 355 instead of 950. The three it does
  not reach are the ones that sold AT the high — dev vs top 0.0% — where the top
  keeps chasing the price and the gap never opens. That is the compounder case
  again, and this does not solve it.

THE RISK, AND IT IS MEASURABLE

  By construction the days this adds are days the price is still at least 10%
  ABOVE its own median: if the median condition already fired there would be
  nothing to add. So it buys into a fall that has not finished being expensive.
  Whether being conditional on a drawdown is selective enough to beat the
  unconditional widening that already failed is the whole question.

THE GRID

  The existing condition already fires on 35.7% of days, so what matters is how
  many the new one ADDS. Measured over 58 symbols and 124,382 post-warmup
  observations:

      threshold      -10    -20    -30    -40    -50    -60
      extra days    42.3%  21.7%   8.6%   2.3%   0.0%   0.0%     median symbol
      never fires       1      2      7     17     30     47     of 58 symbols

  -10 would take total coverage past three quarters of all days. -50 and below is
  inert for most of the universe. So the step is 2 through -20 to -44, with three
  coarse points above and four below to show both collapses.

  Distribution of the quantity itself, for placing that grid:

      p5     p25    p50    p75    p95
      -61    -39    -23    -11     -1

REFERENCE

  This parameter's own None, the way sweep_percent_sell references the live value
  of what it sweeps. With the median trigger also off, None means the arm never
  redeploys at all — and, because the timeout valve lives on the same class,
  drops that too. It is a low floor and labelled as one. PERCENT_REINVEST is not a
  row; it is printed once under the table as context.

COSTS NO WARMUP

  local_top is on the same range_stats row the median already reads.

WHAT IT FOUND: THE BEST AGGREGATE OF ANY REINVEST SETTING, AND STILL A TIE

  52 symbols, 20 thresholds. Four points to read it against:

      no reinvest at all, timeout included   mean -27.91  median  -0.47
      None: no top trigger, median inert,
            timeout still on   (reference)   mean +24.75  median  +8.50
      best cell, top at -50                  mean +55.79  median +22.04
      live: PERCENT_REINVEST = 10            mean +52.38  median +20.14

  Against the reference, 1 of 20 cells clears p<0.05 and 9 have a paired median of
  exactly 0.00. The one that clears it, -50, does so with a paired median of +0.15
  and no agreeing neighbours.

  Against live, -50 is 21 symbols up and 22 down, paired median +0.00, p=0.620. A
  coin flip. Its aggregate lead comes from three symbols — VND +430, HPG +265,
  HAG +240 — while the typical symbol does not move.

  A ROUND ROBIN SETTLES IT

  Pooling all 35 reinvest configurations from this sweep and sweep_percent_reinvest
  — legitimate because both now run at PERCENT_SELL = 75, and the shared cell
  agrees to 0.0000 on all 52 symbols — and counting how many opponents each beats
  with a positive paired median at p<0.05:

      RI=10 (live)     23 wins    mean 52.38   median 20.14   worst  -90.7
      TOP=-50          21 wins    mean 55.79   median 22.04   worst -121.6
      RI=20            19 wins    mean 48.65   median 14.73
      TOP=-40          17 wins    mean 46.88   median 14.27

  Live wins the round robin. 23 of the 34 others lose to it significantly. Exactly
  one beats it — RI=5, by a paired median of +0.01 at p=0.040, on a mean seven
  points BELOW live. That is a sign test detecting a hundredth of a point, not an
  improvement.

  One thing does separate the two families: every TOP cell has a worst symbol
  around -121 while nearly every RI cell sits at -155.7. The drawdown trigger has
  a consistently better tail. It is the only one of the four new parameters that
  improves anything without a compensating disaster, and still not enough to
  change a setting on.

  THE FIRST RUN OF THIS SWEEP WAS WRONG AND THE MISTAKE IS WORTH KEEPING

  It reported 17 of 20 cells beating the reference with 15 of them having both
  neighbours agree. That reference was built by handing the factory None for both
  price triggers, which falls back to the base class — and the base class has no
  timeout. So the reference lost the 400-bar valve as well as the trigger, while
  every cell kept it. The bare-None floor scored -27.91 against +44.8 for a cell
  at -70 where the top trigger fires almost never: 72 of those points were the
  clock. Isolating a parameter means everything else stays, including the parts
  that live on the same object.

Usage:
    python single/multi_signal/sweep_reinvest_top.py             # all symbols
    python single/multi_signal/sweep_reinvest_top.py FPT GMD     # a subset
    python single/multi_signal/sweep_reinvest_top.py --rescore
```

## sell_bottom

Was `sweep_sell_bottom.py`.

```text
Sweep the second sell trigger: PERCENT_SELL_BOTTOM.

Sell when the price is this far above the SELL_MEDIAN_WINDOW LOW. In the strategy
it is AND'd with the existing test against the median; in this sweep the median
test is switched OFF in every cell, so the bottom condition is judged on its own.

  THIS SWEEP PREDATES THE AND. It ran when the two were OR'd, and the numbers
  below are still valid because the median test is off in every cell -- with one
  condition live the join does not apply. What has changed is what the sweep says
  about the SHIPPED config: adding a bottom threshold now REMOVES sells rather
  than adding them, so the increment it declined to measure has changed sign.

WHY THE MEDIAN TEST IS OFF IN THE CELLS

  Left on, the bottom trigger can only ever ADD sells to a condition that already
  catches most of what there is to catch, and the sweep measures an increment
  rather than the idea. Off, the two are a head-to-head: is distance-from-the-low
  a better price test than distance-from-the-median?

  That needed a change in the None convention. PERCENT_SELL = None used to mean
  "replace the arm with SellStrategy and never sell", which would have made the
  bottom threshold unreachable. The arm now has two price conditions, each
  switches off independently, and only both being off falls back to the base
  class. In the
  shipped config the bottom trigger is None, so PERCENT_SELL = None still means
  "never sell" there and the all-None engine check is unaffected.

  The grid is then homogeneous — one parameter, twelve values plus None — and is
  read the way sweep_percent_sell is read: the reference is a ROW, chosen in the
  browser, defaulting to this parameter's own None. PERCENT_SELL is not a row and
  is not the baseline for anything. It is printed once under the table as context,
  because "is this trigger any good" and "is it better than the median one" are
  different questions and only the first is what this grid answers.

THE FIRST THING HERE THAT LOOSENS THE SELL ARM INSTEAD OF RESTRAINING IT

  Every previous attempt on this arm was a filter, and all three lost the same
  way:

      SELL_MIN_ZDEV                     0 of 66 cells
      PERCENT_SELL x PERCENT_REINVEST   FPT +91, GMD +428  ->  15 up, 34 down
      SELL_MIN_PELOG                    FPT +88, GMD  +96  ->  19 up, 21 down

  Each fixed the symbol it was built for and each charged the rest of the
  portfolio for it. The reading recorded on SellMedian1000Strategy is that this
  arm is net positive, so quieting it pays the majority to rescue the minority.
  That reading has an obvious untested corollary and this is it: if restraining
  the arm costs, does loosening it pay?

  Expect the mirror-image failure mode. A filter can win by never selling; a
  second trigger can lose by selling constantly. Watch the sells column before
  anything else.

WHAT IT CATCHES THAT THE MEDIAN CANNOT

  A symbol that runs away from its floor while the median chases the price up.
  The distance to the median never opens, so the existing condition stays quiet
  the whole way, while the distance to the window low keeps growing.

THE GRID

  Measured over 58 symbols and 124,382 post-warmup observations:

      p5     p25     p50     p75     p95     p99
      14      70     132     227     488     986      price vs 1000-bar low
     -26       0      24      60     172     386      price vs 1000-bar median

  The two are on completely different scales — the low is a floor, so the price
  can never be under it and the distance is one-sided and large, while the median
  sits in the middle. The same percentile is a different number in each:

      percentile     5%    25%    50%    75%    90%    95%    99%
      vs median     -26      0     24     60    117    172    386
      vs low         14     70    132    227    364    488    986
      ratio           -      -   5.5x   3.8x   3.1x   2.8x   2.6x

  So this grid deliberately does NOT reuse PERCENT_SELL's numbers, and reusing
  them would waste it. Applied to distance-from-the-low, PERCENT_SELL's grid runs
  -20 to 300, which here means:

      -20  sells on 100.0% of days      0  sells on 99.4%
       75  72.7%                      150  43.7%
      300  15.2%  -- still busy, and that is the TOP of that grid

  Its whole lower half would be a single degenerate cell repeated, and its top
  would stop before reaching the quiet end where the parameter switches itself
  off. What is matched is the coverage, not the digits: PERCENT_SELL's grid spans
  the 8th to 98th percentile of its own quantity, this one the 16th to 97th of
  its own.

  Where the grid is dense is set by where the arm's behaviour actually changes,
  measured as sells per symbol:

      threshold     50    75   100   150   200   250   300   350   400   500   600
      sells       21.4  14.1  12.6   8.8   6.1   3.9   2.8   1.5   1.1   0.5   0.2

  So 150 to 400 is where it goes from churning to quiet, and that is where the
  step is 25. Below it, four coarse points to show the collapse; above it, 450 and
  500 plus one near-inert anchor at 600, by which point 52 of 58 symbols never
  trigger it at all.

  An earlier grid ran to 1000. Those cells were dead weight — at 800 and 1000 the
  arm sells 0.08 and 0.02 times per symbol, which is the None row with extra
  steps.

COSTS NO WARMUP

  local_bottom comes out of the same range_stats row the median already does, so
  every cell shares the start index run_all would use anyway, so no row is judged
  on more bars than another.

WHAT IT FOUND: A REAL SIGNAL, AND STILL THE WEAKER OF THE TWO

  52 symbols, 18 thresholds plus None. Reference is None — no trigger at all,
  which with the median trigger off in every cell means the arm never sells:
  mean +5.17, median +3.06, worst -29.1.

  Three cells beat it with p<0.05, which no previous sweep on this arm managed:

      threshold   vs None      p   nb    mean   median    worst   sells
            200    +7.82   0.002    1   +28.5     +9.0   -260.3    6.06
            225    +3.32   0.003    2   +34.8     +5.3   -257.6    5.19
            250    +1.30   0.019    1   +39.2     +5.2   -254.6    3.87

  225 is the only cell in five sweeps of this arm with BOTH neighbours agreeing,
  and the trigger lifts the mean from +5.17 to +51.4 at its best. Distance from
  the window low is a genuine sell signal, not noise.

  IT IS STILL WORSE THAN THE MEDIAN CONDITION, ON THREE COUNTS

      condition            mean   median    worst   sells
      median 75 (live)   +52.38   +20.14    -90.7    2.35
      bottom 350         +51.44    +4.27   -243.2    1.50
      bottom 225         +34.80    +5.30   -257.6    5.19

  1. The evidence is CONCENTRATED, not broad. The two are within a point on mean
     and four-fold apart on median, so the bottom trigger keeps up only through a
     few large winners — VND +424, HPG +349, SHB +257 at 225 — while the typical
     symbol does far worse. sweep_percent_sell's case was the opposite: four
     consecutive settings clearing the sign test, 29 to 35 of ~45 symbols
     improving.

  2. Isolated cells, not a plateau. Three of eighteen, and about one of eighteen
     reaches p<0.05 by chance. Only 225 has two agreeing neighbours; the median
     condition has a contiguous band.

  3. It creates a tail disaster the median condition does not. Worst symbol runs
     -230 to -280 at every useful threshold against -90.7 live. LPB is the case:
     +84.1 with no trigger, -90.7 under the median condition, -257.6 at bottom
     225. Two of the three winning cells also churn, at 5.19 and 6.06 sells per
     symbol against 2.35.

  Left off. The open question this does not answer is the OR of both, which is
  what the strategy actually implements — median for the typical symbol and the
  tail, bottom to catch the VND and HPG cases the median misses. Expect less than
  the +424s suggest: the bottom trigger worsens the worst symbol at every
  threshold, so an OR inherits that unless its threshold is high enough to fire
  rarely.

Usage:
    python single/multi_signal/sweep_sell_bottom.py             # all symbols
    python single/multi_signal/sweep_sell_bottom.py FPT GMD     # a subset
    python single/multi_signal/sweep_sell_bottom.py --rescore
```

## sell_reinvest

Was `sweep_sell_reinvest.py`.

```text
Sweep the sell threshold against the reinvest threshold: PERCENT_SELL x PERCENT_REINVEST.

The first sweep here that exists because of a MECHANISM rather than because a
parameter had not been measured yet. Both of these have already been swept alone
and both won their own grid. The claim under test is that winning alone is not
enough, because they are coupled.

WHAT COUPLES THEM: THE DEAD ZONE

  The sell arm lets go when the price is PERCENT_SELL above its 1000-day median.
  The reinvest arm is allowed back in when the price is within PERCENT_REINVEST
  of that median. Live, those are 75 and 10, so after a sell the price has to
  fall 65 points before the money may return on merit.

  On a symbol that keeps compounding, it does not fall that far. Measured on the
  two worst long-history losses:

      sell            dev at sell    bars until dev <= +10
      FPT 2015-11-03      77.5%       1101   (4.4 years)
      FPT 2018-01-29      82.0%        538
      FPT 2022-01-19     125.3%       1022
      GMD 2021-06-17      80.4%        950

  REINVEST_TIMEOUT_DAYS is 400, so the clock always gets there first. Five of the
  seven re-entries across FPT and GMD are the timeout firing at exactly 400 bars,
  not the price condition. The timeout is documented as insurance for a regime
  where the price condition stops firing; on a compounder it is the only way back
  in, and it buys at whatever the market costs by then:

      FPT  sold  9.39M  ->  bought back 11.29M  (+20%, 400 bars)
      FPT  sold 15.56M  ->  bought back 19.24M  (+24%, 400 bars)
      FPT  sold 44.21M  ->  bought back 67.57M  (+53%, 400 bars)
      GMD  sold 31.66M  ->  bought back 36.91M  (+17%, 400 bars)
      GMD  sold 41.30M  ->  bought back 61.92M  (+50%, 400 bars)

  Sell high, buy back higher, five times out of seven. FPT ends 85.03 points
  behind buying at every interval and GMD 75.17 behind, on full 2816-bar history.

WHY THE ISOLATED SWEEPS COULD NOT SEE IT

  Not an oversight in either sweep; a consequence of doing them one at a time.

      a5c6ec1  swept PERCENT_REINVEST, settled on 10   -- PERCENT_SELL was 60
      4f8103d  raised PERCENT_SELL from 60 to 75

  The reinvest threshold was chosen against a dead zone of 50 points. Raising the
  sell threshold widened it to 65 and nothing re-examined the pair. Sweeping one
  parameter with the others held live is the right method and it is exactly what
  hides an interaction: each arm was asked whether it was individually optimal,
  never whether the distance between them was.

THE GRID

  Raw percentages on both axes. Neither is a windowed quantity, so there is
  nothing to normalise and no q -- see dispersion.py, where only slope, sharpe
  and dev needed reparameterising.

      PERCENT_SELL      60..90   the 1D sweep's significant band was 65..80 and
                                 the 2D window sweep put every winning cell in
                                 73..78, so the grid spans that and both edges
      PERCENT_REINVEST -10..80   live 10 at the low end, and up past the sell
                                 threshold at the other. The 1D sweep found
                                 -5..+35 all safe and a collapse past +50, but it
                                 measured that against a sell threshold of 60,
                                 which is the coupling this sweep exists to test:
                                 a reinvest ceiling that hurt at one dead-zone
                                 width says nothing about another

  Live (75, 10) is a cell in this grid, so it is the reference every other cell
  is paired against -- unlike sweep_zdev, which had to invent an "off" cell.

  Neither axis moves the warmup, so every cell is judged on identical bars and
  the grid costs no symbols.

READ THE DIAGONALS TOO

  The mechanism is about the DISTANCE between the two thresholds, and cells with
  equal distance lie on a diagonal. The report prints a gap table beside the heat
  map for that reason. Treat it as shape, not as a test: it averages each cell's
  paired median across the cells sharing a gap, which describes cells, not
  symbols, and carries no significance of its own.

WHAT IT FOUND: THE HYPOTHESIS IS DEAD, AND IT DIED THE INTERESTING WAY

  52 symbols, 70 cells, 4.6 min. The mechanism above is real and the sweep
  confirms it — narrowing the dead zone does hand the re-entry back to the price
  condition, exactly as described:

      PERCENT_REINVEST    10 (live)    40     60     80
      reinvests/symbol         3.96  4.71   7.15  16.63

  The prediction about what that would be worth was wrong, and wrong in sign.
  Collapsed along the diagonals, a NARROWER gap is worse and a wider one is
  neutral to slightly better:

      gap        15     30     45   65 (live)    80     85
      paired  -4.63  -2.66  -2.51      -0.62  +0.03  +0.52

  At sell=75 reinvest=60, the narrowest sensible cell, 15 symbols improve and 34
  get worse, paired median -4.85. FPT and GMD improve enormously — +91 and +428 —
  which is precisely what the diagnosis predicted, and they are two symbols out
  of fifty-two. Against them: SHB -173, HPG -172, HCM -163, SSI -161, MBB -121.

  So the dead zone is not a defect that had gone unnoticed. It is protecting the
  portfolio, and FPT and GMD are what it costs.

  This does not retract the diagnosis. The 400-bar timeout really is the only way
  back into a compounder and really does buy higher than it sold. What is retracted
  is that PERCENT_REINVEST is the lever: a global threshold that fixes those two
  charges 34 other symbols for it. Anything that fixes it has to tell a compounder
  apart from an oscillator, which is not a number either of these axes can hold.

  THE ONE THING THAT DID WIN IS NOT ON THE REINVEST AXIS

      sell  reinv  gap  paired      p  nb   up/down/unchanged
        85     10   75   +1.89  0.000   2   29 / 8 / 15
        80     10   70   +1.67  0.000   1   29 / 6 / 17
        90     10   80   +0.93  0.004   1

  All three sit at reinvest=10, i.e. unchanged. The reinvest axis contributes
  nothing; what wins is selling even less often. Not adopted, on three counts:
  no cell has more than 2 agreeing neighbours (with 70 cells about 3.5 reach
  p<0.05 by chance, and there are exactly 3), the size is +1.89 median points
  against a live mean of +52, and config.py records a 1D sweep finding that 85
  and up was NOT significant.

  That last one is not the contradiction it looks like: the 1D sweep paired
  against 60 and this pairs against 75. Paired medians do not chain —
  median(85-60) is not median(85-75) + median(75-60) — so "85 does not beat 60"
  and "85 beats 75" can both hold. The same non-additivity that has been the
  recurring trap here, in its transitive form.

  Nothing rescues the worst symbol either: LPB stays at -90.68 in every cell, and
  the "worst symbol" metric picks the live cell.

Usage:
    python single/multi_signal/sweep_sell_reinvest.py             # all symbols
    python single/multi_signal/sweep_sell_reinvest.py FPT GMD     # a subset
    python single/multi_signal/sweep_sell_reinvest.py --rescore
```

## sell_signal1

Was `sweep_sell_signal1.py`.

```text
Sweep the SELL arm's signal1 gate: SELL_SIGNAL1_WINDOW x SELL_MIN_SIGNAL1.

The reinvest arm reads the same slope with the opposite polarity and is swept
separately in sweep_reinvest_signal1.py. Neither sweep may move the other's
window: this one used to hand the reinvest gate whatever window it was sweeping,
which changed the reinvest strictness row by row — REINVEST_MIN_SIGNAL1 is a raw
slope derived as k/sqrt(its own window) — so a cell answered two questions at
once. Fixed; the reinvest map is now read at its configured window.

signal1 blocks ~61% of all sell-eligible days — more than the other two filters
combined — so it looked like the obvious thing to tune. This maps the surface.

RE-SWEPT ON THE CURRENT BASIS — 0.228 SURVIVES

  52 symbols, 340 cells, paired against the live cell (w=120, k=2.5). Nothing
  beats it meaningfully. Five cells clear p<0.05 and their paired medians are
  +1.35, +0.22, +0.11, +0.06, +0.01 — real by the sign test, worthless in points,
  and all at w=50..70 where a block only postpones a sell rather than cancelling
  it. With 340 cells about 17 would clear p<0.05 by chance anyway.

  The gate itself is still worth having, which the grid cannot show because it
  contains no "off" cell. Measured directly: switching it off costs mean -21.06
  and a net -1095 (+336 gained, -1431 lost), and even dropping the largest mover
  leaves -7.58. 25 of 52 symbols are untouched at any setting, and the effect is
  in the timing rather than the count — sells move only from 2.35 to 2.73 and
  those 0.4 sells are worth 21 points.

  This replaces an earlier sweep that produced the same number on a worse basis:
  44 symbols with z_dev on, and every cell moving the reinvest window along with
  the sell window, so its "w=110-130, k=2-3" region could not be read as stated.

READING THE RESULT: WHY THE GRID ALONE WILL MISLEAD YOU

  Difference PER SYMBOL, always. Keep every symbol and report the mean beside how
  concentrated it is; neither half stands alone. Two failure modes, both of which
  caught us here:

  - median(A) - median(B) is not median(A - B). The first compares the middle
    symbol of one run with a DIFFERENT symbol in the middle of the other, because
    changing a parameter reorders the ranking.
  - Half the symbols are untouched by this filter at any setting, so an aggregate
    median lands among them and reads ~0 regardless of what happens in the tails
    — and the tails are the whole effect.

  Do not trim the tails to make the mean behave either. A large single-symbol
  contribution is a real result, not noise; trimming answers "is the effect
  broad?" and is a diagnostic only.

  Two traps in the grid itself:

  - The flat green region at w=10-20 is flat because the gate is INERT there, not
    because it is robust. Blocking share is held constant across windows by
    k/sqrt(w), but persistence is not: at w=10 a block lasts ~36 days on average,
    at w=100 it lasts ~293. A 10-day slope flips sign constantly, so a sell is
    merely postponed and still happens. A plateau can mean "every value works" or
    "no value does anything" — both render as smooth green.
  - Win rate is measured against the DCA arm, not against the gate being off, so
    it stays high while a setting does damage.

WHY THE THRESHOLD IS SCALED BY THE WINDOW

  The slope's spread shrinks as the window grows. Measured over all 45 eligible
  symbols (~3.1M observations, 20 windows):

      p95 = 3.991 * w^(-0.494)      R^2 = 0.9994

  i.e. very close to 4/sqrt(w). A fixed threshold therefore means something
  different at every window — at w=200 anything above 0.3 blocks nothing, while
  at w=10 the same number sits mid-distribution. A rectangular grid of raw
  thresholds spends most of its cells on two degenerate states ("never sells"
  and "no filter at all").

  What matters is not the formula but that a column means one thing everywhere,
  and it does — share of sell-eligible days blocked, by window:

      k        -4    -2    -1     0     1     2     4
      w=10    95%   86%   74%   52%   30%   17%    5%
      w=100   95%   86%   75%   56%   36%   21%    6%
      w=200   95%   87%   78%   60%   40%   23%    5%

  So the swept quantity is k, with

      min_signal1 = k / sqrt(window)

  which holds strictness roughly constant across windows: k=-4 blocks ~95% of
  days, k=0 about 55%, k=+4 about 5%. It is arithmetic on the window, not a
  fitted quantile, so it introduces no look-ahead.

READING THE RESULT

  Default score is the MEDIAN per-symbol diff; --mean switches to the mean, which
  tracks whichever symbol dominates. When the two disagree that IS the finding —
  the effect lives in the tails — so read the per-symbol list rather than picking
  the aggregate you prefer. See the section above for what that costs here.

  Every metric is computed for every cell and embedded in the page, so the
  selector switches between them without recomputing; --mean only chooses which
  one the console prints and stars.

  Per-symbol diffs are saved to sweep_sell_signal1_raw.json, so switching score costs
  seconds instead of another full sweep:

      python sweep_sell_signal1.py --rescore          # median
      python sweep_sell_signal1.py --rescore --mean   # mean

  Look for a plateau, not the maximum. Taking the best of 340 cells will find a
  good-looking number whether or not any edge exists; a contiguous region that
  stays good is evidence, an isolated spike beside bad neighbours is noise. And
  a plateau is still only a candidate — check it against the gate-off baseline,
  paired per symbol, before believing it. Note that at 340 cells about 17 are
  expected to reach p < 0.05 by chance alone, so a single significant cell means
  nothing on its own.

Usage:
    python single/multi_signal/sweep_sell_signal1.py            # all eligible symbols
    python single/multi_signal/sweep_sell_signal1.py FPT VIX    # a subset
```

## sell_slope

Was `sweep_sell_slope.py`.

```text
Sweep the sell price threshold against the slope gate that vetoes it:
PERCENT_SELL x SELL_MIN_SIGNAL1, slope window fixed at 120 days.

THE HYPOTHESIS

  The slope gate blocks a sell while short-term momentum is still up, on the
  reasoning that a rising price should be left to run. But the two conditions are
  read on the same bar, and they do not turn at the same time: the price clears
  its median threshold at the top of a move, which is exactly when the trailing
  slope is still positive. By the time the slope rolls over enough to release the
  gate, the price has already given back part of the peak the gate was protecting.

  If that is right, the two parameters are not independent. Sell earlier (a lower
  PERCENT_SELL) and the lag costs more, because the gate holds through a larger
  share of the remaining move. Sell later (a higher one) and it costs less. The
  best gate setting would then depend on the price threshold, and vice versa.

WHY THIS NEEDS A GRID AND NOT TWO ROWS

  Both parameters have been swept alone, and each was swept with the other sitting
  at its live value. sweep_sell_signal1 covered window x threshold at
  PERCENT_SELL = 75 and nothing else; converting its k axis through
  min_signal1 = k / sqrt(window), its row at window 120 reads:

      threshold   0.000   0.183   0.228   0.274   0.365
      median diff 13.58   15.64   20.14   20.09   20.09
                                  ^ live

  So at 75 the live setting already sits at the top of a plateau. That is an
  answer about the column through 75, and it says nothing about whether the same
  threshold is best at 60 or at 90 — which is the entire question here.

  The standing reminder that one-dimensional results do not compose is
  sweep_reinvest_2d: two triggers that each tied on their own were worse together
  than either alone, and no pair of 1D sweeps could have predicted it.

POLARITY, WHICH IS EASY TO GET BACKWARDS

  The gate blocks when signal1_slope >= SELL_MIN_SIGNAL1. A HIGHER threshold
  therefore blocks FEWER bars — it is the loose direction, and it is the direction
  the hypothesis above points in. None is not merely a very high threshold: it
  removes the gate entirely, and bars above 0.7 do exist, so the None column is a
  real extra setting rather than the end of the axis.

WHAT MOTIVATES SPENDING THE RUN ON THIS GATE

  diag_sell_gates counted where the sell decision dies across 117,163 bars. The
  slope gate is the single largest killer: 8,234 of the 21,916 bars where the
  price test fires, 38% of them, against the Sharpe gate's 17%. Every one of
  VN30's 24 firings dies there and it has never sold.

  That same diagnostic found the arm has 9,931 permitted bars and makes 122 sells,
  81 to 1, because selling needs shares to sell and re-entry is what governs that.
  This sweep is NOT exposed to that finding. It does not try to create more
  permitted bars; it moves WHICH bar in a run of them is the first one, and the
  first one is the only one that becomes a sell.

THE GRID

      PERCENT_SELL          60 .. 90 by 5, live 75
      SELL_MIN_SIGNAL1      None, 0.0, 0.1, 0.15, 0.183, 0.21, 0.228, 0.25,
                            0.274, 0.32, 0.365. Live 0.228, and the spacing is
                            deliberately uneven — see the comment beside SLOPES
                            for the block rates that set it. In short: past 0.365
                            the gate stops binding at all, so spending columns out
                            there only buys duplicates of None, while the step
                            from 0.228 to 0.274 moved a smoke test by 43 points.

  Live (75, 0.228) is a cell, so it is the reference every other cell is paired
  against. Neither axis moves the warmup — but signal1 is loaded for every cell
  INCLUDING the None column, so the start index is identical across the grid.
  Dropping the load when the gate is off would hand that column extra bars and
  break every comparison in the table; sweep_reinvest_top made exactly that
  mistake with the reinvest timeout and 72 points of an apparent gain turned out
  to be the clock.

WHAT IT FOUND — 54 symbols, 77 cells, run of 2026-08-16

  The hypothesis is not supported, and the grid answers it more flatly than a
  wrong-direction result would have.

  Holding PERCENT_SELL fixed and moving only the gate, the paired median is
  EXACTLY 0.00 in 70 of the 70 comparisons. Not small — zero. Six of the seven
  rows are flat end to end, and no row's best cell beats its own live-slope cell
  at p<0.05. The single cell that clears 0.05 (60|0.183, p=0.049) is one of 70,
  and 3.5 are expected by chance.

  So there is no interaction to find, for the reason that there is no slope effect
  to interact with: at every price threshold from 60 to 90, moving the gate
  anywhere from off to 0.365 leaves the median symbol where it was.

  THE MEAN SAYS THE OPPOSITE, LOUDLY, AND IS WRONG TO LISTEN TO

      within-row mean vs the row's own 0.228 cell
      sell   None      0.1     0.15     0.25    0.365
        60  -25.66   +57.11   +56.46    -8.81   -22.82
        75  -56.95   +13.14   +15.03   -10.28   -29.28
        85  -42.27    +3.85    +7.69    -8.59   -21.93

  Read alone this says tighten the gate hard — the opposite of the hypothesis, and
  worth +57 at PERCENT_SELL = 60. But every one of those cells medians to 0.00, so
  the mean is a handful of symbols and nothing else.

  EVERY FIGURE BELOW EXCLUDES VIX AND VIC

    RAW keeps all 54 symbols so the exclusion can be changed by re-scoring, and
    the first reading of this file forgot to apply it. VIX alone moves -574 points
    between two cells, which is enough to flip the sign of any mean in the table:
    85|0.228 reads mean -1.44 over 54 symbols and +6.68 over the configured 52.
    The medians barely move, which is exactly why the paired median is the metric
    this project scores on — but never quote a mean off the raw file.

  WHAT THE RUN DID CONFIRM, AND IT IS NOT ABOUT THE GATE

      cell         paired median   paired mean   up/dec       p
      80|0.228         +1.67          +3.67       29/35    0.0001
      85|0.228         +1.89          +6.68       29/37    0.0004
      90|0.228         +0.93          +5.87       27/37    0.0038

  PERCENT_SELL moved, gate untouched, and the three form a contiguous band rather
  than one lucky cell. sweep_percent_sell scored 85 at +1.87 on a different grid
  and a different run; this reproduces it at +1.89.

  Cells with a higher median exist — 85|0.25 at +3.92, 85|0.365 and 85|None both
  at +3.78 — but the two loose ones carry paired means of -9.16 and -7.84, so they
  buy their median by moving a few symbols a long way in the wrong direction.
  85|0.25 is positive on both and is the one cell of the three worth a second look.

  WHAT ADOPTING 85 COSTS, STATED PLAINLY

      cell       mean    p25   median    p75    worst   losers   sells
      75|0.228   52.38   0.04   20.14   56.54   -90.68     12     2.35
      85|0.228   59.06   0.04   14.09   75.04   -90.68     12     1.77

  The aggregate median FALLS by 6 while 29 of 37 decided symbols individually
  improve. Both are true and they are not in conflict: median(A) - median(B) is
  not median(A - B), and the paired figure is the one that answers "does this help
  each symbol". What actually happens to the distribution is that the top half
  stretches (p75 +18.5) while the middle sags; p25, the worst symbol and the count
  of losing symbols are all unchanged. Expect report_all's headline median to look
  worse after this change, and expect that to be the shape moving rather than a
  regression. The arm also acts less: 2.35 sells per symbol down to 1.77.

  Sell counts corroborate diag_sell_gates: at PERCENT_SELL = 75 the mean sells per
  symbol runs 1.56 at slope 0.0 to 2.73 with the gate off. Removing the largest
  gate in the chain buys 1.2 extra sells per symbol over fifteen years, because
  re-entry and not the gate is what governs how often there is anything to sell.

Usage:
    python single/multi_signal/sweep_sell_slope.py             # all symbols
    python single/multi_signal/sweep_sell_slope.py FPT GMD     # a subset
    python single/multi_signal/sweep_sell_slope.py --rescore
```

## sell_slope3d

Was `sweep_sell_slope3d.py`.

```text
PERCENT_SELL x SELL_MIN_SIGNAL1 x SELL_SIGNAL1_WINDOW — one heat map per price
threshold, so the whole cube can be read by eye.

WHY A THIRD AXIS AFTER TWO FLAT RESULTS

  Two faces through the live point are already measured and both are flat:

      sweep_sell_signal1   window x k at PERCENT_SELL = 75, 340 cells. Every
                           window from 80 to 200 has a best paired median of
                           exactly +0.00, and that is the best of 17 k values.
      sweep_sell_slope     sell x threshold at window 120, 77 cells. Paired
                           median exactly 0.00 in 70 of 70.

  What neither touches is PERCENT_SELL != 75 AND window != 120 at the same time,
  and there is a mechanism that would live exactly there. The hypothesis is about
  LAG: the gate holds a sell while the trailing slope is still positive, and by
  the time it releases, part of the peak is gone. Lag is a function of window
  length above all — a 20-day slope turns quickly, a 200-day slope barely turns at
  all. If the price threshold and the gate interact anywhere, it is across window.

  The honest prior is still that nothing is there. Read WHAT IT FOUND at the
  bottom before spending another run on this family.

THE DEAD ZONE, WHICH IS THE REAL OBSTACLE AND IS NOT A GRID PROBLEM

  Most cells in both earlier sweeps have a paired median of exactly 0.00. Not
  small — zero. The cause is not resolution and cannot be fixed by refining the
  grid: diag_sell_gates counted 9,931 permitted bars producing 122 sells, about
  2.35 sells per symbol over fifteen years. Moving a gate rarely changes which bar
  of a run is first by enough to change any sell, so most symbols come out
  bit-identical and the median of the differences sits on zero.

  So the median alone cannot see a plateau here, and neither can `nb`, which is
  built on it. Two metrics are carried specifically for this:

      dec    how many symbols the cell moves AT ALL against live. A region where
             many symbols move is a region where the parameter does something,
             whatever the median says.
      updn   up minus down among those. The sign test's own statistic, and it
             keeps discriminating when half the sample is frozen.

  Read dec and updn before median. A block of cells with high dec and consistently
  positive updn is a real plateau even if every median in it reads 0.00.

THE GRID

      panels   PERCENT_SELL   30, 40, 50, 60, 70, 80, 85, 90, 100
                              85 is off the step-10 ladder on purpose: it is the
                              standing candidate, at +1.89 paired median with
                              p=0.0004 on two independent runs.
      rows     window         10, 20, 30, 50, 70, 100, 140, 200 — geometric, not
                              linear. The signal's own scale goes as w^-0.494, so
                              even steps waste cells at the long end where that
                              barely changes.
      cols     k              None, then -1.0 to 4.0 by 0.5.

  9 x 8 x 12 = 864 cells.

k IS NORMALISED AND MUST BE

      SELL_MIN_SIGNAL1 = k / sqrt(window)

  The dispersion study puts the slope's p95 at 3.991 * w^-0.494, which is w^-1/2
  to within measurement error. A raw threshold therefore means something entirely
  different at window 10 and at window 200 — 0.228 blocks almost nothing at 10 and
  almost everything at 200 — and a cube built on raw thresholds would be measuring
  the normalisation rather than the gate. k is the same sweep_sell_signal1 used,
  so its 340 cells remain directly comparable to the w-row through 75 here.

THE ONE STRUCTURAL TRAP IN THIS GRID

  PERCENT_BUY = 60. The buy arm fires when the price is BELOW 60% over its median;
  the sell arm fires when it is ABOVE PERCENT_SELL.

      PERCENT_SELL >= 60    the two zones do not overlap. This is the regime every
                            result so far was measured in.
      PERCENT_SELL = 50     they overlap by 10 points
                   = 40     by 20
                   = 30     by 30

  In the overlap both conditions are true on the same bar, and the churn guard
  starts biting: the factory hands the buy arm a reference to the sell arm and it
  stands down on any bar the sell fires, gates included. Without it the position
  would liquidate and re-enter the same day.

  So the bottom three panels are running a DIFFERENT MECHANISM from the rest, not
  merely a looser threshold, and their numbers are not on the same footing as the
  panels at 60 and above. They are kept because nobody has ever measured that
  region, and labelled because comparing across the boundary without knowing is
  how a mechanism change gets read as a parameter effect.

WARMUP IS FREE ON THE WINDOW AXIS

  start_idx is pinned at max(1000, max(WINS) - 1, ...) so every cell shares it.
  The longest window here is 200 and the median window is 1000, so the slope
  warmup never binds and no panel gains bars from a shorter window. sweep_
  reinvest_top is the reminder of what happens otherwise: 72 points of an apparent
  gain turned out to be a start index that had moved.

WHAT IT FOUND — 52 symbols, 864 cells, run of 2026-08-16

  201 cells beat live on the sign test at p<0.05 against 43 expected by chance,
  and 88 of those have 13 or more of their 26 neighbours agreeing. So unlike the
  two flat 2D faces there is something here. It is not what the sweep was built
  to look for.

  THE WINDOW AXIS IS NOT IT

    The 88 solid cells spread across every window on the ladder — 10:10, 20:19,
    30:18, 50:12, 70:8, 100:6, 140:10, 200:5. A lag effect would cluster. This
    does not, so the third axis earned its run by ruling itself out.

  THE GATE IS NOT IT EITHER

    Holding the price threshold and taking the BEST of all 96 gate settings in
    each panel, measured against that panel's own near-live gate cell:

        sell 80   +0.34  p=0.068      sell 90   +0.03  p=0.082
        sell 85   +1.15  p=0.048      sell 100  +0.00  p=0.025

    Best of 96 reaching p=0.048 is not a finding. And the k axis only rules out
    the tight end: no solid cell sits below k=1.0, all 88 are at 1.5 to 4.0, which
    says do not tighten the gate rather than loosen it.

  IT IS PERCENT_SELL, FOR THE THIRD INDEPENDENT TIME

    Panel by panel at a fixed near-live gate (w=100, k=2.5 -> 0.250), so only the
    price threshold moves and nothing is selected:

        30  -7.92 p=0.80    60  -7.85 p=0.99    85  +3.92 p=0.014
        40  -1.67 p=0.66    70  -0.42 p=0.98    90  +0.96 p=0.040
        50  -6.64 p=0.88    80  +0.99 p=0.019   100 +0.00 p=0.50

    85 is the peak, and 85|100|2.5 also improves the tail: worst -90.7 -> -86.2
    and losing symbols 12 -> 11. sweep_percent_sell scored 85 at +1.87 and
    sweep_sell_slope at +1.89; the figures differ because the reference gate here
    is 0.250 rather than 0.228, the direction does not.

  ONE GENUINELY NEW LEAD, IN THE REGION THAT WAS ADDED ON A HUNCH

    PERCENT_SELL = 30 is the deep-overlap panel — sell zone inside the buy zone,
    churn guard live — and nobody had ever measured it. 30|140|0.0 is the only
    configuration in this study that improves the shape of the distribution rather
    than stretching its top half:

        cell           mean   p25    med   p75    worst  losers  sells
        LIVE 75        52.4   0.0   20.0  53.8    -90.7    12     2.35
        85|100|2.5     50.8   0.1   12.0  64.0    -86.2    11     1.77
        30|140|0.0     68.3   3.3   24.8  70.3   -156.7    10     4.56

    Median UP, p25 up, losers down, mean up, and 4.56 sells per symbol against
    2.35 — the only cell that escapes the dead zone by making the arm act twice as
    often. Paired +10.54, 34/50, p=0.0077, though selected from 12 k values so
    call it p~0.09 after correction. The cost is the tail: worst symbol -90.7 to
    -156.7.

    That is a lead for a dedicated sweep of the overlap regime, not something to
    adopt off this grid. It is a different mechanism and it is being read off the
    edge of a study built for something else.

Usage:
    python single/multi_signal/sweep_sell_slope3d.py             # all symbols
    python single/multi_signal/sweep_sell_slope3d.py FPT GMD     # a subset
    python single/multi_signal/sweep_sell_slope3d.py --rescore
```

## sell_window

Was `sweep_sell_window.py`.

```text
Sweep the SELL arm's median window against its threshold: SELL_MEDIAN_WINDOW x q.

The sell arm compared the price to a 1000-day median because that number was
hardcoded. Buy and reinvest stay at their configured windows; only the sell arm
moves.

WHY q AND NOT PERCENT_SELL

  A fixed percentage is not the same condition at different windows. The price's
  distance from its own median widens as the window grows — 59 symbols, 182,522
  observations per window (single/multi_signal/dispersion.py):

      p95 = 1.290 * w^0.698      R^2 = 0.9991      w in 20..1000

  so the swept quantity is

      PERCENT_SELL = q * 1.290 * w^0.698

  and a column is roughly constant strictness at every window: q = 1.0 is that
  window's 95th percentile of price-to-median distance, q = 0 is "sell whenever
  the price is above its median at all". Live, w=1000 with PERCENT_SELL=60, is
  q = 0.375.

  Note the sign runs the opposite way from the buy sweep. Sell fires on
  pct > threshold, so a LARGER q sells LESS.

WHY THESE q VALUES

  The 1D sweep of PERCENT_SELL at w=1000 already narrowed the interesting band: 65
  to 80 is significant against live on the paired sign test, everything below 60
  and above 85 is not. In q terms that band is 0.41 to 0.50, so the grid is dense
  from 0.1 to 0.6 and thins out after. Negative q is dropped — it means selling
  while the price is below its own median, and the 1D sweep found that region
  uniformly bad (p >= 0.97 at every setting below zero).

WHY THE GRID STOPS AT 1000

  The reinvest arm still guards on index > 1000, so any sell window at or below
  that leaves the backtest start where it is and every cell sees the same symbols
  over the same bars. That floor is the reinvest arm's alone now — the buy arm no
  longer provides it, and the day reinvest gets its own window this stops being
  free.

WHAT IT FOUND: THE WINDOW CONTRIBUTES NOTHING

  52 symbols, 750 cells. Five beat live at p<0.05, and they are five consecutive
  windows all sitting in one q column:

      w     q   PERCENT_SELL   paired      p   nb   sells
    880   0.5           73.3    +3.05  0.004    1    2.12
    900   0.5           74.4    +2.53  0.004    2    2.12
    920   0.5           75.6    +2.23  0.007    2    2.15
    940   0.5           76.7    +1.56  0.007    2    2.12
    960   0.5           77.8    +1.55  0.016    1    2.12

  Those are not five window findings. They are the five windows where q=0.5
  happens to land inside the threshold band the 1D sweep already located, 65..80.
  The window is incidental; the threshold is the finding, and it is ~75.

  Extending q past p95 settled the other open question. The q=1.3 edge of the
  first run was still climbing at short windows, so the grid now runs to 4.0. It
  peaks and turns: at w=20 the mean reads 16, 30, 13, 7, 9, 6 across q = 1.3, 1.6,
  2.0, 2.5, 3.0, 4.0. Nothing in that region is significant against live.

TWO LIMITS OF THIS GRID, BOTH WORTH KNOWING BEFORE TRUSTING nb

  The neighbour count reads 0 everywhere at the 4+ threshold, and that is an
  artefact rather than a verdict. At w=900 the q step spans PERCENT_SELL 59.5 to
  74.4 — fifteen points, which is exactly as wide as the significant band itself.
  A band that wide can only ever occupy ONE column, so counting agreement in two
  directions cannot reach 4. nb only means something when the grid resolves the
  effect in both directions; here it does not.

  And the "live" cell is w=1000, q=0.4, which is PERCENT_SELL 64.1 rather than
  the actual 60 — the grid cannot express 60, that would need q=0.375. So every
  comparison in this table is against 64.1. It is why w=1000/q=0.5 reads p=0.063
  here while the 1D sweep's 80-against-60 reads p=0.036.

WATCH THE BUY COUNT

  With different windows on the two arms the buy and sell conditions stop being
  complementary even at equal percentages: the price can be 60% above its
  1000-day median and only 20% above its 200-day one. So the churn guard fires
  across most of this grid rather than in a corner of it, and the buys column
  falling is the guard working, not the strategy improving.

Usage:
    python single/multi_signal/sweep_sell_window.py             # all symbols
    python single/multi_signal/sweep_sell_window.py FPT STB     # a subset
    python single/multi_signal/sweep_sell_window.py --rescore
```

## zdev

Was `sweep_zdev.py`.

```text
Sweep the z_dev sell gate: SELL_ZDEV_WINDOW x SELL_MIN_ZDEV.

The one gate never measured on its own. It is currently OFF, so this sweep turns
it back on cell by cell; everything else stays at its configured value.

WHY IT WAS TURNED OFF, AND WHY THAT IS NOT AN ANSWER

  z_dev was switched off in 73b7ce6 for a reason that had nothing to do with its
  merit: a 700-bar stat window on top of the 1000-bar median put the backtest
  start at 1699 and cost 12 of 57 symbols. A quarter of the universe for one gate.

  The performance figure quoted alongside it, mean -2.50, was signal3 AND z_dev
  measured together. signal3 alone has since measured at +6.04, so that -2.50
  cannot be read as z_dev's, and it cannot be subtracted out either — overlapping
  gates do not compose additively.

  So the open question is narrow and specific: at a SHORT stat window, where the
  warmup is affordable, does this gate earn anything?

NO NORMALISATION — MEASURED, NOT ASSUMED

  z_dev is a z-score, so its spread should not depend on the stat window, and it
  does not: p95 = 2.218 * w^0.009 with R^2 = 0.27, which is a flat line with
  noise (dispersion.py zdev). Percentiles are steady across w = 50..700:

      p5     p25     p50     p75     p95
      -2.30  -1.18   -0.15   +1.05   +2.31

  Note the distribution is WIDER than a unit normal, ±2.3 rather than ±1.64, and
  the centre sits slightly below zero. So the raw threshold is directly
  comparable across windows — no k/sqrt(w), no q. This is the one quantity of the
  four in dispersion.py that needed no reparameterisation.

  The old 0.9 blocked a sell whenever z_dev was at or below it, which off that
  distribution is roughly 72% of sell-eligible days. Very restrictive.

POLARITY

  Opposite to the two momentum gates. They block while a reading is HIGH ("trend
  intact, hold"); this one blocks while z_dev is LOW, because a low reading means
  the price is above its trailing median only because the business grew into it
  rather than because it is dislocated. So a HIGHER threshold blocks MORE and
  sells LESS — the reverse of MIN_SIGNAL3 and SELL_MIN_SIGNAL1.

THE WINDOW IS CAPPED AT 400 ON PURPOSE

  Every cell shares one start index, fixed at 1000 + the longest swept window, so
  no cell is judged on more bars than its neighbour. That makes the cap a direct
  cost: 400 puts the start at 1400 and leaves ~50 symbols, against 52 today.
  Including the old 700 would push it to 1700 and take the same 12 symbols that
  caused the gate to be switched off in the first place — which is exactly the
  hypothesis under test, so it is excluded rather than paid for.

WHAT IT FOUND: NOTHING, AND NOW THAT IS MEASURED

  50 symbols, 66 cells plus the off cell, 6.5 min. Reference is the gate off:
  mean +38.16, median +15.25, 1.92 sells per symbol.

  Not one cell beats it. 62 of the 66 have a paired median of exactly 0.00 — at
  almost every setting the gate changes nothing for the typical symbol. The single
  cell reaching p<0.05, w=100 with min_zdev -1.5, has 5 decided symbols out of 50;
  all five improve, for a mean of +1.84. With 66 cells about three would reach
  p<0.05 by chance.

  The strict end is the only place with a real effect and it is the wrong sign: at
  min_zdev >= 2 the gate blocks most sells (1.92 per symbol down to 0.58) and the
  mean falls to between -20 and -30.

  So the answer to the question this sweep existed for — does it earn anything at
  a stat window short enough to afford — is no. The gate stays off.

Usage:
    python single/multi_signal/sweep_zdev.py             # all symbols
    python single/multi_signal/sweep_zdev.py FPT STB     # a subset
    python single/multi_signal/sweep_zdev.py --rescore
```
