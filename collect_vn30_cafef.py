"""
Backfill historical net profit and shares for all VN30 members using CafeF.
Prices already collected via vnstock — this only fills fundamentals.
"""

import time
from datetime import date

import database as db
from sources import cafef

db.init_db()

members = db.load_vn30_members(as_of=date.today().isoformat())["symbol"].tolist()
print(f"Backfilling CafeF fundamentals for {len(members)} VN30 members\n")

errors = []

for i, symbol in enumerate(members, 1):
    print(f"[{i:02d}/{len(members)}] {symbol}")

    try:
        profit = cafef.get_net_profit(symbol)
        db.save_net_profit(symbol, profit, override=True)
        print(f"  net_profit: {len(profit)} quarters")
    except Exception as e:
        print(f"  ERROR net_profit {symbol}: {e}")
        errors.append((symbol, "net_profit", str(e)))

    time.sleep(0.3)

print("\n" + "=" * 55)
print(db.summary().to_string(index=False))

if errors:
    print(f"\nErrors ({len(errors)}):")
    for sym, kind, msg in errors:
        print(f"  {sym} [{kind}]: {msg}")
