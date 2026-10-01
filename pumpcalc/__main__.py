"""命令行入口：python -m pumpcalc CURVE.csv PLANS.json OUT.csv OUT.json"""

from __future__ import annotations

import csv
import io
import json
import os
import sys

from .curve import load_curve
from .errors import InputError
from .plans import load_plans
from .solve import evaluate_all

CSV_FIELDS = ["name", "status", "flow", "head", "efficiency", "input_power_kw", "energy_kwh"]


def _render_csv(results) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    for result in results:
        row = {"name": result.name, "status": result.status}
        for field in CSV_FIELDS[2:]:
            value = getattr(result, field)
            row[field] = "" if value is None else repr(value)
        writer.writerow(row)
    return buffer.getvalue()


def _render_json(results) -> str:
    payload = {
        "plans": [
            {
                "name": r.name,
                "status": r.status,
                "flow": r.flow,
                "head": r.head,
                "efficiency": r.efficiency,
                "input_power_kw": r.input_power_kw,
                "energy_kwh": r.energy_kwh,
            }
            for r in results
        ]
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _write_atomic(path: str, text: str) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 4:
        print("用法: python -m pumpcalc CURVE.csv PLANS.json OUT.csv OUT.json", file=sys.stderr)
        return 2
    curve_path, plans_path, out_csv, out_json = args
    try:
        curve = load_curve(curve_path)
        plans = load_plans(plans_path)
        results = evaluate_all(curve, plans)
    except (InputError, OSError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    _write_atomic(out_csv, _render_csv(results))
    _write_atomic(out_json, _render_json(results))
    print(f"已输出 {out_csv} 与 {out_json}，共 {len(results)} 个方案")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
