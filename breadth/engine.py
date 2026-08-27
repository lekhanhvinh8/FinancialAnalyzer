"""
The daily loop for a one-instrument, breadth-timed method.

WHAT IS DIFFERENT FROM portfolio/engine.py, AND WHY IT IS NOT A PARAMETER OF IT

  There is no candidate list, no ranking and no allocator. One instrument is
  held, so "which" has no meaning and the whole of rules.py's cross-sectional
  half is irrelevant. What is left is "how much, today", and the answer comes
  from a signal computed across the basket rather than from the instrument's own
  price.

  That inverts the role of the other symbols: in portfolio/ they compete for the
  money, here none of them is ever bought. A shared engine would have to pretend
  those are the same shape of day.

TWO ARMS, AND BOTH CAN BE SWITCHED OFF

  MODULATED BUYING is the default and the safer claim. The contribution always
  goes in; breadth decides how much of it, between a floor and a ceiling
  multiple. At worst this is DCA with the pace varied, and it cannot sit out a
  decade by accident.

  SELLING TO CASH is the stronger claim and the more dangerous one. It is market
  timing: get it wrong twice and the result trails plain DCA badly. Off unless a
  sell rule is configured.

  Both arms are Rules, so switching one off is a config change and its code path
  still runs -- the same arrangement portfolio/ uses, for the same reason.

WHY THE SIZING IS A MULTIPLE AND NOT A TARGET WEIGHT

  A target weight ("be 80% invested when breadth is cheap") needs selling to
  reach the target from above, which quietly turns the modulated arm into the
  timing arm. A multiple of the contribution can only ever change the PACE of
  accumulation, which keeps the two claims separate and separately measurable.

THE CASH THAT IS NOT SPENT

  Carried, and earning the deposit rate. It is not a third arm: it accumulates
  when breadth is expensive and is spent when breadth improves, so the reserve
  is the mechanism by which restraint becomes a purchase later rather than a
  purchase forgone.
"""

from core.models import Trade, Wallet

# Same guard as portfolio/engine.py: binary division leaves residue that is not
# zero and is not money either, and a ghost trade of 1e-13 VND is worse than a
# rounding error because it appears in the ledger.
CASH_EPSILON = 1.0


def _new_month(last, date) -> bool:
    return last is None or (date.year, date.month) != (last.year, last.month)


def execute_buy(wallet, symbol, amount, index, price, date) -> bool:
    if amount < CASH_EPSILON or price <= 0:
        return False
    pos = wallet.position(symbol)
    shares = amount / price
    pos.shares += shares
    pos.basis += amount
    pos.basis_current += amount
    pos.last_buy_index = index
    pos.trades.append(Trade("buy", symbol, date, index, price, amount, shares,
                            basis=amount))
    return True


def execute_sell(wallet, symbol, index, price, date) -> bool:
    """
    Sell the whole position into the reserve.

    Whole rather than partial, matching portfolio/: a partial sale needs a size
    rule of its own, and inventing one here would be a second untested decision
    riding on the first.
    """
    pos = wallet.position(symbol)
    if pos.shares <= 0 or price <= 0:
        return False
    proceeds = pos.shares * price
    shares = pos.shares

    # The basis leaves with the shares. Keeping it would double-count the
    # capital: it is about to be recorded again against the reserve.
    wallet.reserve += proceeds
    wallet.reserve_basis += pos.basis
    pos.basis = 0.0
    pos.basis_current = 0.0
    pos.shares = 0.0
    pos.last_sell_index = index
    pos.trades.append(Trade("sell", symbol, date, index, price, proceeds,
                            shares, basis=0.0))
    return True


def buy_multiple(plan, index: int) -> float:
    """
    How many contributions to spend today, as a multiple.

    THREE STATES, NOT A CURVE, deliberately. A continuous function of breadth
    would carry several more parameters and, on roughly a dozen independent
    cycles in this history, no way to tell whether any of them did anything.
    Three states can be read off a chart and argued about.

    Order matters: the strong arm is checked first and should be the stricter,
    since the normal arm is the fallback.
    """
    if plan.fires(plan.buy_when, index):
        return plan.buy_strong
    if plan.fires(plan.hold_when, index):
        return plan.buy_normal
    return plan.buy_weak


def run_backtest(market, breadth_series, plan, contribution: float,
                 deposit_rate: float = 4.0, track: bool = False) -> dict:
    """
    `plan.symbol` is the only instrument traded. Everything else in `market` is
    read to build `breadth_series` and is never bought.
    """
    wallet = Wallet()
    symbol = plan.symbol

    curve: dict = {}
    last_price = None
    monthly = 0.0

    for day in market.days():
        date = day.date
        bar = day.bars.get(symbol)
        i = breadth_series.row_of.get(date)

        if bar is not None:
            last_price = bar.price

        # 1. Interest on idle cash, monthly, before the contribution lands so a
        #    deposit cannot earn a month it was not there for.
        if _new_month(wallet.last_interest_month, date):
            wallet.last_interest_month = date
            if wallet.reserve > 0 and deposit_rate:
                earned = wallet.reserve * (deposit_rate / 100.0) / 12.0
                wallet.reserve += earned
                wallet.interest_paid += earned

        # 2. The monthly contribution.
        if _new_month(wallet.last_contribution_month, date):
            wallet.last_contribution_month = date
            wallet.months += 1
            wallet.contribution += contribution
            monthly = contribution

        if bar is None or i is None:
            continue

        support = breadth_series.counts[i]
        thin = support < plan.min_symbols

        # 3. Sell, if the arm is configured and breadth says the run is over.
        if not thin and plan.fires(plan.sell_when, i):
            execute_sell(wallet, symbol, bar.index, bar.price, date)

        # 4. Buy. On a thin day the pace falls back to plain DCA rather than to
        #    zero: a signal computed over six symbols is not evidence of
        #    anything, and treating it as evidence of "expensive" would sit out
        #    the earliest years for no reason.
        if wallet.contribution < CASH_EPSILON:
            continue

        mult = 1.0 if thin else buy_multiple(plan, i)

        # THE MULTIPLE IS OF WHAT IS PENDING, NOT OF ONE MONTH'S CONTRIBUTION.
        # A month whose first trading days the instrument did not trade leaves
        # two contributions waiting, and sizing off "one month" would push the
        # difference into the reserve where -- at a multiple of one -- it would
        # circulate for ever without ever being spent. That is what made the DCA
        # baseline hold 80m of principal it should have invested.
        pending = wallet.contribution
        want = pending * mult

        # PENDING FIRST, RESERVE ONLY ABOVE IT. At a multiple of one the reserve
        # is deliberately untouched: the normal pace is the normal pace, and the
        # reserve exists to be spent when the signal asks for MORE than normal.
        # Spending reserve first instead would drain and refill it every month
        # and the pace rule would move no money at all.
        from_pending = min(want, pending)
        from_reserve = min(max(0.0, want - from_pending), wallet.reserve)
        spend = from_pending + from_reserve

        if spend >= CASH_EPSILON and execute_buy(wallet, symbol, spend,
                                                 bar.index, bar.price, date):
            wallet.contribution -= from_pending

            # THE BASIS LEAVING THE RESERVE IS PROPORTIONAL, NOT THE WHOLE
            # AMOUNT. The reserve holds contributions AND the interest they
            # earned, and interest is profit, not capital. Deducting the full
            # withdrawal from reserve_basis while execute_buy adds the full
            # amount to the position's basis books the interest as though it
            # had been paid in: this run reported 1,103,038,348 invested
            # against 1,096,000,000 actually contributed, and growth is
            # measured against that denominator.
            if from_reserve > 0:
                share = (wallet.reserve_basis / wallet.reserve) if wallet.reserve else 0.0
                moved = min(wallet.reserve_basis, from_reserve * share)
                wallet.reserve -= from_reserve
                wallet.reserve_basis -= moved
                # execute_buy credited the whole spend as basis; give back the
                # part that was interest.
                pos = wallet.position(symbol)
                pos.basis -= (from_reserve - moved)
                pos.basis_current -= (from_reserve - moved)
                pos.trades[-1].basis -= (from_reserve - moved)

        # 5. Whatever today would not take moves to the reserve, where it earns
        #    the deposit rate until breadth improves.
        if wallet.contribution > CASH_EPSILON:
            wallet.reserve += wallet.contribution
            wallet.reserve_basis += wallet.contribution
        wallet.contribution = 0.0
        monthly = 0.0

        if track:
            held = wallet.position(symbol).shares * bar.price
            curve[(date.year, date.month)] = {
                "date": str(date.date()),
                "equity": held + wallet.reserve,
                "invested": wallet.basis + wallet.reserve_basis,
                "holdings": held,
                "cash": wallet.reserve,
                "below_pct": breadth_series.at("below_pct", i),
                "median_prem": breadth_series.at("median_prem", i),
                "n": float(support),
            }

    out = summarise(wallet, symbol, last_price)
    out["curve"] = [curve[k] for k in sorted(curve)]
    out["wallet"] = wallet
    return out


def summarise(wallet, symbol, price) -> dict:
    pos = wallet.position(symbol)
    held = pos.shares * (price or 0.0)
    value = held + wallet.reserve
    invested = wallet.basis + wallet.reserve_basis
    return {
        "months": wallet.months,
        "buys": pos.count("buy"),
        "sells": pos.count("sell"),
        "invested": invested,
        "value": value,
        "holdings": held,
        "reserve": wallet.reserve,
        "interest": wallet.interest_paid,
        "growth_%": ((value - invested) / invested * 100) if invested else 0.0,
        "shares": pos.shares,
    }
