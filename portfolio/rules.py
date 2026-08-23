"""
Conditions: does this arm want to act on this symbol today?

A rule answers yes or no about ONE symbol on ONE day. It never decides how much
to trade — with one wallet and many symbols, size depends on the whole candidate
list at once, so it belongs to the allocator. Ordering is not a rule's business
either; that is scoring.py. Three questions, three objects:

    rules.py        who is eligible
    scoring.py      in what order
    allocator.py    how much each

WHY THESE ARE NEW RULES AND NOT THE OLD ONES

  The conditions in single/strategies are entangled with the ledger they were
  written for: each one both tests a price and executes a trade against a
  single-symbol tracker. Pulling the test out of them would mean editing them,
  and they carry years of measured findings that should not be disturbed to
  serve a different method.

  So the tests are restated here, cleanly and with better names, and the two
  bodies of code stay independent. Where a threshold is deliberately the same
  idea as an old one, the docstring says so — but nothing here imports anything
  there, and a change here cannot move a single-symbol result.

SIGN CONVENTION, STATED ONCE

  `premium` throughout this package means

      (price - reference) / reference * 100

  so it is positive when the price is ABOVE the reference and negative below.
  Every threshold is read on that scale, which is the one thing worth getting
  right before reading any rule below.
"""

from dataclasses import dataclass


def premium(price: float, reference: float) -> "float | None":
    """Percent by which `price` exceeds `reference`. None if there is nothing to
    compare against."""
    if reference is None or not reference:
        return None
    return (price - reference) / reference * 100


class Rule:
    """Base: never acts. Also the real implementation of a switched-off arm."""

    def applies(self, series, index: int) -> bool:
        return False

    def windows(self) -> set:
        """Window sizes this rule reads, so the loader knows what to fetch."""
        return set()

    def describe(self) -> str:
        return type(self).__name__


class NeverRule(Rule):
    """
    An arm that does nothing.

    A named class rather than `None` because the engine always runs all three
    arms; switching one off should change what it decides, not whether it exists.
    """

    def describe(self) -> str:
        return "never"


class AlwaysRule(Rule):
    """
    Every eligible symbol, every day.

    This is the equal-weight DCA baseline's buy rule. Paired with an allocator
    that splits across the whole list, it spreads each month's money evenly over
    whatever is tradable — the plainest thing a person could do with a basket,
    and therefore the honest thing to measure against.
    """

    def applies(self, series, index: int) -> bool:
        return True

    def describe(self) -> str:
        return "always"


@dataclass
class PremiumBelowRule(Rule):
    """
    Act while the price is at most `max_premium` percent above `reference` over
    `window` bars.

    Read the sign carefully, because it decides everything: max_premium = 60
    means "act unless the price is more than 60% ABOVE its median". That is a
    PERMISSIVE condition which admits most of the universe on an ordinary day —
    it is a refusal to chase something wildly extended, not a hunt for bargains.

    It is deliberately named for what it tests rather than for the arm that uses
    it. The same rule reads as "buy unless overextended" on the buy arm and
    "redeploy while still reasonable" on the reinvest arm, and it should not have
    to be written twice to say so.

    `reference` is one of 'median', 'mean', 'top', 'bottom'. Median is the
    default because it is the reference least moved by a single spike in the
    window, which matters when the window is years long.

    A threshold is NOT transferable across window sizes: how far a price
    typically strays from its own median grows with the window, so a number
    that blocks nothing over 50 bars will block a fifth of days over 1000.
    """
    window: int = 1000
    max_premium: float = 60.0
    reference: str = "median"
    use_pe: bool = False

    def applies(self, series, index: int) -> bool:
        if index < series.warmup:
            return False
        current = series.pe(index) if self.use_pe else series.close(index)
        if current is None:
            return False
        p = premium(current, series.reference(self.reference, self.window, index))
        return p is not None and p < self.max_premium

    def windows(self) -> set:
        return {self.window}

    def describe(self) -> str:
        return (f"premium vs {self.reference}[{self.window}] < {self.max_premium:g}%"
                + (" (P/E)" if self.use_pe else ""))


@dataclass
class PremiumAboveRule(Rule):
    """
    Act once the price is more than `min_premium` percent above `reference`.

    The mirror of PremiumBelowRule, and the natural shape of a sell condition:
    something has run far enough from its own normal to be worth trimming.

    Not wired to anything yet — the shipped configuration only buys. It exists
    so the sell arm has a real rule to be switched on with rather than one to be
    written under pressure later, and so the engine's sell path is exercised by
    tests today.
    """
    window: int = 1000
    min_premium: float = 75.0
    reference: str = "median"
    use_pe: bool = False

    def applies(self, series, index: int) -> bool:
        if index < series.warmup:
            return False
        current = series.pe(index) if self.use_pe else series.close(index)
        if current is None:
            return False
        p = premium(current, series.reference(self.reference, self.window, index))
        return p is not None and p > self.min_premium

    def windows(self) -> set:
        return {self.window}

    def describe(self) -> str:
        return (f"premium vs {self.reference}[{self.window}] > {self.min_premium:g}%"
                + (" (P/E)" if self.use_pe else ""))


@dataclass
class SymbolIn(Rule):
    """
    Admit a symbol purely by name.

    The only rule here that asks WHICH symbol rather than what its price is
    doing, and it exists because a portfolio can hold instruments that are not
    candidates in the same sense as the rest.

    Two uses, both in strategy.py:

      - the benchmark buys the index and nothing else, which is
        SymbolIn({"VN30"}) on its own
      - the plan must NOT treat the index as an ordinary candidate competing
        with its own members, which is Not(SymbolIn({"VN30"})) AND the real
        condition. Without it the index would be bought alongside the very
        stocks it is composed of, and the comparison would be against a
        benchmark the plan partly holds.

    Reads no window, so it adds nothing to what the loader must fetch.
    """
    symbols: frozenset

    def __init__(self, symbols):
        self.symbols = frozenset(str(s).upper() for s in symbols)

    def applies(self, series, index: int) -> bool:
        return series.symbol.upper() in self.symbols

    def windows(self) -> set:
        return set()

    def describe(self) -> str:
        # "is VN30", not "in VN30" — this matches the symbol's own NAME, and the
        # index shares its name with the basket it tracks. Read as "in" it looks
        # like a membership test over the constituents, which is the opposite of
        # what Not(SymbolIn({"VN30"})) is doing.
        names = " or ".join(sorted(self.symbols))
        return f"is {names}"


@dataclass
class AllOf(Rule):
    """
    Every sub-rule must agree. Empty means never — an AND over nothing is
    vacuously true in logic, but a rule that fires on everything because it was
    left empty is a bug waiting to happen, so this reads it as "unconfigured".
    """
    rules: list

    def applies(self, series, index: int) -> bool:
        return bool(self.rules) and all(r.applies(series, index) for r in self.rules)

    def windows(self) -> set:
        return set().union(*(r.windows() for r in self.rules)) if self.rules else set()

    def describe(self) -> str:
        return " AND ".join(r.describe() for r in self.rules) if self.rules else "never"


@dataclass
class AnyOf(Rule):
    """Any sub-rule suffices. Empty means never, for the same reason as AllOf."""
    rules: list

    def applies(self, series, index: int) -> bool:
        return any(r.applies(series, index) for r in self.rules)

    def windows(self) -> set:
        return set().union(*(r.windows() for r in self.rules)) if self.rules else set()

    def describe(self) -> str:
        return " OR ".join(r.describe() for r in self.rules) if self.rules else "never"


@dataclass
class Not(Rule):
    """Inverts a rule. Useful for keeping one arm out of another's way."""
    rule: Rule

    def applies(self, series, index: int) -> bool:
        return not self.rule.applies(series, index)

    def windows(self) -> set:
        return self.rule.windows()

    def describe(self) -> str:
        return f"NOT ({self.rule.describe()})"
