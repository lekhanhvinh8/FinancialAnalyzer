"""
Median1000 strategy configuration.
Edit these parameters to tune the analysis, then re-run run_one.py or run_all.py.
"""

INTERVAL_MONEY = 8_000_000   # VND invested per interval

# BuyMedian1000: buy when price is this % below the 1000-day median
PERCENT_BUY      = 60

# SellMedian1000: sell when price is this % above the 1000-day median
PERCENT_SELL     = 60

# ReInvestMedian1000: reinvest when price is this % below the 1000-day median
PERCENT_REINVEST = 10

# Timeout reinvest: if no reinvest has occurred X trading days after last sell,
# use a looser threshold (same scale: -10 = reinvest if 10%+ below median)
REINVEST_TIMEOUT_DAYS    = 400   # (0 = disabled)
REINVEST_TIMEOUT_PERCENT = 999

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
# UNTUNED AND UNDER SUSPICION. Paired over 44 symbols, signal3 and z_dev together
# are worth mean +1.76 (13/27 symbols, p=0.649) against no sell gate at all, and
# layering them on top of signal1 costs mean -2.50 (10/26, p=0.916) — so signal1
# alone (+14.47) beats all three together (+11.97). Neither has been swept. Do
# that before trusting either value. See SELL_MIN_ZDEV below and the docstring in
# sweep_signal1.py for how to measure it (paired per symbol, trimmed mean).
MIN_SIGNAL3 = 1.1

# SellMedian1000: block sell when short-term momentum slope (signal1) is above this — momentum still up → hold
SELL_SIGNAL1_WINDOW = 120    # trading days for the slope window
SELL_MIN_SIGNAL1   = 0.1369  # % per day, = k/sqrt(window) with k=1.5 at window 120.
                            # This filter is the one that works. Measured against the
                            # sell gate switched off, over 44 symbols: +1039 points of
                            # gain against 402 of loss, net +637 — mean +14.47, 10%
                            # trimmed mean +7.31, 23/36 symbols improved (p=0.066).
                            # But the effect is CONCENTRATED: 20 of 44 symbols are
                            # untouched at any setting, VND alone is +277 of the +637,
                            # and dropping the three largest contributors takes the mean
                            # to +2.6. It rescues a handful of symbols; it does not
                            # improve the typical one.
                            # The exact value is kept, not tuned. The 20x17 sweep is
                            # scored on the median, which sits in that 20-symbol dead
                            # zone and reads ~0.00 for every cell including the best
                            # one, so the grid cannot rank settings for this filter at
                            # all. Nothing in it justified moving off this value; that
                            # is not the same as the value being optimal.
                            # Before re-sweeping, read the docstring at the top of
                            # sweep_signal1.py — it records why the grid misleads here.

# SellMedian1000: block sell when relative valuation (z_dev) is at or BELOW this —
# the price is above its trailing median only because the business grew into it,
# not because it is dislocated, so do not sell. Note this is the opposite
# comparison to the two momentum filters above: there a high reading means "trend
# intact, hold", whereas a high z_dev is the reason to sell.
# Set SELL_MIN_ZDEV = None to disable. Window is the z_dev stat_window to read.
# UNTUNED AND UNDER SUSPICION, same measurement as MIN_SIGNAL3 above — the two were
# only ever measured together. The z_dev computation itself is sound (no
# look-ahead, verified three ways), but at 0.9 it is not paying for itself. Sweep
# it before assuming the threshold is the problem; the window may be.
SELL_ZDEV_WINDOW = 700    # stat_window in valuation_zdev (median_window is fixed at 1000)
SELL_MIN_ZDEV    = 0.9

# ReInvestMedian1000: require the slope to have turned up before redeploying the reserve.
# Inverse polarity to the sell gate above: sell is BLOCKED while momentum is up, reinvest
# is only ALLOWED once momentum is up. Set REINVEST_MIN_SIGNAL1 = None to disable.
REINVEST_SIGNAL1_WINDOW = 100    # trading days for the slope window
REINVEST_MIN_SIGNAL1    = 0.05   # % per day — reinvest only once slope >= this
