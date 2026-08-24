"""
Configuration for the portfolio method.

Self-contained on purpose. It would have been shorter to re-export the
single-symbol runner's config, and that would have been a mistake: those numbers
were fitted to a different question — one wallet per symbol, no competition for
capital — and every one of them has to be re-measured here before it means
anything. Sharing the file would have made borrowed values look settled.

Where a value starts out equal to one over there, the comment says so and says it
is a STARTING POINT, not a finding.
"""

PLAN_NAME = "premium-below-median, equal split"

# ── Universe ──────────────────────────────────────────────────────────────────

# Which symbols the portfolio may hold.
#
#   "all"          every stock in the DB with enough history, minus EXCLUDE
#   "vn30"         current members of that index
#   ["FPT", ...]   an explicit list
#
# "all" carries SURVIVORSHIP BIAS and there is no way to configure that away: the
# database holds what is worth collecting today, so a name that delisted or
# collapsed years ago was never available for this backtest to buy. Naming an
# index is not a fix — a symbol admitted to VN30 last year still brings its whole
# pre-admission history with it.
#
# The fix is point-in-time membership, and the data is not there yet: the
# index_members table has 5 distinct join dates for vn30 and no departures at all
# for vnfinlead. Until that is filled in, every number this package produces is
# an upper bound, and should be quoted as one.
UNIVERSE = "all"

# Never held. Kept separate from the universe rule so a data problem with one
# symbol does not force a change of universe.
EXCLUDE = ["VIX", "VIC"]

# The index this plan is measured against, and the instrument it falls back to.
#
# Independent of UNIVERSE. The benchmark is what the result is compared with, not
# a restriction on what may be bought — the plan picks from the whole database
# and is asked whether that beats simply holding the index.
#
# It is loaded into the Market alongside the members, so it is genuinely
# tradable, but strategy.py excludes it from the plan's own candidates — holding
# the index next to its constituents would mean partly holding the benchmark.
#
# None turns both behaviours off: the baseline becomes equal-weight DCA across
# the members, and there is no fallback.
BENCHMARK = "VN30"

# When the buy rule admits nobody on a day money is available, buy BENCHMARK
# instead of letting the cash wait.
#
# This is what keeps the comparison about SELECTION. A strict rule with no
# fallback is two bets at once — which stocks, and whether to be in the market at
# all — and a result then cannot say which of the two produced it. With the
# fallback the plan is invested on exactly the bars the benchmark is, so the
# difference is attributable to the choosing.
FALLBACK_TO_BENCHMARK = True

# A symbol needs at least this many rows before it is worth including at all,
# counted before warmup. 0 leaves it to the warmup requirement alone.
MIN_ROWS = 0

# ── Money ─────────────────────────────────────────────────────────────────────

CONTRIBUTION = 8_000_000     # VND added to the wallet every month
DEPOSIT_RATE = 4.0           # annual %, paid monthly on idle reserve cash

# Where an unspent contribution goes: "carry" keeps it for tomorrow, "reserve"
# moves it to the reserve.
#
# "carry" while the reinvest arm is off, because the reserve's only exit is that
# arm — with it disabled, "reserve" makes the pool a one-way sink and the
# backtest gradually measures the deposit rate instead of the buy rule. See
# engine.py.
LEFTOVER = "carry"

# ── The buy condition ─────────────────────────────────────────────────────────

# Buy while the price is less than BUY_MAX_PREMIUM percent ABOVE its own
# BUY_WINDOW-bar reference.
#
# MIND THE SIGN. 60 does not mean "buy when 60% below". It means "buy unless the
# price is more than 60% above its median" — a permissive condition that admits
# most of the universe on an ordinary day. It refuses to chase something wildly
# extended; it does not hunt for bargains.
#
# 60 and 1000 are STARTING POINTS carried over from the single-symbol work, not
# findings that transfer. They were chosen where each symbol had its own wallet
# and no symbol competed with any other for money, which is precisely the
# constraint this method removes. Both need re-measuring here.
#
# The two are not independent: how far a price typically strays from its own
# median widens with the window, so a threshold tuned at 1000 bars means
# something much stricter at 100. Sweep them together, never one alone.
BUY_WINDOW = 1000
BUY_MAX_PREMIUM = 10
BUY_REFERENCE = "median"     # 'median' | 'mean' | 'top' | 'bottom'

# Measure against the P/E's own history instead of the price's. Off: the P/E
# series has real holes — a company with a loss-making trailing year has no P/E
# at all — and the shared pipeline forward-fills across them, so a rule reading
# it would be comparing a frozen number against a frozen median and finding
# everything perfectly normal.
USE_PE = False

# ── Market capitalisation ─────────────────────────────────────────────────────

# Keep only symbols in the top (1 - CAP_MIN_RANK) of the day's universe by market
# capitalisation. None switches the filter off.
#
# RELATIVE, NEVER ABSOLUTE. The median market cap in this database runs about 10
# trillion VND in 2015 and 50 trillion in 2026, so a fixed threshold would admit
# almost nobody early and almost everybody late — it would be measuring the
# calendar. market.py ranks the universe fresh every day.
#
# THE STRONGEST RESULT MEASURED HERE SO FAR. Sweeping it at K=5 with the shipped
# scorer:
#
#     min_rank   keeps   growth        min_rank   keeps   growth
#       0.30      70%    131.79%         0.50      50%    163.60%
#       0.35      65%    141.80%         0.55      45%    154.71%
#       0.40      60%    153.25%         0.60      40%    108.69%
#       0.45      55%    164.31%         0.70      30%     83.51%
#
# +25 points over no filter (138.77%), on a smooth unimodal curve rather than a
# single lucky cell, and robust to the allocator: at 0.50 the result is 160.7 to
# 163.6 across K = 3, 5, 8, 10 and None. The gain is the filter's, not an
# interaction.
#
# 0.5 rather than the peak at 0.45 — they are within half a point of each other
# and the rounder number is not pretending to a precision this has not earned.
#
# BOTH ENDS ARE BAD, which is the interesting part. Below 0.40 the small caps
# drag; above 0.55 it collapses, and it should — filtering to the very largest
# converges on the benchmark, and the benchmark returns 95.75%.
CAP_MIN_RANK = 0.5

# Weight of market-cap rank in the buy SCORE, blended with the price scorer over
# same-day ranks (see scoring.BlendScorer). 0 switches the blend off entirely.
#
# MEASURED AND REJECTED. Across every filter level, adding cap to the score made
# things worse, monotonically:
#
#     filter        w=0     w=.25    w=.5    w=.75    w=1
#     none        138.8%   136.0%   129.1%  133.2%  129.5%
#     top 65%     141.8%   139.1%   134.7%  133.9%  133.5%
#     top 50%     163.6%   160.4%   156.9%  152.6%  153.0%
#
# So size decides WHO IS ELIGIBLE and nothing else; among the eligible, ordering
# by size is worse than ordering by cheapness. The blend machinery is kept
# because it is the only way to combine scorers whose units do not compare, and
# the next scorer worth trying will need it.
CAP_WEIGHT = 0.0

# ── The sell condition ────────────────────────────────────────────────────────

# Sell a holding once its price is more than SELL_MIN_PREMIUM percent ABOVE its
# own BUY_WINDOW-bar median. None switches the sell arm off entirely.
#
# Full exit, not a trim: whatever the position is worth goes to the reserve.
#
# NO CHURN GUARD IS NEEDED, and that is a property of these two numbers rather
# than of the code. The engine runs sell before buy, so a bar that satisfied both
# conditions would liquidate and re-enter the same day. It cannot here: selling
# needs premium > 70 and buying needs premium < 10, which are complementary. Move
# SELL_MIN_PREMIUM below BUY_MAX_PREMIUM and that stops being true — the arms
# would then need the cross-check single/median1000's factory wires in.
# OFF. Measured, and it costs 65 points:
#
#     buy only            163.44%
#     + sell + reinvest    98.76%
#     DCA VN30             95.75%
#
# 70.0 with the momentum gate below is the best version of this arm found so
# far, and it is still worse than never selling. Set it back to 70.0 to switch
# the arm on; everything it needs is wired and measured.
SELL_MIN_PREMIUM = None

# Momentum gate on the sell arm: only sell once the SELL_SIGNAL1_WINDOW-bar
# regression slope has fallen below SELL_MAX_SIGNAL1 percent per day. None
# removes the gate and the arm sells on price alone.
#
# THIS IS THE FIX FOR HOW THE PRICE RULE FAILS, and the failure was measured
# before the gate was added. Selling on price alone turned +163.60% into
# +63.05%: it sold every one of the ten best holdings, because "70% above its
# own median" IS the definition of a symbol that is winning. ACB went at 3,780
# and ended at 21,650; STB at 20,100 and ended at 75,200. Across 24 sells the
# proceeds were 1.87bn where holding would have been 2.92bn.
#
# Requiring the slope to have flattened changes the claim from "sell what is
# expensive" to "sell what has stopped rising", which is a different and far
# more defensible thing to do.
#
# THE THRESHOLD SCALES WITH THE WINDOW: k / sqrt(window), k = 2.5, so 0.228 at
# 120. Change one and the other has to move. Both are single/median1000's
# values, carried over as a starting point and not yet swept here.
SELL_SIGNAL1_WINDOW = 120
SELL_MAX_SIGNAL1 = 0.228

# ── The reinvest condition ────────────────────────────────────────────────────

# Where money in the reserve goes. Same price test as the buy arm; the market-cap
# filter is the only thing that differs. None switches the reinvest arm off.
#
# WHY TIGHTER THAN THE BUY ARM. Reserve money is realised profit, not this
# month's wage. The buy arm is fed a fixed contribution whatever the market is
# doing, so it has to accept a broad set of candidates; the reserve arrives only
# after something ran up 70% and was sold, and it can afford to wait for the
# larger, steadier names. 0.8 keeps the top fifth of the day's universe against
# the buy arm's top half.
#
# NOT MEASURED YET. Unlike CAP_MIN_RANK this is a stated preference, not a swept
# result — and the buy-arm sweep is a warning, not a precedent: there, tightening
# past 0.55 collapsed the return, because filtering to the very largest converges
# on the benchmark. Sweep this before believing it.
# OFF with the sell arm — with nothing selling there is no reserve for it to
# deploy, so leaving it on would only be misleading.
#
# THIS IS THE ARM TO FIX, not the sell arm. The sell timing is defensible once
# gated on momentum; where the money lands afterwards is not. single/median1000
# makes proceeds return to the SAME symbol, while this sends them to whatever is
# cheapest — a systematic rotation out of what is winning into what is not. The
# "breaking the dead zone" property this package was designed around is the
# mechanism doing the damage, and this arm has never been varied once.
REINVEST_CAP_MIN_RANK = None

# ── Ranking and sizing ────────────────────────────────────────────────────────

# How candidates are ORDERED before TOP_K cuts the list. See scoring.py.
#
#   "premium"    distance from the same reference the buy rule tests, so the
#                ranking and the condition agree about what "attractive" means
#   "drawdown"   how far below its own rolling high
#   "none"       every candidate ties
SCORER = "premium"

# How many of the ranked candidates share one day's money. None = all of them.
#
# 5 rather than None, which is what makes SCORER do anything at all: an equal
# split over the whole list gives the first and last candidate the same money,
# so the ranking is inert until there is a cutoff. SCORER and TOP_K are one
# axis, never two.
#
# MEASURED, AND THE MARGIN IS THIN. Sweeping K against four scorers on the full
# universe, with the price rule at premium < 10%:
#
#     scorer                K=1     K=3     K=5    K=10   K=all
#     cheapest vs median   66.1   139.1   138.8   138.7   137.1
#     dearest vs median   141.8   148.0   142.2   136.6   137.1
#     drawdown deepest    158.2   131.3   140.7   139.0   137.1
#     no ranking          117.1    92.4   104.1   129.0   137.1
#
# 5 with the shipped scorer buys +1.7 points over K=None. That is small, and the
# whole table is ONE RUN with no error bar — K=1 swings from 66 to 158 across
# scorers, which is what noise looks like. 5 is chosen as the least concentrated
# setting that still lets the ranking matter, not because 138.8 beat 137.1.
#
# Two results in that table are worth more than the number adopted:
#   - "no ranking" is the control, and it is WORSE at every cutoff. So the
#     ordering carries something; it is not just concentration.
#   - "dearest" beats "cheapest" almost everywhere, which is the opposite of
#     what the buy rule assumes. Do not treat the shipped scorer as settled.
#
# Nothing here is trustworthy until the same sweep runs over many start dates.
TOP_K = 5

# Smallest single purchase, in VND. 0 disables the floor. Fractional shares are
# allowed throughout, so nothing forces a minimum yet.
MIN_TICKET = 0
