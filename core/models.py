"""
The wallet: cash pools shared across the universe, one Position per symbol.

TWO POOLS AND MANY POSITIONS

    contribution   this month's money, waiting to be deployed
    reserve        cash raised by selling, plus anything the rules declined to
                   deploy, earning a deposit rate while it waits
    positions      one Position per symbol ever bought

THE RESERVE HOLDS CASH AND NOTHING ELSE

  This is the one place where a portfolio genuinely cannot mirror a per-symbol
  ledger. When the proceeds of every sale belong to one symbol, it is meaningful
  to carry a share count alongside the cash and speak of the reserve's average
  price. Once money from selling A can buy B, an average price over a mixture of
  symbols is not the price of anything, so the reserve here is a number of dong
  and no more.

  It is also the point of the whole design. Money is fungible across the basket:
  that is what lets an expensive holding be turned into a cheap one, which is the
  move no single-symbol method can make.

COST BASIS: TWO NUMBERS, AND WHICH ONE THE RETURN IS MEASURED AGAINST

    basis           the ORIGINAL outside capital behind this holding
    basis_current   what was actually paid for the shares held right now

  They agree until the first sale and diverge after it, and the difference is
  the whole point.

  Sell FPT for 40m that was bought with 18m of outside money, then put all 40m
  into STB. STB now costs 40m — that is basis_current, and it is the right
  number for "how is this position doing against what I paid for it". But only
  18m ever came out of the investor's pocket; the other 22m is profit being
  recycled. Measuring the final return against 40m would count the same gain
  twice, once as profit already earned and again as capital at risk.

  So basis travels with the money: it leaves a position on a sale, waits in
  reserve_basis, and comes back proportionally on the reinvest. Because it is
  reduced on the way out, summing it can never double-count, which is exactly
  what an "every dong ever put in, never reduced" field cannot promise.

  This mirrors totalCapital / totalCurrentCapital in single/models.py. The two
  methods are independent, but the accounting question is the same one and it
  has the same answer.
"""

from dataclasses import dataclass, field


@dataclass
class Trade:
    """One executed transaction. `kind` is 'buy', 'sell' or 'reinvest'."""
    kind: str
    symbol: str
    date: object
    index: int              # row index in that symbol's own series
    price: float            # VND per share
    amount: float           # VND moved
    shares: float           # shares moved
    basis: float = 0.0      # ORIGINAL capital moved (see Position.basis)


@dataclass
class Position:
    """One symbol's holding."""
    symbol: str
    shares: float = 0.0
    # The original outside capital behind what is held. Follows the money: out on
    # a sale, into reserve_basis, back on a reinvest. Never counts a dong twice,
    # which is why the final return is measured against this one.
    basis: float = 0.0
    # What was actually paid for the shares held right now. On a reinvest this
    # takes the full cash deployed, profit included, so it answers "how is this
    # position doing against what I paid" and NOT "what did I put in".
    basis_current: float = 0.0

    # Per-symbol clocks, not portfolio-wide. Every rule that would read them asks
    # "how long since we last touched THIS name", which a shared clock answers
    # wrongly as soon as two symbols trade in the same week.
    last_buy_index: int = -1
    last_sell_index: int = -1
    last_reinvest_index: int = -1

    trades: list = field(default_factory=list)

    @property
    def is_open(self) -> bool:
        return self.shares > 0

    def value(self, price: float) -> float:
        return self.shares * price

    def count(self, kind: str) -> int:
        return sum(1 for t in self.trades if t.kind == kind)


@dataclass
class Candidate:
    """
    One symbol a rule admitted on one day, carrying its rank key.

    Arms hand these over already sorted, best first. The allocator does not
    re-sort: ordering is the scorer's judgement and sizing is the allocator's,
    and keeping those apart is what lets a new scorer rank on something the
    allocator has never heard of.
    """
    symbol: str
    index: int
    price: float
    score: float = 0.0


class Wallet:
    def __init__(self):
        self.contribution = 0.0
        self.reserve = 0.0
        self.reserve_basis = 0.0

        self.positions: dict = {}

        self.last_contribution_month = None
        self.last_interest_month = None
        self.months = 0
        self.interest_paid = 0.0

    # ── Positions ─────────────────────────────────────────────────────────────

    def position(self, symbol: str) -> Position:
        pos = self.positions.get(symbol)
        if pos is None:
            pos = Position(symbol=symbol)
            self.positions[symbol] = pos
        return pos

    def open_positions(self) -> list:
        return [p for p in self.positions.values() if p.is_open]

    def held_symbols(self) -> list:
        return [p.symbol for p in self.positions.values() if p.is_open]

    # ── Aggregates ────────────────────────────────────────────────────────────

    @property
    def basis(self) -> float:
        """Original outside capital across every position. Safe to sum: it is
        reduced on a sale, so nothing is counted twice."""
        return sum(p.basis for p in self.positions.values())

    @property
    def basis_current(self) -> float:
        return sum(p.basis_current for p in self.positions.values())

    def holdings_value(self, prices: dict) -> float:
        """
        Mark every open position to `prices` ({symbol: VND}).

        Raises on a symbol with no price rather than valuing it at zero. The
        caller builds `prices` from the same universe the positions came from, so
        a gap is a bug in the run, not an event in the market, and a silent zero
        would look exactly like a company going to nothing.
        """
        total = 0.0
        for p in self.positions.values():
            if p.shares <= 0:
                continue
            price = prices.get(p.symbol)
            if price is None:
                raise KeyError(f"no price to value the position in {p.symbol}")
            total += p.shares * price
        return total

    def trades(self, kind: "str | None" = None) -> list:
        out = []
        for p in self.positions.values():
            out.extend(t for t in p.trades if kind is None or t.kind == kind)
        return out

    def count(self, kind: str) -> int:
        return sum(p.count(kind) for p in self.positions.values())
