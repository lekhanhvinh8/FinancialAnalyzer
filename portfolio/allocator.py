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

WHAT THIS DELIBERATELY DOES NOT DO

  No re-sorting: the order is the scorer's judgement, and re-deriving it here
  would make two places responsible for one decision. No concentration cap and no
  view of what is already held, so allocation is stateless with respect to the
  wallet. A position limit means giving allocate() the wallet, which is a real
  interface change and should happen when there is a limit to enforce.
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

    def allocate(self, amount: float, candidates: list) -> list:
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

        each = amount / len(chosen)
        return [(c, each) for c in chosen]

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

    def allocate(self, amount: float, candidates: list) -> list:
        if amount <= 0 or not candidates:
            return []

        chosen = candidates if self.top_k is None else candidates[:self.top_k]
        if not chosen:
            return []

        if amount < self.min_split:
            return [(chosen[0], amount)]

        quota = amount * self.quota_pct / 100
        if self.min_ticket > 0:
            quota = max(quota, self.min_ticket)

        out, left = [], amount
        for c in chosen:
            if left < max(self.min_ticket, 1.0):
                break
            take = min(quota, left)
            out.append((c, take))
            left -= take
        return out

    def describe(self) -> str:
        k = "" if self.top_k is None else f", top {self.top_k}"
        return (f"quota {self.quota_pct:g}% each (all-in below "
                f"{self.min_split:,.0f}){k}")
