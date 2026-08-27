"""
Portfolio investing: one wallet, the whole basket.

A per-symbol method asks "does this rule beat buy-and-hold on FPT", once per
symbol, with a separate wallet each time. This package asks a different question:
given one monthly contribution and the whole basket to choose from, where should
it go. That is not a loop over the first question, because the money is shared
and the symbols compete for it.

THREE DECISIONS THAT COLLAPSE INTO ONE FOR A SINGLE SYMBOL

    rules.py       who is eligible today
    scoring.py     in what order they deserve the money
    allocator.py   how much each one gets

  With one candidate, eligibility is the whole decision and the size is "whatever
  cash there is" — so a per-symbol method can and does fuse all three. With a
  shared wallet they come apart, and the middle one has no per-symbol equivalent
  at all.

MODULE MAP

    allocator.py   sizing
    strategy.py    Plan — the three arms plus the allocator, i.e. the strategy
    engine.py      the daily loop and execution
    report.py      text comparison
    run.py         CLI

  Reading the market — data, universe, market, models — and the vocabulary for
  conditions — rules, scoring — moved to core/ when a second method needed the
  same things. What is left here is what makes this method THIS method: ranking
  symbols that compete for one wallet, and dividing that wallet between them.

RELATIONSHIP TO THE REST OF THE PROJECT

  This package shares core/ and the database. Prices, P/E and rolling statistics
  are facts about the market, and a second definition of them is how two halves
  of a project start disagreeing about reality.

  The strategy above that line is its own: its own arms, its own ledger, its own
  engine. Nothing here imports the single-symbol method, and nothing here can
  change one of its results — which is the point, because those results carry
  years of measured findings that a new experiment has no business disturbing.

  STATUS: closed. See CONCLUSIONS.md. The code and its tests stay; the parameter
  search does not continue.
"""
