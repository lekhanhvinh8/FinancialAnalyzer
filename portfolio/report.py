"""
Text report comparing one plan against the baseline.

Deliberately plain and deliberately separate from the engine: the engine returns
numbers, this decides how to show them, and neither should have to change when
the other does.

WHAT THE COMPARISON IS NOT

  The baseline is equal-weight DCA over the SAME universe and calendar. It is not
  buy-and-hold of an index, and it is not the single-symbol runner's results
  added up. A difference printed here does not belong in the same table as one
  from there — different question, different denominator.
"""


def compare(result: dict, baseline: dict, top_n: int = 15) -> str:
    lines = []
    w = 22

    def row(label, a, b, fmt="{:>16,.0f}"):
        lines.append(f"{label:<{w}}{fmt.format(a):>18}{fmt.format(b):>20}")

    lines.append(f"{'':<{w}}{'plan':>18}{'equal-weight DCA':>20}")
    lines.append("-" * (w + 38))

    for label, key in (("months", "months"),
                       ("symbols traded", "symbols_traded"),
                       ("symbols held", "symbols_held"),
                       ("buys", "buys"),
                       ("sells", "sells"),
                       ("reinvests", "reinvests")):
        row(label, result[key], baseline[key], "{:>16,}")

    lines.append("")
    for label, key in (("invested", "invested"),
                       ("final value", "final"),
                       ("holdings", "holdings_value"),
                       ("reserve", "reserve"),
                       ("idle cash", "idle_cash"),
                       ("interest earned", "interest_paid")):
        row(label, result[key], baseline[key])

    lines.append("-" * (w + 38))
    a, b = result["growth_%"], baseline["growth_%"]
    lines.append(f"{'growth':<{w}}{a:>17.2f}%{b:>19.2f}%")
    lines.append(f"{'difference':<{w}}{a - b:>17.2f}%")

    lines.append("")
    lines.append(f"Top {top_n} holdings")
    lines.append(f"{'symbol':<8}{'weight':>9}{'value':>18}{'shares':>12}"
                 f"{'buys':>7}{'sells':>7}")
    for symbol, h in list(result["holdings"].items())[:top_n]:
        lines.append(f"{symbol:<8}{h['weight_%']:>8.2f}%{h['value']:>18,.0f}"
                     f"{h['shares']:>12,.0f}{h['buys']:>7}{h['sells']:>7}")

    held = len(result["holdings"])
    if held > top_n:
        lines.append(f"... and {held - top_n} more")
    return "\n".join(lines)
