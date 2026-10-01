"""单泵性能曲线的读取、校验与分段线性插值。"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass

from .errors import InputError


@dataclass(frozen=True)
class PumpCurve:
    """单泵性能曲线：流量(m3/s)、扬程(m)、效率(-)。"""

    flows: tuple[float, ...]
    heads: tuple[float, ...]
    efficiencies: tuple[float, ...]

    def interpolate(self, values: tuple[float, ...], flow: float) -> float:
        """在曲线上按流量做分段线性插值，禁止外推。"""
        if flow < self.flows[0] or flow > self.flows[-1]:
            raise InputError(f"流量 {flow} 超出曲线范围，禁止外推")
        return _interp(self.flows, values, flow)

    def head_at(self, flow: float) -> float:
        return self.interpolate(self.heads, flow)

    def efficiency_at(self, flow: float) -> float:
        return self.interpolate(self.efficiencies, flow)


def _interp(xs: tuple[float, ...], ys: tuple[float, ...], x: float) -> float:
    lo, hi = 0, len(xs) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if xs[mid] <= x:
            lo = mid
        else:
            hi = mid
    x0, x1 = xs[lo], xs[hi]
    if x1 == x0:
        return ys[lo]
    t = (x - x0) / (x1 - x0)
    return ys[lo] + t * (ys[hi] - ys[lo])


def _parse_finite(text: str, what: str) -> float:
    if text is None or text.strip() == "":
        raise InputError(f"{what} 缺失")
    try:
        value = float(text)
    except ValueError as exc:
        raise InputError(f"{what} 不是数值: {text!r}") from exc
    if not math.isfinite(value):
        raise InputError(f"{what} 不是有限数: {text!r}")
    return value


def load_curve(path: str) -> PumpCurve:
    """从 CSV 读取曲线，表头需含 flow,head,efficiency 三列。"""
    flows: list[float] = []
    heads: list[float] = []
    effs: list[float] = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        required = {"flow", "head", "efficiency"}
        if reader.fieldnames is None or not required.issubset(
            {name.strip() for name in reader.fieldnames}
        ):
            raise InputError("曲线 CSV 表头必须包含 flow,head,efficiency")
        for row_no, row in enumerate(reader, start=2):
            flows.append(_parse_finite(row.get("flow", ""), f"第{row_no}行 flow"))
            heads.append(_parse_finite(row.get("head", ""), f"第{row_no}行 head"))
            effs.append(
                _parse_finite(row.get("efficiency", ""), f"第{row_no}行 efficiency")
            )
    return build_curve(flows, heads, effs)


def build_curve(
    flows: list[float], heads: list[float], effs: list[float]
) -> PumpCurve:
    """校验并构造曲线：至少两点，流量从零严格递增，扬程为正且严格递减。"""
    if len(flows) < 2:
        raise InputError("曲线至少需要两个采样点")
    if not (len(flows) == len(heads) == len(effs)):
        raise InputError("曲线各列长度不一致")
    if flows[0] != 0.0:
        raise InputError("曲线流量必须从零开始")
    for i in range(1, len(flows)):
        if not flows[i] > flows[i - 1]:
            raise InputError("曲线流量必须严格递增")
    for i, head in enumerate(heads):
        if head <= 0.0:
            raise InputError(f"第{i + 1}个采样点扬程必须为正")
        if i and not head < heads[i - 1]:
            raise InputError("曲线扬程必须严格递减")
    for eff in effs:
        if not 0.0 < eff <= 1.0:
            raise InputError("效率必须大于零且不超过一")
    return PumpCurve(tuple(flows), tuple(heads), tuple(effs))
