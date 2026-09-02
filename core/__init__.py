"""
Shared machinery: reading the market, and the vocabulary for describing a
condition. No strategy lives here.

WHY THIS PACKAGE EXISTS

  Two methods now read the same database and mean the same thing by a price, a
  rolling median and a trading calendar. A second definition of any of those is
  how two halves of a project start disagreeing about reality, and the loading
  is also the expensive part of a run -- measured at roughly ten seconds per
  symbol per window -- so duplicating it duplicates the cost as well as the risk.

WHAT BELONGS HERE

  A module belongs in core when it would read the same whichever strategy asked.
  Prices, universes, calendars, a ledger of trades, and the rule and scorer
  vocabulary: these describe the market and the language for talking about it,
  not what to do about it.

    data.py       one symbol out of the database, as arrays
    universe.py   which symbols are in scope
    market.py     one calendar across many symbols, warmup per symbol
    models.py     Wallet, Position, Trade, Candidate
    rules.py      conditions -- pure, and they never see a wallet
    scoring.py    ranking
    progress.py   the run's progress page
    range_calc.py rolling window statistics for one price series
    zdev_calc.py  z_dev: a price against its own history, in its own sigmas

  range_calc and zdev_calc arrived here from single/ because syncs/ imports
  them: the data layer was depending on an investing method, which is the wrong
  way round. Both are arithmetic on a price series and know nothing about a
  wallet.

WHAT DOES NOT

  Engines, allocators and plans. Those ARE the strategy: portfolio/ ranks symbols
  competing for one wallet, breadth/ reads the basket as evidence about the
  market and acts on one instrument. They disagree about what a day means, and
  a shared engine would have to pretend otherwise.

  rules.py sits on the core side of that line because a Rule is a pure question
  about one series -- applies(series, index) -- and never touches a wallet. The
  wallet-shaped conditions, cooldown and the position cap, live in the engines
  for exactly that reason.
"""
