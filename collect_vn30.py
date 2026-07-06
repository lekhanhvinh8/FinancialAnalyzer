"""
Collect prices and fundamentals for all current VN30 members.
"""

import time
from datetime import date

import database as db
import collect

db.init_db()

START = "2015-01-01"
END   = date.today().isoformat()

_RETRY_WAIT = 40   # seconds to wait after a rate-limit hit
_RETRIES    = 3


def _call_with_retry(fn, *args, label="", **kwargs):
    for attempt in range(1, _RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            msg = str(e)
            if "rate" in msg.lower() or "limit" in msg.lower() or "20/" in msg or "exceeded" in msg.lower():
                print(f"  Rate limited — waiting {_RETRY_WAIT}s (attempt {attempt}/{_RETRIES})")
                time.sleep(_RETRY_WAIT)
            else:
                raise  # non-rate-limit error, propagate immediately
    raise RuntimeError(f"Still rate-limited after {_RETRIES} retries for {label}")


members = db.load_vn30_members(as_of=END)["symbol"].tolist()
print(f"Collecting data for {len(members)} VN30 members: {', '.join(members)}")
print(f"Price range: {START} → {END}\n")

errors = []

for i, symbol in enumerate(members, 1):
    print(f"[{i:02d}/{len(members)}] {symbol}")
    try:
        _call_with_retry(collect.collect_prices, symbol, START, END, label=f"{symbol} prices")
    except Exception as e:
        print(f"  ERROR prices {symbol}: {e}")
        errors.append((symbol, "prices", str(e)))

    try:
        _call_with_retry(collect.collect_fundamentals, symbol, label=f"{symbol} fundamentals")
    except Exception as e:
        print(f"  ERROR fundamentals {symbol}: {e}")
        errors.append((symbol, "fundamentals", str(e)))

    # 20 req/min limit: 3 calls per symbol → need ~9s minimum; use 15s to be safe
    time.sleep(15)
    print()

print("\n" + "=" * 55)
print("DONE")
print("=" * 55)
print(db.summary().to_string(index=False))

if errors:
    print(f"\nErrors ({len(errors)}):")
    for sym, kind, msg in errors:
        print(f"  {sym} [{kind}]: {msg}")
