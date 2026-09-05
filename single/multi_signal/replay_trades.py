import sys, importlib, json
sys.path.insert(0, r"C:\projects\Stock_Analyzer\PriceToEarn_v2")
import pandas as pd
import database as db
from single.runner import load_symbol_df, run_estimate
import single.multi_signal.config as config
from single.multi_signal.factory import make_median_strategies
from single.multi_signal.profiles import apply as apply_profile
from single.multi_signal.breadth_map import build_breadth_map


def run(sym, profile):
    importlib.reload(config)
    # "default" = khong ap overlay nao, tuc config.py nguyen van -- dung nhu
    # run_all khi chay khong tham so.
    if profile != "default":
        apply_profile(config, profile)
    df = load_symbol_df(sym)
    bw = getattr(config, "BUY_MEDIAN_WINDOW", 1000)
    sw = getattr(config, "SELL_MEDIAN_WINDOW", 1000)
    crc = db.load_range_stats(symbol=sym, df=df, range_days={1000, bw, sw})
    d2i = {pd.Timestamp(r["time"]): i for i, r in df.iterrows()}

    def sig(w, col):
        d = db.load_trend_signals(sym, window_days=w)
        return {d2i[pd.Timestamp(t)]: float(v) for t, v in d[col].items()
                if pd.Timestamp(t) in d2i} if not d.empty else {}

    s3 = sig(1000, "signal3_sharpe") if config.MIN_SIGNAL3 is not None else {}
    s1 = (sig(config.SELL_SIGNAL1_WINDOW, "signal1_slope")
          if config.SELL_MIN_SIGNAL1 is not None else {})
    bm = {}
    if any(getattr(config, k, None) is not None for k in
           ("BUY_MAX_BREADTH", "SELL_MIN_BREADTH", "REINVEST_MAX_BREADTH")):
        bm = build_breadth_map(df)
    start = max([1000, bw, sw] + [min(m) for m in (s1, s3, bm) if m])
    buy, sell, rei = make_median_strategies(signal3_map=s3, signal1_map=s1,
                                            reinvest_signal1_map=s1, breadth_map=bm)
    r = run_estimate(sym, df, config.INTERVAL_MONEY, buy, sell, rei, crc,
                     start_index=start)
    idx2date = {i: str(t)[:10] for t, i in d2i.items()}

    dates = [str(t)[:10] for t in df["time"]]

    def fmt(infos):
        return [[dates[x.index] if 0 <= x.index < len(dates) else "?",
                 round(float(x.close) / 1000, 2),
                 round(float(getattr(x, "sellGrowthRatito", 0.0)), 1)] for x in infos]
    return {"growth": round(r["allRatioGrowth"], 1), "buys": r["totalBuys"],
            "sells": fmt(r["sellInfos"]), "reinv": fmt(r["reinvestInfos"])}


if __name__ == "__main__":
    print(json.dumps({s: {p: run(s, p) for p in ("price", "breadth", "default")}
                      for s in sys.argv[1:]}, ensure_ascii=False))
