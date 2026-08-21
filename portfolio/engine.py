"""
The portfolio backtest: one wallet, one calendar, many symbols.

THE DAY

    1. pay interest on the reserve          (monthly)
    2. add this month's contribution        (monthly)
    3. SELL     — every held symbol its rule fires on; proceeds to the reserve
    4. REINVEST — rank candidates, split the reserve among them
    5. BUY      — rank candidates, split the contribution among them
    6. sweep the division residue

  Sell runs before buy so that a day which both raises and deploys cash does so
  in the order a person would: you cannot spend what you have not yet sold. And
  reinvest runs before buy so the older money, which has been waiting, gets first
  refusal on today's opportunities.

WHY AN ARM IS THREE OBJECTS

  An arm is a rule (who is eligible), a scorer (in what order) and — shared
  between arms — an allocator (how much each). A per-symbol method can collapse
  all three, because with one candidate eligibility is the whole decision and the
  size is "whatever cash there is". With a shared wallet they are genuinely
  separate questions, and the one that has no per-symbol equivalent at all is the
  ordering.

WHERE UNSPENT CONTRIBUTION GOES

  Two settings, and the default is not the obvious one.

    carry (default)   unspent cash stays in `contribution` and is offered again
                      tomorrow
    reserve           unspent cash moves to the reserve

  The reserve's only exit is the reinvest arm. While that arm is switched off —
  which is the shipped configuration, since this method only buys so far —
  sending money there makes it a ONE-WAY SINK: it would go in, earn the deposit
  rate, and never buy anything again. The backtest would slowly stop measuring
  the buy rule and start measuring a savings account.

  So carry is the default, and `reserve` becomes reasonable the day the reinvest
  arm can get the money back out.

COSTS ARE ZERO

  No brokerage, no sell tax, no lot size, no settlement delay, and fractional
  shares are allowed. That is a simplification, not an oversight, and it matters
  MORE here than for a single symbol: a portfolio trades far more often, so real
  costs would bite harder. Adding them is a separate change with its own switch,
  and until then every return here is an upper bound.
"""

from .models import Trade, Wallet


# Cash below this is numerically zero, in VND.
#
# NOT a tuning knob — a defence against an equal split that does not divide
# evenly in binary. 8,000,000 / 4 is exact and leaves the wallet at 0.0;
# 8,000,000 / 3 is not, and leaves a residue near 1e-10. That residue is still
# > 0, so the next day the arm runs again, the allocator splits the residue, and
# the engine books another trade — for a fraction of a dong.
#
# No return is affected: the money involved is nothing. The TRADE COUNTS are,
# badly, and a cost model would charge brokerage on every ghost. 1 VND is safely
# above any residue on wallets of this size and below the smallest amount that
# can buy anything.
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


# ── Arms ──────────────────────────────────────────────────────────────────────

def rank(market, day, rule, scorer, symbols) -> list:
    """
    Candidates among `symbols` that the rule admits, best score first.

    Ties break on symbol name so a run is reproducible. Not an edge case: with a
    NullScorer every candidate ties, and even a real scorer ties whenever two
    symbols sit the same distance from their references. Without the tie-break
    the order would follow dict iteration.
    """
    from .models import Candidate

    out = []
    for symbol in symbols:
        bar = day.bars.get(symbol)
        if bar is None:
            continue
        series = market[symbol]
        if not rule.applies(series, bar.index):
            continue
        out.append(Candidate(symbol=symbol, index=bar.index, price=bar.price,
                             score=float(scorer(series, bar.index))))
    out.sort(key=lambda c: (-c.score, c.symbol))
    return out


# ── The loop ──────────────────────────────────────────────────────────────────

def run_backtest(market, plan, contribution: float, deposit_rate: float = 4.0,
                 leftover: str = "carry") -> dict:
    """
    `plan` carries the three arms and the allocator; see strategy.py.

    Returns a flat result dict. The wallet itself is included so a caller can
    walk individual trades without this function having to anticipate every
    report anyone might want.
    """
    if leftover not in ("carry", "reserve"):
        raise ValueError(f"leftover must be 'carry' or 'reserve', got {leftover!r}")

    wallet = Wallet()

    for day in market.days():
        date = day.date

        # 1. Interest on idle cash, monthly.
        if _new_month(wallet.last_interest_month, date):
            wallet.last_interest_month = date
            interest = wallet.reserve * (deposit_rate / 100) / 12
            wallet.reserve += interest
            wallet.interest_paid += interest

        # 2. This month's contribution.
        if _new_month(wallet.last_contribution_month, date):
            wallet.last_contribution_month = date
            wallet.contribution += contribution
            wallet.months += 1

        # 3. Sell. Full exits, proceeds to the shared pool.
        #    The whole list acts: selling is not rationed the way buying is, so
        #    the allocator takes no part and the ordering is presentational.
        for cand in rank(market, day, plan.sell_rule, plan.sell_scorer,
                         wallet.held_symbols()):
            pos = wallet.position(cand.symbol)
            execute_sell(wallet, cand.symbol, pos.shares * cand.price,
                         cand.index, cand.price, date)

        # 4. Reinvest out of the shared reserve.
        if wallet.reserve >= CASH_EPSILON:
            candidates = rank(market, day, plan.reinvest_rule,
                              plan.reinvest_scorer, day.bars)
            for cand, amount in plan.allocator.allocate(wallet.reserve, candidates):
                execute_reinvest(wallet, cand.symbol, amount, cand.index,
                                 cand.price, date)
            if wallet.reserve < CASH_EPSILON:
                # Sweep the residue, and the basis with it — a cost basis must
                # not outlive the cash it describes.
                wallet.reserve = 0.0
                wallet.reserve_basis = 0.0

        # 5. Buy with this month's cash.
        if wallet.contribution >= CASH_EPSILON:
            candidates = rank(market, day, plan.buy_rule, plan.buy_scorer, day.bars)
            for cand, amount in plan.allocator.allocate(wallet.contribution,
                                                        candidates):
                execute_buy(wallet, cand.symbol, amount, cand.index,
                            cand.price, date)
            if wallet.contribution < CASH_EPSILON:
                wallet.contribution = 0.0

        # 6. Whatever the rules would not take. See the module docstring.
        if leftover == "reserve" and wallet.contribution > 0:
            wallet.reserve += wallet.contribution
            wallet.reserve_basis += wallet.contribution
            wallet.contribution = 0.0

    return summarise(wallet, market)


def summarise(wallet: Wallet, market) -> dict:
    prices = market.final_prices()
    holdings_value = wallet.holdings_value(prices)

    # ORIGINAL capital only. wallet.basis is reduced whenever a position is sold
    # and the same amount lands in reserve_basis, so the three terms partition
    # the money rather than overlapping — every dong is in exactly one of them:
    # invested in something, waiting in the reserve, or not yet deployed.
    invested = wallet.basis + wallet.reserve_basis + wallet.contribution
    final = holdings_value + wallet.reserve + wallet.contribution
    growth = (final - invested) / (invested or 1) * 100

    # The other question: how are the CURRENT holdings doing against what was
    # actually paid for them. Differs from `growth` only once a sale has recycled
    # profit into a new position, and it is not the number to judge the strategy
    # by — see models.py.
    growth_current = ((holdings_value - wallet.basis_current)
                      / (wallet.basis_current or 1) * 100)

    holdings = {
        p.symbol: {
            "shares": p.shares,
            "value": p.shares * prices[p.symbol],
            "weight_%": (p.shares * prices[p.symbol] / holdings_value * 100
                         if holdings_value else 0.0),
            "basis": p.basis,
            "basis_current": p.basis_current,
            "buys": p.count("buy"),
            "sells": p.count("sell"),
            "reinvests": p.count("reinvest"),
        }
        for p in sorted(wallet.open_positions(),
                        key=lambda q: -q.shares * prices[q.symbol])
    }

    return {
        "wallet": wallet,
        "months": wallet.months,
        "invested": invested,
        "final": final,
        "growth_%": growth,
        "growth_current_%": growth_current,
        "basis": wallet.basis,
        "basis_current": wallet.basis_current,
        "holdings_value": holdings_value,
        "reserve": wallet.reserve,
        "idle_cash": wallet.contribution,
        "interest_paid": wallet.interest_paid,
        "symbols_held": len(wallet.open_positions()),
        "symbols_traded": len([p for p in wallet.positions.values() if p.trades]),
        "buys": wallet.count("buy"),
        "sells": wallet.count("sell"),
        "reinvests": wallet.count("reinvest"),
        "holdings": holdings,
    }
