"""
What is actually stopping the sell arm — the price test, or the gates behind it?

WHY THIS EXISTS

  Grouping the run by sell count shows the diff rising almost monotonically with
  it: 0 sells -> +0.3 median diff, 4 sells -> +64.9. Six symbols never sell at all
  and sit at +0.3, which is not a result, it is the arm never having been invoked.
  So "make the arm sell more" is worth testing.

  But there are two completely different ways to sell more, and they call for
  different work:

      the price test rarely fires   -> add a second trigger, OR'd
      the gates eat the firings     -> loosen a gate

  PERCENT_SELL_BOTTOM was the first of those and it lost. Before building another
  one, count which of the two is binding. This script does not backtest anything;
  it replays each bar and tallies where the sell decision dies.

WHAT IS COUNTED

  Per symbol, over exactly the bars run_all evaluates (same start index, computed
  the same way — a diagnostic that measured a different window would not describe
  the run we are trying to explain):

      fire     price is more than PERCENT_SELL above its own median
      -s1      of those, blocked by the slope gate  (signal1 >= SELL_MIN_SIGNAL1)
      -s3      of those left, blocked by the Sharpe gate (signal3 >= MIN_SIGNAL3)
      pass     survived every gate

  `pass` is an OPPORTUNITY count, not a sell count. The engine can only sell when
  the tracker holds shares, so a run of consecutive passing bars becomes one sell.
  The gap between pass and the run's actual sells is the position state, not a
  filter, and it is reported so the two are never confused.

AND WHAT A z_dev TRIGGER WOULD ADD

  z_dev has been measured once, as a gate that BLOCKS selling, and it failed on
  all 66 cells. As a TRIGGER that causes selling it has never been tried, and it
  is the one quantity we hold whose scale does not depend on the symbol: the
  dispersion study puts its p95 at 2.218 * w^0.009, essentially flat, where the
  price-vs-median distance the live trigger uses goes as 1.29 * w^0.698. That
  matters because the six never-selling symbols include three indices, and a
  basket does not travel 75% from its own median the way a single stock does.

  That last sentence was the reason this script was written and the script
  disproved it. VN30 clears +75% on 24 bars; every one of the 24 is killed by the
  slope gate. The threshold was never what stopped it.

  So for each candidate threshold the script also counts the bars that z_dev alone
  would have fired on, AFTER the same gates, EXCLUDING the ones the median test
  already catches. That last exclusion is the whole point: an OR is only worth
  adding for what it adds.

WHAT IT FOUND — 52 symbols, 117,163 bars, config of 2026-08-16

  Neither of the two candidates is the bottleneck. The price test fires on 18.71%
  of all bars (21,916), and 45% of those firings survive every gate — 9,931 bars
  on which the arm wants to sell and is allowed to.

  The run makes 122 sells. That is 81 permitted bars per sell.

  What limits selling is neither the trigger nor the gates: it is POSITION STATE.
  The engine can only sell shares it holds, so after a sell the arm is mute until
  the reinvest arm buys back in. The sell count is set by the RE-ENTRY rate. Any
  new OR'd trigger lands, 98.8% of the time, on a bar that already said sell and
  could not.

  So "make the sell arm fire more" is pushing on an open door — everywhere except
  the handful of symbols where the door was never open at all:

      pass = 0   VN30, SAB, VRE, PLX, VNDIAMOND, VNFINLEAD — the six that have
                 never sold, and their combined diff is +6.5. There a new trigger
                 does not compete with anything; it creates the first sell.
                 VNDIAMOND and VNFINLEAD are out of reach regardless: 682 bars,
                 and z_dev needs a 700-bar warmup, so it has no coverage there.

  The gate split is per-symbol and worth reading before blaming any one gate:

      FPT   926 fire, 544 (59%) die on the Sharpe gate, 132 pass — the
            "do not sell a compounder" job is already being done, hard, and FPT
            still loses 85 points. Restraint there is exhausted.
      VN30  24 fire, 24 die on the slope gate, 0 pass.
      CTD   697 fire, 687 blocked, 10 pass.
      PNJ   918 fire, 865 blocked, 53 pass — a heavily gated LOSER, which is a
            different disease from FPT's.

Usage:
    python single/median1000/diag_sell_gates.py            # all symbols
    python single/median1000/diag_sell_gates.py FPT VN30   # a subset
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import json
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

import pandas as pd
import database as db
from single.runner import load_symbol_df
from single.median1000 import config

# Thresholds tried for the hypothetical z_dev trigger. Sell when z_dev is at least
# this many of the symbol's own sigmas above its own base.
ZDEV_TRIGGERS = [1.0, 1.5, 2.0, 2.5, 3.0]

OUT_JSON = Path(__file__).parent / "diag_sell_gates.json"


def analyse(symbol: str):
    t0 = time.time()
    try:
        if symbol.upper() in {s.upper() for s in getattr(config, "EXCLUDE_SYMBOLS", [])}:
            return symbol, None, "excluded"

        df = load_symbol_df(symbol)
        if len(df) < 1010:
            return symbol, None, f"only {len(df)} rows"

        buy_w  = getattr(config, "BUY_MEDIAN_WINDOW", 1000)
        sell_w = getattr(config, "SELL_MEDIAN_WINDOW", 1000)
        cal = db.load_range_stats(symbol, df, range_days={1000, buy_w, sell_w})
        if cal is None:
            return symbol, None, "no range_stats"

        date_to_idx = {pd.Timestamp(r["time"]): i for i, r in df.iterrows()}

        def _map(loader, col):
            out = {}
            d = loader()
            if not d.empty:
                for date, v in d[col].items():
                    i = date_to_idx.get(pd.Timestamp(date))
                    if i is not None and v is not None:
                        out[i] = float(v)
            return out

        s1 = ({} if config.SELL_MIN_SIGNAL1 is None else
              _map(lambda: db.load_trend_signals(symbol, window_days=config.SELL_SIGNAL1_WINDOW),
                   "signal1_slope"))
        s3 = ({} if config.MIN_SIGNAL3 is None else
              _map(lambda: db.load_trend_signals(symbol, window_days=1000),
                   "signal3_sharpe"))

        # Same start index run_all computes. z_dev is NOT allowed to move it: it is
        # switched off in the shipped config, so including its warmup here would
        # shorten the window and stop this describing the run being explained.
        first = {"median1000": max(1000, buy_w, sell_w),
                 "signal1": min(s1) if s1 else None,
                 "signal3": min(s3) if s3 else None}
        avail = {k: v for k, v in first.items() if v is not None}
        start = max(avail.values())
        bars  = len(df) - start
        if config.MIN_EVAL_BARS and bars < config.MIN_EVAL_BARS:
            return symbol, None, f"only {bars} bars after warmup"

        # Loaded for the counterfactual only, never to gate anything here.
        zd = _map(lambda: db.load_zdev(symbol, 1000, config.SELL_ZDEV_WINDOW), "z_dev")

        # x1000, because that is what the engine hands the strategies —
        # single/engine.py does `close = row['close'] * 1000` while range_stats is
        # stored in the same scaled unit. Reading df['close'] raw compares 58,380
        # against a median of 20,140,000 and the price test never fires once.
        closes  = df["close"].to_numpy(dtype=float) * 1000
        pct     = config.PERCENT_SELL
        s1_min  = config.SELL_MIN_SIGNAL1
        s3_min  = config.MIN_SIGNAL3

        n_fire = n_b1 = n_b3 = n_pass = 0
        n_zcov = 0
        z_add  = {t: 0 for t in ZDEV_TRIGGERS}   # extra passing bars the median missed
        z_fire = {t: 0 for t in ZDEV_TRIGGERS}   # bars z_dev alone fires on, before gates

        for i in range(start, len(df)):
            ic = cal.get(i)
            if ic is None or sell_w not in ic.rangeDayCloses:
                continue
            med = ic.rangeDayCloses[sell_w].pct50(config.USE_PE)
            if not med:
                continue
            cur = closes[i]

            fired = (cur - med) / med * 100 > pct
            # Missing signal defaults to 0.0, exactly as the strategy reads it —
            # below both thresholds, so an absent signal never blocks.
            blocked1 = bool(s1) and s1.get(i, 0.0) >= s1_min
            blocked3 = bool(s3) and s3.get(i, 0.0) >= s3_min

            if fired:
                n_fire += 1
                if blocked1:
                    n_b1 += 1
                elif blocked3:
                    n_b3 += 1
                else:
                    n_pass += 1

            z = zd.get(i)
            if z is None:
                continue
            n_zcov += 1
            for t in ZDEV_TRIGGERS:
                if z > t:
                    z_fire[t] += 1
                    # Only what the median test does NOT already catch, and only
                    # after the same gates. Anything else would flatter the trigger
                    # with sells the arm already makes.
                    if not fired and not blocked1 and not blocked3:
                        z_add[t] += 1

        return symbol, {
            "bars": bars, "start": start,
            "fire": n_fire, "blk_s1": n_b1, "blk_s3": n_b3, "pass": n_pass,
            "zdev_bars": n_zcov,
            "z_fire": {str(t): z_fire[t] for t in ZDEV_TRIGGERS},
            "z_add":  {str(t): z_add[t]  for t in ZDEV_TRIGGERS},
            "secs": round(time.time() - t0, 1),
        }, None

    except Exception as e:
        return symbol, None, f"{type(e).__name__}: {e}"


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    symbols = [s.upper() for s in args] if args else db.list_symbols()

    rows, skipped = {}, []
    t0 = time.time()
    with ProcessPoolExecutor() as ex:
        futs = {ex.submit(analyse, s): s for s in symbols}
        for k, fut in enumerate(as_completed(futs), 1):
            sym, row, err = fut.result()
            if row:
                rows[sym] = row
            else:
                skipped.append((sym, err))
            print(f"  [{k}/{len(symbols)}] {sym}"
                  f"{'' if row else '  SKIP: ' + str(err)}", flush=True)

    OUT_JSON.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print(f"\nraw -> {OUT_JSON}   ({time.time()-t0:.0f}s, {len(rows)} symbols, "
          f"{len(skipped)} skipped)\n")

    zt = ZDEV_TRIGGERS
    head = (f"{'sym':10}{'bars':>7}{'fire':>7}{'-s1':>7}{'-s3':>7}{'pass':>7}"
            + "".join(f"{'+z' + str(t):>7}" for t in zt))
    print(head)
    print("-" * len(head))
    tot = {k: 0 for k in ("bars", "fire", "blk_s1", "blk_s3", "pass")}
    ztot = {t: 0 for t in zt}
    for sym in sorted(rows, key=lambda s: -rows[s]["pass"]):
        r = rows[sym]
        for k in tot:
            tot[k] += r[k]
        for t in zt:
            ztot[t] += r["z_add"][str(t)]
        print(f"{sym:10}{r['bars']:7}{r['fire']:7}{r['blk_s1']:7}{r['blk_s3']:7}"
              f"{r['pass']:7}" + "".join(f"{r['z_add'][str(t)]:7}" for t in zt))
    print("-" * len(head))
    print(f"{'TOTAL':10}{tot['bars']:7}{tot['fire']:7}{tot['blk_s1']:7}"
          f"{tot['blk_s3']:7}{tot['pass']:7}"
          + "".join(f"{ztot[t]:7}" for t in zt))

    if tot["fire"]:
        print(f"\nOf {tot['fire']} bars where the price test fires: "
              f"{tot['blk_s1']} ({100*tot['blk_s1']/tot['fire']:.0f}%) die on the "
              f"slope gate, {tot['blk_s3']} ({100*tot['blk_s3']/tot['fire']:.0f}%) "
              f"on the Sharpe gate, {tot['pass']} "
              f"({100*tot['pass']/tot['fire']:.0f}%) survive.")
    print(f"The price test fires on {tot['fire']} of {tot['bars']} evaluated bars "
          f"({100*tot['fire']/tot['bars']:.2f}%).")

    if skipped:
        print("\nskipped: " + ", ".join(f"{s} ({e})" for s, e in skipped))


if __name__ == "__main__":
    db.init_db()
    main()
