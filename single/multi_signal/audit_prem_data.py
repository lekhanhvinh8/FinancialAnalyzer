# -*- coding: utf-8 -*-
"""
Du lieu cho bao cao kiem tra ba duong prem.

MOI MA DEU LA MOT DONG, ke ca VIC va VIX. Ban truoc chi liet ke ro 54 ma, nen
hai ma bi loai khong xuat hien o dau ca -- doc bao cao khong the biet chung ton
tai. Ro nao dang duoc do la mot LUA CHON trong trang, khong phai la mot su that
co dinh cua bang.

Tinh lai TU GIA THO, chi dung du lieu <= ngay dang xet. Gia tri da luu chi lay
ra de dat canh so tu tinh.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, r"C:\projects\Stock_Analyzer\PriceToEarn_v2")

import numpy as np

import database as db
from core.breadth_calc import universe_key
from core.universe import resolve
import syncs.breadth as sb

DATES = ["2018-01-23", "2022-01-04", "2026-08-04"]
W = sb.WINDOW
TRIM_LO, TRIM_HI = 5, 95

BASKETS = {universe_key(spec, exc): sorted(resolve(spec, exc))
           for spec, exc in sb.BASKETS}
ALL = sorted({s for v in BASKETS.values() for s in v})

px, cap = {}, {}
for s in ALL:
    d = db.load_daily_prices(s)["close"]
    d.index = [str(i)[:10] for i in d.index]
    px[s] = d
    k = db.load_pe_ratios(s)
    if not k.empty and "total_market_cap" in k:
        k = k["total_market_cap"].dropna()
        k.index = [str(i)[:10] for i in k.index]
        cap[s] = k


def stored(uni, date):
    out = {}
    for variant, sig in (("base", "median_prem"), ("trim5-95", "prem_trim"),
                         ("trim5-95", "prem_cap")):
        df = db.load_breadth(uni, W, variant, [sig])
        if df.empty or sig not in df:
            continue
        row = df[df.index.astype(str).str[:10] == date]
        if len(row):
            v = row[sig].iloc[0]
            out[sig] = None if v != v else round(float(v), 4)
            out["n_symbols"] = int(row["n_symbols"].iloc[0])
    return out


def snapshot(date):
    rows = []
    for s in ALL:
        h = px[s][px[s].index <= date]
        traded = len(h) > 0 and h.index[-1] == date
        bars = len(h)
        med = float(h.iloc[-W:].median()) if bars >= W else None
        close = float(h.iloc[-1]) if bars else None
        prem = ((close - med) / med * 100) if (med and traded) else None
        c = None
        if s in cap:
            kk = cap[s][cap[s].index <= date]
            if len(kk):
                c = float(kk.iloc[-1])
        why = ("" if prem is not None else
               "khong giao dich phien nay" if not traded else
               "chi co %d/%d phien" % (bars, W))
        rows.append({
            "sym": s, "bars": bars,
            "close": None if close is None else round(close, 1),
            "med": None if med is None else round(med, 1),
            "prem": None if prem is None else round(prem, 4),
            "cap": None if c is None else round(c / 1e9, 1),
            "ok": prem is not None, "why": why,
            "in": {k: (s in v) for k, v in BASKETS.items()},
        })
    return rows


def compute(rows, basket):
    """Ba duong tren mot ro -- giong het ham JS trong trang."""
    live = [r for r in rows if r["ok"] and r["in"][basket]]
    p = np.array([r["prem"] for r in live], dtype=float)
    if not len(p):
        return {}
    lo, hi = np.percentile(p, [TRIM_LO, TRIM_HI])
    keep = (p >= lo) & (p <= hi)
    w = np.array([(r["cap"] if r["cap"] else np.nan) for r in live], dtype=float)
    mc = keep & ~np.isnan(w)
    return {"median_prem": round(float(np.median(p)), 4),
            "prem_trim": round(float(p[keep].mean()), 4),
            "prem_cap": round(float((p[mc] * w[mc]).sum() / w[mc].sum()), 4),
            "n": int(len(p)), "n_trim": int(keep.sum()), "n_cap": int(mc.sum()),
            "lo": round(float(lo), 4), "hi": round(float(hi), 4)}


out = {"dates": DATES, "window": W, "trim": [TRIM_LO, TRIM_HI],
       "baskets": {k: len(v) for k, v in BASKETS.items()},
       "basket_members": BASKETS, "sections": {}}
for d in DATES:
    rows = snapshot(d)
    out["sections"][d] = {
        "rows": rows,
        "mine": {b: compute(rows, b) for b in BASKETS},
        "stored": {b: stored(b, d) for b in BASKETS},
    }
    for b in BASKETS:
        m, s2 = out["sections"][d]["mine"][b], out["sections"][d]["stored"][b]
        ok = all(s2.get(k) is not None and abs(m[k] - s2[k]) < 5e-4
                 for k in ("median_prem", "prem_trim", "prem_cap"))
        print("%s %-12s n=%2d  %.4f %.4f %.4f  %s"
              % (d, b, m["n"], m["median_prem"], m["prem_trim"], m["prem_cap"],
                 "KHOP" if ok else "LECH " + str(s2)), file=sys.stderr)

print(json.dumps(out, ensure_ascii=False))
