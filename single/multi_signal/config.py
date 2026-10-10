"""
Median1000 strategy configuration.
Edit these parameters to tune the analysis, then re-run run_one.py or run_all.py.

None SWITCHES A CONDITION OFF — see single/multi_signal/factory.py, which is the
one place that implements it. Two kinds, and "off" means something different
for each:

  Filters      MIN_SIGNAL3, SELL_MIN_SIGNAL1, SELL_MIN_ZDEV, REINVEST_MIN_SIGNAL1
               None removes a restriction, so the arm acts MORE often. The
               signal is then not loaded at all, which also stops its warmup
               from pushing the backtest start index forward.

  Conditions   PERCENT_BUY, PERCENT_SELL, PERCENT_REINVEST
               None replaces the whole arm with its neutral base class:
               buy every interval / never sell / never reinvest.

Setting all three PERCENT_* to None makes the median1000 arm identical to the
interval arm, so every diff must come out at 0.00 — a cheap engine check.
"""

INTERVAL_MONEY = 8_000_000   # VND invested per interval

# Trading costs, in percent of each trade. Zero is how every number recorded in
# this package was measured, so it stays the default. Realistic for HOSE is about
# 0.15 on a buy (brokerage) and 0.25 on a sell (brokerage plus the 0.1% tax).
# The DCA arm pays the buy cost on every monthly purchase as well.
BUY_COST_PCT = 0.0
SELL_COST_PCT = 0.0

# BuyMedian1000: which median the buy arm measures the price against. The sell arm
# has its own (SELL_MEDIAN_WINDOW below); reinvest is still fixed at 1000. Not a
# condition, so the None convention does not apply — it is a size.
# PERCENT_BUY below is not transferable across values of this: the price's
# distance from its own median grows as p95 = 1.29 * w^0.698, so 60 blocks
# nothing at w=50 and about a fifth of days at w=1000. See dispersion.py.
# Keep it <= 1000 unless you mean to move the backtest start. The reinvest arm
# still needs 1000 bars of warmup, so anything at or below that is free — but
# that floor disappears the day reinvest gets its own window too.
# Swept 20..1000 against the threshold, 500 cells over 52 symbols. This barely
# matters: taking the best threshold in each row, the mean spans 36.5 to 41.1
# across a 50x change in window. The good region is w=500..1000 and 1000 is
# inside it, 0.2 mean points off the best cell. Left where it was. Nothing above
# 1000 is worth trying — the top rows are flat, not climbing.
BUY_MEDIAN_WINDOW = 1000

# BuyMedian1000: buy while price is BELOW median x (1 + PERCENT_BUY/100).
# Read the sign carefully: the code tests (price - median)/median*100 < this, so
# 60 means "buy unless the price is more than 60% ABOVE the median" — a permissive
# condition that buys nearly every interval, not "buy when 60% below".
# Confirmed twice, and this one does matter unlike the window beside it. Swept
# alone at w=1000 it was the best of 19 settings on both mean and vote; swept
# again as part of the 2D window x threshold grid, every one of the top ten cells
# is the column 60 sits in. See SWEEPS.md, buy_window.
PERCENT_BUY      = None

# SellMedian1000: which median the sell arm measures the price against. The
# reinvest arm is still fixed at 1000 and does not follow this — which is also
# what keeps the backtest start index from moving when this drops below 1000.
# PERCENT_SELL below is not transferable across values of this; see dispersion.py.
# Swept 20..1000 against 15 thresholds, 750 cells (SWEEPS.md, sell_window). The
# window contributes nothing: the only five cells that beat live are five
# different windows all landing on the same THRESHOLD band, 73 to 78. Same
# conclusion the buy window reached.
SELL_MEDIAN_WINDOW = 1000

# SellMedian1000: sell when price is this % above the SELL_MEDIAN_WINDOW median.
# Raised from 60 — the arm was selling too early. Three independent grids agree:
#
#   1D, step 5 at w=1000     65..80 significant against 60, p from 0.000 to 0.036
#   1D refined 60..110       the band is exactly 65, 70, 75, 80; 85 and up is not
#   2D, 750 cells            the only 5 cells beating live are PERCENT_SELL 73..78
#
# Paired per symbol against 60, +75 is 31/45 symbols with a median of +5.25 and
# p=0.008. Unlike most findings here the evidence is BROAD, not carried by one
# symbol: 29 to 35 of ~45 symbols improve across the whole band. The mean is
# still one-symbol business — HPG alone is +425 — so quote the median and count.
#
# Mechanism: sells fall from 4.3 to 2.3 per symbol and the worst symbol improves
# from -238 to -101. Three gates were bolted onto this arm to restrain selling,
# and it turns out the price condition itself was the thing to loosen.
#
# UNRESOLVED, and left unresolved deliberately: the 2D sweep against
# PERCENT_REINVEST found 85 beating 75 with a paired median of +1.89 and p=0.000,
# 29 symbols up against 8 down. Not adopted — no cell there has more than 2
# agreeing neighbours, 3 of 70 cells reach p<0.05 and about 3.5 would by chance,
# and +1.89 is small beside a live mean of +52.
#
# It also looks like it contradicts the refined 1D grid above, and does not:
# that one paired against 60, this one against 75, and paired medians do not
# chain. median(85-60) is not median(85-75) + median(75-60), so 85 can fail
# against 60 and win against 75 at the same time. Settling this needs a grid
# paired against 75 with enough resolution for neighbours to agree or not.
PERCENT_SELL     = 55

# SellMedian1000: a SECOND price condition, AND'd with PERCENT_SELL — sell when
# the price is this far above the SELL_MEDIAN_WINDOW LOW as well as above its
# median. None switches it off and the arm behaves exactly as before.
#
# It was OR'd until it became the only OR in a list of ANDs. AND'ing it makes the
# arm act LESS often, not more, so setting it now RESTRAINS the arm — the
# opposite of what the sweep that introduced it was measuring.
#
# The reason to try it is the reason the filters failed. Three separate attempts
# to quiet this arm — SELL_MIN_ZDEV, PERCENT_SELL x PERCENT_REINVEST, and
# SELL_MIN_PELOG — each fixed the symbol they were built for and each lost across
# the portfolio, because the arm is net positive and restraining it pays the
# majority to rescue the minority. The question none of them asked is the
# opposite one.
#
# What it can catch that the median cannot: a symbol that doubles off its floor
# while the median chases the price up, so the distance to the median never opens
# and the arm stays quiet the whole way.
#
# Costs no warmup — local_bottom comes from the same range_stats row the median
# already does.
#
# SWEPT ON ITS OWN, with the median trigger off so PERCENT_SELL took no part
# (SWEEPS.md, sell_bottom). It is a real signal: 3 of 18 thresholds beat having no
# trigger at all with p<0.05, and at its best it lifts the mean from +5.17 to
# +51.4. That is more than the four previous attempts on this arm managed between
# them, and 225 is the only cell in any of them with both neighbours agreeing.
#
# It is still the weaker of the two price tests, on three counts:
#
#     condition            mean   median    worst   sells
#     median 75 (live)   +52.38   +20.14    -90.7    2.35
#     bottom 350         +51.44    +4.27   -243.2    1.50
#
#   - within a point on mean, four-fold apart on median: the bottom trigger keeps
#     up only through a few large winners (VND +424, HPG +349) while the typical
#     symbol does much worse
#   - three isolated cells out of eighteen, where about one reaches p<0.05 by
#     chance, against a contiguous four-setting band for PERCENT_SELL
#   - it creates a tail disaster the median condition does not. LPB: +84.1 with no
#     trigger, -90.7 under the median condition, -257.6 at bottom 225
#
# Untested and still open: the OR of both, which is what the arm implements.
PERCENT_SELL_BOTTOM = None

# ReInvestMedian1000: reinvest while price is BELOW median x (1 + PERCENT_REINVEST/100).
# Same sign as PERCENT_BUY, not "below the median": 10 means "up to 10% ABOVE it".
# Swept over 14 settings and 52 symbols (SWEEPS.md, percent_reinvest). 10 is the
# peak of a cleanly unimodal median curve and also wins the mean and the win rate.
# The safe region is wide, -5 to +35 all give a median of 16 to 21, so this does
# not need to be right to the point. Above +50 it collapses: redeploying
# constantly means holding more shares, which triggers more sells — reinvests run
# 4.4 to 22.9 and sells 4.3 to 11.8 across the top of the grid.
#
# This arm matters far more than its trade count suggests. It carries 94% of all
# capital deployed (median over 52 symbols), because a blocked buy goes into the
# reserve and the reserve only leaves through here. Setting this to None costs 78
# mean points.
#
# Re-swept at PERCENT_SELL = 75 (the first sweep ran at 60) and 10 still wins. A
# round robin over all 35 reinvest configurations from this sweep and
# sweep_reinvest_top puts it first on 23 head-to-head wins, with 23 of the other
# 34 losing to it significantly.
#
# Re-tested JOINTLY with PERCENT_SELL (SWEEPS.md, sell_reinvest), because the two
# are coupled: the distance between them is a band the money cannot return
# through, and 10 was chosen while PERCENT_SELL was still 60. Widening that band
# to 65 turned out not to matter — 10 survives at the new sell level, and every
# cell that beats live does so at reinvest=10 unchanged.
#
# The coupling is real but points the other way from what was expected. Raising
# this closes the dead zone and hands re-entry back to the price condition, with
# reinvests going 3.96 -> 7.15 -> 16.63 at 10, 60 and 80. That is worse, not
# better: at reinvest=60, 15 symbols improve and 34 decline, paired median -4.85.
# The band is protecting the portfolio. What it costs is FPT and GMD, which gain
# +91 and +428 there and are the two worst long-history losses today.
PERCENT_REINVEST = None

# ReInvestMedian1000: a SECOND price condition, AND'd with PERCENT_REINVEST —
# redeploy once the price has fallen this far from the 1000-bar HIGH as well as
# having come back to its median. Was OR'd; see PERCENT_SELL_BOTTOM above.
#
# Same comparison direction as PERCENT_REINVEST (reinvest while dev is BELOW the
# threshold), but measured against the top, where dev is always <= 0. So the
# threshold is negative: -30 reads as "at least 30% off the high". None switches
# it off and the arm behaves exactly as before.
#
# WHY IT MIGHT WORK WHERE WIDENING PERCENT_REINVEST DID NOT
#
# The dead zone is the real problem: after a sell at +75% over the median the
# price has to fall 65 points before the money may return, and on a compounder it
# never does, so the 400-bar timeout buys back higher than it sold. Widening
# PERCENT_REINVEST was the obvious fix and it lost — 15 symbols up against 34 down
# — because it lets money back in UNCONDITIONALLY, on symbols whose price simply
# stayed high. A drawdown condition is selective: it only opens after a real fall
# from the peak.
#
# Measured on the seven FPT and GMD re-entries, bars until each condition first
# allows a buy-back (the timeout fires at 400):
#
#     sell            dev vs top   median<=10   top<=-30   top<=-40
#     FPT 2015-11-03      0.0%        1101        1101       2583
#     FPT 2018-01-29     -2.9%         538         538       2020
#     FPT 2022-01-19    -11.7%        1022         204       1026
#     FPT 2025-04-18    -27.7%         215         112        219
#     GMD 2017-03-07      0.0%         332         286        726
#     GMD 2021-06-17      0.0%         950         355        951
#     GMD 2023-02-03     -8.9%         543         542        544
#
# At -30, four of the seven re-entries happen on the price condition instead of
# the clock, and much sooner — 204 bars instead of 1022, 355 instead of 950. The
# three it does not help are the ones that sold AT the high (dev vs top 0.0%),
# where the top keeps chasing the price and the gap never opens.
#
# -40 is useless and -10 or -20 are far too loose: the existing condition already
# fires on 35.7% of days, and -10 would add 42 points on top of that. The usable
# band is roughly -25 to -35, where it adds 8.6% of days for the median symbol.
#
# THE RISK, AND IT IS MEASURABLE. By construction the days this adds are days the
# price is still >= 10% above its own median — it buys into a fall that has not
# finished being expensive. Whether the drawdown condition is selective enough to
# beat the unconditional widening that already failed is exactly what the sweep
# has to answer.
#
# Costs no warmup — local_top is on the same range_stats row as the median.
#
# SWEPT, AND IT TIES. 20 thresholds against a reference that keeps the timeout and
# only drops this trigger. 1 of 20 clears p<0.05 and 9 have a paired median of
# exactly 0.00. Against live it is 21 symbols up and 22 down, paired median +0.00,
# p=0.620.
#
# It has the best aggregate of any reinvest setting measured — mean 55.79 and
# median 22.04 at -50, against live's 52.38 and 20.14 — but that lead is three
# symbols wide: VND +430, HPG +265, HAG +240, with the typical symbol unmoved.
#
# A round robin over all 35 reinvest configurations from both sweeps puts live
# first on 23 wins and -50 second on 21. Exactly one setting beats live at p<0.05
# and it does so by +0.01 of a point.
#
# Worth remembering rather than deleting: every TOP cell has a worst symbol near
# -121 where nearly every PERCENT_REINVEST cell sits at -155.7. The drawdown
# trigger has a better tail than the level one. It is the only one of the four new
# parameters that improves something without a compensating disaster.
PERCENT_REINVEST_TOP = None

# Timeout reinvest: if no reinvest has occurred X trading days after last sell,
# release the reserve using a looser threshold, on the same scale as
# PERCENT_REINVEST above (so -10 = only if 10%+ BELOW the median).
#
# Swept over 14 settings and 52 symbols (SWEEPS.md, reinvest_timeout). Nothing beats
# 400 and there is only one way to get it wrong: too short. At 20 days the arm
# loses 17 paired points on 13/49 symbols, with releases at 27.3 and sells at 12.1
# — constant redeployment means holding more shares, which triggers more selling.
# From 190 days up the paired median is exactly 0.00 at every setting, and past
# 1200 the rows are identical because the valve fires once and never again.
#
# Switching it off is indistinguishable from 400 too: 23/48 symbols, paired median
# 0.00, p=0.667, with half the releases. Kept anyway — it is insurance for a
# regime where the price condition stops firing, and it currently costs nothing.
#
# Note the aggregate median peaks exactly here at +20.0 with 15.8 and 12.1 either
# side, which looks like a fine-tuned optimum and is not: paired, both neighbours
# are 0.00.
REINVEST_TIMEOUT_DAYS    = 400   # (0 = disabled)
REINVEST_TIMEOUT_PERCENT = 999   # 999 is effectively no price condition at all:
                                 # once the timeout is reached, reinvest regardless.
                                 # Deliberately not swept — the intent is that the
                                 # timeout alone decides, with no price test.

USE_PE = False   # use P/E-adjusted median instead of price median

# SellMedian1000: block the sell while the P/E is NOT stretched, measured as
# ln(P/E / its own PE_MEDIAN_WINDOW median). Blocks when that is <= the threshold,
# so a HIGHER value blocks MORE — the same polarity as SELL_MIN_ZDEV and the
# opposite of the two momentum gates. None switches it off.
#
# WHY IT EXISTS. The price condition cannot tell "expensive" from "the business
# grew into the price", and on a compounder that costs real money. FPT is 85.03
# points behind buying at every interval, on four sells where the price was 77%
# to 125% above its median while the P/E was barely above its own:
#
#     sell date     price vs median    P/E vs median    ln(P/E/median)
#     2015-11-03         +77.5%            +63.6%           0.492
#     2018-01-29         +82.0%             +7.4%           0.071
#     2022-01-19        +125.3%            +65.7%           0.505
#     2025-04-18         +77.7%             +1.7%           0.017
#
# So a threshold of 0.51 blocks all four; 0.07 blocks the two where earnings had
# fully caught up. Over FPT's whole history the price condition fires on 926 days
# and the P/E one on 217.
#
# SWEPT, AND IT LOSES. 52 symbols, 16 thresholds against the gate being off
# (SWEEPS.md, pelog). Not one beats it, and 13 of the 16 have a paired median of
# exactly 0.00.
#
# The mechanism is not in doubt — at a threshold of 0.30 it does precisely what it
# was built to do, and to more than the two symbols it was built from: FPT -85.0
# to +3.2, LPB +116, DPM +108, GMD +96, CTG +93. LPB is the worst symbol in the
# run and nothing else had ever moved it.
#
# It loses on the bill. 19 symbols up and 21 down, and the damage is both larger
# and more concentrated than the gain: HPG -340 alone is 36% of it, then VND -197
# and SHB -138. Total +833 against -945, net -112.
#
# Two things in that make it clear the gate is not selective, only quiet. FPT's
# rescue comes from taking its sell count from 4 to 0. And VND loses 197 points
# with its sell count UNCHANGED at 1 — the gate blocked the right day and the sell
# landed on a worse one, so it delays sells as well as preventing them.
#
# Left off. See sell.py before considering a fourth gate of this shape: this is
# the third such attempt and all three failed the same way.
SELL_MIN_PELOG = None

# Which median the P/E is measured against. NOT tied to BUY/SELL_MEDIAN_WINDOW:
# the two norms answer separate questions about separate series, and matching them
# for symmetry turned out to cost more than the symmetry is worth.
#
# SELL_MIN_PELOG does not transfer across this. p95 = 0.094 * w^0.360, so the
# spread runs 0.681 at w=250 and 1.114 at w=1000 (dispersion.py pelog).
#
# The gate needs a FULL window of P/E observations before its median means
# anything — range_stats builds these with min_periods=1, so it happily reports a
# median of one observation, and on the first day a symbol has P/E the median IS
# that day's P/E, making ln(P/E/median) exactly 0.000. A gate reading "perfectly
# normal" when it knows nothing is worse than one reading nothing at all. 31 of
# the 59 symbols have P/E starting later than their price, so this is 13,312 rows.
#
#     window   symbols   median eval bars   cost vs off
#       off       54          2,816              -
#       250       54          2,638            178
#       500       53          2,556            260
#      1000       52          2,149            667
#
# Picked 500 over 1000 on evidence, not taste. A longer window does not make the
# case stronger, only more expensive: to block all four of FPT's sells needs a
# threshold at the 79th percentile of the distribution at w=500 and the 90th at
# w=1000, while w=1000 also costs two symbols and a quarter of the evaluated bars.
#
#     FPT sell      w=250   w=500   w=750  w=1000
#     2015-11-03     0.175   0.181   0.241   0.492
#     2018-01-29    -0.078   0.021   0.049   0.071
#     2022-01-19    -0.115   0.262   0.448   0.505
#     2025-04-18    -0.304  -0.077   0.032   0.017
#     blocks all 4   0.175   0.262   0.448   0.505
#
# Picked 500 over 250 on one substantive argument: a valuation anchor should be
# slow. At 250 the median re-rates within a year, so a stock that stays expensive
# for a year becomes "normal"; at 500 that takes two. 250 is cheaper (no symbol
# lost, 178 bars) and is the fallback if the cost ever bites. Provisional either
# way — this deserves to be a sweep axis once the threshold has been swept alone.
PE_MEDIAN_WINDOW = 500

# Minimum bars a symbol must have AFTER the start index (see run_all.py) to be
# reported. Not total history — the existing len(df) < 1010 check covers that.
# Below this there is too little post-warmup data for the result to mean anything:
# the strategy may make no trades at all, and every short symbol ends up testing
# the same recent months, so they add correlated noise rather than evidence.
# 0 disables the guard.
MIN_EVAL_BARS = 500

# Where report_all.html splits its summary into long-history and short-history
# symbols. A reporting boundary, not a strategy parameter — nothing in the
# backtest reads it.
#
# The two groups are not comparable evidence and averaging over both hides it:
# on the 52-symbol run the long group's median per-symbol diff was +31.3 and the
# short group's +9.2. Worse, the short symbols nearly all start in the same year,
# so they are 16 readings of one market period rather than 16 independent ones.
#
# 2000 is not a round number chosen for neatness — the universe is genuinely
# bimodal and this sits in the gap. Sorted evaluated bars run 682..1420, then
# jump to 2021..2816. That 601-bar gap is four times the largest gap inside
# either group, so the boundary is insensitive to where in it you put the line.
# The report says which gap the threshold landed in and warns if it ever stops
# being a gap; re-read it after the universe changes.
LONG_HISTORY_BARS = 2000

# Symbols kept out of every aggregate. Not a data-quality guard like the one
# above — these are excluded by judgement, so the reason belongs here in writing.
#   VIX — has been ~30% of total gains in every run; the mean diff largely
#         tracked it rather than the strategy, and it swung from -35 to +702
#         on a single signal1 parameter change.
#   VIC — the mirror case on the loss side (-458 in one run, larger than the
#         entire net), so removing only the big winner would bias the result.
# They are still computed and still written to the sweep's raw JSON; only the
# aggregation drops them, so the decision stays reversible without a re-run.
EXCLUDE_SYMBOLS = ["VIX", "VIC"]

# SellMedian1000: block sell when 1000-day Sharpe (signal3) is above this —
# stable/trending regime, so let it run. Higher blocks fewer days and sells MORE,
# the same polarity as the signal1 sell gate.
#
# Swept at last: 16 settings, 52 symbols (SWEEPS.md, min_signal3). Nothing beats
# 1.1 and it is the mean peak (+52.4). The old figure of -2.50 was signal3 and
# z_dev measured together, and z_dev has been off since 73b7ce6, so it never said
# anything about this gate alone.
#
# The shape matters more than the value. Below +0.45 the gate is destructive: it
# blocks nearly every day, the arm stops selling entirely (0.0 sells) and the
# paired loss reaches -16.1. From +0.45 to +1.1 the surface is flat — paired 0.00
# throughout — so the exact value inside that band is not doing work. Above +1.1
# the tail gives way: the worst symbol goes from -91 to -225.
#
# Keeping the gate is worth about 6 mean points. Off, the net is -314 (+148
# gained, -462 lost) and even without the largest mover it is -3.39. Concentrated
# as usual: 34 of 52 symbols are untouched. What it mainly does is protect LPB,
# which runs -91 with the gate and -225 without; HPG -141 and FPT -102 also
# depend on it, while GMD gains +126 from its removal.
#
# No k/sqrt(w) normalisation: the gate always reads window 1000, so one scale
# throughout. Adding MIN_SIGNAL3_WINDOW would change that — Sharpe narrows sharply
# with the window, p95 = 124.6 * w^-0.654 (dispersion.py) — so normalise before
# ever sweeping the window.
# ON AGAIN BY DEFAULT since 2026-10-10, at the reader's request. It was switched
# off by default in 457121a; the case that prompted that is kept below.
# VCS peaked around 76,000 in December 2017 at
# +587% over its own 1000-bar median -- nearly eight times the sell threshold --
# and the arm never sold. Three gates blocked it, and they never cleared
# together: the basket reached 70 in January 2018, signal1 fell below 0.228 in
# February, and signal3 stayed between 2.7 and 3.6 until 30 December 2019.
# Across the whole of VCS's history, ZERO days satisfied all four conditions.
#
# That is the gate working as designed -- "do not sell a symbol whose 1000-bar
# Sharpe is still high, let it run" -- and on VCS the design was wrong: the
# price fell for years afterwards. It is also why VCS was the worst symbol for
# the hybrid configuration against breadth, -118 points, since breadth switches
# this gate off and could therefore sell.
#
# The measurements below were taken with the gate ON and are kept as the record
# of what it was worth then. Re-measure before trusting them now.
#
MIN_SIGNAL3 = 1.1

# SellMedian1000: block sell when short-term momentum slope (signal1) is above this — momentum still up → hold
SELL_SIGNAL1_WINDOW = 120    # trading days for the slope window
SELL_MIN_SIGNAL1   = 0.228   # % per day, = k/sqrt(window) with k=2.5 at window 120.
                            # The one sell filter that earns its keep, re-confirmed
                            # on the current 52-symbol basis after PERCENT_SELL rose
                            # to 75. Switching it off costs mean -21.06 and a net
                            # -1095 across the universe (+336 gained, -1431 lost);
                            # even dropping the largest mover leaves -7.58.
                            #
                            # Concentrated, as it has always been: 25 of 52 symbols
                            # are untouched at any setting. And the effect is in the
                            # TIMING, not the count — switching it off moves sells
                            # only from 2.35 to 2.73 per symbol, and those 0.4 sells
                            # are worth 21 points. Quote both halves or it misleads.
                            #
                            # The value survived a clean re-sweep: 340 cells over 52
                            # symbols, paired against this cell, and nothing beats it
                            # meaningfully. The best rival is +1.35 at w=50 and the
                            # other four significant cells are +0.01 to +0.22 — real
                            # by the sign test, worthless in points, and all in the
                            # short-window region where a block only postpones a sell
                            # rather than cancelling it (36-day blocks at w=10
                            # against 293-day blocks at w=100).
                            #
                            # That re-sweep replaces the earlier one that produced
                            # this number. The old grid was measured on 44 symbols
                            # with z_dev on, and it moved the reinvest window along
                            # with the sell window in every cell — so its "w=110-130,
                            # k=2-3" region could not be read as stated. The value
                            # happens to have held up anyway.

# SellMedian1000: block sell when relative valuation (z_dev) is at or BELOW this —
# the price is above its trailing median only because the business grew into it,
# not because it is dislocated, so do not sell. Note this is the opposite
# comparison to the two momentum filters above: there a high reading means "trend
# intact, hold", whereas a high z_dev is the reason to sell.
# Set SELL_MIN_ZDEV = None to disable. Window is the z_dev stat_window to read.
#
# OFF, and the honest reason is the warmup, not a performance number.
#
# A 700-bar stat window on top of the 1000-bar median put the backtest start at
# 1699, and 12 of 57 symbols were skipped for it — six with no z_dev at that
# window at all, six with too few bars left afterwards. A quarter of the universe
# spent on one gate.
#
# Now measured on its own, which it never had been (SWEEPS.md, zdev). The -2.50
# once written here was signal3 AND z_dev together, and signal3 alone has since
# measured at +6.04, so that figure said nothing about this gate.
#
# 66 cells, stat windows 50..400 where the warmup is affordable, thresholds
# -2.5..+2.5, every cell paired against the gate being off. NOT ONE beats it, and
# 62 of the 66 have a paired median of exactly 0.00 — the gate does nothing for
# the typical symbol at almost any setting. The single cell reaching p<0.05
# (w=100, -1.5) moves 5 of 50 symbols by a mean of +1.84; with 66 cells about 3
# would reach p<0.05 by chance.
#
# The strict end does have an effect and it is the wrong one: at min_zdev >= 2 it
# blocks most sells, 1.92 down to 0.58 per symbol, and the mean falls to between
# -20 and -30.
#
# So the gate stays off for a measured reason now, not an inherited one. Its
# original cost stands too: a 700-bar stat window put the backtest start at 1699
# and took 12 of 57 symbols.
#
# The computation itself is sound — no look-ahead, verified three ways — and
# z_dev is the one quantity in dispersion.py needing no reparameterisation, being
# a z-score: p95 = 2.218 * w^0.009, R^2 = 0.27, flat across stat windows.
SELL_ZDEV_WINDOW = 700    # stat_window in valuation_zdev (median_window is fixed
                          # at 1000). Only read when the gate below is on.
SELL_MIN_ZDEV    = None

# ReInvestMedian1000: require the slope to have turned up before redeploying the reserve.
# Inverse polarity to the sell gate above: sell is BLOCKED while momentum is up, reinvest
# is only ALLOWED once momentum is up.
#
# OFF, and its premise is what the sweep rejected. 340 cells over 52 symbols
# (SWEEPS.md, reinvest_signal1): not one beats switching the gate off, and the mean
# falls monotonically as the gate gets stricter — at w=100, k=-4 scores 45.9 and
# k=+4 scores 16.4. "Wait for momentum to turn before redeploying" costs 29 points
# across the grid. Redeploying immediately is better; idle cash earns nothing.
#
# Mean spans 31 points across that grid while the reinvest COUNT spans 0.4 (3.1 to
# 3.5), so the gate never changed how often the arm acts — only when. It could
# never block anything outright either: REINVEST_TIMEOUT_DAYS releases the reserve
# regardless.
#
# Set a float to switch it back on. The direct off-against-old comparison is only
# +4.85 mean and 88% of that is STB alone (+0.61 without it), 20/38 symbols,
# p=0.436 — the monotone trend is the evidence, not that number.
REINVEST_SIGNAL1_WINDOW = 100    # kept for when the gate is switched back on
REINVEST_MIN_SIGNAL1    = None


# ── The basket, as a signal source ────────────────────────────────────────────
#
# Gates on all three arms, read from the breadth_signals table. None switches a
# gate off. See core/breadth_calc.py for how the number is built.
#
# BUY_MAX_BREADTH      buy only while the basket's BREADTH_SIGNAL is at or below
# SELL_MIN_BREADTH     sell only when it is above
# REINVEST_MAX_BREADTH put the reserve back only when it is at or below
#
# ALL THREE ARE ON. The buy and reinvest arms run on the basket ALONE --
# PERCENT_BUY and PERCENT_REINVEST are None, so those arms have no price
# condition left and the gate below is their whole test. That is the "breadth"
# profile for those two arms.
#
# THE SELL ARM IS THE EXCEPTION and keeps both: the symbol's own price above its
# median by PERCENT_SELL, AND the basket above SELL_MIN_BREADTH, AND the signal1
# and signal3 gates. It is the arm the sweeps found the basket helps most (+108,
# against +1.1 on the buy arm), and the one place where asking the symbol as
# well is worth the extra condition.
#
# 80 IS THE TOP OF A 80-85 PLATEAU, AND 90 WAS A HOLE. Swept twice on
# prem_median over the all-VIC-VIX basket, 52 symbols, once with PERCENT_SELL=55
# and once with it off, because a threshold measured with the price condition
# removed says nothing about the same threshold when the two are AND'd:
#
#     vs 90        PERCENT_SELL=55            PERCENT_SELL=None
#     80        +1,102  20/29  p=0.031     +1,248  31/42  p=0.001
#     85          +890  20/28  p=0.018     +1,144  29/39  p=0.002
#
# Both runs agree, so 90 was the wrong pick -- it sat between two better regions
# rather than on a plateau. 80 then tops the grid on mean and total in both runs,
# but the sign test does not separate it from any neighbour (85 is +4.1 and +2.0
# behind at p=0.42 and p=0.56): 80 wins on size, not on count, and 85 would be
# the same setting by any honest reading.
#
# WHAT THE PRICE CONDITION DOES TO THIS GRID. With PERCENT_SELL=55 the paired
# median against 90 is exactly 0.00 at EVERY threshold, and only 28 of 52
# symbols move at all; with it off, 39 move. The price condition already blocks
# most sells, so the basket gate only reaches a minority and the whole effect
# lives there. Comparing 55 against None directly at each threshold gives p from
# 0.79 to 1.00 with a paired median of exactly 0.00 -- on this history the extra
# price condition on the sell arm does not distinguish itself either way.
#
# Everything from 110 up is not a threshold at all: prem_median never reaches it
# on this basket, sells fall to 0.0 and mean collapses to +9.4. That is the arm
# switched off, and it is why the grid ends there.
#
# NOTE THIS CHANGES WHAT config.py ALONE MEANS. It used to be the "price"
# profile by definition; that profile now spells out the whole price
# configuration so the measurements in CONCLUSIONS.md stay reproducible under
# that name whatever the shipped default becomes.
BUY_MAX_BREADTH = 60.0
SELL_MIN_BREADTH = 80.0
REINVEST_MAX_BREADTH = 10.0

# Reinvest: join the price source and the basket source with OR instead of AND.
# Measured and rejected (see the class comment); kept switchable because the
# result -- that AND is doing the work of a rate limiter -- is worth being able
# to re-test rather than take on faith.
REINVEST_JOIN_OR = False

# Which stored breadth run to read. Must match what syncs/breadth.py wrote; see
# core/breadth_calc.py::variant and ::universe_key.
#
# THE BASKET NAME SAYS WHAT IS IN IT. "all" is every stock; "all-VIC-VIX" is
# every stock without those two. Both are stored, so switching is a config
# change rather than a re-sync.
#
# "all-VIC-VIX" is the shipped value because it is what every measurement in
# CONCLUSIONS.md was taken on -- those rows used to be filed under the name
# "all", which was wrong. Pointing at the true "all" is a legitimate choice and
# a different experiment; it is not the same numbers under a tidier name.
BREADTH_UNIVERSE = "all-VIC-VIX"
BREADTH_WINDOW = 1000
BREADTH_SIGNAL = "prem_median"


# ── The index trend, as a signal source ───────────────────────────────────────
#
# The classic trend filter, read from the index rather than from the symbol:
# see trend_map.py. Gates on all three arms, each switched off by None, so the
# shipped config and every profile that does not name them are unchanged.
#
# TREND_SIGNAL   "ma200"   index close vs its 200-bar MA, in percent
#                "mom12_1" index return from 252 to 21 bars ago, in percent
#
# BUY_MIN_TREND       buy only while the reading is at or above this
# SELL_MAX_TREND      sell only while it is BELOW this -- the trend has broken
# REINVEST_MIN_TREND  reinvest only while it is at or above this
#
# 0 / 0 / 0 is the textbook rule: in while the index is above its MA (or up
# over the year), out while it is below. The "trend" profile runs exactly that.
#
# MEASURED AND NOT ADOPTED (SWEEPS.md, trend). The textbook rule loses to DCA:
# median -8.3 on ma200, 44% of symbols beat DCA, 29 sells per symbol, and -13.9
# once costs are charged. As a gate on the breadth sell it lowers the mean at
# every threshold. All three stay off.
TREND_INDEX = "VN30"
TREND_SIGNAL = "ma200"
BUY_MIN_TREND = None
SELL_MAX_TREND = None
REINVEST_MIN_TREND = None
