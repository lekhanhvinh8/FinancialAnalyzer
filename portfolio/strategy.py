"""
A Plan: the complete description of one thing to measure.

Three arms, each a rule and a scorer, plus one allocator shared between them.
Nothing else in this package holds strategy state, so a Plan IS the strategy, and
two Plans over the same Market are a controlled experiment — same calendar, same
universe, same warmup, differing only in what is written here.

WHY THE ALLOCATOR IS SHARED AND THE SCORERS ARE NOT

  Ordering is a judgement about opportunity and differs by arm: the buy arm wants
  the cheapest name, a sell arm the most stretched. Sizing is a policy about the
  wallet, and one wallet should not fund a five-name buy and a fifty-name
  reinvest on the same day without someone deciding it should.
"""

from dataclasses import dataclass, field

from .allocator import EqualSplitAllocator
from .rules import AlwaysRule, NeverRule, PremiumBelowRule, Rule
from .scoring import NullScorer, PremiumScorer, Scorer


@dataclass
class Plan:
    name: str
    buy_rule: Rule
    sell_rule: Rule = field(default_factory=NeverRule)
    reinvest_rule: Rule = field(default_factory=NeverRule)
    buy_scorer: Scorer = field(default_factory=NullScorer)
    sell_scorer: Scorer = field(default_factory=NullScorer)
    reinvest_scorer: Scorer = field(default_factory=NullScorer)
    allocator: EqualSplitAllocator = field(default_factory=EqualSplitAllocator)

    def windows(self) -> set:
        """
        Every window size this plan reads, so Market.load fetches those and no
        others. Collected from the rules and scorers themselves rather than from
        config, so adding a rule that reads a new window cannot leave the loader
        behind.
        """
        out: set = set()
        for part in (self.buy_rule, self.sell_rule, self.reinvest_rule,
                     self.buy_scorer, self.sell_scorer, self.reinvest_scorer):
            out |= part.windows()
        return out or {1000}

    def describe(self) -> str:
        lines = [f"plan: {self.name}",
                 f"  allocator : {self.allocator.describe()}"]
        for arm in ("buy", "sell", "reinvest"):
            rule = getattr(self, f"{arm}_rule")
            scorer = getattr(self, f"{arm}_scorer")
            lines.append(f"  {arm:<9} : {rule.describe()}   [rank: {scorer.describe()}]")
        return "\n".join(lines)


def build_plan(config) -> Plan:
    """
    The plan under test, from config.

    Buy only today. The sell and reinvest arms get NeverRule, which is a real
    rule that declines rather than a special case the engine has to know about —
    so their code paths run every day and switching one on is a config change.
    """
    scorer = _scorer(config)
    allocator = EqualSplitAllocator(top_k=getattr(config, "TOP_K", None),
                                    min_ticket=getattr(config, "MIN_TICKET", 0))

    buy_rule = PremiumBelowRule(
        window=config.BUY_WINDOW,
        max_premium=config.BUY_MAX_PREMIUM,
        reference=config.BUY_REFERENCE,
        use_pe=config.USE_PE,
    )

    return Plan(
        name=getattr(config, "PLAN_NAME", "portfolio"),
        buy_rule=buy_rule,
        buy_scorer=scorer(config.BUY_WINDOW, config.BUY_REFERENCE, cheapest_first=True),
        # Both arms stay off; their scorers are irrelevant until a rule admits
        # anything, and a NullScorer says that plainly.
        sell_rule=NeverRule(),
        reinvest_rule=NeverRule(),
        allocator=allocator,
    )


def build_baseline(config) -> Plan:
    """
    Equal-weight DCA: every eligible symbol gets 1/n of every contribution,
    nothing is ever sold.

    The comparison this method has to beat, and the plainest thing a person could
    do with a basket. Two details are deliberate:

      - NullScorer, not for lack of a better one. Every eligible symbol is
        equally deserving by definition here; an ordering would quietly make the
        baseline a second strategy.
      - top_k=None regardless of what the plan under test uses, for the same
        reason. A baseline that concentrated would be testing concentration.

    It shares the Market with the plan under test, so warmup, eligibility and the
    tradable calendar are identical by construction rather than by agreement.
    """
    return Plan(
        name="equal-weight DCA",
        buy_rule=AlwaysRule(),
        allocator=EqualSplitAllocator(top_k=None, min_ticket=0),
    )


def _scorer(config):
    """`(window, reference, cheapest_first) -> Scorer` for the configured SCORER."""
    from .scoring import DrawdownScorer

    name = getattr(config, "SCORER", "premium")
    if name in (None, "none", "null"):
        return lambda w, ref, cheapest_first=True: NullScorer()
    if name == "premium":
        return lambda w, ref, cheapest_first=True: PremiumScorer(
            window=w, reference=ref, cheapest_first=cheapest_first,
            use_pe=config.USE_PE)
    if name == "drawdown":
        return lambda w, ref, cheapest_first=True: DrawdownScorer(
            window=w, use_pe=config.USE_PE)
    raise ValueError(f"unknown SCORER {name!r}")
