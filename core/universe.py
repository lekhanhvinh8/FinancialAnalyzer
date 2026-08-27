"""
Which symbols the portfolio may hold.

Reads the shared registry and index membership; see config.UNIVERSE for the
survivorship caveat that applies to every option here.
"""

import sqlite3

from database import DB_PATH


def resolve(spec, exclude=(), extra=()) -> list:
    """
    `spec` is "all", an index name, or an explicit list of symbols.

    `extra` is appended AFTER the exclusion filter — it is for instruments the
    portfolio must be able to trade without their being ordinary candidates,
    i.e. the benchmark index. Filtering it out here would leave the plan with
    nothing to fall back to and the baseline with nothing to buy.
    """
    excluded = {s.upper() for s in exclude}

    if isinstance(spec, (list, tuple, set)):
        symbols = sorted({s.upper() for s in spec})
    elif isinstance(spec, str) and spec.lower() == "all":
        symbols = _all_stocks()
    else:
        symbols = _index_members(str(spec).lower())

    out = [s for s in symbols if s not in excluded]
    for e in extra:
        e = str(e).upper()
        if e not in out:
            out.append(e)
    return out


def _all_stocks() -> list:
    with sqlite3.connect(DB_PATH) as con:
        return [r[0].upper() for r in con.execute(
            "SELECT symbol FROM symbols WHERE symbol_type = 'stock' ORDER BY symbol")]


def _index_members(index_symbol: str) -> list:
    """
    CURRENT composition: a member with a departure date is out.

    Not point-in-time. Everything in this list carries its entire history,
    including the years before it joined the index, which is survivorship by
    construction — see config.UNIVERSE.
    """
    with sqlite3.connect(DB_PATH) as con:
        rows = con.execute(
            "SELECT DISTINCT member_symbol FROM index_members "
            "WHERE index_symbol = ? AND date_removed IS NULL ORDER BY member_symbol",
            (index_symbol,)).fetchall()
        if not rows:
            seeded = [r[0] for r in con.execute(
                "SELECT DISTINCT index_symbol FROM index_members ORDER BY index_symbol")]
            raise ValueError(
                f"no current members for index {index_symbol!r}; seeded: {seeded}")
    return [r[0].upper() for r in rows]
