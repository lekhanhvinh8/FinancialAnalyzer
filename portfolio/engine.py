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

from .models import Candidate, Trade, Wallet


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

def apply_cooldown(wallet, candidates, bars: int, field: str) -> list:
    """
    Drop candidates whose last action of this kind was fewer than `bars` ago.

    APPLIED HERE RATHER THAN IN A RULE because it asks about the WALLET and not
    about the market, and a Rule only ever sees one symbol's price series.

    BARS, NOT CALENDAR DAYS. Both numbers are row indices into the same symbol's
    own series, which is what makes the subtraction meaningful -- and what makes
    100 mean roughly five months of trading rather than three of calendar.

    It runs AFTER the ranking, so it only ever removes names and never reorders
    them. The consequence is easy to miss: removing the top of a list PROMOTES
    everything under it, so a cooldown does not merely restrain the names it
    blocks, it hands their money to whatever ranked below.
    """
    if not bars:
        return candidates
    out = []
    for c in candidates:
        last = getattr(wallet.position(c.symbol), field)
        if last < 0 or c.index - last >= bars:
            out.append(c)
    return out


def position_headroom(wallet, candidates, prices, max_pct, cash,
                      exempt=()) -> dict:
    """
    How much more may be put into each candidate before it exceeds `max_pct` of
    the portfolio. {symbol: VND}, and a symbol already at or over the cap gets 0.

    WHAT THE PORTFOLIO MEANS HERE

      Holdings marked to today's prices, PLUS the cash in hand. Including cash is
      what makes the rule solvable in one step: a purchase moves money from cash
      into a position, so the total is the same before and after it, and the
      constraint is a plain inequality rather than a fixed point.

      It is also the only denominator that works at the start. Measured against
      holdings alone, the first purchase into an empty wallet is 100% of the
      portfolio whatever its size, and nothing could ever be bought.

      The consequence is that the cap BINDS HARDEST EARLY and loosens on its own.
      With 8m a month and a 10% cap, month one allows 800k into any one name;
      by month twenty the portfolio is around 160m and a full month's
      contribution fits in a single position. That is the rule working, not a
      flaw in it, but it does mean the early years buy less than they receive.

    WHAT IT DOES NOT DO

      Nothing is ever sold to enforce this. A position that grows past the cap on
      its own is left alone -- the cap governs DECISIONS, not outcomes -- and it
      simply stops being eligible for more money until it falls back under.
    """
    if not max_pct:
        return {}

    held = 0.0
    for p in wallet.positions.values():
        if p.shares > 0:
            held += p.shares * prices.get(p.symbol, 0.0)
    total = held + cash + wallet.reserve
    if total <= 0:
        return {}

    ceiling = total * max_pct / 100.0
    out = {}
    for c in candidates:
        # AN INDEX IS NOT A COMPANY. The cap exists to stop the portfolio
        # depending on one issuer; a thirty-name aggregate is already the
        # diversification the cap is trying to buy, so holding it does not
        # concentrate anything. market.py excludes indices from the size ranking
        # on exactly this reasoning.
        #
        # It matters most because the index is the FALLBACK. Capping the one
        # destination for money nothing else will take does not spread the money
        # around -- there is nowhere else for it to go -- it simply leaves it in
        # cash.
        if c.symbol in exempt:
            out[c.symbol] = float("inf")
            continue
        pos = wallet.positions.get(c.symbol)
        value = (pos.shares * prices.get(c.symbol, c.price)) if pos and pos.shares > 0 else 0.0
        out[c.symbol] = max(0.0, ceiling - value)
    return out


def apply_position_cap(wallet, candidates, prices, max_pct, cash, exempt=()):
    """
    -> (candidates that may still take money, {symbol: ceiling})

    Both halves of the rule come from one calculation. A name with no headroom is
    dropped rather than allocated zero, so `candidates` stays an honest answer to
    "did anything qualify today" -- which is what decides whether the fallback
    fires.
    """
    if not max_pct or not candidates:
        return candidates, None
    room = position_headroom(wallet, candidates, prices, max_pct, cash, exempt)
    if not room:
        return candidates, None
    keep = [c for c in candidates if room.get(c.symbol, 0.0) > CASH_EPSILON]
    return keep, room


def _pool_cap_ranks(market, day, rule, symbols) -> dict:
    """
    Size percentile of each symbol WITHIN the day's survivors of the
    symbol-level conditions.

    This is the second reading of "top half of the basket" -- top half of what
    is LEFT after the price test, rather than of everything trading. The two are
    genuinely different filters, and which one you get is decided by the order
    of the two stages. See CapRankAboveRule and config.CAP_RANK_BASIS.

    symbol_only() is what makes the first stage expressible: the rule with every
    cross-sectional part stripped out. It already exists because a per-symbol
    chart may only draw that part.

    Indices are excluded, for the reason market.py excludes them from the
    universe ranking -- an aggregate is not a company and would take first place
    every day.
    """
    sym_rule = rule.symbol_only()
    pre = []
    for symbol in symbols:
        bar = day.bars.get(symbol)
        if bar is None:
            continue
        series = market[symbol]
        if series.is_index:
            continue
        if sym_rule is not None and not sym_rule.applies(series, bar.index):
            continue
        c = series.cap(bar.index)
        if c is not None:
            pre.append((symbol, c))

    if not pre:
        return {}
    pre.sort(key=lambda kv: kv[1])
    last = max(1, len(pre) - 1)
    return {s: pos / last for pos, (s, _v) in enumerate(pre)}


def rank(market, day, rule, scorer, symbols, cap_basis="universe") -> list:
    """
    Candidates among `symbols` that the rule admits, best score first.

    Ties break on symbol name so a run is reproducible. Not an edge case: with a
    NullScorer every candidate ties, and even a real scorer ties whenever two
    symbols sit the same distance from their references. Without the tie-break
    the order would follow dict iteration.
    """
    parts = getattr(scorer, "parts", None)

    # Only computed when something asks for it: it costs a second pass over the
    # universe and a sort, and the default basis needs neither.
    pool = (_pool_cap_ranks(market, day, rule, symbols)
            if cap_basis == "pool" else None)

    out, admitted = [], []
    for symbol in symbols:
        bar = day.bars.get(symbol)
        if bar is None:
            continue
        series = market[symbol]
        if not rule.applies(series, bar.index,
                            None if pool is None else pool.get(symbol)):
            continue
        admitted.append((symbol, bar, series))
        out.append(Candidate(symbol=symbol, index=bar.index, price=bar.price,
                             score=0.0 if parts else float(scorer(series, bar.index))))

    # A BlendScorer combines parts whose units do not compare, so it is resolved
    # HERE rather than per symbol: each part ranks the day's candidates, the
    # ranks are scaled to 0..1, and those are averaged by weight. rank() is the
    # only place the whole list exists. See scoring.BlendScorer.
    if parts and len(out) > 1:
        total_w = sum(w for _sc, w in parts) or 1.0
        blended = [0.0] * len(out)
        for sub, weight in parts:
            vals = [float(sub(series, bar.index)) for _sym, bar, series in admitted]
            order = sorted(range(len(vals)), key=lambda i: vals[i])
            last = len(vals) - 1
            pct = [0.0] * len(vals)
            for pos, i in enumerate(order):
                pct[i] = pos / last
            for i in range(len(out)):
                blended[i] += weight / total_w * pct[i]
        for c, v in zip(out, blended):
            c.score = v

    out.sort(key=lambda c: (-c.score, c.symbol))
    return out


# ── The loop ──────────────────────────────────────────────────────────────────

def run_backtest(market, plan, contribution: float, deposit_rate: float = 4.0,
                 leftover: str = "carry", track: bool = False) -> dict:
    """
    `plan` carries the three arms and the allocator; see strategy.py.

    Returns a flat result dict. The wallet itself is included so a caller can
    walk individual trades without this function having to anticipate every
    report anyone might want.
    """
    if leftover not in ("carry", "reserve"):
        raise ValueError(f"leftover must be 'carry' or 'reserve', got {leftover!r}")

    wallet = Wallet()

    # Month-end snapshots of the equity curve. Kept in a dict keyed by (year,
    # month) and overwritten every day, so what survives for each month is its
    # LAST trading day — no need to know in advance which day that is.
    #
    # Marking to market needs a price for every open position, and a position's
    # symbol may not trade on the snapshot day, so the last price seen is carried
    # forward. Off by default: it costs one pass over the positions per day, and
    # a sweep running thousands of backtests wants none of it.
    curve: dict = {}
    last_price: dict = {}

    # Computed once: it cannot change mid-run, and asking the Market per day
    # would be a lookup per candidate per bar. See position_headroom.
    cap_exempt = (frozenset(s for s in market.symbols if market[s].is_index)
                  if getattr(plan, "cap_exempt_index", True) else frozenset())

    for day in market.days():
        date = day.date
        # Kept up to date on every day, not only when tracking: the position cap
        # marks the portfolio to market before each decision, and a stale price
        # would size the purchase against a portfolio that no longer exists.
        for _sym, _bar in day.bars.items():
            last_price[_sym] = _bar.price

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
                         wallet.held_symbols(), cap_basis=plan.cap_basis):
            pos = wallet.position(cand.symbol)
            execute_sell(wallet, cand.symbol, pos.shares * cand.price,
                         cand.index, cand.price, date)

        # 4. Reinvest out of the shared reserve.
        if wallet.reserve >= CASH_EPSILON:
            candidates = rank(market, day, plan.reinvest_rule,
                              plan.reinvest_scorer, day.bars,
                              cap_basis=plan.cap_basis)
            candidates = apply_cooldown(wallet, candidates,
                                        plan.reinvest_cooldown,
                                        "last_reinvest_index")
            candidates, room = apply_position_cap(
                wallet, candidates, last_price, plan.max_position_pct,
                wallet.contribution, cap_exempt)
            alloc = getattr(plan, "reinvest_allocator", None) or plan.allocator
            for cand, amount in alloc.allocate(wallet.reserve, candidates, room):
                execute_reinvest(wallet, cand.symbol, amount, cand.index,
                                 cand.price, date)
            if wallet.reserve < CASH_EPSILON:
                # Sweep the residue, and the basis with it — a cost basis must
                # not outlive the cash it describes.
                wallet.reserve = 0.0
                wallet.reserve_basis = 0.0

        # 5. Buy with this month's cash.
        if wallet.contribution >= CASH_EPSILON:
            candidates = rank(market, day, plan.buy_rule, plan.buy_scorer,
                              day.bars, cap_basis=plan.cap_basis)
            # Nobody qualified: put the money in the fallback instead of letting
            # it sit. See Plan.fallback_symbol — this is what keeps a strict rule
            # from silently becoming a bet on holding cash.
            # The buy arm's own cooldown, kept separate from the reinvest
            # arm's: the two spend different money on different schedules, and
            # a monthly contribution meets a very different list from a lump
            # that arrives whenever something was sold.
            candidates = apply_cooldown(wallet, candidates, plan.buy_cooldown,
                                        "last_buy_index")

            # The cap runs BEFORE the fallback is considered, so a day on
            # which every candidate is full falls back like a day on which
            # nobody qualified. The fallback is then capped in its turn: it is a
            # position like any other and concentrating into the index would be
            # the same mistake wearing a different hat.
            candidates, room = apply_position_cap(
                wallet, candidates, last_price, plan.max_position_pct,
                wallet.contribution, cap_exempt)
            if not candidates and plan.fallback_symbol:
                bar = day.bars.get(plan.fallback_symbol)
                if bar is not None:
                    fb = [Candidate(symbol=bar.symbol, index=bar.index,
                                    price=bar.price, score=0.0)]
                    candidates, room = apply_position_cap(
                        wallet, fb, last_price, plan.max_position_pct,
                        wallet.contribution, cap_exempt)
            for cand, amount in plan.allocator.allocate(wallet.contribution,
                                                        candidates, room):
                execute_buy(wallet, cand.symbol, amount, cand.index,
                            cand.price, date)
            if wallet.contribution < CASH_EPSILON:
                wallet.contribution = 0.0

        # 6. Whatever the rules would not take. See the module docstring.
        if leftover == "reserve" and wallet.contribution > 0:
            wallet.reserve += wallet.contribution
            wallet.reserve_basis += wallet.contribution
            wallet.contribution = 0.0

        if track:
            held = 0.0
            for p in wallet.positions.values():
                if p.shares > 0:
                    held += p.shares * last_price.get(p.symbol, 0.0)
            curve[(date.year, date.month)] = {
                "date": str(date.date()),
                "equity": held + wallet.reserve + wallet.contribution,
                "invested": wallet.basis + wallet.reserve_basis + wallet.contribution,
                "holdings": held,
                "cash": wallet.reserve + wallet.contribution,
            }

    out = summarise(wallet, market)
    out["curve"] = [curve[k] for k in sorted(curve)]
    return out


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

    # Every symbol the run could have bought, whether it did or not. `holdings`
    # above is open positions only, which is what a "top holdings" list wants;
    # this is what a report wants, because a symbol the rule NEVER admitted in
    # eleven years is a finding, and one that is simply absent from the table
    # cannot be told apart from one that was never in the universe.
    #
    # state: held / closed / never. Rows that were never bought carry zeros, so
    # they change no total — the contribution column still sums to growth_%.
    universe = {}
    for symbol in market.symbols:
        p = wallet.positions.get(symbol)
        if p is None or not p.trades:
            state = "never"
            shares = basis = basis_cur = value = 0.0
            buys = sells = reinvests = 0
        else:
            shares = p.shares
            basis, basis_cur = p.basis, p.basis_current
            value = shares * prices[symbol]
            buys, sells = p.count("buy"), p.count("sell")
            reinvests = p.count("reinvest")
            state = "held" if shares > 0 else "closed"
        universe[symbol] = {
            "state": state, "shares": shares, "basis": basis,
            "basis_current": basis_cur, "value": value,
            "weight_%": (value / holdings_value * 100) if holdings_value else 0.0,
            "buys": buys, "sells": sells, "reinvests": reinvests,
        }

    return {
        "wallet": wallet,
        "universe": universe,
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
        "curve": [],
    }
