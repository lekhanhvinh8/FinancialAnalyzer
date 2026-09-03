# multi_signal — what the three profiles measured

Measured 2026-09-03 on 52 symbols, every figure against the same DCA baseline on
the same evaluation window. `i` (the DCA arm) and `eb` (evaluated bars) were
checked identical across all runs before anything was compared: 0/52 differ.

## The result

**The basket beats the symbol's own price.**

| profile | All | Long (35) | Short (17) | median | beats DCA | buys | sells | reinv |
|---|---|---|---|---|---|---|---|---|
| `price` | +46.75 | +70.56 | −2.27 | +16.16 | 38/52 | 4171 | 119 | 204 |
| **`breadth`** | **+92.33** | **+130.32** | **+14.11** | **+19.77** | **44/52** | 4688 | 79 | 204 |
| `both_or` | +73.71 | +103.62 | +12.13 | +10.07 | 38/52 | 3815 | 43 | 526 |

Paired per symbol — the only valid comparison between two configurations:

```
breadth  -  price      mean +45.58   median +12.78   32/52   p = 0.063
both+OR  -  price      mean +26.96   median  +0.50   29/52   p = 0.244
both+OR  -  breadth    mean -18.62   median  -4.85   19/52   p = 0.982
```

`breadth` wins on every column and every subgroup. Read the **median**, not the
mean: +12.78 is what a typical symbol gains, while +45.58 is that number plus a
tail. The sign test at p = 0.063 is suggestive, not conclusive.

## What the advantage is, and is not

**It is not a bug.** Five independent checks, in the order they were run:

1. All three breadth lines recomputed from raw prices by separate code using
   only data dated ≤ the bar — matched the stored values to 0.01 on six sample
   days spanning 2016–2026.
2. The date→row join carries 0 wrong values and 0 collisions with an adjacent
   date, so no off-by-one.
3. **Placebo.** Reversing the signal in time preserves its distribution, its
   day-to-day persistence and its trade count (135 sells against the real 117),
   and changes only *when* it fires. Result: +94 becomes −52. Shuffling gives
   −35, a one-year lag −11. So the advantage is in the timing, not in the
   holding of cash — a strategy that merely deferred purchases would score the
   same backwards.
4. `price` carries three gates (`MIN_SIGNAL3`, `SELL_MIN_ZDEV`,
   `SELL_MIN_PELOG`) that `breadth` switches off, so the comparison could have
   been measuring the gates. `price_nogates` isolates them: worth +6 of the 45.
5. `median_prem` uses no market cap at all and scores within 2 points of
   `prem_cap`, so no defect in the cap data can be the source.

**It is smaller than the mean suggests, and concentrated.** The top 5 symbols
supply 62% of the total edge and the top 10 supply 83%. Four of the six largest
winners are brokers and banks — the highest-beta corner of this market, which is
what a market-timing signal should be expected to help most. The Short group
(17 symbols, under `LONG_HISTORY_BARS`) shows a median advantage of +1.53 over
`price`: 9/17, indistinguishable from a coin.

**Three limits no test here can remove.** The database holds zero delisted
symbols, so the basket is today's survivors projected backwards — which inflates
both profiles, and inflates the basket signal more, since the basket is
*composed of* the survivors. The window 2015–2026 contains one large drawdown,
and a market-timing signal is being scored on one observation of the thing it
exists to catch. And prices are retroactively adjusted, as is market cap: 27 of
59 symbols have an exactly constant implied share count over their whole
history, so `prem_cap`'s historical weights are today's weights, not the weights
that were true then.

## Which line, and which thresholds

**The three lines are indistinguishable.** `median_prem` +92.33, `prem_trim`
+90.14, `prem_cap` +94.18 — a 4-point spread on a base of 92, and the ranking by
median reverses the ranking by mean. `median_prem` ships because it is the
simplest and depends on no market-cap data.

**Sweeps found one real plateau and three traps.**

| parameter | worth | shape |
|---|---|---|
| `SELL_MIN_BREADTH` | +108 | flat 70–90; the peak at 95–100 is **one bar** |
| `BUY_MAX_BREADTH` | +1.1 | no structure; off is within noise of on |
| `REINVEST_MAX_BREADTH` | arm +159, gate ~0 | jagged; the gate sets dates, not counts |
| `REINVEST_TIMEOUT_DAYS` | — | **genuine plateau 400–1500**, median flat at +20.8 |

The sell peak at 95–100 is a trap worth naming: `prem_cap` crosses 100 in
exactly three episodes in eleven years, one of which is the single day
2022-04-06, the top before the crash. A threshold of 105 misses that one day and
the mean falls from +148 to +24. Any parameter chosen there is fitted to one
bar.

Nothing was adopted. Every threshold stays where it was, because the only flat
region found already contains the live value.

## Why the reinvest arm is AND

`both_or` was the one structural change tried, and it lost. OR takes reinvests
from 204 to 526 and costs 18.6 mean / 4.9 median against `breadth`.

The timeout sweep explains it and is the more useful finding: a 60-day valve
gives 9.91 reinvests per symbol and +21.4; a 400-day valve gives 3.39 and
+117.7. **Redeploying the reserve often is what destroys the result.** The arm
wants roughly two well-placed redeploys per symbol per decade, and AND is what
holds it there — it works as a rate limiter, not only as a condition.

`REINVEST_JOIN_OR` stays in the config as a switch, defaulting to False, so that
claim can be re-measured rather than believed.

## Reproducing any of this

```bash
python -m single.multi_signal.run_all --all --profile=price
python -m single.multi_signal.run_all --all --profile=breadth
python -m single.multi_signal.run_all --all --profile=both_or
python -m single.multi_signal.sweep_breadth --arm=sell --signal=prem_cap
python -m single.multi_signal.sweep_breadth --arm=timeout --signal=prem_cap
```

Three runs fit concurrently on eight cores at `--workers=3`.
