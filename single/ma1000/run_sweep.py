"""
Run BuyMAStrategy sweep (localRangeDays x decreasePercent, use_pe=True)
and save results to Excel heatmap.

Usage:
    python -m single.ma1000.run_sweep
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import itertools
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
from openpyxl.formatting.rule import ColorScaleRule

import database as db
from single.engine import estimate
from core.range_calc import build_cal_range_close
from single.strategies.buy import BuyMAStrategy
from single.strategies.sell import SellTopOfMA1000Strategy
from single.strategies.reinvest import ReInvestUnderMA1000Strategy

INTERVAL_MONEY  = 8_000_000
INDEX_SYMBOL    = 'VN30'
RANGE_DAYS_VALS = list(range(1, 1501))              # [1..1500]
DECREASE_VALS   = [1, 3, 5, 10, 15, 20, 30]        # 7 values


def load_df():
    prices = db.load_daily_prices(INDEX_SYMBOL).reset_index().rename(columns={'date': 'time'})
    pe     = db.load_pe_ratios(INDEX_SYMBOL).reset_index().rename(columns={'date': 'time'})
    pe     = pe.dropna(subset=['pe_ratio'])[['time', 'pe_ratio']]
    df     = prices.merge(pe, on='time', how='left')
    df['pe_ratio'] = df['pe_ratio'].ffill()
    return df.reset_index(drop=True)


def run_sweep(df, cal_range_close):
    first_close  = df['close'].iloc[0] * 1000
    sell_s       = SellTopOfMA1000Strategy(percentSell=45)
    reinvest_s   = ReInvestUnderMA1000Strategy()

    combos = list(itertools.product(RANGE_DAYS_VALS, DECREASE_VALS))
    total  = len(combos)
    results = {}

    for i, (rd, dp) in enumerate(combos, 1):
        buy_s = BuyMAStrategy(localRangeDays=rd, decreasePercent=dp, use_pe=False)
        _, _, ratio, *_ = estimate(df, INTERVAL_MONEY, buy_s, sell_s, reinvest_s,
                                   cal_range_close, isPrint=False)
        results[(rd, dp)] = ratio
        if i % 14 == 0 or i == total:
            print(f"  {i}/{total}")

    return results


def save_excel(results):
    mat = pd.DataFrame(index=RANGE_DAYS_VALS, columns=DECREASE_VALS, dtype=float)
    for (rd, dp), v in results.items():
        mat.loc[rd, dp] = v

    best_key = max(results, key=results.get)
    best_val = results[best_key]
    print(f"Best: rangeDays={best_key[0]}, decreasePercent={best_key[1]} -> {best_val:.2f}%")

    wb = Workbook()
    ws = wb.active
    ws.title = "Sweep"

    bold  = Font(bold=True, size=10)
    ctr   = Alignment(horizontal="center", vertical="center")
    hfill = PatternFill("solid", fgColor="D9E1F2")
    bfill = PatternFill("solid", fgColor="FFD700")  # gold for best

    # Header row: decrease percent values
    ws.cell(1, 1, "rangeDays \\ decreasePercent%").font = bold
    ws.cell(1, 1).alignment = ctr
    ws.cell(1, 1).fill = hfill
    ws.column_dimensions["A"].width = 24
    for j, dp in enumerate(DECREASE_VALS, 2):
        c = ws.cell(1, j, dp)
        c.font = bold; c.alignment = ctr; c.fill = hfill
        ws.column_dimensions[get_column_letter(j)].width = 10

    # Data rows
    for i, rd in enumerate(RANGE_DAYS_VALS, 2):
        c = ws.cell(i, 1, rd)
        c.font = bold; c.alignment = ctr; c.fill = hfill
        for j, dp in enumerate(DECREASE_VALS, 2):
            val = mat.loc[rd, dp]
            cell = ws.cell(i, j, round(float(val), 2))
            cell.number_format = '0.00"%"'
            cell.alignment = ctr
            if (rd, dp) == best_key:
                cell.fill = bfill
                cell.font = Font(bold=True, size=10)

    # Color scale: red (low) → yellow → green (high)
    first_data = f"B2"
    last_data  = f"{get_column_letter(1 + len(DECREASE_VALS))}{1 + len(RANGE_DAYS_VALS)}"
    ws.conditional_formatting.add(
        f"{first_data}:{last_data}",
        ColorScaleRule(start_type="min", start_color="F8696B",
                       mid_type="percentile", mid_value=50, mid_color="FFEB84",
                       end_type="max", end_color="63BE7B"),
    )

    ws.freeze_panes = "B2"
    ws.row_dimensions[1].height = 28

    out = "exports/sweep_price_buymastrategy.xlsx"
    wb.save(out)
    print(f"Saved: {out}")
    return out


def run_one(range_days: int, decrease_percent: float, use_pe: bool = False):
    """Run a single estimate and print + chart the result."""
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker

    db.init_db()
    print("Loading data ...")
    df = load_df()

    print(f"Building cal_range_close (rangeDays={range_days}) ...")
    cal_range_close = build_cal_range_close(df, range_days=[range_days], max_workers=5)

    first_val    = df['pe_ratio'].dropna().iloc[0] if use_pe else df['close'].iloc[0] * 1000
    first_close  = df['close'].iloc[0] * 1000
    sell_s       = SellTopOfMA1000Strategy(percentSell=45)
    reinvest_s   = ReInvestUnderMA1000Strategy()
    buy_s        = BuyMAStrategy(localRangeDays=range_days,
                                 decreasePercent=decrease_percent,
                                 use_pe=use_pe)

    _, _, ratio, buyed, sold, reinvested, _ = estimate(
        df, INTERVAL_MONEY, buy_s, sell_s, reinvest_s, cal_range_close, isPrint=True
    )
    print(f"\nallRatioGrowth: {ratio:.2f}%")

    # Chart
    close_vals = df['close'] * 1000
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 10), sharex=True,
                                   gridspec_kw={"height_ratios": [3, 1]})

    ax1.plot(df.index, close_vals, color='black', linewidth=1, label='Price')
    if len(df) >= 1000:
        ax1.plot(df.index, close_vals.rolling(1000).mean(), color='royalblue',
                 linewidth=1.5, label='MA1000', alpha=0.7)

    if buyed:
        ax1.scatter([b.index for b in buyed],
                    close_vals.iloc[[b.index for b in buyed]],
                    color='green', s=40, zorder=4, label=f'Buy ({len(buyed)})')
    if sold:
        ax1.scatter([s.index for s in sold],
                    close_vals.iloc[[s.index for s in sold]],
                    color='red', s=40, zorder=4, label=f'Sell ({len(sold)})')
    if reinvested:
        ax1.scatter([r.index for r in reinvested],
                    close_vals.iloc[[r.index for r in reinvested]],
                    color='orange', s=30, zorder=4, label=f'Reinvest ({len(reinvested)})')

    signal = 'P/E' if use_pe else 'Price'
    ax1.set_title(f"VN30 | {signal} | rangeDays={range_days}, decrease={decrease_percent}% | Growth={ratio:.2f}%",
                  fontsize=12, fontweight='bold')
    ax1.set_ylabel('Price')
    ax1.legend(fontsize=8)
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))

    if 'pe_ratio' in df.columns:
        ax2.plot(df.index, df['pe_ratio'].ffill(), color='purple', linewidth=1, label='P/E')
        ax2.set_ylabel('P/E')
        ax2.legend(fontsize=8)

    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    # Usage:
    #   python -m single.ma1000.run_sweep                        -> full sweep (price)
    #   python -m single.ma1000.run_sweep 150 1                  -> single run, price
    #   python -m single.ma1000.run_sweep 150 1 pe               -> single run, P/E
    args = sys.argv[1:]

    if len(args) >= 2:
        rd  = int(args[0])
        dp  = float(args[1])
        pe  = len(args) >= 3 and args[2].lower() == 'pe'
        run_one(rd, dp, use_pe=pe)
    else:
        db.init_db()
        print("Loading data ...")
        df = load_df()
        print(f"  {len(df)} rows, {df['pe_ratio'].notna().sum()} with P/E")

        print("Building cal_range_close with P/E (in-memory, not cached) ...")
        cal_range_close = build_cal_range_close(df, range_days=RANGE_DAYS_VALS, max_workers=5)

        print(f"Running sweep ({len(RANGE_DAYS_VALS)} x {len(DECREASE_VALS)} = {len(RANGE_DAYS_VALS)*len(DECREASE_VALS)} combos) ...")
        results = run_sweep(df, cal_range_close)
        save_excel(results)
