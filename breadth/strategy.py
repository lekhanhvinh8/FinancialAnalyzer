"""
The plan: which signals each arm reads, and what it does about them.

A Plan here is smaller than portfolio/'s because two of its three decisions have
no meaning with one instrument. There is no ordering and no allocation; there is
a pace, and a switch.

WHY AN ARM IS A LIST OF (SIGNAL, RULE) AND NOT ONE RULE TREE

  core/rules.py composes conditions with AllOf and AnyOf, and every rule in the
  tree is handed the SAME series. That is right for a symbol, which has one price
  and one set of statistics.

  Breadth does not work that way. "A large share of the basket is under its
  median" and "the average momentum has stopped falling" are two different
  series, and the useful conditions almost always want both -- the first alone
  is a falling-knife rule, the second alone misses the bottom. A single tree
  cannot express that, because it has nowhere to say which series each leaf
  reads.

  So an arm is a list of pairs, ALL of which must hold. Each pair is still an
  ordinary core Rule reading an ordinary series, so nothing about the rule
  vocabulary had to change; only the wiring did. An empty list means the arm
  never fires, matching AllOf([]).
"""

from dataclasses import dataclass, field

from core.rules import NeverRule, Rule, ValueAboveRule, ValueBelowRule

from . import series as sig


@dataclass
class Plan:
    name: str
    symbol: str                       # the only instrument traded

    # [(signal name, Rule)] -- all must hold. buy_when is checked first and
    # should be the stricter of the two, since hold_when is the fallback.
    buy_when: list = field(default_factory=list)
    hold_when: list = field(default_factory=list)
    sell_when: list = field(default_factory=list)

    buy_strong: float = 2.0           # contributions to spend when buy_when holds
    buy_normal: float = 1.0
    buy_weak: float = 0.5

    min_symbols: int = 20
    window: int = 1000
    slope_window: int = 120

    _views: dict = field(default_factory=dict, repr=False)

    # ── what the loader must fetch ──────────────────────────────────────────

    def windows(self) -> set:
        """Per-symbol price windows the Market must load. See signal_windows."""
        return {self.window}

    def slope_windows(self) -> set:
        return {self.slope_window}

    def signal_windows(self) -> set:
        """
        Windows the RULES read over the breadth signal itself.

        Kept apart from windows() on purpose: one is a rolling statistic over a
        single series already in memory, the other is gigabytes fetched per
        symbol. Confusing them loads the database for nothing.
        """
        out = set()
        for arm in (self.buy_when, self.hold_when, self.sell_when):
            for _name, rule in arm:
                out |= rule.windows()
        return out or {1}

    def signals(self) -> set:
        return {n for arm in (self.buy_when, self.hold_when, self.sell_when)
                for n, _r in arm}

    def attach(self, breadth) -> None:
        """One SignalSeries per signal any arm names."""
        w = self.signal_windows()
        for name in self.signals():
            self._views[name] = sig.build(breadth, name, w)

    # ── evaluation ──────────────────────────────────────────────────────────

    def fires(self, arm: list, index: int) -> bool:
        if not arm:
            return False
        return all(rule.applies(self._views[name], index) for name, rule in arm)

    def describe(self) -> str:
        def arm(a):
            return " AND ".join(f"{n} {r.describe()}" for n, r in a) or "never"
        return "\n".join([
            f"Plan     : {self.name}",
            f"  symbol : {self.symbol}",
            f"  strong : {arm(self.buy_when)}   -> x{self.buy_strong:g}",
            f"  normal : {arm(self.hold_when)}   -> x{self.buy_normal:g}",
            f"  else   : x{self.buy_weak:g}",
            f"  sell   : {arm(self.sell_when)}",
            f"  min n  : {self.min_symbols}",
        ])


def build_plan(config) -> Plan:
    """
    THE DEFAULT SHAPE

      Buy hardest when a large share of the basket is under its own median AND
      average momentum is no longer deeply negative. The momentum half is what
      keeps the first condition from being a rule that buys all the way down;
      the level half is what keeps the second from buying every bounce.

      Buy normally when the basket is merely soft. Buy less otherwise -- less,
      not nothing, because sitting out entirely on a signal measured over a
      dozen independent cycles is a claim this data cannot support.
    """
    buy_when = [
        ("below_pct", ValueAboveRule(config.BUY_STRONG_BELOW_PCT)),
        ("mean_slope", ValueAboveRule(config.BUY_STRONG_MIN_SLOPE)),
    ]
    hold_when = [
        ("below_pct", ValueAboveRule(config.BUY_NORMAL_BELOW_PCT)),
    ]

    sell_when = []
    if getattr(config, "SELL_BELOW_PCT", None) is not None:
        # Sell when the basket is broadly extended AND momentum has rolled over.
        # Both, for the same reason the buy arm wants both: an extended market
        # can stay extended for years.
        sell_when = [
            ("below_pct", ValueBelowRule(config.SELL_BELOW_PCT)),
            ("mean_slope", ValueBelowRule(config.SELL_MAX_SLOPE)),
        ]

    return Plan(
        name=getattr(config, "PLAN_NAME", "breadth"),
        symbol=config.SYMBOL,
        buy_when=buy_when,
        hold_when=hold_when,
        sell_when=sell_when,
        buy_strong=config.BUY_STRONG_MULT,
        buy_normal=config.BUY_NORMAL_MULT,
        buy_weak=config.BUY_WEAK_MULT,
        min_symbols=config.MIN_SYMBOLS,
        window=config.WINDOW,
        slope_window=config.SLOPE_WINDOW,
    )


def build_baseline(config) -> Plan:
    """
    Plain DCA into the same instrument: every contribution, every month,
    whatever breadth says.

    This is the comparison the method has to win, and it is not the portfolio
    package's baseline -- a different question with a different denominator, and
    a difference printed here does not belong in the same table as one from
    there.

    Every branch spends exactly one contribution, so which branch fires cannot
    matter.
    """
    return Plan(
        name=f"DCA {config.SYMBOL}",
        symbol=config.SYMBOL,
        buy_strong=1.0, buy_normal=1.0, buy_weak=1.0,
        min_symbols=0,
        window=config.WINDOW,
        slope_window=config.SLOPE_WINDOW,
    )
