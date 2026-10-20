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

---

## 4. No free float — market cap overstates investable size (HIGH IMPACT)

**What's wrong:**  
`pe_ratios.total_market_cap` counts every issued share. It is not adjusted for
free float, so it includes shares that never reach the market: state holdings,
founder and family stakes, strategic blocks locked by agreement.

**Root cause:**  
Free-float ratios are not in any source currently collected. vnstock's free tier
does not expose them, and they are not derivable from the balance sheet — the
distinction is about *who holds* the shares, not how many exist.

**Impact:**  
Anything that ranks or filters by size is partly ranking by *who is not selling*.
In this market that is not a rounding error: several VN30 names are majority
state-owned, so their investable size is a fraction of their headline size. Two
companies with the same total capitalisation can differ several-fold in the
capital an outside investor can actually deploy, and in liquidity.

This is what stopped the `portfolio/` strand — see `portfolio/CONCLUSIONS.md`.
Market cap was standing in for company quality, and without free float it is not
even a reliable measure of size.

**Most affected:**  
State-linked large caps — VCB, BID, CTG, GAS, and the VN30 aggregate that
includes them.

**Resolution options:**  
- A provider that publishes free-float ratios (FiinPro, or HOSE's own index
  methodology files, which carry free-float factors for index members).
- HOSE index review announcements list the free-float factor per constituent at
  each review; those are point-in-time by construction, which is the right shape.
- Failing both, drop size as a proxy rather than continue tuning against it.

---

## 5. Profit is used from the quarter-end, not from publication (HIGH IMPACT)

**What's wrong:**  
TTM profit switches to a new quarter on that quarter's last day (30/06 for Q2).
The report itself arrives weeks later — typically late July for Q2. So every
P/E between the quarter-end and the publication date uses a figure nobody had
on that date.

**Root cause:**  
No publication dates are collected; the quarter-end is the only date each
quarter carries. Since the fix that recomputes P/E when a profit quarter
arrives late (sync.py feeds the arrival back from the quarter-end), the recent
tail follows the same convention as the rest of history — before it, the
stretch between quarter-end and arrival was accidentally point-in-time.

**Impact:**  
Look-ahead of roughly a month after every quarter-end, across the whole series.
P/E and anything built on it (zones, range_stats, signals, backtests) can react
to an earnings change before the market could have. A backtest that trades on
P/E is shown that quarter's result early — it is a view of the future from the
moment of decision, not a view the decision could have had.

**Resolution options:**  
- Use profit from quarter-end + a fixed lag (the reporting deadline, ~30–45
  days) instead of the quarter-end. Simple, conservative, point-in-time.
- Collect real publication dates per report and switch on those.
- Until then, treat any edge measured within ~45 days after a quarter-end as
  suspect.
