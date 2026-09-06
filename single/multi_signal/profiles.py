"""
Named sets of config overrides: which signal sources a run reads.

WHY PROFILES AND NOT TWO PACKAGES

  median1000 and market_breadth were separate packages, and they should not have
  been. They share the engine, the money, the report and the strategy classes;
  the only difference is WHICH CONDITION each arm reads. Two packages made that
  look like two methods and made the interesting combination -- this symbol is
  cheap AND the market is cheap -- impossible to write, because a run could only
  have one buy arm.

  Every condition is now a gate on the same three classes, and a profile is just
  which gates are on. None switches a gate off.

    price     the original: each arm reads the symbol against its own median,
              with the momentum, sharpe, zdev and pelog gates as configured.
              Reproduces what median1000 measured.

    breadth   the price triggers off, the basket's prem_median on.

              NOT BIT-IDENTICAL to the old market_breadth package, and the
              difference is real rather than a porting slip. That package had
              three bare strategy classes; these arms carry machinery those
              never had, and it still runs when only a breadth gate is on:

                REINVEST_TIMEOUT_DAYS   an unconditional release valve that
                                        fires when nothing has sold or
                                        reinvested for 400 bars, whatever the
                                        breadth gate says
                sell_strategy on buy    no buying on a bar that also sells

              Measured on five symbols, old / merged:
                FPT  262.9 / 245.6    HPG 577.2 / 174.0
                STB  805.5 / 357.8    VNM  25.6 /   4.0    VN30 182.5 / 92.3

              The merged run is the more conservative one. Set
              REINVEST_TIMEOUT_DAYS = 0 in this profile to drop the valve if the
              older behaviour is what you want to measure.

    both      both on, which is the arrangement neither package could express:
              act only when the symbol AND the market agree. Unmeasured.

Apply with `--profile=NAME` on run_all, or `apply(config, "breadth")`.
"""

PROFILES = {
    "price": {
        # The symbol's own price and nothing else.
        #
        # SPELLED OUT RATHER THAN LEFT EMPTY. It began as an empty overlay
        # meaning "config.py as it stands", which worked only while the shipped
        # config happened to be this. It no longer is -- the default runs the
        # buy and reinvest arms on the basket -- and an empty overlay would have
        # made every figure recorded under this name unreproducible without
        # anything failing. A named baseline states its own values.
        "PERCENT_BUY": 60,
        "PERCENT_REINVEST": 10,
        "BUY_MAX_BREADTH": None,
        "SELL_MIN_BREADTH": None,
        "REINVEST_MAX_BREADTH": None,
    },

    "breadth": {
        # Price triggers off on all three arms.
        "PERCENT_BUY": None,
        "PERCENT_SELL": None,
        "PERCENT_SELL_BOTTOM": None,
        "PERCENT_REINVEST": None,
        "PERCENT_REINVEST_TOP": None,
        # The gates that made median1000 what it is go with them: they were
        # tuned against a price trigger that is no longer firing.
        "MIN_SIGNAL3": None,
        "SELL_MIN_ZDEV": None,
        "SELL_MIN_PELOG": None,
        # The basket decides instead.
        "BUY_MAX_BREADTH": 60.0,
        "SELL_MIN_BREADTH": 70.0,
        "REINVEST_MAX_BREADTH": 10.0,
        # Kept: market_breadth measured with this momentum gate on the sell arm.
        "SELL_MIN_SIGNAL1": 0.228,
        "SELL_SIGNAL1_WINDOW": 120,
    },

    # "both", with the reinvest arm's two sources OR'd instead of AND'd.
    # Measured and rejected; kept so the comparison can be re-run in one command
    # instead of by editing a strategy class twice.
    "both_or": {
        "PERCENT_BUY": 60,
        "PERCENT_SELL": 75,
        "PERCENT_REINVEST": 10,
        "BUY_MAX_BREADTH": 60.0,
        "SELL_MIN_BREADTH": 70.0,
        "REINVEST_MAX_BREADTH": 10.0,
        "REINVEST_JOIN_OR": True,
    },

    # DIAGNOSTIC, not a strategy. "price" carries four gates that "breadth"
    # switches off, so comparing the two measures the gates and the signal at
    # once. This is "price" with the same gates off, which isolates the signal.
    "price_nogates": {
        # PRICE plus the three gates off, so it carries price's values too:
        # inheriting them made this "the default with three gates off", a
        # different experiment under the same name.
        "PERCENT_BUY": 60,
        "PERCENT_REINVEST": 10,
        "BUY_MAX_BREADTH": None,
        "SELL_MIN_BREADTH": None,
        "REINVEST_MAX_BREADTH": None,
        "MIN_SIGNAL3": None,
        "SELL_MIN_ZDEV": None,
        "SELL_MIN_PELOG": None,
    },

    # Both sources on every arm. The price half is spelled out for the same
    # reason "price" is: inheriting it from config.py made this profile an exact
    # copy of the default the moment the default's buy and reinvest arms moved
    # to the basket -- two names, one configuration, and nothing said so.
    "both": {
        "PERCENT_BUY": 60,
        "PERCENT_SELL": 75,
        "PERCENT_REINVEST": 10,
        "BUY_MAX_BREADTH": 60.0,
        "SELL_MIN_BREADTH": 70.0,
        "REINVEST_MAX_BREADTH": 10.0,
    },
}


def apply(config, name: str) -> dict:
    """
    Overlay a profile onto the config module, in place. Returns what changed.

    In place because factory.py and the report both read the module directly,
    and threading a settings object through either would be a larger change than
    the thing it enables.
    """
    if name not in PROFILES:
        raise SystemExit(f"profile khong co: {name}. Co: {', '.join(PROFILES)}")
    changed = {}
    for k, v in PROFILES[name].items():
        changed[k] = (getattr(config, k, None), v)
        setattr(config, k, v)
    setattr(config, "PROFILE", name)
    return changed
