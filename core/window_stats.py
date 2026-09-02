"""
The shape of a rolling-window statistic: what range_calc returns.

Moved out of single/models.py because core/range_calc.py produces these and
core may not import a strategy package. database.py reads them back too, so
they were never single/'s to own -- they describe a price series, not a wallet.
"""

from dataclasses import dataclass, field


@dataclass
class RangeDaysClose:
    localTop: float
    localAvg: float
    localBottom: float
    p25: float = 0.0
    median: float = 0.0
    p75: float = 0.0
    pe_top: float = 0.0
    pe_avg: float = 0.0
    pe_bottom: float = 0.0
    pe_p25: float = 0.0
    pe_median: float = 0.0
    pe_p75: float = 0.0

    def top(self, use_pe: bool = False) -> float:
        return self.pe_top if use_pe else self.localTop

    def avg(self, use_pe: bool = False) -> float:
        return self.pe_avg if use_pe else self.localAvg

    def bottom(self, use_pe: bool = False) -> float:
        return self.pe_bottom if use_pe else self.localBottom

    def pct25(self, use_pe: bool = False) -> float:
        return self.pe_p25 if use_pe else self.p25

    def pct50(self, use_pe: bool = False) -> float:
        return self.pe_median if use_pe else self.median

    def pct75(self, use_pe: bool = False) -> float:
        return self.pe_p75 if use_pe else self.p75


@dataclass
class IndexCloses:
    rangeDayCloses: dict[int, RangeDaysClose] = field(default_factory=dict)
