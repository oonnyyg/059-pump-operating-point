"""组合曲线构造与工况点求解。"""

from __future__ import annotations

from dataclasses import dataclass

from .curve import PumpCurve
from .errors import InputError
from .plans import Plan

RHO = 1000.0
GRAVITY = 9.80665

STATUS_OK = "ok"
STATUS_NO_FLOW = "no_flow"
STATUS_OUT_OF_RANGE = "out_of_range"


@dataclass(frozen=True)
class Result:
    """单个方案的计算结果；失败时数值字段为 None。"""

    name: str
    status: str
    flow: float | None = None
    head: float | None = None
    efficiency: float | None = None
    input_power_kw: float | None = None
    energy_kwh: float | None = None


def combined_curve(curve: PumpCurve, plan: Plan) -> tuple[list[float], list[float]]:
    """按转速比缩放并组合串并联曲线，返回 (总流量, 总扬程) 采样点。"""
    ratio = plan.speed_ratio
    scaled_q = [q * ratio for q in curve.flows]
    scaled_h = [h * ratio * ratio for h in curve.heads]
    if plan.arrangement == "series":
        return scaled_q, [h * plan.pumps for h in scaled_h]
    return [q * plan.pumps for q in scaled_q], scaled_h


def _intersect(
    qs: list[float], hs: list[float], static_head: float, resistance: float
) -> float:
    """求组合曲线与管路曲线的唯一交点流量（分段线性对抛物线）。"""
    for i in range(1, len(qs)):
        q0, q1 = qs[i - 1], qs[i]
        f0 = hs[i - 1] - (static_head + resistance * q0 * q0)
        f1 = hs[i] - (static_head + resistance * q1 * q1)
        if f0 == 0.0:
            return q0
        if f0 * f1 > 0.0:
            continue
        slope = (hs[i] - hs[i - 1]) / (q1 - q0)
        a = resistance
        b = -slope
        c = static_head - hs[i - 1] + slope * q0
        if a == 0.0:
            root = -c / b
        else:
            sqrt_disc = (b * b - 4.0 * a * c) ** 0.5
            candidates = [(-b + sqrt_disc) / (2.0 * a), (-b - sqrt_disc) / (2.0 * a)]
            root = next(q for q in candidates if q0 - 1e-12 <= q <= q1 + 1e-12)
        return min(max(root, q0), q1)
    raise InputError("未找到交点")


def evaluate(curve: PumpCurve, plan: Plan) -> Result:
    """计算单个方案的工况点、功率与耗能。"""
    qs, hs = combined_curve(curve, plan)
    if plan.static_head >= hs[0]:
        return Result(name=plan.name, status=STATUS_NO_FLOW)
    system_at_max = plan.static_head + plan.resistance * qs[-1] * qs[-1]
    if hs[-1] > system_at_max:
        return Result(name=plan.name, status=STATUS_OUT_OF_RANGE)
    flow = _intersect(qs, hs, plan.static_head, plan.resistance)
    head = plan.static_head + plan.resistance * flow * flow
    if plan.arrangement == "series":
        pump_flow_scaled = flow
    else:
        pump_flow_scaled = flow / plan.pumps
    base_flow = pump_flow_scaled / plan.speed_ratio
    efficiency = curve.efficiency_at(base_flow)
    hydraulic_w = RHO * GRAVITY * flow * head
    input_kw = hydraulic_w / efficiency / 1000.0
    energy_kwh = input_kw * plan.hours
    return Result(
        name=plan.name,
        status=STATUS_OK,
        flow=flow,
        head=head,
        efficiency=efficiency,
        input_power_kw=input_kw,
        energy_kwh=energy_kwh,
    )


def evaluate_all(curve: PumpCurve, plans: list[Plan]) -> list[Result]:
    """计算全部方案；成功方案按输入功率再按名称升序，失败方案保留状态排后。"""
    results = [evaluate(curve, plan) for plan in plans]
    ok = [r for r in results if r.status == STATUS_OK]
    failed = [r for r in results if r.status != STATUS_OK]
    ok.sort(key=lambda r: (r.input_power_kw, r.name))
    failed.sort(key=lambda r: r.name)
    return ok + failed
