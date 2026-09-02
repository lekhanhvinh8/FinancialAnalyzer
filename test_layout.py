"""
The project's shape, asserted rather than described.

WHY THIS IS A TEST AND NOT A README

  Layout rules are the ones that rot silently. A module dropped in the wrong
  package still imports, still runs, and only shows up months later as "why is
  single/charts_breadth under single". Every rule below was broken at least once
  in this project and fixed by hand; asserting them is what stops the next one.

Run with:  python -m test_layout
"""

import importlib
import pkgutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Reading the market and the money ledger. No strategy may define its own.
CORE = "core"

# One package per method. A method decides; it does not define how to read
# prices or how a buy moves money.
METHODS = ["portfolio", "breadth",
           "single.ma1000", "single.median1000", "single.market_breadth"]

# Shared inside single/: used by more than one method there.
SINGLE_SHARED = {"engine", "models", "runner", "sweep", "strategies"}

# The money primitives. Written once, in core.ledger, after a second engine
# reimplemented them and got three accounting bugs in a row.
LEDGER = {"execute_buy", "execute_sell", "execute_reinvest", "CASH_EPSILON"}


def main() -> int:
    fails = []

    def check(cond, msg):
        if not cond:
            fails.append(msg)

    # ── every method package imports ────────────────────────────────────────
    for m in METHODS:
        try:
            importlib.import_module(m)
        except Exception as exc:
            fails.append(f"{m}: {type(exc).__name__}: {exc}")

    # ── single/ holds only what its methods share ───────────────────────────
    loose = {p.stem for p in (ROOT / "single").glob("*.py")
             if p.stem != "__init__"}
    extra = loose - SINGLE_SHARED
    check(not extra,
          f"single/ co module roi khong dung chung: {sorted(extra)} "
          f"-> chuyen vao package cua phuong phap")

    # ── each method package has a runner and a config ───────────────────────
    for m in METHODS:
        d = ROOT / Path(m.replace(".", "/"))
        names = {p.stem for p in d.glob("*.py")}
        check(bool(names & {"run", "run_all", "run_one", "run_sweep"}),
              f"{m}: khong co runner (run/run_all/run_one)")

    # ── nothing writes its own money code ───────────────────────────────────
    import core.ledger as ledger
    for fn in LEDGER:
        check(hasattr(ledger, fn), f"core.ledger thieu {fn}")

    for m in METHODS:
        d = ROOT / Path(m.replace(".", "/"))
        for f in d.glob("*.py"):
            src = f.read_text(encoding="utf-8")
            for fn in ("def execute_buy", "def execute_sell", "def execute_reinvest"):
                check(fn not in src,
                      f"{f.relative_to(ROOT)} tu dinh nghia {fn[4:]} "
                      f"-> phai goi core.ledger")

    # ── no method imports another method ────────────────────────────────────
    # Reports and chart helpers are the deliberate exception and are named here,
    # so a new cross-import has to be argued for rather than appearing.
    ALLOWED = {("single.market_breadth", "single.median1000"),   # the report
               ("single.market_breadth", "breadth")}             # add_signal_line
    for m in METHODS:
        d = ROOT / Path(m.replace(".", "/"))
        for f in d.glob("*.py"):
            src = f.read_text(encoding="utf-8")
            for other in METHODS:
                if other == m or (m, other) in ALLOWED:
                    continue
                top = other.split(".")[0]
                needle = f"from {other}" if "." in other else f"from {top} import"
                check(needle not in src,
                      f"{f.relative_to(ROOT)} import {other} "
                      f"-> hai phuong phap khong duoc phu thuoc nhau")

    # ── core does not import a method ───────────────────────────────────────
    for f in (ROOT / CORE).glob("*.py"):
        src = f.read_text(encoding="utf-8")
        for m in METHODS:
            check(f"import {m.split('.')[0]}" not in src.replace("import core", ""),
                  f"core/{f.name} import {m} -> core khong duoc biet chien luoc")

    # ── core imports nothing above it ───────────────────────────────────────
    # Broader than the method check: core must not reach into single/, syncs/ or
    # export/ either. range_calc lived in single/ while syncs/ imported it, so
    # the data layer depended on an investing method -- and moving it up
    # revealed a second such edge, core.range_calc needing single.models.
    ABOVE = ("single", "syncs", "export", "portfolio", "breadth")
    for f in (ROOT / CORE).glob("*.py"):
        src = f.read_text(encoding="utf-8")
        for pkg in ABOVE:
            for form in ("import " + pkg + chr(10), "from " + pkg + " import",
                         "from " + pkg + "."):
                check(form not in src,
                      f"core/{f.name} import {pkg} -> core la tang duoi cung")

    # ── syncs does not import a method ──────────────────────────────────────
    for f in (ROOT / "syncs").rglob("*.py"):
        if "__pycache__" in str(f):
            continue
        src = f.read_text(encoding="utf-8")
        for pkg in ("portfolio", "breadth"):
            check(f"from {pkg}" not in src
                  and ("import " + pkg + chr(10)) not in src,
                  f"{f.relative_to(ROOT)} import {pkg} -> tang du lieu khong "
                  f"duoc phu thuoc chien luoc")

    # ── the project root holds no utilities ─────────────────────────────────
    # progress.py sat here for a long time and three runners imported it from
    # the root while a fourth imported a second copy from core. A module at the
    # root is a module with no owner.
    ROOT_OK = {"database", "sync", "test_layout"}
    at_root = {p.stem for p in ROOT.glob("*.py")} - ROOT_OK
    check(not at_root,
          f"goc du an co module khong thuoc ve dau: {sorted(at_root)}")

    # ── one implementation per shared concern ───────────────────────────────
    # Same class name in two packages is fine when the packages are METHODS --
    # Plan and run_backtest mean different things in portfolio/ and breadth/.
    # It is not fine for infrastructure.
    for name in ("RunProgress", "RunAllProgress", "SyncProgress"):
        homes = [f for f in ROOT.rglob("*.py")
                 if "__pycache__" not in str(f)
                 and f"class {name}" in f.read_text(encoding="utf-8", errors="replace")]
        check(len(homes) == 1,
              f"{name} dinh nghia o {len(homes)} noi: "
              f"{[str(h.relative_to(ROOT)) for h in homes]}")

    # ── every test module is runnable ───────────────────────────────────────
    tests = sorted(p for p in ROOT.rglob("test_*.py")
                   if "__pycache__" not in str(p) and p != Path(__file__))
    check(len(tests) >= 4, f"chi thay {len(tests)} file test")

    if fails:
        print(f"LOI ({len(fails)}):")
        for f in fails:
            print("  -", f)
        return 1
    print(f"OK — {len(METHODS)} phuong phap, single/ chi con "
          f"{len(loose)} module dung chung, khong ai tu viet code tien, "
          f"{len(tests)} bo test")
    return 0


if __name__ == "__main__":
    sys.exit(main())
