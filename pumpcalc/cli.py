"""Command-line entry: python -m pumpcalc CURVE_CSV SCHEMES_JSON OUT_CSV OUT_JSON."""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import tempfile

from .curve import CurveError, load_curve_csv
from .engine import STATUS_OK, OperatingPoint, analyze_scheme
from .scheme import SchemeError, load_schemes_json

CSV_FIELDS = (
    "name",
    "status",
    "pump_count",
    "connection",
    "speed_ratio",
    "static_head_m",
    "resistance_s2m5",
    "hours",
    "total_flow_m3s",
    "total_head_m",
    "per_pump_flow_m3s",
    "efficiency",
    "hydraulic_power_w",
    "input_power_w",
    "energy_kwh",
)

_RESULT_KEYS = (
    "total_flow_m3s",
    "total_head_m",
    "per_pump_flow_m3s",
    "efficiency",
    "hydraulic_power_w",
    "input_power_w",
    "energy_kwh",
)


def order_results(results: list[OperatingPoint]) -> list[OperatingPoint]:
    """Successes by input power then name; failures keep input order at the end."""
    ok = sorted(
        (r for r in results if r.status == STATUS_OK),
        key=lambda r: (r.input_power_w, r.name),
    )
    failed = [r for r in results if r.status != STATUS_OK]
    return ok + failed


def results_to_csv(results: list[OperatingPoint]) -> str:
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    for r in results:
        row = {key: getattr(r, key) for key in CSV_FIELDS}
        for key in _RESULT_KEYS:
            if row[key] is None:
                row[key] = ""
        writer.writerow(row)
    return buf.getvalue()


def results_to_json(results: list[OperatingPoint]) -> str:
    payload = []
    for r in results:
        item = {
            "name": r.name,
            "status": r.status,
            "pump_count": r.pump_count,
            "connection": r.connection,
            "speed_ratio": r.speed_ratio,
            "static_head_m": r.static_head_m,
            "resistance_s2m5": r.resistance_s2m5,
            "hours": r.hours,
        }
        for key in _RESULT_KEYS:
            item[key] = getattr(r, key)
        payload.append(item)
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _atomic_write(path: str, text: str) -> None:
    directory = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(prefix=".pumpcalc-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def run(curve_csv: str, schemes_json: str, out_csv: str, out_json: str) -> int:
    curve = load_curve_csv(curve_csv)
    schemes = load_schemes_json(schemes_json)
    results = order_results([analyze_scheme(curve, s) for s in schemes])

    csv_text = results_to_csv(results)
    json_text = results_to_json(results)
    _atomic_write(out_csv, csv_text)
    try:
        _atomic_write(out_json, json_text)
    except BaseException:
        try:
            os.unlink(out_csv)
        except OSError:
            pass
        raise
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pumpcalc",
        description="计算泵站工况并比较同型泵运行方案",
    )
    parser.add_argument("curve_csv", help="单泵性能曲线 CSV")
    parser.add_argument("schemes_json", help="运行方案 JSON")
    parser.add_argument("out_csv", help="输出工况 CSV 路径")
    parser.add_argument("out_json", help="输出汇总 JSON 路径")
    args = parser.parse_args(argv)
    try:
        return run(args.curve_csv, args.schemes_json, args.out_csv, args.out_json)
    except (CurveError, SchemeError, OSError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
