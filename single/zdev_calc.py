"""
Compute z_dev — relative valuation of a price series against its own history.

    M     = rolling median of price over median_window
    dev   = ln(price / M)
    mu    = rolling mean of dev over stat_window, shifted one bar
    sigma = rolling std  of dev over stat_window (ddof=1), shifted one bar
    z_dev = (dev - mu) / sigma

Why each piece:

  median, not mean — a median shrugs off a short crash; a mean stays dragged
  down by it for the whole window afterwards.

  log ratio — makes the scale symmetric: +60% and -37.5% are both 0.47 in
  magnitude. Without the log the distribution is right-skewed and an upper
  threshold means something different from the matching lower one.

  mu absorbs the part of "always above its own median" that is just growth,
  so a compounder is not permanently flagged as expensive. sigma is the
  security's own dispersion, so a 30% move is read against what is normal for
  that symbol. z_dev is therefore comparable across symbols with different
  growth rates and volatility.

No value at bar t uses data from after t:
  - M(t) uses closes up to and including t. That is intended: M is a
    contemporaneous base, not a forecast.
  - mu(t) and sigma(t) are shifted one bar, so they see dev only up to t-1.
    Today is scored against a baseline that does not know about today.

dev stays NaN until the median has a full window, and that matters more than
it looks. dev is not consumed one bar at a time — it feeds a rolling window.
A partial-window median at bar 500 would otherwise leak into mu/sigma for the
next stat_window bars, long past the point where callers guard on index.
Requiring a full median window is what stops that, and it is why the total
warmup is median_window + min_periods rather than just median_window.
"""

import numpy as np
import pandas as pd

MEDIAN_WINDOW = 1000

# The stat window is swept rather than fixed — see syncs/zdev.py. min_periods is
# always held equal to it, so a single-config call only needs one number.


def compute_dev(close: pd.Series, median_window: int = MEDIAN_WINDOW) -> pd.Series:
    """
    ln(price / rolling median). NaN until the median has a full window — see the
    module docstring for why a partial-window median must not be allowed through.

    dev depends only on median_window, so when sweeping stat windows it is
    computed once and reused rather than recomputed per configuration.
    """
    px = pd.Series(close, dtype="float64")
    px = px.where(px > 0)  # ln() needs positive prices
    m  = px.rolling(median_window, min_periods=median_window).median()
    return np.log(px / m)


def zdev_arrays(
    dev: pd.Series,
    stat_window: int,
    min_periods: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    mu/sigma/z_dev as raw numpy arrays for one (stat_window, min_periods) pair.

    Used by the sweep, which calls this once per stat window — building a
    DataFrame per call is pure overhead when the caller only needs the values.
    """
    roll  = dev.rolling(stat_window, min_periods=min(min_periods, stat_window))
    mu    = roll.mean().shift(1).to_numpy()
    sigma = roll.std(ddof=1).shift(1).to_numpy()
    # A flat window gives sigma == 0; dividing by it would yield ±inf
    with np.errstate(invalid="ignore"):
        z_dev = (dev.to_numpy() - mu) / np.where(sigma > 0, sigma, np.nan)
    return mu, sigma, z_dev


def zdev_from_dev(
    dev: pd.Series,
    stat_window: int,
    min_periods: int,
) -> pd.DataFrame:
    """mu/sigma/z_dev for one (stat_window, min_periods) pair from a prepared dev."""
    mu, sigma, z_dev = zdev_arrays(dev, stat_window, min_periods)
    return pd.DataFrame({"mu": mu, "sigma": sigma, "z_dev": z_dev}, index=dev.index)


def compute_zdev(
    close: pd.Series,
    median_window: int = MEDIAN_WINDOW,
    stat_window:   int = MEDIAN_WINDOW,
    min_periods:   int | None = None,   # None → stat_window
) -> pd.DataFrame:
    """
    Args:
        close         : price series, ascending by date (any index)
        median_window : window for the long-term price base M
        stat_window   : window for mu/sigma of dev
        min_periods   : observations required before mu/sigma emit a value.
                        Equal to stat_window means every value is built from
                        the same number of samples; lower starts earlier but
                        leaves a stretch of thin estimates between
                        median_window + min_periods and median_window + stat_window.

    Returns:
        DataFrame on the same index with columns dev, mu, sigma, z_dev.
        Rows before the warmup are NaN, never 0 — z_dev == 0 is a real reading
        ("exactly at its own average"), so it must not double as "no data".
    """
    if min_periods is None:
        min_periods = stat_window
    dev = compute_dev(close, median_window)
    out = zdev_from_dev(dev, stat_window, min_periods)
    out.insert(0, "dev", dev)
    return out


def price_ratio_at_z(mu: float, sigma: float, z: float) -> float:
    """
    Inverse of z_dev: the price/M ratio that corresponds to a given z.

        price/M = exp(mu + z * sigma)

    Useful for reading a z threshold back as a plain percentage above or
    below the long-term base.
    """
    return float(np.exp(mu + z * sigma))
