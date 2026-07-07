"""
CafeF data source adapter.

Scrapes https://apiweb.cafef.vn — the same JSON API the cafef.vn financial
pages call in the browser. No login required; no rate-limit headers observed.

Public interface:
    get_net_profit(symbol) -> DataFrame   year, quarter, net_profit (VND)

Prices and shares are NOT available here — use sources.vnstock for those.

Notes:
  - Net profit code is KQKD_13 for standard companies/banks; KQKD_10 for securities brokers.
  - TypeTime="QUY" returns individual quarterly figures (not cumulative).
  - pageSize=100 fetches all quarters in one call (typical depth: 40-85 quarters).
"""

import time

import pandas as pd
import requests

_BASE = "https://apiweb.cafef.vn/api/v1/BCTC/GetReportSummary"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Referer": "https://cafef.vn/",
}

# Profit codes in priority order:
#   KQKD_13 = standard (non-bank, bank)
#   KQKD_10 = securities brokers (SSI, BSR etc. — shorter income template)
_NET_PROFIT_CODES = ["KQKD_13", "KQKD_10"]


def _fetch(symbol: str, report_type: str) -> list[dict]:
    """Fetch all quarterly periods for a report type in a single request."""
    r = requests.get(
        _BASE,
        params={
            "symbol": symbol.upper(),
            "pageIndex": 1,
            "pageSize": 100,
            "reportType": report_type,
            "TypeTime": "QUY",
        },
        headers=_HEADERS,
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    if not data.get("isSuccess"):
        raise ValueError(f"[cafef] API returned isSuccess=false for {symbol}/{report_type}")

    sections = data.get("value", {}).get("data", [])
    if not sections:
        return []
    return sections[0].get("data", [])


def _extract_code(quarter_data: dict, code: str) -> float | None:
    for item in quarter_data.get("data", []):
        if item["code"] == code:
            v = item.get("value")
            return float(v) if v is not None else None
    return None


def _extract_first(quarter_data: dict, codes: list[str]) -> float | None:
    for code in codes:
        v = _extract_code(quarter_data, code)
        if v is not None:
            return v
    return None


def get_net_profit(symbol: str) -> pd.DataFrame:
    """
    Fetch quarterly net profit after tax from CafeF.
    Returns DataFrame with columns: year (int), quarter (int), net_profit (float, VND).
    """
    quarters = _fetch(symbol, "KQKD")
    if not quarters:
        raise ValueError(f"[cafef] No income statement data for {symbol}")

    records = []
    for q in quarters:
        year = int(q["year"])
        quarter = int(q["quater"])
        profit = _extract_first(q, _NET_PROFIT_CODES)
        if profit is not None:
            records.append({"year": year, "quarter": quarter, "net_profit": profit})

    if not records:
        raise ValueError(f"[cafef] No net profit rows found for {symbol} (tried: {_NET_PROFIT_CODES})")

    return (
        pd.DataFrame(records)
        .sort_values(["year", "quarter"])
        .reset_index(drop=True)
    )



if __name__ == "__main__":
    for sym in ["FPT", "ACB", "VNM"]:
        print(f"\n=== {sym} ===")
        p = get_net_profit(sym)
        print(f"  Net profit: {len(p)} quarters, {p.iloc[0].year}-Q{p.iloc[0].quarter} → {p.iloc[-1].year}-Q{p.iloc[-1].quarter}")
        print(p.tail(4).to_string(index=False))
        time.sleep(0.5)
