"""
Median1000 strategy configuration.
Edit these parameters to tune the analysis, then re-run run_one.py or run_all.py.

None SWITCHES A CONDITION OFF — see analyze/median1000/factory.py, which is the
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
# is the column 60 sits in. See sweep_buy_window.py.
PERCENT_BUY      = 60

# SellMedian1000: which median the sell arm measures the price against. The
# reinvest arm is still fixed at 1000 and does not follow this — which is also
# what keeps the backtest start index from moving when this drops below 1000.
# PERCENT_SELL below is not transferable across values of this; see dispersion.py.
# Swept 20..1000 against 15 thresholds, 750 cells (sweep_sell_window.py). The
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
PERCENT_SELL     = 75

# ReInvestMedian1000: reinvest while price is BELOW median x (1 + PERCENT_REINVEST/100).
# Same sign as PERCENT_BUY, not "below the median": 10 means "up to 10% ABOVE it".
# Swept over 14 settings and 52 symbols (sweep_percent_reinvest.py). 10 is the
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
PERCENT_REINVEST = 10

# Timeout reinvest: if no reinvest has occurred X trading days after last sell,
# release the reserve using a looser threshold, on the same scale as
# PERCENT_REINVEST above (so -10 = only if 10%+ BELOW the median).
REINVEST_TIMEOUT_DAYS    = 400   # (0 = disabled)
REINVEST_TIMEOUT_PERCENT = 999   # 999 is effectively no price condition at all:
                                 # once the timeout is reached, reinvest regardless

USE_PE = False   # use P/E-adjusted median instead of price median

# Minimum bars a symbol must have AFTER the start index (see run_all.py) to be
# reported. Not total history — the existing len(df) < 1010 check covers that.
# Below this there is too little post-warmup data for the result to mean anything:
# the strategy may make no trades at all, and every short symbol ends up testing
# the same recent months, so they add correlated noise rather than evidence.
# 0 disables the guard.
MIN_EVAL_BARS = 500

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

# SellMedian1000: block sell when 1000-day Sharpe (signal3) is above this — stable/trending regime → hold
# UNTUNED, AND COSTING MONEY. Paired over 44 symbols against no sell gate at all,
# signal3 and z_dev together are worth mean +1.76 (13/27 symbols, p=0.649); layered
# on top of signal1 they cost mean -2.50 (10/26, p=0.916). signal1 alone (+14.47)
# beats all three together (+11.97). The two were only ever measured jointly, so
# which of them does the damage is unknown. Sweep them before trusting either.
MIN_SIGNAL3 = 1.1

# SellMedian1000: block sell when short-term momentum slope (signal1) is above this — momentum still up → hold
SELL_SIGNAL1_WINDOW = 120    # trading days for the slope window
SELL_MIN_SIGNAL1   = 0.228   # % per day, = k/sqrt(window) with k=2.5 at window 120.
                            # The one sell filter that earns its keep. Paired against
                            # the gate switched off, over 44 symbols: +1039 gain / -402
                            # loss = net +637, mean +14.47, 23/36 improved (p=0.066).
                            # Concentrated, not broad: VND alone is +277 of the +637,
                            # 20 of 44 symbols are untouched at any setting, and the top
                            # 3 contributors carry the mean from +14.5 down to +2.6. It
                            # rescues a handful of symbols; it does not improve the
                            # typical one. Quote both halves or the number misleads.
                            #
                            # Chosen as the CENTRE of the only region that ranks in the
                            # top 15% on both grids that can rank this filter — mean and
                            # the round-robin vote — which is w=110-130, k=2-3. Here
                            # mean 34 / vote 294, with 7 of 8 neighbours also qualifying.
                            # The previous 0.1369 (k=1.5) sat on the edge of that region
                            # at mean 31 / vote 271 and only 4 of 8 neighbours.
                            # Two parts of this are judgement, not data: the top-15% cut,
                            # and w=120 over w=130 (which has a higher mean of 39 but a
                            # lower vote of 261) — 120 was kept because it was already
                            # the live window. What the data supports is the region, not
                            # the point: k anywhere in 2-3 at w=110-130 is equivalent.
                            # Do not score this filter on the median. 20 of 44 symbols
                            # sit at exactly zero, so the median lands among them and
                            # reads 0.00 at every cell in the grid, best included.

# SellMedian1000: block sell when relative valuation (z_dev) is at or BELOW this —
# the price is above its trailing median only because the business grew into it,
# not because it is dislocated, so do not sell. Note this is the opposite
# comparison to the two momentum filters above: there a high reading means "trend
# intact, hold", whereas a high z_dev is the reason to sell.
# Set SELL_MIN_ZDEV = None to disable. Window is the z_dev stat_window to read.
# UNTUNED — see MIN_SIGNAL3 above for the measurement covering both. The z_dev
# computation is sound (no look-ahead, verified three ways); at 0.9 it is simply
# not paying for itself. The window may be as much at fault as the threshold.
SELL_ZDEV_WINDOW = 700    # stat_window in valuation_zdev (median_window is fixed at 1000)
SELL_MIN_ZDEV    = None   # OFF. It cost mean -2.50 layered on signal1 (see above), and
                          # its 700-bar warmup pushed the start index to 1699, which
                          # skipped 12 of 57 symbols outright — a quarter of the universe
                          # paid for a filter that was not earning anything. Set a float
                          # to switch it back on; the threshold has never been swept, so
                          # off is a measured default, not a verdict on the idea.

# ReInvestMedian1000: require the slope to have turned up before redeploying the reserve.
# Inverse polarity to the sell gate above: sell is BLOCKED while momentum is up, reinvest
# is only ALLOWED once momentum is up.
#
# OFF, and its premise is what the sweep rejected. 340 cells over 52 symbols
# (sweep_reinvest_signal1.py): not one beats switching the gate off, and the mean
# falls monotonically as the gate gets stricter — at w=100, k=-4 scores 45.9 and
# k=+4 scores 16.4. "Wait for momentum to turn before redeploying" costs 29 points
# across the grid. Redeploying immediately is better; idle cash earns nothing,
# and that outweighs entering a few months early.
#
# The mechanism is worth knowing before anyone tries this idea again. Mean spans
# 31 points across the grid while the reinvest COUNT spans 0.4 (3.1 to 3.5), so
# the gate never changed how often the arm acts — only when. With ~3 reinvests per
# symbol over ~11 years each one is a large allocation, and delaying it by months
# swings a symbol by hundreds of points. Unlike the sell gate this one cannot
# block anything outright: REINVEST_TIMEOUT_DAYS releases the reserve regardless.
#
# Set a float to switch it back on. Note the direct comparison, off against the
# old 0.05, is only +4.85 mean and 88% of that is STB alone (+0.61 without it),
# 20/38 symbols improved, p=0.436. The reason to leave it off is the monotone
# trend across 17 thresholds and every window, not that number.
REINVEST_SIGNAL1_WINDOW = 100    # kept for when the gate is switched back on
REINVEST_MIN_SIGNAL1    = None
