"""
One method, many signal sources. Formerly median1000 and market_breadth.

THE NAME median1000 WAS WRONG FOR A LONG TIME. The sell arm already read seven
different things -- the 1000-bar median, the window low, signal3_sharpe,
signal1_slope, z_dev, pe-log, and price-or-P/E -- and the median was one of
them. market_breadth then added an eighth, the basket's median_prem, as three
separate classes in a separate package.

They were never two methods. Same engine, same money, same report; the only
difference is WHICH CONDITION each arm reads. Splitting them made the
interesting combination impossible to write -- act only when this symbol AND the
market agree -- because a run could have one buy arm and no more.

Every condition is now a gate on the same three strategy classes, and which
gates are on is a PROFILE:

    python -m single.multi_signal.run_all --all                    # price
    python -m single.multi_signal.run_all --all --profile=breadth
    python -m single.multi_signal.run_all --all --profile=both

    config.py     every threshold; None switches a gate off
    profiles.py   named overlays, and what each one is for
    factory.py    config -> the three arms
    breadth_map.py  the date -> row join a market signal needs
    run_all.py    one symbol or every symbol, in parallel
"""
