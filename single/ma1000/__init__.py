"""
The MA1000 method: buy under the 1000-bar moving average, sell above it.

The project's oldest strategy. Split out of loose modules at single/main.py and
single/run_sweep.py so that every method under single/ is a package and the
files left at single/ are the ones every method shares.

    run_one.py    one symbol end to end, with a heatmap sweep
    run_sweep.py  BuyMAStrategy over localRangeDays x decreasePercent, to Excel
"""
