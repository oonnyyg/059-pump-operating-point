"""Operating-point solver: affinity scaling, series/parallel combination, power."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .curve import PumpCurve
from .scheme import Scheme

RHO = 1000.0          # kg/m^3
GRAVITY = 9.80665     # m/s^2

STATUS_OK = "ok"
STATUS_NO_FLOW = "no_flow"
STATUS_OUT_OF_RANGE = "out_of_range"


@dataclass(frozen=True)
class OperatingPoint:
    name: str
    status: str
    pump_count: int
    connection: str
    speed_ratio: float
    static_head_m: float
    resistance_s2m5: float
    hours: float
    total_flow_m3s: float | None
    total_head_m: float | None
    per_pump_flow_m3s: float | None
    efficiency: float | None
    hydraulic_power_w: float | None
    input_power_w: float | None
    energy_kwh: float | None


def _combined_knots(curve: PumpCurve, scheme: Scheme) -> list[tuple[float, float]]:
    """Knots (total flow, combined head) after scaling and connection."""
    r = scheme.speed_ratio
    n = scheme.pump_count
    knots: list[tuple[float, float]] = []
    for q0, h0 in zip(curve.flows, curve.heads):
        if scheme.connection == "series":
            q_total = r * q0
            h_total = n * r * r * h0
        else:
            q_total = n * r * q0
            h_total = r * r * h0
        knots.append((q_total, h_total))
    return knots


def _piecewise_head(knots: list[tuple[float, float]], q: float) -> float:
    for i in range(len(knots) - 1):
        q0, h0 = knots[i]
        q1, h1 = knots[i + 1]
        if q <= q1:
            t = (q - q0) / (q1 - q0)
            return h0 + t * (h1 - h0)
    return knots[-1][1]


def _solve_intersection(
    knots: list[tuple[float, float]], static_head: float, resistance: float
) -> float | None:
    """Return total flow at the unique intersection, or None if beyond range."""

    def diff(q: float) -> float:
        return _piecewise_head(knots, q) - static_head - resistance * q * q

    q_max = knots[-1][0]
    if diff(q_max) > 0.0:
        return None

    for i in range(len(knots) - 1):
        q0, h0 = knots[i]
        q1, h1 = knots[i + 1]
        d0 = diff(q0)
        d1 = diff(q1)
        if d1 > 0.0:
            continue
        if d0 == 0.0:
            return q0
        lo, hi, f_lo, f_hi = q0, q1, d0, d1
        for _ in range(200):
            mid = 0.5 * (lo + hi)
            slope = (h1 - h0) / (q1 - q0)
            f_mid = h0 + slope * (mid - q0) - static_head - resistance * mid * mid
            if f_mid > 0.0:
                lo, f_lo = mid, f_mid
            else:
                hi, f_hi = mid, f_mid
        root = 0.5 * (lo + hi)
        if abs(f_lo - f_hi) > 0.0:
            root = (lo * f_hi - hi * f_lo) / (f_hi - f_lo)
        return root
    return None


def analyze_scheme(curve: PumpCurve, scheme: Scheme) -> OperatingPoint:
    knots = _combined_knots(curve, scheme)
    base = OperatingPoint(
        name=scheme.name,
        status="",
        pump_count=scheme.pump_count,
        connection=scheme.connection,
        speed_ratio=scheme.speed_ratio,
        static_head_m=scheme.static_head_m,
        resistance_s2m5=scheme.resistance_s2m5,
        hours=scheme.hours,
        total_flow_m3s=None,
        total_head_m=None,
        per_pump_flow_m3s=None,
        efficiency=None,
        hydraulic_power_w=None,
        input_power_w=None,
        energy_kwh=None,
    )

    shutoff = knots[0][1]
    if scheme.static_head_m >= shutoff:
        return OperatingPoint(**{**base.__dict__, "status": STATUS_NO_FLOW})

    q_total = _solve_intersection(knots, scheme.static_head_m, scheme.resistance_s2m5)
    if q_total is None:
        return OperatingPoint(**{**base.__dict__, "status": STATUS_OUT_OF_RANGE})

    h_total = scheme.static_head_m + scheme.resistance_s2m5 * q_total * q_total

    n = scheme.pump_count
    if scheme.connection == "series":
        q_scaled_per_pump = q_total
    else:
        q_scaled_per_pump = q_total / n
    q_pre_scale = q_scaled_per_pump / scheme.speed_ratio
    efficiency = curve.efficiency_at(q_pre_scale)

    hydraulic_power = RHO * GRAVITY * h_total * q_total
    input_power = hydraulic_power / efficiency
    energy_kwh = input_power / 1000.0 * scheme.hours

    values = {
        "status": STATUS_OK,
        "total_flow_m3s": q_total,
        "total_head_m": h_total,
        "per_pump_flow_m3s": q_scaled_per_pump,
        "efficiency": efficiency,
        "hydraulic_power_w": hydraulic_power,
        "input_power_w": input_power,
        "energy_kwh": energy_kwh,
    }
    return OperatingPoint(**{**base.__dict__, **values})
