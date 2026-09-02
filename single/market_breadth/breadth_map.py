"""
The basket's breadth, aligned to one symbol's rows.

Every strategy in single/ is handed `index` -- a row number in that symbol's own
DataFrame -- and nothing else. A breadth signal is dated, not indexed, and it
belongs to the whole market rather than to any symbol, so it has to be joined by
DATE and handed over as {row_index: value}. That join is all this module does.
"""

import pandas as pd

import database as db

from . import config


def build_breadth_map(df, signal: str = None, universe: str = None,
                      window: int = None, variant: str = None) -> dict:
    """
    {row_index: signal value} for the rows of `df` (which needs a `time` column).

    Rows with no breadth reading are simply absent, and every strategy reading
    this treats a missing key as "do not act". A market reading we do not have
    is not a reason to buy or sell.

    Returns an empty dict when the configuration was never stored, so a caller
    that forgot to run breadth/ gets a strategy that never fires rather than a
    crash -- which run_breadth.py checks for and reports.
    """
    signal = signal or config.SIGNAL
    stored = db.load_breadth(universe or config.UNIVERSE,
                             window or config.WINDOW,
                             variant or config.VARIANT, [signal])
    if stored.empty or signal not in stored:
        return {}

    by_date = {pd.Timestamp(d): v for d, v in stored[signal].items()}
    out = {}
    for i, t in enumerate(df["time"]):
        v = by_date.get(pd.Timestamp(t))
        if v is not None and v == v:
            out[i] = float(v)
    return out


def describe(m: dict, label: str = "breadth") -> str:
    if not m:
        return f"{label}: khong co du lieu"
    v = sorted(m.values())
    return (f"{label}: {len(m)} ngay, min {v[0]:.1f}, "
            f"p50 {v[len(v) // 2]:.1f}, max {v[-1]:.1f}")
