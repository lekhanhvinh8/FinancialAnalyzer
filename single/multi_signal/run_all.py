"""
Sweep all symbols in the DB with the Median1000 strategy.

Outputs (in single/multi_signal/charts/):
  - <symbol>_backtest.html       per-symbol backtest chart
  - run_all_progress.html        live progress (auto-refreshes every 3s)
  - report_all.html              final comparison table

Symbols are processed in parallel, one process each — the work is CPU-bound
inside run_estimate and every symbol is independent.

THE REPORT SPLITS LONG FROM SHORT HISTORY

  Every figure in the summary is shown three times: All, Long and Short, split
  at config.LONG_HISTORY_BARS. The single blended column that used to be there
  was averaging two things that do not belong in one average — a symbol with
  2816 evaluated bars spans several market regimes, one with 682 spans one, and
  the short ones nearly all span the SAME one, so they are close to a single
  reading rather than sixteen.

  On the 52-symbol run the two groups say different things:

      group   n    median diff   sign test    net diff, and excluding its best
      long    36      +37.27%    28/36  p=0.0006    +2707  ->  +2162 excl. VND
      short   16       +1.06%    12/16  p=0.0384      +16  ->    -23 excl. VPB

  The blended +20.14% describes neither. The short group is the more useful half
  of the split: its direction is real (12 of 16 improve, p=0.038) but its size is
  not — a median of +1.06%, and its entire net comes from one symbol.

  The split also separates two different shapes of outcome, which no aggregate
  over both could show. Avg win against avg loss is 3.20x in the long group
  (+106% against -33%) and 0.38x in the short one (+12% against -30%). So on
  short history the strategy wins more often than it loses and still barely
  breaks even, because the few losses are far larger than the many wins. That is
  a warning about a newly listed symbol, not about the strategy.

  The Long and Short columns are DIFFERENT SYMBOLS, so nothing subtracts one from
  the other; there is no pairing available between two disjoint sets.

WHERE THE PRICE SITS IN ITS OWN RANGE

  Four columns show the latest close against its 1000-bar top, bottom, median and
  mean, as percentages. Fixed at 1000 rather than following BUY/SELL_MEDIAN_WINDOW
  on purpose: they describe the symbol for a reader, they are not an input to any
  decision, and they should not move when a strategy parameter does.

  All four render neutral. Colouring them by sign was the first attempt and it was
  wrong twice over: it contradicts the Diff column two cells to the left, where
  green is positive, and it implies a verdict these columns do not carry — a price
  above its median is not bad news, it is the condition the sell arm exists to act
  on. vs Top is <= 0 and vs Bottom >= 0 by construction anyway, so their sign
  never carried information to colour.

  One highlight survives because it is tied to a real threshold rather than to a
  sign: vs Median is the exact quantity PERCENT_SELL is compared against, so a row
  at or past it turns amber. That is the sell arm's own condition, and it should
  agree with Signal now.

SORTING AND FILTERING

  Every column header sorts, Diff descending by default. Filter chips sit above
  the table and combine as OR WITHIN A ROW, AND ACROSS ROWS — "Beat" plus "Lost"
  means decided either way rather than a contradiction, and "Long" plus "Short"
  is the whole universe. Only a genuine cross-row conflict empties the table, and
  it says so when it does.

  A filtered-out symbol leaves the table AND the summary, so the three columns
  always describe what is on screen. Two summary rows are there specifically to be
  read after filtering: Signal today counts the symbols flagged Buy / Sell /
  Reinvest / None out of the filtered set, and Total actions sums the buys, sells
  and reinvests over the whole evaluated history of that set. The first three
  Signal counts overlap — one bar can carry two flags — so they need not sum to
  the total, and the row says so when they do not. The per-row checkbox is the individual
  override: it drops one symbol from the summary while leaving it visible.

  Every chip carries how many symbols it matches ON ITS OWN, out of the run total
  shown in the panel header. Fixed, not conditional on the other chips: a
  conditional count reads 0 almost everywhere once two groups are active, and the
  sizes worth knowing before you click — 30 in VN30, 6 never sold — would be the
  first thing lost. What is on screen right now is the live count on the right.
  The numbers within a row need not sum to the total and need not be disjoint: a
  symbol signalling Buy and Reinvest on the same bar is counted under both.

  The chips that earn their place are the ones that isolate a finding the sorted
  table cannot:

    No real effect <1%   the strategy ran and changed nothing — 5 symbols, all
                         short, which is most of what the short group's +1.06%
                         median is made of
    Never sold           6 symbols, and one of them (VN30) has full history, so
                         this is not purely a short-history artifact
    Median1000 in the red   absolute, not relative, and the two genuinely differ:
                         NVL beats the interval arm by 8.67 points while being
                         down 16.23% in its own right
    Signal today         3 symbols say Sell right now; this is the row to act on
    Index                one chip per seeded index, from index_members, plus
                         Outside for a symbol in none of them. CURRENT composition
                         only — the point is "of the baskets buyable today, where
                         does the strategy work", so a symbol admitted to VN30 last
                         year carries its whole history into the VN30 chip. That is
                         survivorship by construction and it is the intended
                         reading; a point-in-time membership backtest is a
                         different question and this filter does not answer it.
                         Outside is not the same as clearing the group: with every
                         index chip on, Outside is still hidden.

Usage:
    python single/multi_signal/run_all.py                 # all symbols, all cores
    python single/multi_signal/run_all.py FPT STB         # a subset
    python single/multi_signal/run_all.py --workers=4     # cap the pool
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
import pandas as pd
import database as db
from single.runner import load_symbol_df, run_estimate
from export.chart import save_backtest_chart
from core.progress import RunAllProgress
from single.multi_signal import config
from single.multi_signal.factory import (make_median_strategies,
                                        make_interval_strategies, build_pelog_map)

CHARTS_DIR = Path(__file__).parent / "charts"


def process_symbol(symbol: str, run_dir: Path | None = None, profile: str | None = None,
                   signal: str | None = None, universe: str | None = None
                   ) -> tuple[str, dict | None, str | None, float]:
    """
    Returns (symbol, row, skip_reason, duration_s). Exactly one of row and
    skip_reason is non-None.

    Runs in a worker process, so it takes no progress object: RunAllProgress
    writes an HTML file and each worker would own a private copy of it. The
    parent owns progress and updates it from what this returns. Everything in
    and out must be picklable, which is why run_dir is a Path and not an
    open handle.
    """
    # Applied HERE, not only in the parent: each worker is a fresh process that
    # re-imports config, so an overlay done in the parent never reaches it. The
    # breadth profile ran and produced the price profile's numbers until this
    # line existed.
    from single.multi_signal.profiles import apply as _apply
    # None means NO OVERLAY: config.py exactly as written. It used to default to
    # "price", and once "price" started pinning SELL_MIN_BREADTH back to None,
    # a no-argument run silently undid the very setting config.py had just
    # switched on -- 52 symbols, zero difference, no warning.
    if profile:
        _apply(config, profile)
    # Which breadth line to read, as an ARGUMENT rather than a config edit.
    # Comparing the three lines meant editing config.py between runs, which makes
    # them impossible to run at the same time -- the workers re-import the module
    # and would pick up whichever edit landed last.
    if signal:
        config.BREADTH_SIGNAL = signal
    # Which stored basket to read. Same reason as `signal`: a worker re-imports
    # config, so a value set only in the parent never arrives here.
    if universe:
        config.BREADTH_UNIVERSE = universe

    t0 = time.time()
    try:
        if symbol.upper() in {s.upper() for s in getattr(config, "EXCLUDE_SYMBOLS", [])}:
            return symbol, None, "excluded by EXCLUDE_SYMBOLS", time.time() - t0

        df = load_symbol_df(symbol)
        if len(df) < 1010:
            return symbol, None, f"only {len(df)} rows", time.time() - t0

        # Only the windows actually read: the sell and reinvest arms are fixed at
        # 1000, the buy arm uses BUY_MEDIAN_WINDOW. Loading all ~1500 was the
        # slowest step in the run. The chart only forwards this to strategy.check(),
        # so it needs nothing more.
        buy_w  = getattr(config, "BUY_MEDIAN_WINDOW", 1000)
        sell_w = getattr(config, "SELL_MEDIAN_WINDOW", 1000)
        # The P/E median comes out of range_stats too, so its window has to be
        # requested here or build_pelog_map finds nothing to read.
        pe_w   = getattr(config, "PE_MEDIAN_WINDOW", 500)
        windows = {1000, buy_w, sell_w}
        if config.SELL_MIN_PELOG is not None:
            windows.add(pe_w)
        cal_range_close = db.load_range_stats(symbol, df, range_days=windows)
        if cal_range_close is None:
            return symbol, None, "no range_stats in DB", time.time() - t0

        date_to_idx = {pd.Timestamp(row["time"]): i for i, row in df.iterrows()}

        # A gate set to None is not loaded at all. This is not just saved work:
        # an unused signal must not appear in first_idx below, or its warmup would
        # keep pushing the start index forward and keep costing symbols for a
        # filter that is switched off.
        def _slope_map(window: int) -> dict:
            d = db.load_trend_signals(symbol, window_days=window)
            out: dict = {}
            if not d.empty:
                for date, v in d["signal1_slope"].items():
                    idx = date_to_idx.get(pd.Timestamp(date))
                    if idx is not None:
                        out[idx] = float(v)
            return out

        # signal3 map: {row_index → signal3_sharpe} for window=1000
        signal3_map: dict = {}
        if config.MIN_SIGNAL3 is not None:
            sig3_df = db.load_trend_signals(symbol, window_days=1000)
            if not sig3_df.empty:
                for date, s3 in sig3_df["signal3_sharpe"].items():
                    idx = date_to_idx.get(pd.Timestamp(date))
                    if idx is not None:
                        signal3_map[idx] = float(s3)

        # signal1 map for the sell gate
        signal1_map: dict = {}
        if config.SELL_MIN_SIGNAL1 is not None:
            signal1_map = _slope_map(config.SELL_SIGNAL1_WINDOW)

        # Reinvest slope map — reuse signal1_map when the window matches, else load it
        reinvest_signal1_map: dict = {}
        if config.REINVEST_MIN_SIGNAL1 is not None:
            reinvest_signal1_map = (
                signal1_map
                if (signal1_map
                    and config.REINVEST_SIGNAL1_WINDOW == config.SELL_SIGNAL1_WINDOW)
                else _slope_map(config.REINVEST_SIGNAL1_WINDOW))

        # z_dev map for the sell filter — {row_index: z_dev} at the configured stat window
        zdev_map: dict = {}
        if config.SELL_MIN_ZDEV is not None:
            zd = db.load_zdev(symbol, 1000, config.SELL_ZDEV_WINDOW)
            for date, z in zd["z_dev"].items() if not zd.empty else []:
                idx = date_to_idx.get(pd.Timestamp(date))
                if idx is not None and z is not None:
                    zdev_map[idx] = float(z)

        # ln(P/E / its own median) for the sell gate. build_pelog_map owns the
        # warmup rule — see factory.py; it is not "skip the first pe_w rows".
        pelog_map: dict = {}
        if config.SELL_MIN_PELOG is not None:
            pelog_map = build_pelog_map(symbol, df, cal_range_close, pe_w)
            if not pelog_map:
                return (symbol, None,
                        f"no usable P/E at window={pe_w}", time.time() - t0)

        # Start once EVERY input the strategies read is available — the latest
        # first-appearance wins. Before that point the early period would be running
        # a different strategy than the later one, because whichever inputs are still
        # missing simply do not filter. Adding a signal means adding a line here;
        # nothing else needs to know the arithmetic.
        #
        # Applied to BOTH arms. Moving only the treatment's start would hand the
        # interval arm extra years of compounding and invalidate the comparison.
        first_idx = {
            # The reinvest arm still guards on index > 1000; buy and sell each
            # guard on their own window, so the longest of the three sets the floor.
            "median1000":       max(1000, buy_w, sell_w),
            "signal1":          min(signal1_map)          if signal1_map          else None,
            "signal3":          min(signal3_map)          if signal3_map          else None,
            "reinvest_signal1": min(reinvest_signal1_map) if reinvest_signal1_map else None,
            "zdev":             min(zdev_map)             if zdev_map             else None,
            "pelog":            min(pelog_map)            if pelog_map            else None,
        }
        if config.SELL_MIN_ZDEV is not None and not zdev_map:
            return (symbol, None,
                    f"no z_dev at stat_window={config.SELL_ZDEV_WINDOW}",
                    time.time() - t0)
        available = {k: v for k, v in first_idx.items() if v is not None}
        start_idx = max(available.values())
        binding   = max(available, key=available.get)

        eval_bars = len(df) - start_idx
        if config.MIN_EVAL_BARS and eval_bars < config.MIN_EVAL_BARS:
            msg = f"only {eval_bars} bars after warmup (start {start_idx}, bound by {binding})"
            return symbol, None, msg, time.time() - t0

        # The basket, joined to this symbol's rows. Empty unless the profile
        # switched a breadth gate on, and an empty map with a None threshold is
        # the arm exactly as it was.
        breadth_map = {}
        if any(getattr(config, k, None) is not None for k in
               ("BUY_MAX_BREADTH", "SELL_MIN_BREADTH", "REINVEST_MAX_BREADTH")):
            from single.multi_signal.breadth_map import build_breadth_map
            breadth_map = build_breadth_map(df)

        buy1, sell1, ri1 = make_median_strategies(signal3_map, signal1_map,
                                                  reinvest_signal1_map, zdev_map,
                                                  pelog_map, breadth_map)
        r1 = run_estimate(symbol, df, config.INTERVAL_MONEY, buy1, sell1, ri1,
                          cal_range_close, start_index=start_idx)

        buy2, sell2, ri2 = make_interval_strategies()
        r2 = run_estimate(symbol, df, config.INTERVAL_MONEY, buy2, sell2, ri2,
                          cal_range_close, start_index=start_idx)

        out_dir = run_dir if run_dir is not None else CHARTS_DIR
        chart_path = out_dir / f"{symbol.lower()}_backtest.html"
        save_backtest_chart(
            df,
            r1["buyedInfos"], r1["sellInfos"], r1["reinvestInfos"],
            path=str(chart_path),
            index=symbol.lower(),
            buy_strategy=buy1, sell_strategy=sell1, reinvest_strategy=ri1,
            cal_range_close=cal_range_close,
            result=r1,
            compare_result=r2,
            start_index=start_idx,
            sig1_window=config.SELL_SIGNAL1_WINDOW,
            sig3_window=1000,   # run_all reads signal3 at window 1000
            zdev_window=config.SELL_ZDEV_WINDOW,
        )

        # THE LINE THE DECISIONS WERE MADE ON. Without it a breadth run shows
        # sells with nothing on the chart that explains them -- the reason lives
        # in the basket, not in this symbol's price.
        #
        # Lost when median1000 and market_breadth were merged: the old package
        # drew it here and the merged runner did not, so every chart since has
        # been missing the one series that explains a breadth decision. Nothing
        # failed, because a missing overlay looks exactly like a chart.
        if breadth_map:
            from breadth.chart import add_signal_line
            x = [str(t)[:10] for t in df["time"]]
            add_signal_line(
                chart_path, x,
                {config.BREADTH_SIGNAL: [breadth_map.get(i) for i in range(len(x))]},
                [(v, lbl) for v, lbl in
                 ((config.BUY_MAX_BREADTH, "mua"),
                  (config.SELL_MIN_BREADTH, "ban"),
                  (config.REINVEST_MAX_BREADTH, "reinvest"))
                 if v is not None],
                axis_title=config.BREADTH_SIGNAL)

        # Current state of the three conditions at the latest bar — the same
        # check() calls the backtest chart uses to paint its condition zones.
        # Note reinvest.check() covers only the price path; the timeout fallback
        # lives in considerReinvest and is not reflected here.
        last = len(df) - 1
        close_last = float(df["close"].iloc[last]) * 1000
        pe_last = df["pe_ratio"].iloc[last] if "pe_ratio" in df.columns else None
        if pe_last is not None and pe_last != pe_last:   # NaN
            pe_last = None
        def _chk(strategy):
            try:
                return bool(strategy.check(last, close_last, pe_last, cal_range_close))
            except Exception:
                return False
        now_flags = (_chk(buy1), _chk(sell1), _chk(ri1))

        # Where the latest price sits inside its own 1000-bar range, as a percent
        # of each reference. Hard-wired to 1000 rather than following
        # BUY/SELL_MEDIAN_WINDOW: this is a description of the symbol for the
        # reader, not an input to any decision, so it should not move when a
        # strategy parameter does.
        #
        # vs_top is <= 0 and vs_bottom >= 0 by construction, so only their size
        # carries information. vs_median and vs_mean carry a sign, and vs_median
        # is exactly the quantity PERCENT_SELL and PERCENT_BUY are compared
        # against — a row at +75 or above is one the sell arm is looking at.
        rng = {}
        rc = (cal_range_close[last].rangeDayCloses.get(1000)
              if last in cal_range_close else None)
        if rc is not None:
            for name, ref in (("top", rc.top(config.USE_PE)),
                              ("bottom", rc.bottom(config.USE_PE)),
                              ("median", rc.pct50(config.USE_PE)),
                              ("mean", rc.avg(config.USE_PE))):
                rng[f"vs_{name}_%"] = (round((close_last - ref) / ref * 100, 2)
                                       if ref else None)

        mg = float(round(r1["allRatioGrowth"], 2))
        ig = float(round(r2["allRatioGrowth"], 2))
        return symbol, {
            "symbol":            symbol,
            "median_growth_%":   mg,
            "median_buys":       r1["totalBuys"],
            "median_sells":      r1["totalSells"],
            "median_reinvests":  r1["totalReinvest"],
            "interval_growth_%": ig,
            "chart":             chart_path.name,
            "now_flags":         now_flags,
            "eval_bars":         eval_bars,
            **rng,
        }, None, time.time() - t0

    except Exception:
        err = traceback.format_exc().strip().splitlines()[-1]
        return symbol, None, err, time.time() - t0


def build_report(rows: list[dict], out_path: Path,
                 skipped: list[tuple[str, str]] | None = None,
                 config_module=None, title: str = "Median1000"):
    """
    `config_module` is whose settings the "Configuration used for this run" panel
    reports; it defaults to this package's. Passed in rather than imported so a
    second strategy can reuse this report and have it describe ITS parameters --
    a saved report that names the wrong config is worse than one with no panel.
    """
    config = config_module or globals()["config"]
    df = pd.DataFrame(rows)
    df["diff_%"] = df["median_growth_%"] - df["interval_growth_%"]
    df = df.sort_values("diff_%", ascending=False)

    # Same (buy, sell, reinvest) -> colour/label map the backtest chart uses for
    # its condition zones, so a row here and the chart agree on wording.
    NOW_COMBO = {
        (False, False, False): ("#64748b", "—"),
        (True,  False, False): ("#22c55e", "Buy"),
        (False, True,  False): ("#ef4444", "Sell"),
        (False, False, True):  ("#f97316", "Reinvest"),
        (True,  False, True):  ("#14b8a6", "Buy + Reinvest"),
        (True,  True,  False): ("#eab308", "Buy + Sell"),
        (False, True,  True):  ("#ec4899", "Sell + Reinvest"),
        (True,  True,  True):  ("#94a3b8", "All"),
    }

    WIN_GREEN  = "background:#14532d;color:#bbf7d0"
    LOSE_RED   = "background:#7f1d1d;color:#fca5a5"
    DRAW_GRAY  = "background:#1e293b;color:#94a3b8"

    def winner_styles(m, i):
        if m > i:   return WIN_GREEN, LOSE_RED
        if i > m:   return LOSE_RED,  WIN_GREEN
        return DRAW_GRAY, DRAW_GRAY

    # Every uppercase name in config.py, read at render time. Introspected rather
    # than listed so a parameter added later cannot silently go unreported — the
    # whole point is that a saved report says what produced it.
    cfg = {k: getattr(config, k) for k in dir(config)
           if k.isupper() and not k.startswith("_") and k != "PROFILE"}

    # WHICH PROFILE, AND WHICH VALUES IT REPLACED. The panel used to show final
    # values only, so a reader could not tell a number that came from config.py
    # from one a profile wrote over it -- and BREADTH_SIGNAL reads "prem_median"
    # on a price run that never touches the basket, which looks like the basket
    # is involved.
    # No PROFILE attribute means no overlay was applied, which is its own case --
    # not the "price" profile. Defaulting to "price" here printed that name on a
    # run that had applied nothing, which is exactly the confusion this panel was
    # added to remove.
    profile = getattr(config, "PROFILE", None)
    overridden = set()
    if profile:
        try:
            from single.multi_signal.profiles import PROFILES
            overridden = set(PROFILES.get(profile, {}))
        except Exception:
            overridden = set()
    profile_label = profile or "(mac dinh)"
    profile_note = (
        "config.py nguyen van, khong ghi de gi" if not overridden else
        f"ghi de {len(overridden)} gia tri, danh dau ben duoi")

    cfg_cells = "".join(
        f"<div><span style='color:{'#f59e0b' if k in overridden else '#64748b'}'>{k}"
        f"{' *' if k in overridden else ''}</span> "
        f"<span style='color:{'#fbbf24' if k in overridden else '#e2e8f0'};"
        f"font-weight:600'>{v}</span></div>"
        for k, v in sorted(cfg.items())
    )
    config_html = (
        "<div style='margin:10px 0;padding:10px 14px;background:#0f172a;"
        "border:1px solid #1e293b;border-radius:8px;font-size:12px'>"
        "<div style='color:#94a3b8;font-weight:700;margin-bottom:6px'>"
        "Configuration used for this run &nbsp;"
        f"<span style='color:#f59e0b'>profile = {profile_label}</span> "
        f"<span style='color:#64748b;font-weight:400'>({profile_note})</span></div>"
        "<div style='display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));"
        f"gap:2px 18px'>{cfg_cells}</div></div>"
    )

    skipped = skipped or []
    skipped_note = f", {len(skipped)} skipped" if skipped else ""
    skipped_html = ""
    if skipped:
        items = "".join(
            f"<div><span style='color:#e2e8f0;font-weight:600'>{sym}</span> "
            f"<span style='color:#64748b'>— {why}</span></div>"
            for sym, why in sorted(skipped)
        )
        skipped_html = (
            "<div style='margin:10px 0;padding:10px 14px;background:#0f172a;"
            "border:1px solid #1e293b;border-radius:8px;font-size:12px'>"
            f"<div style='color:#94a3b8;font-weight:700;margin-bottom:6px'>"
            f"Skipped ({len(skipped)}) — excluded from every figure below</div>"
            "<div style='display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));"
            f"gap:2px 18px'>{items}</div></div>"
        )

    # The long/short split. Everything below reports the two groups side by side
    # instead of averaging over both, because they are not comparable evidence:
    # a symbol evaluated on 682 bars saw one market period and one listed in 2014
    # saw four. See config.LONG_HISTORY_BARS.
    LONG_BARS = getattr(config, "LONG_HISTORY_BARS", 2000)
    ebs_all = sorted(int(r.get("eval_bars") or 0) for r in rows)
    max_eb  = ebs_all[-1] if ebs_all else 0
    n_long  = sum(1 for e in ebs_all if e >= LONG_BARS)
    n_short = len(ebs_all) - n_long

    # Is the threshold sitting in a gap, or cutting through a cluster? A split is
    # only meaningful if the universe is actually bimodal there, and that stops
    # being true the moment the universe changes. So the report checks its own
    # boundary rather than asserting one measured months ago.
    below = max((e for e in ebs_all if e <  LONG_BARS), default=None)
    above = min((e for e in ebs_all if e >= LONG_BARS), default=None)
    if below is None or above is None:
        split_note = ("<span style='color:#fbbf24'>every symbol falls on one side "
                      "— the split says nothing about this run</span>")
    else:
        gap = above - below
        # Compare against the widest gap inside either group: the boundary is only
        # a real seam if it is wider than the ones it is choosing not to cut on.
        inner = max((b - a for a, b in zip(ebs_all, ebs_all[1:])
                     if not (a < LONG_BARS <= b)), default=0)
        if gap > inner:
            split_note = (f"<span style='color:#94a3b8'>splits a gap of {gap:,} bars "
                          f"({below:,} &rarr; {above:,}), wider than any gap inside "
                          f"either group ({inner:,})</span>")
        else:
            split_note = (f"<span style='color:#fbbf24'>cuts a gap of only {gap:,} bars "
                          f"({below:,} &rarr; {above:,}) while a gap of {inner:,} sits "
                          f"inside a group — the universe is no longer bimodal here, "
                          f"so re-read config.LONG_HISTORY_BARS</span>")

    split_html = (
        "<div style='margin:10px 0;padding:10px 14px;background:#0f172a;"
        "border:1px solid #1e293b;border-radius:8px;font-size:12px'>"
        "<span style='color:#94a3b8;font-weight:700'>History split</span> "
        f"<span style='color:#64748b'>at {LONG_BARS:,} evaluated bars &mdash;</span> "
        f"<span style='color:#e2e8f0;font-weight:600'>{n_long} long</span> "
        f"<span style='color:#64748b'>/</span> "
        f"<span style='color:#fbbf24;font-weight:600'>{n_short} short</span>. "
        f"{split_note}</div>"
    )

    # Where the latest price sits in its 1000-bar range. All four stay neutral:
    # they describe a symbol, they do not score it, and colouring them by sign
    # would both contradict the Diff column two cells to the left (green there is
    # positive) and imply a judgement they do not carry — a price above its median
    # is not bad news, it is the condition the sell arm is built to act on.
    #
    # The one highlight that means something is exactly that: vs Median is the
    # quantity PERCENT_SELL is compared against, so amber marks the rows the sell
    # arm is looking at right now. Read it beside Signal now.
    RNG_COLS = ["vs_top_%", "vs_bottom_%", "vs_median_%", "vs_mean_%"]

    def _num(v):
        """NaN -> None for the JS payload.

        rows goes through pd.DataFrame, which fills a key some symbols lack with
        NaN rather than None, and json.dumps writes that as the bare literal NaN.
        That parses fine as JavaScript and then poisons the sort comparator, which
        only guards null and undefined — NaN compares false against everything and
        the ordering comes out inconsistent. Rendering was never affected; the
        cell test is `v != v`, which does catch NaN.
        """
        return None if v is None or v != v else float(v)
    sell_at = getattr(config, "PERCENT_SELL", None)

    def rng_cells(row) -> str:
        out = ""
        for key in RNG_COLS:
            v = row.get(key)
            if v is None or v != v:
                out += "<td style='text-align:right;color:#334155'>&mdash;</td>"
                continue
            hot = (key == "vs_median_%" and sell_at is not None and v >= sell_at)
            c = "#fbbf24" if hot else "#94a3b8"
            out += (f"<td style='text-align:right;color:{c}"
                    f"{';font-weight:600' if hot else ''}'>"
                    f"{'+' if v > 0 else ''}{v:.1f}%</td>")
        return out

    # Index membership, CURRENT composition only: a row whose date_removed is null.
    #
    # The historical table would let a symbol be filtered into VN30 for a stretch it
    # is no longer in, which is the honest thing for a point-in-time backtest but
    # not what this filter is for. The question here is "of the baskets I can buy
    # TODAY, how does the strategy do", so the membership is read as of now and the
    # whole score is attributed to it, warts and all. A symbol added to VN30 last
    # year still carries its full 2014-onwards result into the VN30 chip.
    #
    # Discovered rather than hardcoded, so seeding a fourth index gives it a chip
    # without touching this file.
    index_of: dict[str, list[str]] = {}
    index_names: list[str] = []
    for ix in db.list_index_names():
        mem = db.load_index_members(ix)
        if mem.empty:
            continue
        cur = mem[mem["date_removed"].isna()]["symbol"].astype(str).str.upper()
        if cur.empty:
            continue
        index_names.append(ix)
        for s in cur:
            index_of.setdefault(s, []).append(ix)

    rows_html = ""
    data_json  = []
    for _, row in df.iterrows():
        m, i = row["median_growth_%"], row["interval_growth_%"]
        ms, is_ = winner_styles(m, i)
        diff = m - i
        diff_color = "#4ade80" if diff >= 0 else "#f87171"
        diff_sign  = "+" if diff >= 0 else ""
        sym = row["symbol"]
        # Amber a short-history row, on the same threshold the summary splits on
        # so the table and the summary cannot disagree about which group a symbol
        # is in.
        eb = int(row.get("eval_bars") or 0)
        eb_color = "#fbbf24" if eb < LONG_BARS else "#64748b"
        now_color, now_label = NOW_COMBO.get(
            tuple(row.get("now_flags") or (False, False, False)), ("#64748b", "?"))
        rows_html += (
            f'<tr data-sym="{sym}">'
            f'<td><label style="display:flex;align-items:center;gap:6px;cursor:pointer">'
            f'<input type="checkbox" class="sym-toggle" data-sym="{sym}" checked '
            f'style="cursor:pointer;accent-color:#60a5fa">{sym}</label></td>'
            f"<td style='{ms};text-align:right'>{m:.2f}%</td>"
            f"<td style='{is_};text-align:right'>{i:.2f}%</td>"
            f"<td style='text-align:right;color:{diff_color};font-weight:600'>{diff_sign}{diff:.2f}%</td>"
            f"<td style='text-align:right'>{int(row['median_buys'])}</td>"
            f"<td style='text-align:right'>{int(row['median_sells'])}</td>"
            f"<td style='text-align:right'>{int(row['median_reinvests'])}</td>"
            f"<td style='text-align:right;color:{eb_color}'>{eb:,}</td>"
            + rng_cells(row)
            + f"<td style='text-align:center;color:{now_color};font-weight:600'>{now_label}</td>"
            f"<td style='text-align:center'><a href='{row['chart']}' target='_blank'>open</a></td>"
            f"</tr>\n"
        )
        # Everything the summary, the filters and the sort read. They work off
        # this array rather than off the rendered cells, so a number is never
        # parsed back out of the HTML it was formatted into.
        data_json.append({"sym": sym, "m": round(m, 4), "i": round(i, 4),
                          "b": int(row["median_buys"]),
                          "s": int(row["median_sells"]),
                          "r": int(row["median_reinvests"]),
                          "nw": now_label,
                          # The three raw flags beside the label. The Signal chips
                          # used to test the label for a substring, which quietly
                          # failed on the one combo whose label names none of them:
                          # (buy, sell, reinvest) all true renders as "All", so such
                          # a symbol answered no to Buy, Sell AND Reinvest and was
                          # counted under None. Unreachable today — the churn guard
                          # inside buy.check() stands the buy arm down on a bar the
                          # sell fires, so nothing can be both — but the chips now
                          # read the flags, which cannot be wrong whatever the
                          # labels become.
                          "nf": [int(bool(x)) for x in
                                 (row.get("now_flags") or (False, False, False))],
                          "eb": int(row.get("eval_bars") or 0),
                          "vt": _num(row.get("vs_top_%")),
                          "vb": _num(row.get("vs_bottom_%")),
                          "vd": _num(row.get("vs_median_%")),
                          "vm": _num(row.get("vs_mean_%")),
                          "ix": index_of.get(sym, [])})

    import json
    data_js = json.dumps(data_json)

    # (group id, group label, [(chip id, chip label)]). The predicate for each
    # chip id lives in PRED in the JS below; adding a filter means adding a line
    # here and a line there.
    #
    # WITHIN a group the chips are OR'd, ACROSS groups they are AND'd. That is
    # what makes the set combinable without producing accidental empties: "Beat"
    # plus "Lost" reads as "decided either way", not as a contradiction, and
    # "Long" plus "Short" is the whole universe rather than nothing. An empty
    # group constrains nothing.
    FILTERS = [
        ("hist", "History", [
            ("long",   f"Long &ge;{LONG_BARS:,}"),
            ("short",  f"Short &lt;{LONG_BARS:,}")]),
        ("out",  "Vs interval", [
            ("win",    "Beat by &ge;1%"),
            ("lose",   "Lost by &ge;1%"),
            # Its own bucket rather than a slice of the two above: a symbol the
            # strategy left alone is a different finding from one it handled and
            # lost on, and the split showed six of them hiding in the short group.
            ("flat",   "No real effect &lt;1%")]),
        ("act",  "Activity", [
            ("sold",   "Sold at least once"),
            ("nosell", "Never sold")]),
        ("sig",  "Signal today", [
            ("buy",    "Buy"),
            ("sell",   "Sell"),
            ("rei",    "Reinvest"),
            ("nosig",  "None")]),
        # Not the same question as "Lost by >=1%", which is relative. NVL beat the
        # interval arm by 8.67 points and is still down 16.23% in absolute terms.
        ("abs",  "Absolute", [
            ("red",    f"{title} in the red")]),
    ]
    # One chip per seeded index, plus "Outside": a symbol in none of them. Outside
    # is not the complement of "no chip selected" — with every index chip on it
    # would still be hidden, and it is the only way to ask what the strategy does
    # away from the large caps. The index price series themselves (VN30 the row)
    # land in Outside, since an index is not a member of itself.
    IX_LABEL = {"vn30": "VN30", "vndiamond": "VNDiamond", "vnfinlead": "VNFinLead"}
    # Drop an index none of the scored symbols belongs to — a chip that can only
    # ever empty the table is noise. This is the one count Python needs; the counts
    # ON the chips are done in JS, see chipCounts().
    index_names = [ix for ix in index_names
                   if any(ix in d["ix"] for d in data_json)]
    if index_names:
        FILTERS.append(("ix", "Index",
                        [(f"ix:{ix}", IX_LABEL.get(ix, ix.upper()))
                         for ix in index_names]
                        + [("ix:none", "Outside")]))
    ix_pred_js = "".join(
        f"  'ix:{ix}': d => d.ix.indexOf('{ix}') >= 0,\n" for ix in index_names
    ) + ("  'ix:none': d => d.ix.length === 0,\n" if index_names else "")

    filter_html = "".join(
        "<div style='display:flex;align-items:baseline;gap:8px;margin:4px 0'>"
        f"<span style='color:#64748b;font-size:11px;min-width:86px'>{glabel}</span>"
        "<div style='display:flex;flex-wrap:wrap;gap:6px'>"
        # The count span is filled in by chipCounts() from the chip's own
        # predicate. Writing it here would mean stating each rule twice, in two
        # languages, and the two would agree right up until one of them changed.
        + "".join(f"<button class='chip' data-grp='{gid}' data-f='{fid}'>{flabel}"
                  f"<span class='n'></span></button>"
                  for fid, flabel in chips)
        + "</div></div>"
        for gid, glabel, chips in FILTERS
    )
    filter_html = (
        "<div style='margin:10px 0;padding:10px 14px;background:#0f172a;"
        "border:1px solid #1e293b;border-radius:8px;font-size:12px'>"
        "<div style='display:flex;justify-content:space-between;align-items:center;"
        "margin-bottom:8px'>"
        "<span style='color:#94a3b8;font-weight:700'>Filters "
        f"<span style='color:#475569;font-weight:400'>&mdash; {len(data_json)} "
        "symbols</span></span>"
        "<span><span id='f-count' style='color:#64748b;margin-right:10px'></span>"
        "<button id='f-clear' class='chip'>Clear all</button></span></div>"
        f"{filter_html}"
        "<div style='color:#475569;font-size:11px;margin-top:8px'>"
        "Chips in the same row are OR'd, different rows are AND'd. Filtered-out "
        "symbols leave the table and the summary; unchecking a visible row drops "
        "it from the summary only.<br>"
        "The number on a chip is how many of all "
        f"{len(data_json)} symbols it matches on its own &mdash; it is fixed, not "
        "a count of what survives the other chips, so the numbers stay comparable "
        "and never all collapse to the same value as you narrow the selection. The "
        "live count of what is showing is on the right of this box."
        "</div></div>"
    )

    # (js key, row label, extra cell style). None is a horizontal rule. Every row
    # is rendered three times — All, Long, Short — so it is written once here and
    # the JS fills the cells by data-cell / data-grp.
    SUM_ROWS = [
        ("n",      "Symbols compared",                      "font-weight:600"),
        ("mw",     f"{title} wins",                       "color:#4ade80;font-weight:600"),
        ("iw",     "BuyInterval wins",                      "color:#f87171;font-weight:600"),
        ("dr",     "Draws",                                 "color:#94a3b8"),
        None,
        ("mdiff",  "<b>Median per-symbol diff</b><br>"
                   "<span style='color:#475569;font-size:11px'>median of the "
                   "per-symbol diffs, not the difference of the two medians "
                   "below</span>",                          ""),
        ("sign",   "Win rate (sign test)",                  ""),
        ("eb",     "Evaluated bars<br><span style='color:#475569;font-size:11px'>"
                   "median (min / max)</span>",             ""),
        None,
        ("avg",    f"Avg growth — {title} / Interval",    ""),
        ("med",    f"Median growth — {title} / Interval", ""),
        ("wl",     "Avg win / avg loss",                    ""),
        ("quart",  "Diff spread — p25 / p50 / p75",         ""),
        ("conc",   "Gains concentration — top 1 / top 3",   ""),
        ("net",    "Net diff — all / excluding best",       ""),
        ("sig",    "Signal today<br><span style='color:#475569;font-size:11px'>"
                   "symbols flagged, out of the filtered set</span>", ""),
        ("tot",    "Total actions — buys / sells / reinvests<br>"
                   "<span style='color:#475569;font-size:11px'>summed over every "
                   "bar, not today</span>",                  ""),
        ("act",    "Activity — avg sells, never sold",      ""),
        None,
        ("mbest",  f"Best {title}",                       "color:#4ade80"),
        ("ibest",  "Best BuyInterval",                      "color:#4ade80"),
        ("mworst", f"Worst {title}",                      "color:#f87171"),
    ]
    sum_rows_html = ""
    for item in SUM_ROWS:
        if item is None:
            sum_rows_html += ("<tr><td colspan='4'>"
                              "<hr style='border-color:#1e293b;margin:6px 0'></td></tr>\n")
            continue
        key, label, style = item
        cells = "".join(
            f"<td data-cell='{key}' data-grp='{g}' style='{style}'></td>"
            for g in ("all", "long", "short"))
        sum_rows_html += f"<tr><td>{label}</td>{cells}</tr>\n"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title} Backtest — All Symbols</title>
<style>
  body {{ font-family: sans-serif; background: #111; color: #ddd; padding: 20px; }}
  h1 {{ font-size: 1.4rem; margin-bottom: 12px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
  th {{ background: #1e293b; color: #94a3b8; padding: 8px 12px; text-align: left;
        position: sticky; top: 0; z-index: 1; }}
  td {{ padding: 6px 12px; border-bottom: 1px solid #1e293b; }}
  tr:hover td {{ background: rgba(255,255,255,0.04); }}
  tr.excluded td {{ opacity: 0.35; }}
  tr.hidden {{ display: none; }}
  a {{ color: #60a5fa; }}
  th[data-sort] {{ cursor: pointer; user-select: none; }}
  th[data-sort]:hover {{ color: #e2e8f0; }}
  th.sorted {{ color: #60a5fa; }}
  .chip {{ background:#1e293b;color:#94a3b8;border:1px solid #334155;
    border-radius:999px;padding:3px 10px;font-size:11px;font-family:inherit;
    cursor:pointer; }}
  .chip:hover {{ border-color:#475569;color:#e2e8f0; }}
  .chip.on {{ background:#1d4ed8;border-color:#3b82f6;color:#fff;font-weight:600; }}
  /* Dimmer than the label so the chip still reads as its name first. */
  .chip .n {{ color:#64748b;margin-left:6px;font-weight:400; }}
  .chip.on .n {{ color:#bfdbfe; }}
  /* A chip that matches nothing stays clickable — it is a finding that the set is
     empty — but it should not look like an option worth trying. */
  .chip.empty {{ opacity:0.45; }}
  #summary {{ margin-top:28px;background:#0f172a;border:1px solid #1e293b;
    border-radius:10px;padding:20px 24px;font-size:13px;line-height:2; }}
  #summary .s-title {{ font-size:15px;font-weight:700;color:#f1f5f9;margin-bottom:10px; }}
  #summary table {{ font-size:13px; }}
  #summary td {{ vertical-align:top;padding:5px 12px 5px 0;line-height:1.5; }}
  #summary td:first-child {{ color:#64748b;padding-right:24px; }}
  #summary th {{ background:#111827;color:#94a3b8;font-size:12px;
    padding:6px 12px 6px 0;text-align:left;border-bottom:1px solid #1e293b; }}
</style>
</head>
<body>
<h1>{title} Backtest — All Symbols</h1>
<p style="color:#64748b;font-size:12px">
  {len(rows)} symbols reported{skipped_note} &nbsp;|&nbsp;
  vs BuyInterval (no sell/reinvest), both arms starting at the same bar &nbsp;|&nbsp;
  <span style="color:#94a3b8">Click a column header to sort</span> — Diff
  ({title} − Interval) descending by default. &nbsp;|&nbsp;
  <span style="color:#fbbf24">Amber</span> eval bars = short history. &nbsp;|&nbsp;
  vs Top / Bottom / Median / Mean = latest price against its own 1000-bar range;
  <span style="color:#fbbf24">amber</span> vs Median = at or past the sell threshold. &nbsp;|&nbsp;
  <span style="color:#94a3b8">Uncheck a row to exclude it from summary.</span>
</p>
{config_html}
{split_html}
{filter_html}
{skipped_html}
<table>
<thead><tr>
  <th data-sort="sym" data-type="s">Symbol</th>
  <th data-sort="m">{title}</th><th data-sort="i">BuyInterval</th>
  <th data-sort="d">Diff</th>
  <th data-sort="b">Buys</th><th data-sort="s">Sells</th><th data-sort="r">Reinvests</th>
  <th data-sort="eb">Eval bars</th>
  <th data-sort="vt">vs Top</th><th data-sort="vb">vs Bottom</th>
  <th data-sort="vd">vs Median</th><th data-sort="vm">vs Mean</th>
  <th data-sort="nw" data-type="s">Signal now</th>
  <th>Chart</th>
</tr></thead>
<tbody id="tbody">
{rows_html}
</tbody>
</table>
<p id="empty-note" style="display:none;color:#fbbf24;font-size:13px;padding:16px 0">
  No symbol matches every filter group. Chips in the same row widen the set;
  chips in different rows narrow it.
</p>

<div id="summary">
  <div class="s-title">Summary</div>
  <table style="border-collapse:collapse;width:100%">
    <colgroup><col style="width:28%"><col style="width:24%">
              <col style="width:24%"><col style="width:24%"></colgroup>
    <thead><tr>
      <th style="position:static;background:transparent;padding-left:0"></th>
      <th style="position:static">All</th>
      <th style="position:static">Long &ge;{LONG_BARS:,} bars</th>
      <th style="position:static;color:#fbbf24">Short &lt;{LONG_BARS:,} bars</th>
    </tr></thead>
    <tbody>
{sum_rows_html}
    </tbody>
  </table>
  <div style="color:#475569;font-size:11px;margin-top:12px;line-height:1.6">
    The Long and Short columns are <b>different symbols</b>, so the gap between
    them is not a paired comparison and no cell here subtracts one from the
    other. Read each column on its own; the split exists because a short symbol
    was measured over one market period while a long one spans several, and
    averaging the two hides that. Unchecking a row updates all three columns.
  </div>
</div>

<script>
const ALL_DATA = {data_js};
const LONG_BARS = {LONG_BARS};
const excluded = new Set();

// Linear interpolation between the two neighbouring order statistics — the numpy
// and R type-7 default. median() is defined in terms of it so that the two rows
// of this table that both report a middle value cannot disagree: with an even
// number of symbols the old floor() quantile picked the LOWER of the two middle
// symbols, so "Diff spread p50" read +19.98% next to a "Median per-symbol diff"
// of +20.14% on the same 52 numbers.
function quantile(sorted, f) {{
  if (!sorted.length) return NaN;
  const pos = f * (sorted.length - 1);
  const lo = Math.floor(pos), hi = Math.ceil(pos);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}}

function median(arr) {{
  return quantile([...arr].sort((a,b) => a-b), 0.5);
}}

function fmt(v) {{
  return (v >= 0 ? '+' : '') + v.toFixed(2) + '%';
}}

// Every figure in the summary, computed over whichever subset it is handed, and
// returned as ready-to-insert HTML keyed by the data-cell names in the table.
// One function rather than three copies: the All / Long / Short columns must be
// the same arithmetic on different symbols, and the only way to guarantee that
// is for there to be one piece of arithmetic.
function statsFor(a) {{
  if (!a.length) return null;
  const n  = a.length;
  const ms = a.map(d => d.m);
  const is_ = a.map(d => d.i);
  const mw = a.filter(d => d.m > d.i).length;
  const iw = a.filter(d => d.i > d.m).length;
  const mAvg = ms.reduce((x,y)=>x+y,0)/n;
  const iAvg = is_.reduce((x,y)=>x+y,0)/n;
  const diff = mAvg - iAvg;

  // Median of the per-symbol differences, NOT median(m) - median(i). The two are
  // not the same: the symbol at the middle of one distribution is not the symbol
  // at the middle of the other, so a difference of medians describes no actual
  // symbol. On the 45-symbol run they read +1.42% and +8.42% respectively.
  const diffs = a.map(d => d.m - d.i).sort((x,y)=>x-y);
  const mdiff = median(diffs);

  // Sign test over decided symbols only; exact draws carry no directional info.
  const dec  = diffs.filter(v => Math.abs(v) > 1e-9);
  const wins = dec.filter(v => v > 0).length;
  let p = 1;
  if (dec.length) {{
    let c = 0;
    const lg = k => {{ let r = 0; for (let j = 2; j <= k; j++) r += Math.log(j); return r; }};
    for (let k = wins; k <= dec.length; k++)
      c += Math.exp(lg(dec.length) - lg(k) - lg(dec.length - k) - dec.length * Math.LN2);
    p = c;
  }}

  const ebs  = a.map(d => d.eb || 0).filter(v => v > 0).sort((x,y)=>x-y);
  const wArr = dec.filter(v=>v>0), lArr = dec.filter(v=>v<0);
  const avg  = arr => arr.length ? arr.reduce((x,y)=>x+y,0)/arr.length : 0;
  const q    = f => quantile(diffs, f);   // diffs is already sorted ascending
  const totW = wArr.reduce((x,y)=>x+y,0);
  const sortedW = wArr.slice().sort((x,y)=>y-x);
  const top1 = totW ? 100*sortedW[0]/totW : 0;
  const top3 = totW ? 100*sortedW.slice(0,3).reduce((x,y)=>x+y,0)/totW : 0;
  const netAll  = diffs.reduce((x,y)=>x+y,0);
  const bestSym = a.reduce((x,y) => (y.m-y.i) > (x.m-x.i) ? y : x);
  const mBest   = a.reduce((x,y) => y.m > x.m ? y : x);
  const iBest   = a.reduce((x,y) => y.i > x.i ? y : x);
  const mWorst  = a.reduce((x,y) => y.m < x.m ? y : x);
  const noSell  = a.filter(d => d.s === 0).length;
  // Today's signal, counted over whatever survived the filters. Buy, Sell and
  // Reinvest are NOT mutually exclusive — a bar can carry two — so they need not
  // sum to n and None is computed as "no flag set" rather than as the remainder.
  const nBuy  = a.filter(d => d.nf[0]).length;
  const nSell = a.filter(d => d.nf[1]).length;
  const nRei  = a.filter(d => d.nf[2]).length;
  const nNone = a.filter(d => !d.nf[0] && !d.nf[1] && !d.nf[2]).length;
  // Same colours the Signal now column and the chart's condition zones use.
  const sigPart = (label, k, col) =>
    '<span style="color:' + (k ? col : '#475569') + (k ? ';font-weight:600' : '') +
    '">' + label + ' ' + k + '</span>';
  const flat    = a.filter(d => Math.abs(d.m - d.i) < 1e-9).length;
  const grey    = t => '<span style="color:#64748b">' + t + '</span>';

  return {{
    n:  String(n),
    mw: mw + ' ' + grey('(' + Math.round(mw/n*100) + '%)'),
    iw: iw + ' ' + grey('(' + Math.round(iw/n*100) + '%)'),
    dr: String(n - mw - iw),
    mdiff: '<span style="color:' + (mdiff>=0?'#4ade80':'#f87171') +
           ';font-weight:700;font-size:15px">' + fmt(mdiff) + '</span>',
    sign: wins + '/' + dec.length + ' ' +
          grey('(' + (dec.length ? Math.round(100*wins/dec.length) : 0) + '%)') + '<br>' +
          '<span style="color:' + (p<0.05?'#4ade80':'#94a3b8') + '">p = ' + p.toFixed(4) + '</span>',
    // Just the range. There is no "too wide" flag here on purpose: a group always
    // spans some range, and whether the boundary is in the right place is a
    // question about the GAP between the groups, which the History split line
    // above the table answers.
    eb: ebs.length
      ? median(ebs).toFixed(0) + ' ' + grey('(' + ebs[0] + ' / ' + ebs[ebs.length-1] + ')')
      : '—',
    avg: '<span style="color:#60a5fa">' + mAvg.toFixed(2) + '%</span> / ' +
         '<span style="color:#94a3b8">' + iAvg.toFixed(2) + '%</span><br>' +
         '<span style="color:' + (diff>=0?'#4ade80':'#f87171') + ';font-weight:600">' +
         fmt(diff) + '</span>',
    med: '<span style="color:#60a5fa">' + median(ms).toFixed(2) + '%</span> / ' +
         '<span style="color:#94a3b8">' + median(is_).toFixed(2) + '%</span>',
    wl: '<span style="color:#4ade80">' + fmt(avg(wArr)) + '</span> / ' +
        '<span style="color:#f87171">' + fmt(avg(lArr)) + '</span>' +
        (lArr.length ? ' ' + grey('(' + Math.abs(avg(wArr)/avg(lArr)).toFixed(2) + 'x)') : ''),
    quart: '<span style="color:#94a3b8">' + fmt(q(0.25)) + ' / ' + fmt(q(0.50)) +
           ' / ' + fmt(q(0.75)) + '</span>',
    conc: '<span style="color:' + (top1>25?'#fbbf24':'#94a3b8') + '">' + top1.toFixed(0) + '%</span>' +
          ' / <span style="color:' + (top3>50?'#fbbf24':'#94a3b8') + '">' + top3.toFixed(0) + '%</span>',
    net: fmt(netAll) + '<br>' + grey(fmt(netAll - (bestSym.m - bestSym.i)) +
         ' excl. ' + bestSym.sym),
    sig: sigPart('Buy', nBuy, '#22c55e') + ' / ' +
         sigPart('Sell', nSell, '#ef4444') + ' / ' +
         sigPart('Reinvest', nRei, '#f97316') + ' / ' +
         sigPart('None', nNone, '#94a3b8') + '<br>' +
         grey('of ' + n + ' symbols' +
              (nBuy + nSell + nRei > n - nNone
                 ? ' — a bar can carry two, so these overlap' : '')),
    // Totals over the whole evaluated history, not today. Right below the signal
    // row on purpose: one line says what the arms are saying now, the next says
    // how much they ever did, and reading them together is how you tell a quiet
    // filter selection from a quiet strategy.
    tot: '<span style="color:#22c55e">' + a.reduce((x,y)=>x+y.b,0) + '</span> / ' +
         '<span style="color:#ef4444">' + a.reduce((x,y)=>x+y.s,0) + '</span> / ' +
         '<span style="color:#f97316">' + a.reduce((x,y)=>x+y.r,0) + '</span>',
    act: (a.reduce((x,y)=>x+y.s,0)/n).toFixed(1) + ' sells<br>' +
         '<span style="color:' + (noSell > n/4 ? '#fbbf24' : '#94a3b8') + '">' +
         noSell + '/' + n + ' never sold</span>' +
         (flat ? ' ' + grey('(' + flat + ' flat)') : ''),
    mbest:  '<b>' + mBest.sym  + '</b> ' + mBest.m.toFixed(2)  + '%',
    ibest:  '<b>' + iBest.sym  + '</b> ' + iBest.i.toFixed(2)  + '%',
    mworst: '<b>' + mWorst.sym + '</b> ' + mWorst.m.toFixed(2) + '%',
  }};
}}

// ---------------------------------------------------------------- filtering
// One predicate per chip id in the FILTERS list built on the Python side.
const PRED = {{
  long:   d => d.eb >= LONG_BARS,
  short:  d => d.eb <  LONG_BARS,
  win:    d => (d.m - d.i) >=  1,
  lose:   d => (d.m - d.i) <= -1,
  flat:   d => Math.abs(d.m - d.i) < 1,
  sold:   d => d.s >  0,
  nosell: d => d.s === 0,
  // Read off the flags, not off the rendered label — a bar flagged "Buy +
  // Reinvest" answers to both chips because both flags are set, and no label
  // wording can change that. See the nf comment on the Python side.
  buy:    d => !!d.nf[0],
  sell:   d => !!d.nf[1],
  rei:    d => !!d.nf[2],
  nosig:  d => !d.nf[0] && !d.nf[1] && !d.nf[2],
  red:    d => d.m < 0,
  // Index chips are generated from whatever index_members holds, so their
  // predicates are generated with them rather than written out here.
{ix_pred_js}}};

// How many symbols each chip matches ON ITS OWN, out of the whole run. Computed
// from the chip's own predicate, so the number cannot drift from what clicking it
// does — the label and the filter are the same rule read twice by the same code.
//
// Deliberately NOT recomputed as other chips are clicked. A conditional count is a
// different and much less useful statement: with two groups active most chips
// would read 0 or the same small number, and the sizes you actually want when
// deciding what to click next — 30 in VN30, 6 never sold — would be gone. What is
// on screen right now is in #f-count instead.
function chipCounts() {{
  document.querySelectorAll('.chip[data-f]').forEach(btn => {{
    const p = PRED[btn.dataset.f];
    if (!p) return;
    const n = ALL_DATA.filter(p).length;
    btn.querySelector('.n').textContent = n;
    btn.classList.toggle('empty', n === 0);
  }});
}}

// group id -> Set of chip ids currently on.
const filters = {{}};

// OR inside a group, AND across groups. An empty group is not a constraint, so
// the no-filter case falls out of this without a special branch.
function passes(d) {{
  for (const g in filters) {{
    const on = filters[g];
    if (on.size && ![...on].some(k => PRED[k](d))) return false;
  }}
  return true;
}}

function visible() {{
  return ALL_DATA.filter(passes);
}}

function applyFilters() {{
  const shown = new Set(visible().map(d => d.sym));
  document.querySelectorAll('#tbody tr').forEach(tr => {{
    tr.classList.toggle('hidden', !shown.has(tr.dataset.sym));
  }});
  document.getElementById('f-count').textContent =
    'showing ' + shown.size + ' of ' + ALL_DATA.length;
  document.getElementById('empty-note').style.display = shown.size ? 'none' : 'block';
  updateSummary();
}}

// ------------------------------------------------------------------ sorting
let sortKey = 'd', sortDir = -1;   // matches the server-side order: Diff, desc

function sortValue(d, k) {{
  if (k === 'd') return d.m - d.i;
  const v = d[k];
  // A symbol with no range row sorts last either way rather than throwing off
  // the comparator with a null.
  if (v === null || v === undefined || Number.isNaN(v))
    return sortDir > 0 ? Infinity : -Infinity;
  return v;
}}

function applySort() {{
  const by = {{}};
  ALL_DATA.forEach(d => by[d.sym] = d);
  const tbody = document.getElementById('tbody');
  [...tbody.querySelectorAll('tr')]
    .sort((ra, rb) => {{
      const a = sortValue(by[ra.dataset.sym], sortKey);
      const b = sortValue(by[rb.dataset.sym], sortKey);
      return sortDir * (typeof a === 'string' ? a.localeCompare(b) : a - b);
    }})
    // appendChild on an existing node moves it, so this reorders in place.
    .forEach(tr => tbody.appendChild(tr));

  document.querySelectorAll('th[data-sort]').forEach(th => {{
    const on = th.dataset.sort === sortKey;
    th.classList.toggle('sorted', on);
    th.textContent = th.textContent.replace(/ [▲▼]$/, '') + (on ? (sortDir > 0 ? ' ▲' : ' ▼') : '');
  }});
}}

// ------------------------------------------------------------------ summary
function updateSummary() {{
  const active = visible().filter(d => !excluded.has(d.sym));
  const groups = {{
    all:   active,
    long:  active.filter(d => (d.eb || 0) >= LONG_BARS),
    short: active.filter(d => (d.eb || 0) <  LONG_BARS),
  }};
  for (const g in groups) {{
    // A group can be empty — one symbol, or every row on one side unchecked —
    // and an empty group has no median, no best and no worst. Blank the column
    // rather than let a reduce() on [] throw and leave the page half rendered.
    const s = statsFor(groups[g]);
    document.querySelectorAll('[data-grp="' + g + '"]').forEach(td => {{
      const k = td.dataset.cell;
      td.innerHTML = (s && s[k] !== undefined) ? s[k]
                   : '<span style="color:#334155">—</span>';
    }});
  }}
}}

document.querySelectorAll('.sym-toggle').forEach(cb => {{
  cb.addEventListener('change', () => {{
    const sym = cb.dataset.sym;
    const row = document.querySelector('tr[data-sym="' + sym + '"]');
    if (cb.checked) {{ excluded.delete(sym); row.classList.remove('excluded'); }}
    else            {{ excluded.add(sym);    row.classList.add('excluded'); }}
    updateSummary();
  }});
}});

document.querySelectorAll('.chip[data-f]').forEach(btn => {{
  btn.addEventListener('click', () => {{
    const g = btn.dataset.grp, f = btn.dataset.f;
    (filters[g] ||= new Set());
    if (filters[g].has(f)) {{ filters[g].delete(f); btn.classList.remove('on'); }}
    else                   {{ filters[g].add(f);    btn.classList.add('on'); }}
    applyFilters();
  }});
}});

document.getElementById('f-clear').addEventListener('click', () => {{
  for (const g in filters) filters[g].clear();
  document.querySelectorAll('.chip.on').forEach(b => b.classList.remove('on'));
  applyFilters();
}});

document.querySelectorAll('th[data-sort]').forEach(th => {{
  th.addEventListener('click', () => {{
    const k = th.dataset.sort;
    // Re-clicking the active column flips it; a new column starts descending for
    // numbers and ascending for names, which is the useful direction each time.
    if (k === sortKey) sortDir = -sortDir;
    else {{ sortKey = k; sortDir = th.dataset.type === 's' ? 1 : -1; }}
    applySort();
  }});
}});

chipCounts();
applySort();
applyFilters();
</script>
</body>
</html>"""

    out_path.write_text(html, encoding="utf-8")
    print(f"Report -> {out_path}")


if __name__ == "__main__":
    args    = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags   = [a for a in sys.argv[1:] if a.startswith("--")]

    # AN UNKNOWN FLAG IS AN ERROR, not a no-op. Unrecognised flags used to be
    # dropped silently, so `--profil=breadth` ran the price profile and reported
    # nothing wrong -- a whole run measuring something other than what was asked
    # for. `--all` was in the package docstring and never existed in this file;
    # it happened to work because running every symbol is the default.
    KNOWN = ("--profile=", "--workers=", "--signal=", "--universe=", "--all")
    unknown = [f for f in flags if not f.startswith(KNOWN)]
    if unknown:
        raise SystemExit(
            f"co la: {' '.join(unknown)}\n"
            f"dung:  python -m single.multi_signal.run_all [MA ...] "
            f"[--all] [--profile=price|breadth|both] "
            f"[--signal=prem_median|prem_trim|prem_trim_cap] "
            f"[--universe=all|all-VIC-VIX] [--workers=N]")

    # Applied before anything reads config: factory.py and the report both read
    # the module directly, so the overlay has to be in place first.
    profile = next((f.split("=", 1)[1] for f in flags
                    if f.startswith("--profile=")), None)
    from single.multi_signal.profiles import apply as apply_profile
    if profile:
        changed = apply_profile(config, profile)
        print(f"Profile   -> {profile}"
              + (": " + ", ".join(f"{k}={new}" for k, (_old, new) in sorted(changed.items()))
                 if changed else ""))
    else:
        print("Profile   -> (mac dinh) config.py nguyen van")
    signal = next((f.split("=", 1)[1] for f in flags
                   if f.startswith("--signal=")), None)
    if signal:
        config.BREADTH_SIGNAL = signal
        print(f"Signal    -> {signal}")

    universe = next((f.split("=", 1)[1] for f in flags
                     if f.startswith("--universe=")), None)
    if universe:
        config.BREADTH_UNIVERSE = universe
        print(f"Universe  -> {universe}")

    workers = next((int(f.split("=", 1)[1]) for f in flags if f.startswith("--workers=")),
                   None)   # None -> ProcessPoolExecutor picks os.cpu_count()

    db.init_db()
    CHARTS_DIR.mkdir(exist_ok=True)

    # --all is the explicit spelling of the default. Naming both at once is a
    # contradiction rather than a preference, so it is refused instead of one
    # quietly winning.
    if "--all" in flags and args:
        raise SystemExit(f"--all va danh sach ma ({' '.join(args)}) loai tru nhau")
    symbols = [s.upper() for s in args] if args else db.list_symbols()

    run_dir = CHARTS_DIR / datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir.mkdir(exist_ok=True)

    print(f"Processing {len(symbols)} symbols: {', '.join(symbols)}")
    print(f"Output    -> {run_dir}")
    print(f"Progress  -> {run_dir}/run_all_progress.html\n")

    prog = RunAllProgress(symbols, out=str(run_dir / "run_all_progress.html"))
    t0 = time.time()

    report_rows, skipped, done = [], [], 0
    with ProcessPoolExecutor(max_workers=workers) as ex:
        n_slots = ex._max_workers
        futures = {ex.submit(process_symbol, s, run_dir, profile, signal,
                             universe): s for s in symbols}

        # The pool runs submissions FIFO, so the first n_slots symbols are the
        # ones actually in flight. Tracked here rather than reported by the
        # workers, which would need a Manager queue to say "I started".
        for s in symbols[:n_slots]:
            prog.begin(s)
        next_start = n_slots

        # as_completed, not ex.map: map yields in submission order, so one slow
        # symbol holds back every result behind it and the progress page moves
        # in bursts. Order does not matter here — the report sorts by diff.
        for fut in as_completed(futures):
            sym, row, skip_reason, dur = fut.result()
            done += 1
            if row:
                report_rows.append(row)
                prog.end_ok(sym, dur,
                            median_growth=row["median_growth_%"],
                            buys=row["median_buys"], sells=row["median_sells"],
                            reinvests=row["median_reinvests"],
                            interval_growth=row["interval_growth_%"],
                            chart=row["chart"])
                print(f"[{done}/{len(symbols)}] {sym} ... "
                      f"median={row['median_growth_%']:.1f}%  "
                      f"interval={row['interval_growth_%']:.1f}%", flush=True)
            else:
                skipped.append((sym, skip_reason or "unknown"))
                prog.end_err(sym, skip_reason or "unknown")
                print(f"[{done}/{len(symbols)}] {sym} ... skipped — {skip_reason}",
                      flush=True)
            if next_start < len(symbols):
                prog.begin(symbols[next_start])
                next_start += 1

    prog.finish()

    if report_rows:
        build_report(report_rows, run_dir / "report_all.html", skipped)

    print(f"\nDone in {(time.time() - t0)/60:.1f} min on {n_slots} workers.")
