"""
Median1000 strategy configuration.
Edit these parameters to tune the analysis, then re-run run_one.py or run_all.py.
"""

INTERVAL_MONEY = 8_000_000   # VND invested per interval

# BuyMedian1000: buy when price is this % below the 1000-day median
PERCENT_BUY      = 40

# SellMedian1000: sell when price is this % above the 1000-day median
PERCENT_SELL     = 60

# ReInvestMedian1000: reinvest when price is this % below the 1000-day median
PERCENT_REINVEST = -1

USE_PE = False   # use P/E-adjusted median instead of price median
