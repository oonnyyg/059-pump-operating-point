"""运行方案的读取与校验。"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass

from .errors import InputError

ARRANGEMENTS = ("series", "parallel")


@dataclass(frozen=True)
class Plan:
    """一个运行方案：同型泵按串联或并联组合运行。"""

    name: str
    pumps: int
    speed_ratio: float
    arrangement: str
    static_head: float
    resistance: float
    hours: float


def _finite_number(value: object, what: str) -> float:
    if value is None:
        raise InputError(f"{what} 缺失")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InputError(f"{what} 不是数值: {value!r}")
    result = float(value)
    if not math.isfinite(result):
        raise InputError(f"{what} 不是有限数: {value!r}")
    return result


def _nonnegative(value: object, what: str) -> float:
    result = _finite_number(value, what)
    if result < 0.0:
        raise InputError(f"{what} 必须非负: {value!r}")
    return result


def _parse_plan(raw: object, index: int) -> Plan:
    where = f"第{index}个方案"
    if not isinstance(raw, dict):
        raise InputError(f"{where} 必须是对象")
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise InputError(f"{where} 的 name 缺失或不是非空字符串")
    label = f"方案 {name!r}"
    pumps = raw.get("pumps")
    if isinstance(pumps, bool) or not isinstance(pumps, int) or pumps < 1:
        raise InputError(f"{label} 的 pumps 必须是正整数")
    speed = _finite_number(raw.get("speed_ratio"), f"{label} 的 speed_ratio")
    if speed <= 0.0:
        raise InputError(f"{label} 的 speed_ratio 必须为正")
    arrangement = raw.get("arrangement")
    if arrangement not in ARRANGEMENTS:
        raise InputError(f"{label} 的 arrangement 必须是 series 或 parallel")
    return Plan(
        name=name,
        pumps=pumps,
        speed_ratio=speed,
        arrangement=arrangement,
        static_head=_nonnegative(raw.get("static_head"), f"{label} 的 static_head"),
        resistance=_nonnegative(raw.get("resistance"), f"{label} 的 resistance"),
        hours=_nonnegative(raw.get("hours"), f"{label} 的 hours"),
    )


def load_plans(path: str) -> list[Plan]:
    """从 JSON 读取方案列表，方案名称必须唯一。"""
    with open(path, encoding="utf-8") as fh:
        try:
            raw = json.load(fh)
        except json.JSONDecodeError as exc:
            raise InputError(f"方案 JSON 解析失败: {exc}") from exc
    if isinstance(raw, dict) and "plans" in raw:
        raw = raw["plans"]
    if not isinstance(raw, list) or not raw:
        raise InputError("方案 JSON 必须是非空数组")
    plans = [_parse_plan(item, i + 1) for i, item in enumerate(raw)]
    names = [plan.name for plan in plans]
    if len(set(names)) != len(names):
        raise InputError("方案名称必须唯一")
    return plans
