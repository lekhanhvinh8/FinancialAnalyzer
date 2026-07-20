"""
Parameter sweep for strategy combinations, with parallel execution.

Usage:
    from analyze.sweep import sweep_2d, plot_heatmap, plot_best

    results = sweep_2d(
        df, INTERVAL_MONEY, cal_range_close,
        make_strategies=lambda p1, p2: (
            BuyMAStrategy(localRangeDays=p1, decreasePercent=p2),
            sell_strategy,
            reinvest_strategy,
        ),
        param1_name="localRangeDays", param1_vals=[50, 100, 200, 500, 1000],
        param2_name="decreasePercent", param2_vals=[1, 3, 5, 10, 15, 20],
        max_workers=6,
    )
    plot_heatmap(results)
    plot_best(results, df, INTERVAL_MONEY, cal_range_close, make_strategies)
"""

import itertools
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

from .engine import estimate

# ── Worker globals (loaded once per worker process) ───────────────────────────
_df              = None
_cal_range_close = None
_interval_money  = None


def _init_worker(df, cal_range_close, interval_money):
    global _df, _cal_range_close, _interval_money
    _df              = df
    _cal_range_close = cal_range_close
    _interval_money  = interval_money


def _run_one(args):
    """Worker task: (p1, p2, buy_s, sell_s, reinvest_s) → (p1, p2, ratio)."""
    p1, p2, buy_s, sell_s, reinvest_s = args
    _, _, ratio, *_ = estimate(_df, _interval_money, buy_s, sell_s, reinvest_s, _cal_range_close, isPrint=False)
    return p1, p2, ratio


# ── Result container ──────────────────────────────────────────────────────────
@dataclass
class SweepResults:
    param1_name: str
    param1_vals: list
    param2_name: str
    param2_vals: list
    # {(p1, p2): ratio}
    ratios: dict

    def best(self):
        return max(self.ratios, key=self.ratios.get)

    def to_matrix(self) -> pd.DataFrame:
        mat = pd.DataFrame(index=self.param1_vals, columns=self.param2_vals, dtype=float)
        for (p1, p2), v in self.ratios.items():
            mat.loc[p1, p2] = v
        return mat


# ── Sweep ─────────────────────────────────────────────────────────────────────
def sweep_2d(
    df: pd.DataFrame,
    interval_money: float,
    cal_range_close: dict,
    make_strategies: Callable,   # (p1, p2) → (buy, sell, reinvest)
    param1_name: str,
    param1_vals: list,
    param2_name: str,
    param2_vals: list,
    max_workers: int = 4,
) -> SweepResults:
    """Run all (p1, p2) combinations in parallel; return SweepResults."""
    combos = list(itertools.product(param1_vals, param2_vals))
    tasks  = []
    for p1, p2 in combos:
        buy_s, sell_s, reinvest_s = make_strategies(p1, p2)
        tasks.append((p1, p2, buy_s, sell_s, reinvest_s))

    total   = len(tasks)
    ratios  = {}
    done    = 0

    print(f"Sweeping {param1_name} x {param2_name}: {total} combos, {max_workers} workers ...")
    with ProcessPoolExecutor(max_workers=max_workers,
                             initializer=_init_worker,
                             initargs=(df, cal_range_close, interval_money)) as ex:
        futures = {ex.submit(_run_one, t): t for t in tasks}
        for fut in as_completed(futures):
            p1, p2, ratio = fut.result()
            ratios[(p1, p2)] = ratio
            done += 1
            if done % max(1, total // 10) == 0 or done == total:
                print(f"  {done}/{total} done")

    best_p1, best_p2 = max(ratios, key=ratios.get)
    print(f"Best: {param1_name}={best_p1}, {param2_name}={best_p2} -> {ratios[(best_p1, best_p2)]:.2f}%")
    return SweepResults(param1_name, param1_vals, param2_name, param2_vals, ratios)


# ── Heatmap ───────────────────────────────────────────────────────────────────
def plot_heatmap(results: SweepResults, title: str = "Strategy sweep — allRatioGrowth (%)"):
    mat = results.to_matrix()
    best = results.best()

    fig, ax = plt.subplots(figsize=(max(8, len(results.param2_vals) * 1.2),
                                    max(5, len(results.param1_vals) * 0.8)))
    sns.heatmap(
        mat.astype(float),
        annot=True, fmt=".1f", linewidths=0.5,
        cmap="RdYlGn", ax=ax,
        cbar_kws={"label": "Growth %"},
    )

    # Mark best cell
    r = results.param1_vals.index(best[0])
    c = results.param2_vals.index(best[1])
    ax.add_patch(plt.Rectangle((c, r), 1, 1, fill=False, edgecolor="blue", lw=3))

    ax.set_title(title, fontsize=13, fontweight="bold")
    ax.set_xlabel(results.param2_name)
    ax.set_ylabel(results.param1_name)
    plt.tight_layout()
    plt.show()


# ── Chart for best (or given) combo ──────────────────────────────────────────
def plot_best(
    results: SweepResults,
    df: pd.DataFrame,
    interval_money: float,
    cal_range_close: dict,
    make_strategies: Callable,
    p1=None, p2=None,
):
    if p1 is None or p2 is None:
        p1, p2 = results.best()

    buy_s, sell_s, reinvest_s = make_strategies(p1, p2)
    _, _, ratio, buyed, sold, reinvested, _ = estimate(
        df, interval_money, buy_s, sell_s, reinvest_s, cal_range_close, isPrint=True
    )

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 10), sharex=True,
                                   gridspec_kw={"height_ratios": [3, 1]})

    close_vals = df["close"] * 1000
    ax1.plot(df.index, close_vals, color="black", linewidth=1, label="Price")

    ma_w = 1000
    if len(df) >= ma_w:
        ma = close_vals.rolling(ma_w).mean()
        ax1.plot(df.index, ma, color="royalblue", linewidth=1.5, label=f"MA{ma_w}", alpha=0.7)

    buy_idx   = [b.index for b in buyed]
    sell_idx  = [s.index for s in sold]
    reinv_idx = [r.index for r in reinvested]

    if buy_idx:
        ax1.scatter(buy_idx,   close_vals.iloc[buy_idx],   color="green",  zorder=4, s=40, label="Buy")
    if sell_idx:
        ax1.scatter(sell_idx,  close_vals.iloc[sell_idx],  color="red",    zorder=4, s=40, label="Sell")
    if reinv_idx:
        ax1.scatter(reinv_idx, close_vals.iloc[reinv_idx], color="orange", zorder=4, s=30, label="Reinvest")

    ax1.set_title(
        f"{results.param1_name}={p1}, {results.param2_name}={p2}  →  Growth: {ratio:.2f}%",
        fontsize=12, fontweight="bold"
    )
    ax1.set_ylabel("Price")
    ax1.legend(fontsize=8)
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))

    # P/E sub-chart
    if "pe_ratio" in df.columns:
        pe = df["pe_ratio"].ffill()
        ax2.plot(df.index, pe, color="purple", linewidth=1, label="P/E")
        ax2.set_ylabel("P/E")
        ax2.legend(fontsize=8)
        ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.1f}x"))

    plt.tight_layout()
    plt.show()
