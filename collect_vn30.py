"""
Collect prices + fundamentals for all VN30 members.

Prices and shares: vnstock (VCI source)
Net profit history: CafeF API (backfill to earliest available quarter)
Raw JSON responses saved to data/raw/cafef/ for auditing.

Skips symbols that already have data; use override flags in database.py
to force re-collection.
"""

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import time
from datetime import date

import database as db
from sources import vnstock, cafef
from seed_vn30 import VN30_SNAPSHOTS

RAW_DIR = "data/raw/cafef"
START   = "2012-01-01"
END     = date.today().isoformat()

_RETRY_WAIT = 40
_RETRIES    = 3


def _call_with_retry(fn, *args, label="", **kwargs):
    for attempt in range(1, _RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            msg = str(e)
            if any(k in msg.lower() for k in ("rate", "limit", "20/", "exceeded")):
                print(f"  Rate limited -- waiting {_RETRY_WAIT}s (attempt {attempt}/{_RETRIES})")
                time.sleep(_RETRY_WAIT)
            else:
                raise
    raise RuntimeError(f"Still rate-limited after {_RETRIES} retries for {label}")


db.init_db()

# All unique symbols ever in VN30
all_members = sorted(set(s for syms in VN30_SNAPSHOTS.values() for s in syms))

import sqlite3 as _sqlite3
have_prices = set(db.list_symbols())
_con = _sqlite3.connect(db.DB_PATH)
have_profit = {r[0] for r in _con.execute("SELECT DISTINCT symbol FROM net_profit").fetchall()}
_con.close()

need_prices = [s for s in all_members if s not in have_prices]
need_profit = [s for s in all_members if s not in have_profit]

print(f"VN30 unique members ever: {len(all_members)}")
print(f"Need prices : {need_prices or 'none'}")
print(f"Need profit : {need_profit or 'none'}")
print()

errors = []

# ── Prices + shares via vnstock ───────────────────────────────────────────────
for i, symbol in enumerate(need_prices, 1):
    print(f"[{i:02d}/{len(need_prices)}] {symbol} -- prices + shares")
    try:
        prices = _call_with_retry(vnstock.get_prices, symbol, START, END, label=symbol)
        db.save_prices(symbol, prices)
    except Exception as e:
        print(f"  ERROR prices: {e}")
        errors.append((symbol, "prices", str(e)))

    try:
        shares = _call_with_retry(vnstock.get_shares, symbol, label=symbol)
        db.save_shares(symbol, shares)
    except Exception as e:
        print(f"  ERROR shares: {e}")
        errors.append((symbol, "shares", str(e)))

    time.sleep(15)

# ── Net profit via CafeF ──────────────────────────────────────────────────────
print()
for i, symbol in enumerate(need_profit, 1):
    print(f"[{i:02d}/{len(need_profit)}] {symbol} -- net profit (CafeF)")
    try:
        profit = cafef.get_net_profit(symbol, raw_dir=RAW_DIR)
        db.save_net_profit(symbol, profit, override=True)
        codes = profit["source_code"].unique().tolist()
        print(f"  net_profit: {len(profit)} quarters, codes={codes}")
    except Exception as e:
        print(f"  ERROR profit: {e}")
        errors.append((symbol, "net_profit", str(e)))
    time.sleep(0.3)

# ── Summary ───────────────────────────────────────────────────────────────────
print("\n" + "=" * 55)
print(db.summary().to_string(index=False))

if errors:
    print(f"\nErrors ({len(errors)}):")
    for sym, kind, msg in errors:
        print(f"  {sym} [{kind}]: {msg}")
else:
    print("\nAll collected successfully.")
