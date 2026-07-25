"""
Sync rolling trend-classification signals into the trend_signals table.

Three signals are computed per (symbol, date, window_days):
  signal1_slope   — linear-regression slope of price, normalized as % of last price per day
  signal2_return  — simulated BuyInterval return % over the window
  signal3_sharpe  — annualized return / annualized volatility (Sharpe-like ratio)

Points are stored at step-day intervals going back from the latest price date:
  offsets = 0, step_days, 2*step_days, ..., max_lookback
so ~(max_lookback / step_days) rows per (symbol, window_days) instead of one per day.

Default parameters (can be overridden by callers):
  window_days  = 500   rolling lookback in trading days
  step_days    = 10    compute a point every N trading days
  max_lookback = 1500  how far back (in trading days) to go
  interval_days   = 20          BuyInterval: one purchase every N trading days (signal2)
  interval_money  = 8_000_000   BuyInterval: VND per purchase (signal2)
"""

import numpy as np

import database as db
from ._helpers import resolve_symbols

WINDOW_DAYS    = 500
STEP_DAYS      = 10
MAX_LOOKBACK   = 1500
INTERVAL_DAYS  = 20
INTERVAL_MONEY = 8_000_000


def sync_trend_signals(
    symbols:       list[str] | None = None,
    index:         str | None       = None,
    window_days:   int               = WINDOW_DAYS,
    step_days:     int               = STEP_DAYS,
    max_lookback:  int               = MAX_LOOKBACK,
    interval_days: int               = INTERVAL_DAYS,
    interval_money: float            = INTERVAL_MONEY,
    override:      bool              = False,
) -> None:
    """
    Rebuild trend signals for one or more symbols.

    symbols      : specific symbols; None = all in DB
    index        : index name ("vn30") — resolved to its index symbol
    window_days  : rolling lookback window in trading days
    step_days    : compute a signal point every N trading days
    max_lookback : how far back (trading days from latest) to go
    interval_days: interval between buys for signal2 simulation
    interval_money: amount invested per buy in signal2 simulation
    override     : True → INSERT OR REPLACE; False → INSERT OR IGNORE (skip existing)
    """
    targets = resolve_symbols(symbols, index)

    for sym, _ in targets:
        _rebuild_one(
            sym,
            window_days=window_days,
            step_days=step_days,
            max_lookback=max_lookback,
            interval_days=interval_days,
            interval_money=interval_money,
            override=override,
        )


def _rebuild_one(
    sym: str,
    window_days: int,
    step_days: int,
    max_lookback: int,
    interval_days: int,
    interval_money: float,
    override: bool,
) -> None:
    prices_df = db.load_daily_prices(sym)
    if prices_df.empty:
        print(f"  [trend_signals] {sym}: no price data — skipping")
        return

    closes = prices_df["close"].values.astype(float)
    dates  = prices_df.index
    N      = len(closes)

    if N < window_days + 1:
        print(f"  [trend_signals] {sym}: not enough data ({N} rows < window {window_days}) — skipping")
        return

    # Incremental: find latest already-stored date so we only add newer points
    latest_stored = None if override else db.load_latest_trend_signals_date(sym, window_days)

    rows: list[tuple] = []
    offsets = range(0, min(max_lookback, N - window_days) + 1, step_days)

    for offset in offsets:
        end_idx   = N - 1 - offset
        start_idx = end_idx - window_days + 1
        if start_idx < 0:
            break

        date_str = str(dates[end_idx].date())

        if latest_stored and date_str <= latest_stored and not override:
            continue

        window = closes[start_idx : end_idx + 1]

        s1 = _signal1_slope(window)
        s2 = _signal2_interval_return(window, interval_days, interval_money)
        s3 = _signal3_sharpe(window)

        rows.append((sym, date_str, window_days, s1, s2, s3))

    if not rows:
        print(f"  [trend_signals] {sym}: up to date")
        return

    result = db.save_trend_signals(sym, rows, override=override)
    print(f"  [trend_signals] {sym}: saved {result['saved']} rows")


# ── Signal implementations ────────────────────────────────────────────────────

def _signal1_slope(prices: np.ndarray) -> float:
    """Normalized linear-regression slope: % of last price per trading day."""
    x = np.arange(len(prices), dtype=float)
    slope = np.polyfit(x, prices, 1)[0]
    return float(slope / prices[-1] * 100)


def _signal2_interval_return(
    prices: np.ndarray,
    interval_days: int,
    interval_money: float,
) -> float:
    """
    Simulate buying interval_money every interval_days trading days.
    Returns (final_value - total_invested) / total_invested * 100.
    """
    total_invested = 0.0
    total_shares   = 0.0
    for i in range(0, len(prices), interval_days):
        total_shares   += interval_money / prices[i]
        total_invested += interval_money
    if total_invested == 0:
        return 0.0
    return float((total_shares * prices[-1] - total_invested) / total_invested * 100)


def _signal3_sharpe(prices: np.ndarray) -> float:
    """Annualized return / annualized volatility (Sharpe-like, no risk-free rate)."""
    if len(prices) < 2:
        return 0.0
    daily_returns  = np.diff(prices) / prices[:-1]
    annual_return  = float((prices[-1] / prices[0]) ** (252.0 / len(prices)) - 1)
    annual_vol     = float(daily_returns.std() * np.sqrt(252))
    if annual_vol == 0:
        return 0.0
    return annual_return / annual_vol
