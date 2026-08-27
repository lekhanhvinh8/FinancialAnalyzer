"""
Money. What a buy, a sell and a reinvest do to a wallet.

WHY THIS IS ITS OWN MODULE, AND WHY IT WAS EXTRACTED RATHER THAN REWRITTEN

  These functions were written and debugged inside portfolio/engine.py over a
  long series of measured runs. They carry the fixes for a ghost trade of
  2.26e-313 VND, for capital counted twice when a position was sold, and for a
  cost basis outliving the cash it described. Every one of those was found the
  hard way, and every one is still explained in the comment beside the line that
  fixes it.

  A second engine then needed the same operations and got a fresh
  implementation instead. Three of its first four bugs were in this code: a
  contribution sized off the wrong balance, interest booked as capital, and
  basis_current reduced when only basis should have been. All three were already
  solved here, next to a comment explaining the trap.

  So the decision half of an engine is genuinely per-strategy -- who to buy, in
  what order, how much -- and the money half is not. Contributions, reserve,
  interest and the two basis numbers mean exactly the same thing whichever
  strategy is asking.

  This module is a MOVE, not a rewrite. The bodies below are the ones
  portfolio/engine.py ran when it produced the results recorded in its config,
  and both packages now call them. Rewriting them to look tidier here would
  throw away the only thing that makes them trustworthy: that they have been
  run.

THE TWO BASIS NUMBERS

  `basis` is the ORIGINAL outside capital behind a holding; `basis_current` is
  what was actually paid for the shares held right now. They agree until the
  first sale and diverge after it, and keeping them apart is what stops recycled
  profit being counted as money the investor paid in. See core/models.py, and
  the comment inside execute_reinvest for the worked example.
"""

from .models import Trade, Wallet


CASH_EPSILON = 1.0


def _new_month(previous, now) -> bool:
    return (previous is None
            or now.year > previous.year
            or (now.year == previous.year and now.month > previous.month))


# ── Execution ─────────────────────────────────────────────────────────────────

def execute_buy(wallet: Wallet, symbol: str, amount: float, index: int,
                price: float, date) -> bool:
    if amount < CASH_EPSILON or price <= 0:
        return False
    # Only ever a rounding tail from the split; clamp rather than let the wallet
    # go negative.
    amount = min(amount, wallet.contribution)
    if amount < CASH_EPSILON:
        return False

    shares = amount / price
    wallet.contribution -= amount

    # Fresh outside money, so both numbers take the same amount. They only ever
    # diverge once a sale has put profit into the reserve.
    pos = wallet.position(symbol)
    pos.shares += shares
    pos.basis += amount
    pos.basis_current += amount
    pos.last_buy_index = index
    pos.trades.append(Trade("buy", symbol, date, index, price, amount, shares,
                            basis=amount))
    return True


def execute_sell(wallet: Wallet, symbol: str, amount: float, index: int,
                 price: float, date) -> bool:
    """
    Sell `amount` worth of `symbol` into the shared reserve.

    Written proportionally although every sell today is a full exit: partial
    sells are the next thing this arm will want, and proportional costs nothing
    now. Cost basis leaves in the same proportion as value, so what remains still
    describes what is held.
    """
    pos = wallet.position(symbol)
    value = pos.shares * price
    if pos.shares <= 0 or value <= 0 or amount < CASH_EPSILON:
        return False
    amount = min(amount, value)

    # Everything leaves in the same proportion as value, so the average cost per
    # share of what remains is unchanged by a partial sale.
    ratio = amount / value
    shares = pos.shares * ratio
    basis = pos.basis * ratio
    basis_current = pos.basis_current * ratio

    pos.shares -= shares
    pos.basis -= basis
    pos.basis_current -= basis_current
    pos.last_sell_index = index

    # Cash only — the reserve carries no share count. See models.py.
    wallet.reserve += amount
    wallet.reserve_basis += basis

    pos.trades.append(Trade("sell", symbol, date, index, price, amount, shares,
                            basis=basis))
    return True


def execute_reinvest(wallet: Wallet, symbol: str, amount: float, index: int,
                     price: float, date) -> bool:
    if amount < CASH_EPSILON or price <= 0 or wallet.reserve < CASH_EPSILON:
        return False
    amount = min(amount, wallet.reserve)

    # Basis leaves the pool in proportion to value, so the reserve's remaining
    # basis keeps describing the cash still in it.
    # THE ONE PLACE THE TWO BASIS NUMBERS PART COMPANY.
    #
    # `basis` takes only the ORIGINAL capital riding along with this cash, so the
    # profit being recycled is not re-counted as money the investor put in.
    # `basis_current` takes the full amount, because that is genuinely what these
    # shares cost today.
    #
    # Sell 18m of original capital for 40m and put all 40m into another name:
    # basis 18m, basis_current 40m. Measuring the final return against 40m would
    # count the 22m gain twice.
    basis = amount * wallet.reserve_basis / wallet.reserve if wallet.reserve else amount
    wallet.reserve -= amount
    wallet.reserve_basis -= basis

    shares = amount / price
    pos = wallet.position(symbol)
    pos.shares += shares
    pos.basis += basis
    pos.basis_current += amount
    pos.last_reinvest_index = index
    pos.trades.append(Trade("reinvest", symbol, date, index, price, amount,
                            shares, basis=basis))
    return True
