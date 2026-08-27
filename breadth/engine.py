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

THE MONEY CODE IS NOT HERE

  execute_buy, execute_sell and execute_reinvest come from core.ledger, which is
  where portfolio/ debugged them over a long series of measured runs. Writing
  fresh ones for this engine produced three accounting bugs in a row, every one
  of them already solved there next to a comment explaining the trap. What is
  left in this file is the DECISION -- how much, today -- which is the only part
  that differs between the two methods.

  A purchase out of the reserve is recorded as a REINVEST, which is this
  project's word for money held back going in later. That is not a relabelling
  for its own sake: execute_reinvest is the function that knows only the
  original capital riding with that cash counts as basis.

THE CASH THAT IS NOT SPENT

  Carried, and earning the deposit rate. It is not a third arm: it accumulates
  when breadth is expensive and is spent when breadth improves, so the reserve
  is the mechanism by which restraint becomes a purchase later rather than a
  purchase forgone.
"""

from core.ledger import (CASH_EPSILON, _new_month, execute_buy,
                         execute_reinvest, execute_sell)
from core.models import Wallet


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
        # THE SELL CONDITION BLOCKS BOTH OTHER ARMS, whether or not there was
        # anything to sell. It is the CONDITION that carries the meaning: it
        # says the basket is extended today, and that is as much a reason not to
        # buy as it is a reason to leave. Gating on the executed trade instead
        # let an empty position buy on a day the plan had just called expensive.
        selling = not thin and plan.fires(plan.sell_when, i)
        if selling:
            pos = wallet.position(symbol)
            if pos.shares > 0:
                execute_sell(wallet, symbol, pos.shares * bar.price,
                             bar.index, bar.price, date)

        if selling:
            if wallet.contribution > CASH_EPSILON:
                wallet.reserve += wallet.contribution
                wallet.reserve_basis += wallet.contribution
                wallet.contribution = 0.0
            monthly = 0.0
            continue

        # 3b. Reinvest: spend the reserve when its own condition holds. A
        #     separate arm, not a side effect of the buy pace -- the reserve is
        #     older money and answers a different question.
        if not thin and plan.reinvest_when and plan.fires(plan.reinvest_when, i):
            take = wallet.reserve * plan.reinvest_pct
            if take >= CASH_EPSILON:
                execute_reinvest(wallet, symbol, take, bar.index, bar.price, date)

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
        # circulate for ever without being spent.
        pending = wallet.contribution
        want = pending * mult

        # PENDING FIRST, RESERVE ONLY ABOVE IT. At a multiple of one the reserve
        # is deliberately untouched: the normal pace is the normal pace, and the
        # reserve exists to be spent when the signal asks for MORE than normal.
        #
        # Both moves go through core.ledger, which is the whole point. A
        # purchase out of the reserve is a REINVEST in this project's
        # vocabulary -- money that was held back going in later -- and
        # execute_reinvest already knows that only the original capital riding
        # with that cash counts as basis while the full amount counts as
        # basis_current. Doing that arithmetic here is what produced three
        # separate accounting bugs before this call replaced it.
        from_pending = min(want, pending)
        if from_pending >= CASH_EPSILON:
            execute_buy(wallet, symbol, from_pending, bar.index, bar.price, date)

        rest = want - from_pending
        if rest >= CASH_EPSILON:
            execute_reinvest(wallet, symbol, rest, bar.index, bar.price, date)

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
        "reinvests": pos.count("reinvest"),
        "sells": pos.count("sell"),
        "invested": invested,
        "value": value,
        "holdings": held,
        "reserve": wallet.reserve,
        "interest": wallet.interest_paid,
        "growth_%": ((value - invested) / invested * 100) if invested else 0.0,
        "shares": pos.shares,
    }
