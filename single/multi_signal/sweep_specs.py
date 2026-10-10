"""
Every sweep's grid, as data. Run them with sweep_runner; what each one found
when it was last run is in SWEEPS.md.

A spec is a set of cells, and a cell is a dict of config overrides. A cell named
"live" with no overrides is always added: it is the configuration being run,
and every paired comparison defaults to it.

Grids are the ones the original scripts ran, so a re-run is comparable with
what SWEEPS.md records -- with one difference worth knowing: the originals were
measured on the config of their day, and the base is now config.py as it stands
plus --profile / --set. Pass the profile or --set values that SWEEPS.md names to
reproduce an old measurement.
"""

import itertools
import math
from dataclasses import dataclass, field

# Spread of price-to-median distance at window w: p95 = 1.290 * w^0.698
# (dispersion.py). Thresholds that sweep a window are scaled by it, so q means
# the same tail at every window.
P95_C, P95_A = 1.290, 0.698


def _fmt(v) -> str:
    return "none" if v is None else f"{v:g}" if isinstance(v, (int, float)) else str(v)


@dataclass
class Spec:
    name: str
    title: str
    axes: tuple = ()
    cells: dict = field(default_factory=dict)    # key -> config overrides
    coords: dict = field(default_factory=dict)   # key -> one value per axis
    labels: dict = field(default_factory=dict)   # key -> row label
    note: str = ""
    profile: str | None = None                   # default --profile


def grid(name, title, axes: dict, make, extra=None, note="", profile=None) -> Spec:
    """
    Cartesian product of `axes` ({axis_name: values}); `make(*values)` returns
    the overrides for one cell. `extra` adds named context cells outside the grid.
    """
    s = Spec(name, title, tuple(axes), note=note, profile=profile)
    s.cells["live"] = {}
    s.labels["live"] = "live (as configured)"
    for k, v in (extra or {}).items():
        s.cells[k] = v
    for vals in itertools.product(*axes.values()):
        key = "|".join(_fmt(v) for v in vals)
        s.cells[key] = make(*vals)
        s.coords[key] = vals
        s.labels[key] = ", ".join(f"{a}={_fmt(v)}" for a, v in zip(axes, vals)) \
            if len(axes) > 1 else _fmt(vals[0])
    return s


def one(name, title, param, values, extra=None, note="", profile=None) -> Spec:
    return grid(name, title, {param: values}, lambda v: {param: v},
                extra=extra, note=note, profile=profile)


SPECS = {}


def _add(spec):
    SPECS[spec.name] = spec


# ── Single parameters ─────────────────────────────────────────────────────────

_add(one("percent_sell", "PERCENT_SELL — sell when price is X% above its median",
         "PERCENT_SELL",
         [-20, -10, 0, 10, 20, 30] + list(range(40, 111, 5))
         + [120, 135, 150, 175, 200, 250, 300, None],
         note="Larger is stricter (sells less). None removes the price condition."))

_add(one("percent_reinvest", "PERCENT_REINVEST — reinvest when price is under median + X%",
         "PERCENT_REINVEST", [-25, -15, -10, -5, 0, 5, 10, 20, 35, 50, 80, 120, 160, None],
         note="Larger is more permissive. None removes the price condition."))

_add(one("min_signal3", "MIN_SIGNAL3 — block a sell while the 1000-bar Sharpe is above X",
         "MIN_SIGNAL3",
         [-0.5, -0.25, 0.0, 0.15, 0.3, 0.45, 0.6, 0.75, 0.9, 1.1, 1.3, 1.6, 2.0, 2.5, 3.5, None]))

_add(one("reinvest_timeout", "REINVEST_TIMEOUT_DAYS — the unconditional release valve",
         "REINVEST_TIMEOUT_DAYS",
         [0, 20, 40, 60, 90, 130, 190, 270, 400, 550, 800, 1200, 1800, 2800],
         note="0 disables the valve."))

_add(one("pelog", "SELL_MIN_PELOG — block a sell while ln(P/E / its median) is at or below X",
         "SELL_MIN_PELOG",
         [-0.80, -0.60, -0.40, -0.30, -0.20, -0.10, 0.00, 0.10,
          0.20, 0.25, 0.30, 0.35, 0.40, 0.50, 0.70, 0.90, None],
         note="Reads P/E stamped at quarter end, not publication date: lookahead."))

_add(grid(
    "sell_bottom", "PERCENT_SELL_BOTTOM — sell X% above the 1000-bar low, median trigger off",
    {"PERCENT_SELL_BOTTOM": [50, 75, 100, 125] + list(range(150, 401, 25))
     + [450, 500, 600, None]},
    lambda v: {"PERCENT_SELL": None, "PERCENT_SELL_BOTTOM": v},
    note="PERCENT_SELL is off in every grid cell, so the bottom trigger acts alone; "
         "the none cell is that arm with no price trigger at all."))

_add(grid(
    "reinvest_top", "PERCENT_REINVEST_TOP — reinvest X% below the 1000-bar high, median trigger inert",
    {"PERCENT_REINVEST_TOP": [-5, -10, -15] + list(range(-20, -45, -2)) + [-50, -55, -60, -70, None]},
    lambda v: {"PERCENT_REINVEST": -999, "PERCENT_REINVEST_TOP": v},
    extra={"nothing": {"PERCENT_REINVEST": None, "PERCENT_REINVEST_TOP": None,
                       "REINVEST_MAX_BREADTH": None}},
    note="PERCENT_REINVEST = -999 keeps the median trigger from ever passing, so only "
         "the drawdown trigger and the timeout valve reinvest. 'nothing' is no "
         "reinvest arm at all."))


# ── Window x threshold, threshold scaled to the window ────────────────────────

_add(grid("buy_window", "BUY_MEDIAN_WINDOW x q, PERCENT_BUY = q * p95(w)",
          {"BUY_MEDIAN_WINDOW": list(range(20, 1001, 20)),
           "q": [round(-0.2 + 0.2 * i, 1) for i in range(10)]},
          lambda w, q: {"BUY_MEDIAN_WINDOW": w, "PERCENT_BUY": q * P95_C * w ** P95_A}))

_add(grid("sell_window", "SELL_MEDIAN_WINDOW x q, PERCENT_SELL = q * p95(w)",
          {"SELL_MEDIAN_WINDOW": list(range(20, 1001, 20)),
           "q": [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0, 1.3, 1.6, 2.0, 2.5, 3.0, 4.0]},
          lambda w, q: {"SELL_MEDIAN_WINDOW": w, "PERCENT_SELL": q * P95_C * w ** P95_A}))

_add(grid("sell_signal1", "SELL_SIGNAL1_WINDOW x k, SELL_MIN_SIGNAL1 = k / sqrt(w)",
          {"SELL_SIGNAL1_WINDOW": list(range(10, 201, 10)),
           "k": [round(-4.0 + 0.5 * i, 1) for i in range(17)]},
          lambda w, k: {"SELL_SIGNAL1_WINDOW": w, "SELL_MIN_SIGNAL1": k / math.sqrt(w)}))

_add(grid("reinvest_signal1", "REINVEST_SIGNAL1_WINDOW x k, REINVEST_MIN_SIGNAL1 = k / sqrt(w)",
          {"REINVEST_SIGNAL1_WINDOW": list(range(10, 201, 10)),
           "k": [round(-4.0 + 0.5 * i, 1) for i in range(17)]},
          lambda w, k: {"REINVEST_SIGNAL1_WINDOW": w,
                        "REINVEST_MIN_SIGNAL1": k / math.sqrt(w)}))

_add(grid("zdev", "SELL_ZDEV_WINDOW x SELL_MIN_ZDEV",
          {"SELL_ZDEV_WINDOW": [50, 100, 150, 200, 300, 400],
           "SELL_MIN_ZDEV": [-2.5, -2.0, -1.5, -1.0, -0.5, 0.0, 0.5, 0.9, 1.4, 2.0, 2.5]},
          lambda w, q: {"SELL_ZDEV_WINDOW": w, "SELL_MIN_ZDEV": q},
          extra={"off": {"SELL_MIN_ZDEV": None}}))


# ── Two and three parameters ──────────────────────────────────────────────────

_add(grid("sell_reinvest", "PERCENT_SELL x PERCENT_REINVEST",
          {"PERCENT_SELL": [60, 65, 70, 75, 80, 85, 90],
           "PERCENT_REINVEST": [-10, 0, 10, 20, 30, 40, 50, 60, 70, 80]},
          lambda s, r: {"PERCENT_SELL": s, "PERCENT_REINVEST": r}))

_add(grid("reinvest_2d", "PERCENT_REINVEST x PERCENT_REINVEST_TOP",
          {"PERCENT_REINVEST": [None, -10, 0, 5, 10, 20, 35],
           "PERCENT_REINVEST_TOP": [None, -30, -35, -40, -45, -50, -55, -60, -70]},
          lambda m, t: {"PERCENT_REINVEST": m, "PERCENT_REINVEST_TOP": t}))

_add(grid("sell_slope", "PERCENT_SELL x SELL_MIN_SIGNAL1",
          {"PERCENT_SELL": [60, 65, 70, 75, 80, 85, 90],
           "SELL_MIN_SIGNAL1": [None, 0.0, 0.1, 0.15, 0.183, 0.21, 0.228, 0.25,
                                0.274, 0.32, 0.365]},
          lambda s, k: {"PERCENT_SELL": s, "SELL_MIN_SIGNAL1": k}))

_add(grid("sell_slope3d", "PERCENT_SELL x SELL_SIGNAL1_WINDOW x k, SELL_MIN_SIGNAL1 = k / sqrt(w)",
          {"PERCENT_SELL": [30, 40, 50, 60, 70, 80, 85, 90, 100],
           "SELL_SIGNAL1_WINDOW": [10, 20, 30, 50, 70, 100, 140, 200],
           "k": [None] + [round(-1.0 + 0.5 * i, 1) for i in range(11)]},
          lambda s, w, k: {"PERCENT_SELL": s, "SELL_SIGNAL1_WINDOW": w,
                           "SELL_MIN_SIGNAL1": None if k is None else k / math.sqrt(w)}))


# ── The basket as a gate ──────────────────────────────────────────────────────

_BREADTH_NOTE = ("Runs on the breadth profile unless --profile says otherwise; "
                 "--set=PERCENT_SELL=55 measures the gate the way the default config uses it.")

_add(one("breadth_buy", "BUY_MAX_BREADTH — buy while the basket is at or below X",
         "BUY_MAX_BREADTH", [10, 20, 30, 40, 50, 55, 60, 65, 70, 75, 80, 90, None],
         note=_BREADTH_NOTE, profile="breadth"))
_add(one("breadth_sell", "SELL_MIN_BREADTH — sell only while the basket is above X",
         "SELL_MIN_BREADTH",
         [40, 50, 60, 70, 75, 80, 85, 90, 95, 100, 105, 110, 120, 130, None],
         note=_BREADTH_NOTE, profile="breadth"))
_add(one("breadth_reinvest", "REINVEST_MAX_BREADTH — reinvest while the basket is at or below X",
         "REINVEST_MAX_BREADTH", [-10, 0, 5, 10, 15, 20, 30, 40, 50, 60, None],
         note=_BREADTH_NOTE, profile="breadth"))
_add(one("breadth_timeout", "REINVEST_TIMEOUT_DAYS on the breadth profile",
         "REINVEST_TIMEOUT_DAYS", [0, 60, 120, 200, 300, 400, 500, 700, 1000, 1500],
         note=_BREADTH_NOTE, profile="breadth"))
