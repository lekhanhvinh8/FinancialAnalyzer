"""
CafeF data source adapter.

Scrapes https://apiweb.cafef.vn — the same JSON API the cafef.vn financial
pages call in the browser. No login required; no rate-limit headers observed.

Public interface:
    get_net_profit(symbol, raw_dir=None) -> DataFrame
        Columns: year, quarter, kqkd_14, kqkd_13, kqkd_10  (all in VND, NULL if absent)
    get_annual_net_profit(symbol, raw_dir=None) -> DataFrame
        Same columns, one row per fiscal year, quarter = 0.
    load_raw_net_profit(symbol, raw_dir) -> DataFrame
        Quarterly, read from the saved raw JSON instead of the API.

Prices and shares are NOT available here — use sources.vnstock for those.

Notes:
  - KQKD_14 = profit after tax attributable to parent-company shareholders (correct for P/E).
  - KQKD_13 = total consolidated profit after tax (includes minority interest).
  - KQKD_10 = used by securities brokers (SSI, VCI, HCM, VIX, VND) whose template
               lacks KQKD_14/13.
  - All three are stored as separate columns; the caller decides which to use.
  - TypeTime="QUY" returns individual quarterly figures (not cumulative YTD).
  - pageSize=100 fetches all quarters in one call (typical depth: 40-85 quarters).
  - raw_dir: if provided, raw JSON responses are saved to <raw_dir>/<SYMBOL>_KQKD.json
    for auditing and offline replay.
"""

import json
import time
from pathlib import Path

import pandas as pd
import requests

_BASE = "https://apiweb.cafef.vn/api/v1/BCTC/GetReportSummary"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Referer": "https://cafef.vn/",
}

_PROFIT_CODES = ["KQKD_14", "KQKD_13", "KQKD_10"]


def _fetch(symbol: str, report_type: str, raw_dir: Path | None = None,
           type_time: str = "QUY") -> list[dict]:
    """Fetch all periods (QUY = quarters, NAM = years) for a report type in one request."""
    r = requests.get(
        _BASE,
        params={
            "symbol":     symbol.upper(),
            "pageIndex":  1,
            "pageSize":   100,
            "reportType": report_type,
            "TypeTime":   type_time,
        },
        headers=_HEADERS,
        timeout=15,
    )
    r.raise_for_status()
    payload = r.json()

    if raw_dir is not None:
        raw_dir = Path(raw_dir)
        raw_dir.mkdir(parents=True, exist_ok=True)
        suffix = "" if type_time == "QUY" else f"_{type_time}"
        out = raw_dir / f"{symbol.upper()}_{report_type}{suffix}.json"
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if not payload.get("isSuccess"):
        raise ValueError(f"[cafef] API returned isSuccess=false for {symbol}/{report_type}")

    sections = payload.get("value", {}).get("data", [])
    if not sections:
        return []
    return sections[0].get("data", [])


def _extract_code(quarter_data: dict, code: str) -> float | None:
    for item in quarter_data.get("data", []):
        if item["code"] == code:
            v = item.get("value")
            return float(v) if v is not None else None
    return None


def get_net_profit(symbol: str, raw_dir: str | Path | None = None) -> pd.DataFrame:
    """
    Fetch quarterly net profit after tax from CafeF.

    Returns DataFrame with columns:
        year (int), quarter (int), kqkd_14, kqkd_13, kqkd_10  (float VND or None)

    All three profit codes are stored; the caller decides which to use for P/E.
    raw_dir: folder to save raw JSON responses (created if missing).
    """
    quarters = _fetch(symbol, "KQKD", raw_dir=raw_dir)
    if not quarters:
        raise ValueError(f"[cafef] No income statement data for {symbol}")
    return _profit_frame(symbol, quarters)


def get_annual_net_profit(symbol: str, raw_dir: str | Path | None = None) -> pd.DataFrame:
    """Full-year net profit, same columns as get_net_profit with quarter = 0."""
    years = _fetch(symbol, "KQKD", raw_dir=raw_dir, type_time="NAM")
    return _profit_frame(symbol, years) if years else pd.DataFrame()


def load_raw_net_profit(symbol: str, raw_dir: str | Path) -> pd.DataFrame:
    """get_net_profit from the raw JSON a previous fetch saved; empty if none."""
    path = Path(raw_dir) / f"{symbol.upper()}_KQKD.json"
    if not path.exists():
        return pd.DataFrame()
    sections = json.loads(path.read_text(encoding="utf-8")).get("value", {}).get("data", [])
    quarters = sections[0].get("data", []) if sections else []
    return _profit_frame(symbol, quarters) if quarters else pd.DataFrame()


def _profit_frame(symbol: str, quarters: list[dict]) -> pd.DataFrame:
    records = []
    for q in quarters:
        year    = int(q["year"])
        quarter = int(q.get("quater") or 0)   # 0 on a full-year row
        row = {
            "year":     year,
            "quarter":  quarter,
            "kqkd_14":  _extract_code(q, "KQKD_14"),
            "kqkd_13":  _extract_code(q, "KQKD_13"),
            "kqkd_10":  _extract_code(q, "KQKD_10"),
        }
        if any(row[c] is not None for c in ("kqkd_14", "kqkd_13", "kqkd_10")):
            records.append(row)

    if not records:
        raise ValueError(f"[cafef] No net profit rows found for {symbol} (tried: {_PROFIT_CODES})")

    return (
        pd.DataFrame(records)
        .sort_values(["year", "quarter"])
        .reset_index(drop=True)
    )


if __name__ == "__main__":
    for sym in ["FPT", "ACB", "SSI"]:
        print(f"\n=== {sym} ===")
        p = get_net_profit(sym, raw_dir="data/raw/cafef")
        print(f"  {len(p)} quarters, {p.iloc[0].year}-Q{p.iloc[0].quarter} -> {p.iloc[-1].year}-Q{p.iloc[-1].quarter}")
        print(p.tail(4)[["year","quarter","kqkd_14","kqkd_13","kqkd_10"]].to_string(index=False))
        time.sleep(0.5)
