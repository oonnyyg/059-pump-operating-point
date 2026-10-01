"""Single-pump performance curve: loading, validation, piecewise-linear interpolation."""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass


class CurveError(ValueError):
    """Raised when the pump performance curve is invalid."""


def _finite_float(value, what: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise CurveError(f"{what} 不是数值: {value!r}") from exc
    if not math.isfinite(number):
        raise CurveError(f"{what} 必须为有限数: {value!r}")
    return number


@dataclass(frozen=True)
class PumpCurve:
    """Piecewise-linear single-pump curve Q -> (H, eta).

    Q starts at zero and is strictly increasing; head is strictly
    decreasing; efficiency satisfies 0 < eta <= 1. No extrapolation.
    """

    flows: tuple[float, ...]
    heads: tuple[float, ...]
    effs: tuple[float, ...]

    @property
    def q_min(self) -> float:
        return self.flows[0]

    @property
    def q_max(self) -> float:
        return self.flows[-1]

    @property
    def shutoff_head(self) -> float:
        return self.heads[0]

    def _bracket(self, q: float) -> tuple[int, int]:
        if q < self.flows[0] or q > self.flows[-1]:
            raise CurveError(f"流量 {q} 超出曲线范围，禁止外推")
        lo, hi = 0, len(self.flows) - 1
        if q == self.flows[-1]:
            return hi - 1, hi
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if q < self.flows[mid]:
                hi = mid
            else:
                lo = mid
        return lo, hi

    def _fraction(self, q: float, i: int, j: int) -> float:
        return (q - self.flows[i]) / (self.flows[j] - self.flows[i])

    def head_at(self, q: float) -> float:
        i, j = self._bracket(q)
        t = self._fraction(q, i, j)
        return self.heads[i] + t * (self.heads[j] - self.heads[i])

    def efficiency_at(self, q: float) -> float:
        i, j = self._bracket(q)
        t = self._fraction(q, i, j)
        return self.effs[i] + t * (self.effs[j] - self.effs[i])

    def q_at_head(self, head: float) -> float:
        """Inverse of the strictly-decreasing head curve (no extrapolation)."""
        if head > self.heads[0] or head < self.heads[-1]:
            raise CurveError(f"扬程 {head} 超出曲线范围，禁止外推")
        i, j = 0, len(self.flows) - 1
        if head == self.heads[0]:
            return self.flows[0]
        if head == self.heads[-1]:
            return self.flows[-1]
        while j - i > 1:
            mid = (i + j) // 2
            if self.heads[mid] >= head:
                i = mid
            else:
                j = mid
        t = (self.heads[i] - head) / (self.heads[i] - self.heads[j])
        return self.flows[i] + t * (self.flows[j] - self.flows[i])


def load_curve_csv(path: str) -> PumpCurve:
    """Load a curve CSV with columns flow_m3s, head_m, efficiency."""
    rows: list[tuple[float, float, float]] = []
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        required = ("flow_m3s", "head_m", "efficiency")
        if reader.fieldnames is None or any(c not in reader.fieldnames for c in required):
            raise CurveError(f"曲线 CSV 必须包含列 {required}")
        for line_no, raw in enumerate(reader, start=2):
            if any(raw.get(c) is None or str(raw.get(c)).strip() == "" for c in required):
                raise CurveError(f"第 {line_no} 行存在缺失值")
            q = _finite_float(raw["flow_m3s"], f"第 {line_no} 行流量")
            h = _finite_float(raw["head_m"], f"第 {line_no} 行扬程")
            e = _finite_float(raw["efficiency"], f"第 {line_no} 行效率")
            rows.append((q, h, e))

    if len(rows) < 2:
        raise CurveError("性能曲线至少需要两个采样点")

    flows, heads, effs = (tuple(col) for col in zip(*rows))
    if flows[0] != 0.0:
        raise CurveError("首点流量必须为零")
    for k in range(1, len(flows)):
        if flows[k] <= flows[k - 1]:
            raise CurveError("流量必须从零严格递增")
    for k in range(1, len(heads)):
        if heads[k] >= heads[k - 1]:
            raise CurveError("扬程必须严格递减")
    for k, head in enumerate(heads):
        if head <= 0:
            raise CurveError(f"第 {k + 1} 个采样点扬程必须为正")
    for k, eff in enumerate(effs):
        if not (0.0 < eff <= 1.0):
            raise CurveError(f"第 {k + 1} 个采样点效率必须满足 0 < eta <= 1")

    return PumpCurve(flows, heads, effs)
