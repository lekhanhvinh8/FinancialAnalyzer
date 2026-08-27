"""
Sizing: how one day's cash is divided among a ranked candidate list.

THE SPLIT IS EQUAL; THE RANKING DECIDES WHO IS IN

  An equal split over the WHOLE list makes the ordering irrelevant — first and
  last receive the same money — so the ranking only does work once there is a
  cutoff. `top_k` is that cutoff, and it is the parameter that gives a score its
  meaning.

  It is also the answer to a practical problem rather than a preference. A
  permissive buy condition admits most of the universe on an ordinary day, so
  splitting one month's contribution fifty ways funds each name with a rounding
  error. The information that one symbol is far below its median and another is
  barely below it has been averaged away, and the result approximates buying
  everything regardless of what the rule said.

  top_k = None keeps the whole list, and that is the right DEFAULT even so:
  measure the rule with no cutoff first, then sweep top_k and see what the
  ranking is worth. A tuned number nobody has tested yet would only hide which
  half of the design is carrying the result.

MIN_TICKET

  A floor on how small one purchase may be, so the same dilution cannot return in
  a subtler form. When the pot cannot fund the chosen candidates at that size,
  the list is trimmed FROM THE BOTTOM — the ranking already says which names to
  lose. Zero disables it, which is the default.

LIMITS

  `allocate(amount, candidates, limits)` takes an optional {symbol: ceiling} and
  gives no candidate more than its ceiling. That is how the concentration cap
  reaches sizing without either allocator learning what a Wallet is: the engine
  knows the portfolio and works out the headroom, and the allocator only has to
  respect a number it is handed.

  A ceiling of zero is a candidate that may not be funded at all. The engine
  normally drops those before they get here, so an allocator seeing one is not an
  error, just money that goes elsewhere.

WHAT THIS DELIBERATELY DOES NOT DO

  No re-sorting: the order is the scorer's judgement, and re-deriving it here
  would make two places responsible for one decision. Nothing here reads the
  wallet; a ceiling arrives as a plain number.
"""

from dataclasses import dataclass


@dataclass
class EqualSplitAllocator:
    """
    Split `amount` equally across the best `top_k` candidates.

    Returns [(Candidate, money)] summing to at most `amount`. An empty list means
    nothing was allocated; the caller decides what becomes of the cash, because
    the allocator never touches the wallet.
    """
    top_k: "int | None" = None
    min_ticket: float = 0.0

    def allocate(self, amount: float, candidates: list, limits: dict = None) -> list:
        if amount <= 0 or not candidates:
            return []

        chosen = candidates if self.top_k is None else candidates[:self.top_k]
        if not chosen:
            return []

        if self.min_ticket > 0:
            # Floor division, not rounding: a ticket must actually reach
            # min_ticket, not merely come close to it.
            affordable = int(amount // self.min_ticket)
            if affordable <= 0:
                return []
            chosen = chosen[:affordable]

        if not limits:
            each = amount / len(chosen)
            return [(c, each) for c in chosen]

        # WATER-FILLING, not "split then trim". Trimming would leave the money a
        # capped candidate could not take sitting as cash, which turns a
        # concentration limit into an accidental decision to hold cash. Filling
        # tops up whoever still has room, repeatedly, so the cap changes WHERE
        # the money goes and only reduces how much is spent when the whole
        # chosen list is full.
        room = {c.symbol: max(0.0, float(limits.get(c.symbol, amount)))
                for c in chosen}
        give = {c.symbol: 0.0 for c in chosen}
        left = amount
        active = [c for c in chosen if room[c.symbol] > 0]

        while left > 1.0 and active:
            share = left / len(active)
            moved = 0.0
            for c in active:
                take = min(share, room[c.symbol])
                if take <= 0:
                    continue
                give[c.symbol] += take
                room[c.symbol] -= take
                left -= take
                moved += take
            if moved <= 0:
                break
            active = [c for c in active if room[c.symbol] > 1.0]

        return [(c, give[c.symbol]) for c in chosen if give[c.symbol] > 0]

    def describe(self) -> str:
        k = "all" if self.top_k is None else str(self.top_k)
        out = f"equal split over top {k}"
        if self.min_ticket > 0:
            out += f", min ticket {self.min_ticket:,.0f}"
        return out


@dataclass
class QuotaAllocator:
    """
    Give each candidate a FIXED SHARE of the pot, in rank order, until the money
    runs out.

    HOW IT DIFFERS FROM AN EQUAL SPLIT, AND WHY THE RESERVE WANTS IT

      An equal split divides whatever is there by however many candidates there
      are, so the size of a purchase depends on how many other symbols happened
      to qualify that day. That is fine for a monthly contribution, which arrives
      on a schedule and has to go somewhere.

      Reserve money is different. It arrives in lumps, when something was sold,
      and there is no reason a lump should be cut into five just because five
      names look cheap. A quota says how much of the pot ONE name may take, and
      the number of names follows from that rather than the other way round: at
      25% the reserve funds four positions and stops, whatever the list length.

    THE FLOOR

      Below `min_split` the whole pot goes to the top-ranked candidate. Splitting
      a small reserve into quota-sized slices produces purchases too small to be
      worth their own line in the ledger, and — once costs are modelled — too
      small to survive a brokerage minimum. One decisive purchase beats five
      token ones.

    Percentages are of the pot AS PASSED IN, not of what is left after each
    allocation. Taking a percentage of the remainder would make the last
    candidate's share depend on how many came before it, which is exactly the
    dependence this allocator exists to remove.
    """
    quota_pct: float = 25.0
    min_split: float = 20_000_000.0
    top_k: "int | None" = None
    min_ticket: float = 0.0

    def allocate(self, amount: float, candidates: list, limits: dict = None) -> list:
        if amount <= 0 or not candidates:
            return []

        chosen = candidates if self.top_k is None else candidates[:self.top_k]
        if not chosen:
            return []

        def ceiling(c):
            return amount if not limits else max(0.0, float(limits.get(c.symbol, amount)))

        if amount < self.min_split:
            # All-in on the best name, but never past its ceiling. Walk down the
            # ranking for one that can take the money rather than giving up: the
            # pot is small by definition here and splitting it was already
            # rejected.
            for c in chosen:
                room = ceiling(c)
                if room > 1.0:
                    return [(c, min(amount, room))]
            return []

        quota = amount * self.quota_pct / 100
        if self.min_ticket > 0:
            quota = max(quota, self.min_ticket)

        # No water-filling here, unlike the equal split. The quota is a
        # DELIBERATE ticket size -- the whole reason this allocator exists is
        # that the size of a purchase should not depend on how many other names
        # qualified -- so a candidate held below its quota by the cap passes the
        # money down the ranking rather than inflating its neighbours.
        out, left = [], amount
        for c in chosen:
            if left < max(self.min_ticket, 1.0):
                break
            take = min(quota, left, ceiling(c))
            if take <= 1.0:
                continue
            out.append((c, take))
            left -= take
        return out

    def describe(self) -> str:
        k = "" if self.top_k is None else f", top {self.top_k}"
        return (f"quota {self.quota_pct:g}% each (all-in below "
                f"{self.min_split:,.0f}){k}")
