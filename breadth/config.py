"""
Configuration for the breadth method.

Self-contained, like portfolio/config.py and for the same reason: numbers fitted
to a different question mean nothing here until they are re-measured, and sharing
the file would make borrowed values look settled.

NOTHING IN THIS FILE HAS BEEN MEASURED YET. Every value is a starting point
chosen to be legible rather than optimal, and there is a specific reason to
distrust any tuning done here: one instrument over 137 months offers perhaps a
dozen independent cycles, so a parameter search will fit noise long before it
finds anything. Read the first run as a sanity check on the mechanism, not as a
result.
"""

PLAN_NAME = "breadth-timed DCA"

# ── What is traded, and what is watched ───────────────────────────────────────

# The only instrument bought. Everything else in the universe is read to compute
# breadth and is never held.
SYMBOL = "VN30"

# The basket breadth is measured over. "all" is every stock in the database.
UNIVERSE = "all"
EXCLUDE = ["VIX", "VIC"]

# Symbols needed before a day's breadth is treated as evidence. Below this the
# pace falls back to plain DCA rather than to zero: a percentage over six
# symbols is not the same measurement as one over fifty, and treating a thin
# early day as "expensive" would sit out the first years for no reason.
MIN_SYMBOLS = 20

MIN_ROWS = 0

# ── Money ─────────────────────────────────────────────────────────────────────

CONTRIBUTION = 8_000_000     # VND per month
DEPOSIT_RATE = 4.0           # annual %, paid monthly on the reserve

# ── The reference each symbol's premium is measured against ───────────────────

# Carried from portfolio/, where it was itself a starting point. It decides what
# "under its median" means for every symbol before the counting starts, so it
# moves every breadth number at once.
WINDOW = 1000

# Short-window momentum, from trend_signals. Same series portfolio/'s sell arm
# reads.
SLOPE_WINDOW = 120

# signal3_sharpe (return over volatility) is loaded from the same trend_signals
# rows and aggregated as median_sharpe / sharpe_pos.
#
# MEASURED, AND WORSE THAN EITHER OTHER SIGNAL, in BOTH directions:
#
#     contrarian  median_sharpe < -0.24 / < 0.33    93.86%  -1.89     9m reserve
#     contrarian  median_sharpe < -0.85 / < -0.24   87.97%  -7.78   168m
#     momentum    median_sharpe > 1.23 / > 0.33     93.64%  -2.11    13m
#     momentum    median_sharpe > 2.57 / > 0.33     88.93%  -6.82    86m
#     sharpe_pos < 0.41 / < 0.61                    94.30%  -1.45     0m
#     sharpe_pos > 0.77 / > 0.61                    94.04%  -1.71    11m
#     below_pct 0.388 / 0.224  (shipped)            96.58%  +0.83    34m
#
# THIS IS A STRONGER NEGATIVE THAN THE z_dev ONE. Those variants lost roughly in
# proportion to the cash they held; these lose while holding almost none -- 9m
# and 0m still give -1.89 and -1.45. So sharpe is not merely uninformative here,
# it points the wrong way, and it does so whichever direction it is read in.
#
# Combining it with a cheapness signal is worse again (-6.01, -3.23): requiring
# both drops the strong arm to 1-2% of days, so the reserve piles up and the
# earlier pattern takes over.

# Window z_dev standardises over: how many bars of a symbol's own dev history
# define "normal" for it. 250 is about a year.
#
# MEASURED AND IT DID NOT HELP. z_dev was added because dev% is not comparable
# across symbols -- a volatile name is routinely 40% below its median, a stable
# one rarely 15% -- so dividing by each symbol's own sigma should be the better
# cheapness measure. Against DCA's 95.75%:
#
#     median_zdev < -0.81 / < -0.19          95.43%   -0.32
#     median_zdev < -1.38 / < -0.19          95.62%   -0.13
#     median_zdev < -1.38 / < -0.81          89.54%   -6.21
#     + spread_zdev < 1.21 (falling together) 95.92%  +0.17
#     + spread_zdev > 2.02 (rotating)         92.04%  -3.71
#     below_pct 0.388 / 0.224  (shipped)      96.58%  +0.83
#
# Every variant lands within a point of DCA except the two that hold a large
# reserve, and those lose in proportion to what they held. Same pattern as the
# below_pct sweep: the reserve explains the result, the signal does not.
#
# REMOVED. median_zdev, spread_zdev, median_sharpe, sharpe_pos and slope_pos
# were kept "in case a future rule needs them" and no rule ever did; they cost a
# per-symbol rolling pass on every run and two variants in a store nothing
# addressed. The numbers above stay as the record of what was measured -- that is
# what makes deleting the code safe rather than forgetful.
#
# To bring one back: add it to SIGNALS in signals.py and give it a variant.

# ── The pace ──────────────────────────────────────────────────────────────────

# Share of the basket trading under its own median, 0..1.
#
# TWO LEVELS, NOT A CURVE. A continuous function of breadth carries several more
# parameters and, on a dozen independent cycles, no way to tell whether any of
# them did anything.
#
# CALIBRATED TO THE OBSERVED DISTRIBUTION, because the round numbers that
# shipped first were nowhere near it. Over 2,819 days with enough symbols:
#
#     p10   p25   p50   p75   p90   p95   p99   max
#    0.116 0.163 0.224 0.306 0.388 0.509 0.765 0.824
#
# Most of the basket is ABOVE its own median most of the time -- which is what a
# market that rose over the period looks like. So 0.65 is the 98th percentile:
# it fired on 1.6% of days, the strong arm never engaged, and the weak arm ran
# 95% of the time. That is not a strategy, it is an accident of units.
#
# 0.388 is p90 and 0.224 is p50, so the three states get roughly 10 / 40 / 50 of
# the days. IN-SAMPLE by construction -- the quantiles come from the whole
# history -- and quoted here as calibration, not as a finding.
BUY_STRONG_BELOW_PCT = 0.388
BUY_NORMAL_BELOW_PCT = 0.224

# The strong arm also wants momentum to have stopped getting worse. Average
# regression slope across the basket, percent per day.
#
# WHY BOTH CONDITIONS. Cheapness alone buys all the way down a bear market;
# momentum alone buys every bounce in an expensive one. -0.05 is "still falling,
# but no longer falling hard", which is the shape of a bottom rather than of a
# crash.
#
# MEASURED AND REMOVED. Adding it cost 4.3 points at the calibrated thresholds
# (83.50% with, 87.84% without): it halved how often the strong arm engaged, and
# in this history the days it screened out were days worth buying. Set to a
# number below every observation, so the condition is present in the code and
# inert in the result -- switching it back on is a one-line change and the
# comparison is recorded above.
BUY_STRONG_MIN_SLOPE = -99.0

# Contributions to spend per month in each state.
#
# The weak case is 0.5, not 0. Sitting out entirely is a claim this data cannot
# support, and it turns a pace rule into a timing rule by the back door.
#
# NOTE ON THE RESERVE. What is not spent accumulates and earns the deposit rate,
# and it can only be drawn down at BUY_STRONG_MULT contributions a month --
# decisions are made when the contribution lands, once a month, not daily. So a
# reserve built over a long expensive stretch drains slowly. That is deliberate:
# a rule that could dump years of savings into one day would be making a much
# larger bet than the signal can carry.
# MEASURED, AND EVERY SETTING LOST TO PLAIN DCA. The pattern is the finding:
#
#     configuration                       growth   vs DCA   reserve
#     below >=0.65 / >=0.50  (shipped)    63.82%   -31.94     657m
#     p90/p50, with the slope screen      83.50%   -12.25     285m
#     p90/p50, no slope screen            87.84%    -7.91     233m
#     relative to median[500], no screen  90.96%    -4.79      60m
#     p90/p50, pace 3.0/1.0/0.5           94.62%    -1.13     105m
#     p90/p50, pace 2.0/1.0/0.8           95.32%    -0.43      34m
#     plain DCA                           95.75%        --       0
#
# Read the last column. The ranking is almost exactly the ranking of how much
# money was held back, and the best variant is the one that held back least.
# Nothing here timed anything: withholding cash in a market that rose cost more
# than the later purchases recovered.
#
# AND IT IS STRUCTURAL, not a bad choice of level. The only way to buy MORE
# later is to buy less now -- the reserve is the sole source of the strong arm's
# extra contribution -- so an accelerator cannot exist without the brake that
# pays for it. Setting BUY_WEAK_MULT to 1.0 removes the drag and, with it, every
# possibility of ever spending more than one contribution: the plan becomes DCA
# exactly.
#
# 2.0 / 1.0 / 0.8 is the least-bad measured, and it is shipped because a config
# must hold something, NOT because it is good. It still loses.
BUY_STRONG_MULT = 2.0
BUY_NORMAL_MULT = 1.0
BUY_WEAK_MULT = 0.8

# ── The sell arm ──────────────────────────────────────────────────────────────

# None switches selling off entirely, which is the default and the safer claim.
#
# WITH IT OFF this is DCA with the pace varied: at worst it buys the same asset
# on a different schedule, and it cannot sit out a decade by accident. WITH IT ON
# it is market timing, where being wrong twice -- out before a rise, in before a
# fall -- trails plain DCA badly and permanently.
#
# When enabled, both conditions must hold: the basket broadly extended AND
# momentum rolled over. An extended market can stay extended for years, so the
# level alone is not a signal to leave.
SELL_BELOW_PCT = None        # e.g. 0.25 -- fewer than a quarter still cheap
SELL_MAX_SLOPE = -0.10       # and average momentum clearly negative

# ── Three arms on prem_median ─────────────────────────────────────────────────
#
# prem_median is the median distance from median across the basket, so
# "prem_median <= -60" IS "half the basket is at least 60% below its own median".
# One number expresses both halves of that sentence.
#
# None on any of the three switches that arm off.
#
# MIND THE RANGE. prem_median has never been below -28.5% in this history and its
# median day is +24.8%: the market rose, so the typical symbol sits ABOVE its own
# 1000-bar median. A buy threshold of -60 fires on 0.0% of days.
#
#     <= -60:  0.0%      <= -10:  1.6%      >= +40: 29.3%
#     <= -40:  0.0%      <=   0:  5.2%      >= +20: 63.0%
#     <= -20:  0.3%      <= +10: 16.9%      >= +90:  4.5%
# MEASURED. Against DCA's 95.75%:
#
#   mua / reinvest / ban      lai 4%   lai 0%   %tien mat cuoi ky   ban
#   -60 / -10 / +40           151.03%  101.32%        98%            45
#   -20 / -10 / +40           151.04%  --             98%            45
#   -10 /   0 / +40           121.34%  --              0%            45
#     0 / +10 / +40           135.79%  --              0%            45
#   +10 / +20 / +90           212.46%  195.23%         0%             9
#     0 / +10 / khong ban      95.68%  --              0%             0
#   +10 / +20 / khong ban      97.67%  --              0%             0
#
# READ THE LAST TWO COLUMNS FIRST.
#
# The -60 row ends 98% IN CASH: the buy arm never fires (prem_median has never
# been below -28.5%), the sell arm fires on 29% of days, and the reinvest arm at
# -10 fires on 1.6% -- so money leaves the market and does not come back. A third
# of its profit is deposit interest, and at 0% it drops from 151% to 101%. That
# is not an equity strategy, it is a savings account with a stock-shaped start.
#
# The +10/+20/+90 row is the interesting one: it ends fully invested, sells only
# nine times, and 195% survives with no interest at all.
#
# BUT IT IS NINE EVENTS. The whole difference rests on nine sell decisions in
# eleven years, all of them selecting the same two or three market tops, and the
# thresholds were chosen after seeing which ones those were. Treat it as a
# hypothesis, not a result.
#
# Switching the sell arm off collapses everything back to DCA (95.68%, 97.67%),
# which says plainly where the difference comes from: it is the selling, not the
# pace.
# EACH ARM HAS TWO PARAMETERS, not one: the threshold, and HOW MUCH of the
# basket has to pass it.
#
#     SELL:  SELL_PREM_FRAC of the basket is at least SELL_PREM_MIN% above its
#            own median  ->  sell
#
# The fraction was previously hard-coded at 0.5 inside np.median. It is now
# explicit, because "half the basket 40% up" and "a quarter of the basket 80%
# up" are different statements about the market and only one of them was
# expressible.
#
# Implemented by storing premium quantiles every 5% and letting the fraction
# choose which one to read: F of the basket >= T is the same as quantile(1-F)
# >= T. Fractions are rounded to the nearest 5%.
USE_PREM_ARMS = True

# Compare against the TRIMMED MEAN of premium instead of a quantile.
#
# Drop the 5% most extreme symbols at each end, average the rest. A plain mean is
# dragged around by a few names that ran 300% or collapsed; a quantile ignores
# magnitude entirely and only counts heads. The trimmed mean keeps the magnitude
# of the ordinary 90% and throws away just the tails.
#
# With this on, the FRAC settings below are unused: a mean is one number, so
# "how much of the basket" has no meaning for it.
#
# MEASURED, AND IT LOSES TO THE MEDIAN AT EVERY THRESHOLD. Growth %, sell
# threshold across the top, DCA = 95.75%:
#
#     threshold      40     50     60     70     80     90    100
#     prem_trim    71.8   81.7  101.1  108.2  132.5  132.6  143.4
#     prem_median 150.9  189.9  201.8  219.1  224.9  229.0  240.2
#     sells (both)    9      6      7      3    3-5    2-3      4
#
# The two fire on nearly the same days -- the sell counts match almost cell for
# cell -- so this is not about timing. It is about LEVEL: the premium
# distribution is right-skewed, so keeping magnitude pulls the trimmed mean
# above the median everywhere (p50 34.6 against 24.8). The same threshold
# therefore means something laxer, and the plan sells earlier and holds cash
# through more of the rise.
#
# Read the sell counts before either row: nothing here rests on more than nine
# decisions.
USE_TRIM_MEAN = True

BUY_PREM_MAX = -60.0         # mua khi BUY_PREM_FRAC ro nam duoi -60%
BUY_PREM_FRAC = 0.5

REINVEST_PREM_MAX = -10.0    # reinvest khi REINVEST_PREM_FRAC ro duoi -10%
REINVEST_PREM_FRAC = 0.5

# SWEPT, both parameters at once. Growth %, against DCA's 95.75%:
#
#     % of basket \ threshold    20      40      60      80     100
#              25%              48.2    90.6   137.6   152.9   207.0
#              50%             102.7   150.9   201.8   224.9   240.2
#              75%             140.8   213.8   139.4   100.4   100.4
#
#     sells                     20      40      60      80     100
#              25%               4       5       8       9       4
#              50%              14       9       7       3       4
#              75%              10       5       1       0       0
#
# THE SELL COUNTS ARE THE WHOLE STORY. Nothing here rests on more than fourteen
# decisions and most cells rest on fewer than ten; the 240.2 cell fires four
# times in eleven years and the two 100.4 cells never fire at all -- they are
# plain DCA with a rounding difference. A surface built from four-event cells
# has no shape to read, and picking its maximum is picking noise.
#
# 40 / 0.5 is kept because it is legible -- "half the basket 40% above its own
# four-year median" -- not because it won anything.
SELL_PREM_MIN = 40.0         # ban khi SELL_PREM_FRAC ro tren +40%
SELL_PREM_FRAC = 0.5

REINVEST_PCT = 1.0           # phan reserve moi lan reinvest tieu
