# -*- coding: utf-8 -*-
"""
Du lieu tho cho bao cao kiem tra doc lap ba duong prem.

Tinh lai TU GIA THO, chi dung du lieu <= ngay dang xet. Khong doc bang
breadth_signals cho phan tinh toan -- gia tri da luu chi duoc lay ra de dat
canh so tu tinh, cho nguoi doc doi chieu.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, r"C:\projects\Stock_Analyzer\PriceToEarn_v2")

import numpy as np
import pandas as pd

import database as db
from core.universe import resolve
import syncs.breadth as sb

DATES = ["2018-01-23", "2022-01-04", "2026-08-04"]
W = sb.WINDOW          # 1000
TRIM_LO, TRIM_HI = 5, 95

uni = sorted(resolve(sb.UNIVERSE, sb.EXCLUDE))

px, cap = {}, {}
for s in uni:
    d = db.load_daily_prices(s)["close"]
    d.index = [str(i)[:10] for i in d.index]
    px[s] = d
    k = db.load_pe_ratios(s)
    if not k.empty and "total_market_cap" in k:
        k = k["total_market_cap"].dropna()
        k.index = [str(i)[:10] for i in k.index]
        cap[s] = k


def stored(date):
    """Gia tri dang nam trong bang, de doi chieu."""
    out = {}
    for variant, sig in (("base", "median_prem"), ("trim5-95", "prem_trim"),
                         ("trim5-95", "prem_cap")):
        df = db.load_breadth(sb.UNIVERSE, W, variant, [sig])
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
    for s in uni:
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
        why = ("" if (traded and bars >= W and med) else
               "khong giao dich phien nay" if not traded else
               "chi co %d/%d phien" % (bars, W))
        rows.append({
            "sym": s, "bars": bars, "traded": traded,
            "close": None if close is None else round(close, 1),
            "med": None if med is None else round(med, 1),
            "prem": None if prem is None else round(prem, 4),
            "cap": None if c is None else round(c / 1e9, 1),   # ty dong
            "ok": prem is not None, "why": why,
        })
    return rows


def compute(rows):
    """Ba duong, tinh tu danh sach dong hop le -- giong het JS trong bao cao."""
    p = np.array([r["prem"] for r in rows if r["ok"]], dtype=float)
    if not len(p):
        return {}
    lo, hi = np.percentile(p, [TRIM_LO, TRIM_HI])
    keep = (p >= lo) & (p <= hi)
    w = np.array([(r["cap"] if r["cap"] else np.nan)
                  for r in rows if r["ok"]], dtype=float)
    mc = keep & ~np.isnan(w)
    return {
        "median_prem": round(float(np.median(p)), 4),
        "prem_trim": round(float(p[keep].mean()), 4),
        "prem_cap": round(float((p[mc] * w[mc]).sum() / w[mc].sum()), 4),
        "n": int(len(p)), "n_trim": int(keep.sum()), "n_cap": int(mc.sum()),
        "lo": round(float(lo), 4), "hi": round(float(hi), 4),
    }


out = {"dates": DATES, "window": W, "trim": [TRIM_LO, TRIM_HI],
       "universe": len(uni), "sections": {}}
for d in DATES:
    rows = snapshot(d)
    out["sections"][d] = {"rows": rows, "mine": compute(rows), "stored": stored(d)}
    m, s2 = out["sections"][d]["mine"], out["sections"][d]["stored"]
    print("%s  n=%d  median %.4f/%s  trim %.4f/%s  cap %.4f/%s"
          % (d, m["n"], m["median_prem"], s2.get("median_prem"),
             m["prem_trim"], s2.get("prem_trim"),
             m["prem_cap"], s2.get("prem_cap")), file=sys.stderr)

print(json.dumps(out, ensure_ascii=False))
