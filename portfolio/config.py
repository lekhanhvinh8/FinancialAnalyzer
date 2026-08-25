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
# OFF. Size now enters through the SCORE instead — see CAP_WEIGHT, and see the
# reinvest arm, which was rearranged the same way first.
#
# It earned its place while it was here. Swept at K=5 with a pure price scorer,
# before the sell and reinvest arms were switched on:
#
#     min_rank   keeps   growth        min_rank   keeps   growth
#       0.30      70%    131.79%         0.50      50%    163.60%
#       0.35      65%    141.80%         0.55      45%    154.71%
#       0.40      60%    153.25%         0.60      40%    108.69%
#       0.45      55%    164.31%         0.70      30%     83.51%
#
# WHY IT IS OFF ANYWAY. A hard filter and a heavy score weight turn out to do the
# same job — see the two-regime table under CAP_WEIGHT — and they finish within a
# point of each other. The score is the better of two equals because it never
# empties the day: a filter that admits nobody sends the contribution to the
# benchmark, and dropping it took the plan from 546 buys to 671 on the same
# calendar. A ranking always has a first place.
CAP_MIN_RANK = None

# Weight of market-cap rank in the buy SCORE, blended with the price scorer over
# same-day ranks (see scoring.BlendScorer). 0 switches the blend off entirely.
#
# 0.75 = three parts size, one part cheapness. This REPLACES the hard cap filter
# rather than supplementing it; CAP_MIN_RANK is None.
#
# AN EARLIER MEASUREMENT SAID THE OPPOSITE and is worth recording, because it was
# not wrong so much as out of date. With the sell and reinvest arms switched off,
# every weight above zero hurt at every filter level, and the conclusion drawn
# was that size should decide eligibility and nothing else. That table is gone
# now; what follows replaces it, measured with both arms on and the reinvest
# quota at 20.
#
# TWO REGIMES, NOT A HILL. Twenty-one weights, no filter:
#
#     w      0.0   0.25    0.5   0.55  |  0.60   0.70   0.75   0.80   0.90   1.0
#     growth 144.9 148.0  135.9  134.1 | 151.3  165.5  166.6  167.8  164.8  164.0
#
# The step at 0.55 -> 0.60 is 17 points; the mean step across the row is 2.8. One
# phase change, and either side of it is smooth. Above 0.70 is a PLATEAU five
# cells wide, all of it at or above 164, so this is not one lucky cell.
#
# The same walk WITH the top-50% filter is nearly flat -- 159.8 to 166.4, mean
# step 0.71 -- and its best point is w=0. That is the tell: past about 0.7 the
# score is already doing the filter's job, so adding the filter on top changes
# almost nothing.
#
# WHAT THE PLATEAU MEANS. It is flat from 0.7 to 1.0, and 1.0 means the price
# scorer contributes NOTHING to the ordering. So once size dominates the rank,
# cheapness adds almost nothing on top of it — the buy condition has already
# used the cheapness, and ordering the survivors by how cheap they are is close
# to ordering them at random.
#
# 0.75 rather than the peak at 0.80. They are 1.2 points apart inside a plateau
# whose own cells vary by 3, and the rounder number is not pretending to a
# precision this has not earned.
CAP_WEIGHT = 0.75

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
# ON. Selling on price alone cost 65 points; two things had to be true before
# this was worth switching on, and both now are:
#
#   1. the momentum gate below, so the arm sells when a run is OVER rather than
#      while it is happening
#   2. the reinvest arm's quota and cooldown, because the damage was never the
#      sell timing — it was where the proceeds went afterwards
#
#     DCA VN30                                  95.75%
#     buy only                                 163.44%
#     sell + reinvest, before those two         98.76%
#     sell + reinvest, now                     194.23%
#
# None switches the arm off, and takes the reinvest arm with it in practice: the
# reserve has no other source.
SELL_MIN_PREMIUM = 70.0

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

# Where money in the reserve goes. Same price test as the buy arm; everything
# below is what differs. None switches the reinvest arm off.
#
# It cannot run on its own: the reserve's only source is a sale, so this and
# SELL_MIN_PREMIUM go on together or not at all.
REINVEST_ENABLED = True

# NO MARKET-CAP FILTER on this arm — size is a RANKING input here, not a gate.
#
# The buy arm's sweep is the reason. Tightening its cap filter past 0.55
# collapsed the return (154.71% at 0.55, 108.69% at 0.60, 83.51% at 0.70),
# because filtering to the very largest converges on the benchmark, and the
# benchmark returns 95.75%. A hard floor throws away a cheap mid-cap entirely;
# a ranking lets size lose to cheapness when cheapness is extreme enough.
#
# REINVEST_CAP_WEIGHT is that ranking's weight, blended with distance below the
# median over same-day ranks (scoring.BlendScorer). 0 = order by cheapness
# alone, 1 = by size alone.
#
# NOT MEASURED. This is a stated design, and the buy arm's own result is a
# warning rather than a precedent: there, blending cap into the score made
# things worse at every weight. Sweep it before believing it.
REINVEST_CAP_WEIGHT = 0.5

# How much of the reserve ONE symbol may take, as a percent, in rank order until
# the money runs out. See allocator.QuotaAllocator.
#
# A quota rather than an equal split because reserve money arrives in lumps. An
# equal split makes the size of a purchase depend on how many other names
# happened to qualify that day; a quota fixes the size and lets the count follow.
#
# THE QUOTA IS THE POSITION COUNT. It funds ceil(100 / quota) names and stops, so
# 20 means five and 50 means two — REINVEST_TOP_K cannot widen it past that, it
# can only cut it shorter.
#
# 20 IS A DELIBERATE MOVE AWAY FROM THE MEASURED PEAK, chosen to spread the
# reserve over five names instead of two. It costs 28 points and is not a
# mistake — it buys breadth, and breadth is worth something this backtest cannot
# price. What follows is what it costs, so the trade is visible.
#
# THE QUOTA AND THE COOLDOWN DO NOT SEPARATE. Measured together, growth %:
#
#     quota   cooldown 0    10    30    60
#       50%              -  137.75    -  194.23
#       25%              -  178.99    -  154.63
#       20%         131.86  166.32  150.17  152.06
#
# Read the rows, not the columns. At 50% the reserve funds two names and wants a
# LONG cooldown — 194.23 at 60, collapsing to 137.75 at 10. At 20% it funds five
# and wants a SHORT one — 166.32 at 10, down to ~150 at 30 and 60. The best
# quota and the best cooldown cannot be picked separately and combined; each
# pairing has to be measured as a pairing.
#
# WHY THE ROWS REVERSE. Two names is a concentrated bet, and a long cooldown is
# what stops the reserve returning to the same one until the case has genuinely
# refreshed. Five names is already diluted, and a long cooldown on top of that
# keeps handing the money to the sixth-best candidate instead of the first.
#
# 25% at cooldown 10 gives 178.99 on four names — two thirds of the breadth for
# half the cost. It is the better trade if breadth is the goal rather than five
# specifically.
REINVEST_QUOTA_PCT = 20.0

# Hard ceiling on how many names one reinvest may fund. None leaves it to the
# quota alone.
#
# Belt and braces rather than the real control, and MEASURED TO BE INERT: 5 and
# None give the same 166.32% at quota 20, because the money runs out after five
# either way. It is here so that lowering the quota later cannot silently turn
# one reinvest into a ten-way scatter.
REINVEST_TOP_K = 5

# Below this the whole reserve goes to the top-ranked candidate instead of being
# sliced. Quota-sized pieces of a small pot are too small to be worth their own
# line, and — once costs are modelled — too small to clear a brokerage minimum.
REINVEST_MIN_SPLIT = 20_000_000

# Bars before the reserve may buy the SAME symbol again. 0 disables it.
#
# Applied by the engine, not by a rule: it is a fact about the WALLET (when did
# we last act on this name) and rules only see market data.
#
# BARS, NOT CALENDAR DAYS. Both indices are row numbers in the symbol's own price
# series, so 10 is ten trading days — about a fortnight, not ten days.
#
# WHAT IT IS FOR, AND WHAT IT IS NOT FOR. The ranking barely moves from one day
# to the next, so the cheapest name stays cheapest and a reserve spent over
# several consecutive days pours into whichever name happened to be top. The
# cooldown is a brake on that RUN, not a judgement about the symbol.
#
# Which is the argument for keeping it short at THIS quota. A name that keeps
# ranking first keeps deserving the money; a long cooldown throws that away and
# hands the reserve to a worse candidate purely because of when the last
# purchase landed. At quota 20 that is measurable: 166.32 at 10 bars against
# 150.17 at 30 and 152.06 at 60.
#
# BUT IT IS STILL REQUIRED. Switching it off entirely is the worst setting
# measured on that row -- 131.86, below every cooldown that does something.
# Short is not the same as absent: without any brake the reserve pours into one
# name over consecutive days simply because the ranking had not moved yet.
#
# NOT INDEPENDENT of REINVEST_QUOTA_PCT. At quota 50 this row reverses and a
# long cooldown wins by a wide margin. See the table there before changing
# either.
REINVEST_COOLDOWN_DAYS = 10

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
