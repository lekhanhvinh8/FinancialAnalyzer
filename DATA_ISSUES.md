# Known Data Quality Issues

## 1. Shares backfilled from oldest available quarter (HIGH IMPACT)

**What's wrong:**  
Historical shares (pre-2025) are approximated by propagating the oldest known share count backwards. The actual share count on any given historical date may have been different.

**Root cause:**  
vnstock free tier only provides the latest 4 quarters of balance sheet data (~2025-Q1 onward). CafeF balance sheet code `CDKT_32` ("Vốn đầu tư của chủ sở hữu") includes capital surplus — not usable for share count.

**Impact:**  
P/E is calculated as Σ(Price × Shares) / Σ(TTM Profit). If a company's share count was significantly lower in earlier years (e.g., before a large rights issue), the historical market cap — and therefore P/E — will be overstated for those dates.

**Most affected symbols:**  
Companies that have done large capital raises. Likely candidates: VPB, TCB, HDB, LPB (all grew rapidly post-2018 and issued significant new shares).

**Resolution options:**  
- Subscribe to vnstock paid tier or another provider (TCBS, SSI iBoard, Fireant Pro) that provides full historical quarterly balance sheets.
- Manually collect charter capital history from HOSE annual reports for the most affected symbols.

---

## 2. VN30 membership before 2012 not tracked (LOW IMPACT)

**What's wrong:**  
The `vn30_members` table is seeded from 7 review snapshots starting from the inaugural list (2012-01-01). Any index composition changes before 2012 are not recorded.

**Root cause:**  
Historical VN30 membership data before 2012 was not available at the time of seeding.

**Impact:**  
P/E calculation uses point-in-time membership. For dates before 2012 (no price data exists anyway), this is not a practical issue with current data.

**Resolution:**  
Not urgent — price data only goes back to 2014. Track down HOSE review announcements if coverage is extended further back.

---

## 3. Profit data sparse for recently listed companies (LOW IMPACT)

**What's wrong:**  
VPL (listed 2025-05) has only 18 quarters of profit history; SSB (listed 2021-03) has 36. For dates before their listing, these symbols contribute no data to the aggregate P/E.

**Root cause:**  
Companies that listed recently simply have less history.

**Impact:**  
Aggregate P/E for early dates is computed over fewer members, making it less representative of the full VN30. Member count column in `pe_history` reflects this.

**Resolution:**  
No fix needed — the calculation correctly excludes them before their listing date.
