"""Operating schemes: JSON loading and strict validation."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass


class SchemeError(ValueError):
    """Raised when the schemes document or a scheme is invalid."""


_NUMERIC_FIELDS = (
    "speed_ratio",
    "static_head_m",
    "resistance_s2m5",
    "hours",
)


@dataclass(frozen=True)
class Scheme:
    name: str
    pump_count: int
    connection: str  # "series" or "parallel"
    speed_ratio: float
    static_head_m: float
    resistance_s2m5: float
    hours: float


def _require_number(obj, field: str, *, positive: bool = False) -> float:
    if field not in obj or obj[field] is None:
        raise SchemeError(f"方案缺少字段 {field}")
    value = obj[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SchemeError(f"字段 {field} 必须为数值")
    number = float(value)
    if not math.isfinite(number):
        raise SchemeError(f"字段 {field} 必须为有限数")
    if positive:
        if number <= 0:
            raise SchemeError(f"字段 {field} 必须为正数")
    elif number < 0:
        raise SchemeError(f"字段 {field} 不可为负")
    return number


def _parse_scheme(obj, index: int) -> Scheme:
    if not isinstance(obj, dict):
        raise SchemeError(f"第 {index + 1} 个方案必须是对象")

    if "name" not in obj or obj["name"] is None:
        raise SchemeError(f"第 {index + 1} 个方案缺少 name")
    name = obj["name"]
    if not isinstance(name, str) or name == "":
        raise SchemeError(f"第 {index + 1} 个方案的 name 必须是非空字符串")

    if "pump_count" not in obj or obj["pump_count"] is None:
        raise SchemeError(f"方案 {name} 缺少 pump_count")
    pump_count = obj["pump_count"]
    if isinstance(pump_count, bool) or not isinstance(pump_count, int) or pump_count <= 0:
        raise SchemeError(f"方案 {name} 的 pump_count 必须为正整数")

    connection = obj.get("connection", "parallel")
    if connection not in ("series", "parallel"):
        raise SchemeError(f"方案 {name} 的 connection 必须是 series 或 parallel")

    values = {
        field: _require_number(
            obj,
            field,
            positive=(field == "speed_ratio"),
        )
        for field in _NUMERIC_FIELDS
    }

    return Scheme(
        name=name,
        pump_count=pump_count,
        connection=connection,
        **values,
    )


def load_schemes_json(path: str) -> list[Scheme]:
    with open(path, "r", encoding="utf-8-sig") as fh:
        try:
            data = json.load(fh)
        except json.JSONDecodeError as exc:
            raise SchemeError(f"方案 JSON 解析失败: {exc}") from exc

    if isinstance(data, dict) and "schemes" in data:
        data = data["schemes"]
    if not isinstance(data, list) or not data:
        raise SchemeError("方案文档必须是非空数组（或含 schemes 数组的对象）")

    schemes = [_parse_scheme(item, i) for i, item in enumerate(data)]

    names = [scheme.name for scheme in schemes]
    if len(set(names)) != len(names):
        raise SchemeError("方案名称必须唯一")
    return schemes
