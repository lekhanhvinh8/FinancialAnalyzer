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
BUY_MAX_PREMIUM = 60.0
BUY_REFERENCE = "median"     # 'median' | 'mean' | 'top' | 'bottom'

# Measure against the P/E's own history instead of the price's. Off: the P/E
# series has real holes — a company with a loss-making trailing year has no P/E
# at all — and the shared pipeline forward-fills across them, so a rule reading
# it would be comparing a frozen number against a frozen median and finding
# everything perfectly normal.
USE_PE = False

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
# INERT WHILE None: an equal split over the whole list gives the first and last
# candidate the same money, so the ranking changes nothing. That makes SCORER and
# TOP_K a single axis — sweep them together.
#
# None is the deliberate default anyway. Measure the rule with no cutoff first;
# a tuned number nobody has tested would only obscure which half of the design is
# carrying the result. Expect it to matter: with a permissive rule and ~50
# symbols, one month's contribution spread over the whole list funds each name
# with a rounding error and approximates buying everything.
TOP_K = None

# Smallest single purchase, in VND. 0 disables the floor. Fractional shares are
# allowed throughout, so nothing forces a minimum yet.
MIN_TICKET = 0
