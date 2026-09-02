"""
Per-symbol investing: one wallet per symbol, evaluated one symbol at a time.

A method here answers "does this rule beat buy-and-hold on FPT", once per
symbol, with a separate wallet each time. That is a different question from
portfolio/ (one wallet, many symbols competing) and from breadth/ (one wallet,
one instrument, timed by the market).

SHARED — every method below uses these

    engine.py       the daily loop and the three executors
    models.py       InvestmentTracker and the trade records
    runner.py       load_symbol_df, run_estimate
    range_calc.py   rolling statistics per symbol
    zdev_calc.py    z_dev
    sweep.py        generic 2-D parameter sweep and its plots
    strategies/     the vocabulary: buy, sell and reinvest conditions

METHODS — one package each, all with the same shape (config, runner, charts/)

    ma1000/          buy under the 1000-bar moving average
    median1000/      buy below the symbol's own 1000-bar median
    market_breadth/  buy on what the WHOLE MARKET is doing, not this symbol

  Nothing in a method package is imported by another. They share the engine and
  the vocabulary; they do not share decisions.
"""
