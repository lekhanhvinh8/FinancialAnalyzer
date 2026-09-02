"""
Thresholds for the market-breadth strategy.

Every number is compared against median_prem: the median distance from its own
1000-bar median across the whole basket, in percent. See breadth/signals.py.

NOTHING HERE HAS BEEN SWEPT. The values are the ones asked for, and the reason
to distrust a sweep is in the numbers themselves: the sell arm fires three times
in eleven years and the reinvest arm twice, on the same market-wide days for
every symbol. A sweep would be choosing which two days to catch.
"""

# Buy while the basket is not expensive. Fires on roughly 85% of days, so it
# barely restrains the monthly contribution -- which the decomposition confirms:
# buy-only scores within 3 points of plain interval buying.
BUY_MAX_BREADTH = 60.0

# Sell when the basket is broadly extended AND this symbol's own momentum has
# stopped. Both gates, for the reason SellMedian1000Strategy needs its slope
# gate: an extended market can stay extended for years.
SELL_MIN_BREADTH = 70.0
SELL_SIGNAL1_WINDOW = 120
SELL_MAX_SIGNAL1 = 0.228

# Reinvest only when the basket is genuinely cheap -- stricter than the buy arm,
# because the reserve is money already saved and can afford to wait.
#
# THIS IS THE ARM THAT CARRIES THE RESULT. Decomposed on eight symbols, buy-only
# is flat against interval and buy+sell is markedly WORSE (FPT 241% -> 107%);
# only adding the reinvest turns it around. The two reinvests land at the 2020
# and 2025 lows.
REINVEST_MAX_BREADTH = 10.0
REINVEST_PERCENT = 100.0

# Money and warmup, matching median1000 so the two are comparable.
INTERVAL_MONEY = 8_000_000
START_INDEX = 1000

# Which stored breadth run to read. Must match what breadth/ wrote; see
# breadth/signals.py::variant.
UNIVERSE = "all"
WINDOW = 1000
VARIANT = "trim5-95_slope120_zdev250"
SIGNAL = "median_prem"

# The history split the report uses for its Long / Short columns.
LONG_HISTORY_BARS = 2000
