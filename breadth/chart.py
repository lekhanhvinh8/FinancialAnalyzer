"""VN30 backtest chart, rendered by export/chart.py — the same code single/ uses."""

import sqlite3
from pathlib import Path

import pandas as pd

import database as db
from database import DB_PATH
from export.chart import save_backtest_chart


class _Trade:
    """Duck-type for save_backtest_chart. It reads attributes, never types."""

    def __init__(self, row, price_vnd, amount, shares, growth=0.0):
        self.index = row
        self.close = price_vnd * 1000     # the renderer divides by 1000
        self.time = ""
        self.finalBuy = amount
        self.numberOfShareCanBy = shares
        self.sellFinal = amount
        self.sellShare = shares
        self.sellCapital = amount
        self.sellGrowthRatito = growth
        self.reInvestFinal = amount
        self.reInvestShare = shares
        self.reInvestCapital = amount


def _load_df(symbol: str) -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as con:
        prices = pd.read_sql(
            "SELECT date AS time, close FROM daily_prices WHERE symbol = ? "
            "ORDER BY date", con, params=(symbol,))
        pes = pd.read_sql(
            "SELECT date AS time, pe_ratio FROM pe_ratios WHERE symbol = ? "
            "ORDER BY date", con, params=(symbol,))
    df = prices.merge(pes, on="time", how="left")
    df["time"] = pd.to_datetime(df["time"])
    df["pe_ratio"] = df["pe_ratio"].ffill()
    return df.reset_index(drop=True)


def build(result, config, out_dir: Path) -> Path:
    """
    Chart for the traded instrument, with every trade marked.

    Trades are located by DATE, not by the index they carry: the cached run and
    the full run number their bars differently, and only the date is the same in
    both.
    """
    symbol = config.SYMBOL
    df = _load_df(symbol)
    row_of = {d: i for i, d in enumerate(df["time"])}

    buys, sells, reinvests = [], [], []
    bucket = {"buy": buys, "sell": sells, "reinvest": reinvests}
    for t in result["wallet"].position(symbol).trades:
        row = row_of.get(pd.Timestamp(t.date))
        if row is None:
            continue
        growth = ((t.amount - t.basis) / t.basis * 100) if t.basis else 0.0
        bucket[t.kind].append(_Trade(row, t.price, t.amount, t.shares, growth))

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{symbol.lower()}_backtest.html"
    save_backtest_chart(
        df, buys, sells, reinvests,
        path=str(path),
        title=f"{symbol} — {config.PLAN_NAME}",
        index=symbol.lower(),
        cal_range_close=db.load_range_stats(symbol, df,
                                            range_days={config.WINDOW, 1000}),
        result=result,
        start_index=config.WINDOW - 1,
        sig1_window=config.SLOPE_WINDOW,
    )
    return path
