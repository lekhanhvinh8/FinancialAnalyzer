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

from .allocator import EqualSplitAllocator, QuotaAllocator
from .rules import (AllOf, CapRankAboveRule, NeverRule, Not,
                    PremiumAboveRule, PremiumBelowRule, Rule,
                    SlopeBelowRule, SymbolIn)
from .scoring import BlendScorer, CapRankScorer, NullScorer, PremiumScorer, Scorer


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
    # Where this month's money goes when the buy rule admits NOBODY.
    #
    # Without it a strict rule quietly turns into a market-timing bet: the cash
    # waits, and the comparison stops being "which stocks" and becomes "stocks
    # versus cash". Falling back to the index keeps the plan fully invested on
    # every bar the benchmark is, so what is actually measured is the selection —
    # whether picking members beats simply holding the whole index.
    #
    # None restores the old behaviour: nothing is bought and the cash carries.
    fallback_symbol: "str | None" = None
    # The reinvest arm sizes its own purchases. The buy arm's allocator answers
    # "how do I spread a monthly wage", which is not the question a lump of
    # realised profit asks — see allocator.QuotaAllocator. None falls back to
    # `allocator`, so a plan that does not care keeps one policy for everything.
    reinvest_allocator: object = None
    # Bars that must pass before the reserve may buy the SAME symbol again.
    #
    # Cannot live in a Rule: a rule sees market data and this is a fact about
    # the wallet — when we last acted on this name. The engine applies it in the
    # reinvest step, where the wallet is in scope. 0 disables it.
    #
    # Without it the reserve concentrates by accident. The ranking is stable
    # from day to day, so the cheapest name stays cheapest, and a reserve that
    # is deployed over several days pours into the same one or two symbols
    # simply because nothing else has moved.
    reinvest_cooldown: int = 0

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

    def slope_windows(self) -> set:
        """Trend-signal windows this plan reads, for Market.load."""
        out: set = set()
        for r in (self.buy_rule, self.sell_rule, self.reinvest_rule):
            out |= r.slope_windows()
        return out

    def describe(self) -> str:
        lines = [f"plan: {self.name}",
                 f"  allocator : {self.allocator.describe()}"]
        for arm in ("buy", "sell", "reinvest"):
            rule = getattr(self, f"{arm}_rule")
            scorer = getattr(self, f"{arm}_scorer")
            lines.append(f"  {arm:<9} : {rule.describe()}   [rank: {scorer.describe()}]")
            if arm == "reinvest" and not isinstance(rule, NeverRule):
                alloc = self.reinvest_allocator or self.allocator
                extra = (f", cooldown {self.reinvest_cooldown}d"
                         if self.reinvest_cooldown else "")
                lines.append(f"  {'':<9}   {alloc.describe()}{extra}")
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

    # The benchmark instrument sits in the same Market as the members it is made
    # of, because the plan has to be able to BUY it as a fallback. It must not
    # also be admitted as an ordinary candidate: the plan would then hold the
    # index alongside its own constituents, and would be partly holding the very
    # thing it is measured against.
    # Size decides eligibility, not order — see config.CAP_WEIGHT for the
    # measurement that settled which.
    cap_min = getattr(config, "CAP_MIN_RANK", None)
    if cap_min is not None:
        buy_rule = AllOf([buy_rule, CapRankAboveRule(cap_min)])

    benchmark = getattr(config, "BENCHMARK", None)
    if benchmark:
        buy_rule = AllOf([Not(SymbolIn({benchmark})), buy_rule])

    # ── sell ─────────────────────────────────────────────────────────────────
    sell_min = getattr(config, "SELL_MIN_PREMIUM", None)
    if sell_min is None:
        sell_rule, sell_scorer = NeverRule(), NullScorer()
    else:
        sell_rule = PremiumAboveRule(window=config.BUY_WINDOW,
                                     min_premium=sell_min,
                                     reference=config.BUY_REFERENCE,
                                     use_pe=config.USE_PE)
        # Momentum gate. Sell when the run is over, not while it is happening —
        # see config.SELL_MAX_SIGNAL1 for the measurement that made this
        # necessary rather than optional.
        max_slope = getattr(config, "SELL_MAX_SIGNAL1", None)
        if max_slope is not None:
            sell_rule = AllOf([sell_rule, SlopeBelowRule(
                window=getattr(config, "SELL_SIGNAL1_WINDOW", 120),
                max_slope=max_slope)])
        if benchmark:
            # The fallback holding is the benchmark itself. Selling it would be
            # selling the thing the plan falls back TO, and on a rule tuned for
            # single stocks — an index does not stretch 70% above its own median
            # the way one company can.
            sell_rule = AllOf([Not(SymbolIn({benchmark})), sell_rule])
        # Most stretched first. Inert while every candidate sells anyway, and it
        # starts mattering the day sells are rationed or partial.
        sell_scorer = scorer(config.BUY_WINDOW, config.BUY_REFERENCE,
                             cheapest_first=False)

    # ── reinvest ─────────────────────────────────────────────────────────────
    if not getattr(config, "REINVEST_ENABLED", False):
        reinvest_rule, reinvest_scorer = NeverRule(), NullScorer()
        reinvest_alloc = None
    else:
        # The buy arm's price test, and NO cap filter — size enters through the
        # ranking instead. See config.REINVEST_CAP_WEIGHT.
        parts = [PremiumBelowRule(window=config.BUY_WINDOW,
                                  max_premium=config.BUY_MAX_PREMIUM,
                                  reference=config.BUY_REFERENCE,
                                  use_pe=config.USE_PE)]
        if benchmark:
            parts.insert(0, Not(SymbolIn({benchmark})))
        reinvest_rule = AllOf(parts)

        cheap = scorer(config.BUY_WINDOW, config.BUY_REFERENCE, cheapest_first=True)
        w = getattr(config, "REINVEST_CAP_WEIGHT", 0.0) or 0.0
        reinvest_scorer = (cheap if w <= 0 else
                           BlendScorer([(cheap, 1.0 - w), (CapRankScorer(True), w)]))

        reinvest_alloc = QuotaAllocator(
            quota_pct=getattr(config, "REINVEST_QUOTA_PCT", 25.0),
            min_split=getattr(config, "REINVEST_MIN_SPLIT", 20_000_000),
            min_ticket=getattr(config, "MIN_TICKET", 0))

    return Plan(
        name=getattr(config, "PLAN_NAME", "portfolio"),
        buy_rule=buy_rule,
        sell_rule=sell_rule,
        sell_scorer=sell_scorer,
        reinvest_rule=reinvest_rule,
        reinvest_scorer=reinvest_scorer,
        reinvest_allocator=reinvest_alloc,
        reinvest_cooldown=getattr(config, "REINVEST_COOLDOWN_DAYS", 0),
        fallback_symbol=(benchmark
                         if getattr(config, "FALLBACK_TO_BENCHMARK", False)
                         else None),
        buy_scorer=_buy_scorer(config, scorer),
        allocator=allocator,
    )


def build_baseline(config) -> Plan:
    """
    DCA into the benchmark index itself: every contribution buys BENCHMARK, and
    nothing is ever sold.

    A harder and more honest comparison than equal-weight DCA across the members.
    Equal weighting is itself a strategy — a deliberate tilt away from
    capitalisation weighting, which has historically paid on its own. Measuring
    against it would ask the plan to beat stock selection PLUS a weighting
    scheme, and neither a win nor a loss could then be attributed to either.

    Buying the index is what a person can actually do instead, so the difference
    answers one clean question: does choosing among the members beat holding all
    of them.

    Shares the Market with the plan, so warmup, eligibility and the tradable
    calendar are identical by construction rather than by agreement. It inherits
    the same warmup as every stock, which is why it cannot start on day one even
    though its own rule reads no window.

    With no BENCHMARK configured this falls back to equal-weight DCA across
    whatever is eligible.
    """
    benchmark = getattr(config, "BENCHMARK", None)
    if benchmark:
        return Plan(
            name=f"DCA {benchmark}",
            buy_rule=SymbolIn({benchmark}),
            allocator=EqualSplitAllocator(top_k=None, min_ticket=0),
        )

    from .rules import AlwaysRule
    return Plan(
        name="equal-weight DCA",
        buy_rule=AlwaysRule(),
        allocator=EqualSplitAllocator(top_k=None, min_ticket=0),
    )


def _buy_scorer(config, factory):
    """The price scorer, optionally blended with market-cap rank."""
    price = factory(config.BUY_WINDOW, config.BUY_REFERENCE, cheapest_first=True)
    w = getattr(config, "CAP_WEIGHT", 0.0) or 0.0
    if w <= 0:
        return price
    return BlendScorer([(price, 1.0 - w), (CapRankScorer(True), w)])


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
