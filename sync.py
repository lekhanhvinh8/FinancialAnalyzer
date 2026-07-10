"""
Sync all index data to today.

Fetches price tails, latest shares, and latest profit for every symbol
across all three indices. Never overwrites with older data — safe to run anytime.

Usage:
    python sync.py              # sync all three indices
    python sync.py vn30         # sync one index only
"""

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from collectors.engine import sync

INDICES = ["vn30", "vndiamond", "vnfinlead"]

targets = sys.argv[1:] if len(sys.argv) > 1 else INDICES

for index in targets:
    sync(index)
