"""
A single/ strategy whose decisions come from the WHOLE MARKET.

NOT THE SAME THING AS THE TOP-LEVEL breadth/ PACKAGE, and the two are easy to
confuse because they read the same signal:

    breadth/                one wallet, buys the INDEX, breadth decides WHEN
    single/market_breadth/  one wallet PER SYMBOL, buys that symbol, breadth
                            decides when

Same input, different method. This one is a sibling of median1000: same engine,
same interval money, same report — the only difference is where the condition
comes from. median1000 asks "is this symbol cheap against its own history";
this asks "is the market cheap", and buys the symbol either way.

Named market_breadth rather than breadth so that no import, path or sentence
has to say which of the two it means.

    config.py        thresholds
    breadth_map.py   the date -> row join that makes a market signal usable by
                     a strategy that only ever sees row indices
    run_all.py       one symbol, or every symbol in parallel

Needs breadth_signals in the database: run `python -m breadth.run --fresh` if it
is empty.
"""
