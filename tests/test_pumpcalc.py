"""pumpcalc 单元测试：校验、求解、排序与 CLI 原子性。"""

import csv
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest

from pumpcalc.curve import build_curve
from pumpcalc.errors import InputError
from pumpcalc.plans import Plan, load_plans
from pumpcalc.solve import GRAVITY, RHO, evaluate, evaluate_all

CURVE = build_curve(
    [0.0, 0.02, 0.04, 0.06, 0.08],
    [40.0, 38.0, 34.0, 28.0, 20.0],
    [0.05, 0.55, 0.75, 0.70, 0.55],
)


def plan(**kw):
    base = dict(
        name="p", pumps=1, speed_ratio=1.0, arrangement="parallel",
        static_head=10.0, resistance=3000.0, hours=1.0,
    )
    base.update(kw)
    return Plan(**base)


def assert_close(test, got, want, flow=False):
    if flow:
        test.assertAlmostEqual(got, want, delta=1e-8)
    else:
        test.assertAlmostEqual(got, want, delta=1e-6 * max(1.0, abs(want)))


class CurveValidationTest(unittest.TestCase):
    def test_too_few_points(self):
        with self.assertRaises(InputError):
            build_curve([0.0], [40.0], [0.5])

    def test_flow_must_start_at_zero(self):
        with self.assertRaises(InputError):
            build_curve([0.01, 0.02], [40.0, 30.0], [0.5, 0.6])

    def test_flow_strictly_increasing(self):
        with self.assertRaises(InputError):
            build_curve([0.0, 0.0, 0.02], [40.0, 35.0, 30.0], [0.5, 0.5, 0.5])

    def test_head_positive_and_decreasing(self):
        with self.assertRaises(InputError):
            build_curve([0.0, 0.02], [40.0, 40.0], [0.5, 0.5])
        with self.assertRaises(InputError):
            build_curve([0.0, 0.02], [40.0, -1.0], [0.5, 0.5])

    def test_efficiency_bounds(self):
        with self.assertRaises(InputError):
            build_curve([0.0, 0.02], [40.0, 30.0], [0.0, 0.5])
        with self.assertRaises(InputError):
            build_curve([0.0, 0.02], [40.0, 30.0], [0.5, 1.01])

    def test_no_extrapolation(self):
        with self.assertRaises(InputError):
            CURVE.efficiency_at(0.09)


class PlanValidationTest(unittest.TestCase):
    def _write(self, tmp, payload):
        path = os.path.join(tmp, "plans.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        return path

    def test_duplicate_names_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._write(tmp, [
                {"name": "a", "pumps": 1, "speed_ratio": 1.0, "arrangement": "series",
                 "static_head": 0, "resistance": 0, "hours": 1},
                {"name": "a", "pumps": 1, "speed_ratio": 1.0, "arrangement": "series",
                 "static_head": 0, "resistance": 0, "hours": 1},
            ])
            with self.assertRaises(InputError):
                load_plans(p)

    def test_bad_values_rejected(self):
        good = {"name": "a", "pumps": 1, "speed_ratio": 1.0, "arrangement": "parallel",
                "static_head": 0, "resistance": 0, "hours": 1}
        bad_cases = [
            {**good, "pumps": 0},
            {**good, "pumps": 1.5},
            {**good, "speed_ratio": 0},
            {**good, "speed_ratio": -1},
            {**good, "static_head": -0.1},
            {**good, "resistance": -1},
            {**good, "hours": -2},
            {**good, "hours": float("nan")},
            {**good, "hours": float("inf")},
            {k: v for k, v in good.items() if k != "hours"},
            {**good, "arrangement": "mixed"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            for i, payload in enumerate(bad_cases):
                with self.subTest(i=i):
                    with self.assertRaises(InputError):
                        load_plans(self._write(tmp, [payload]))


class SolveTest(unittest.TestCase):
    def test_single_pump_operating_point(self):
        result = evaluate(CURVE, plan())
        self.assertEqual(result.status, "ok")
        # 解析解：交点落在 [0.06, 0.08] 段，H = 52 - 400Q 与 H = 10 + 3000Q^2
        # 3000Q^2 + 400Q - 42 = 0
        want_q = (-400.0 + math.sqrt(400.0**2 + 4.0 * 3000.0 * 42.0)) / 6000.0
        want_h = 10.0 + 3000.0 * want_q * want_q
        want_eta = 0.70 + (want_q - 0.06) / 0.02 * (0.55 - 0.70)
        assert_close(self, result.flow, want_q, flow=True)
        assert_close(self, result.head, want_h)
        assert_close(self, result.efficiency, want_eta)
        want_kw = RHO * GRAVITY * want_q * want_h / want_eta / 1000.0
        assert_close(self, result.input_power_kw, want_kw)
        assert_close(self, result.energy_kwh, want_kw * 1.0)

    def test_speed_scaling(self):
        result = evaluate(CURVE, plan(speed_ratio=0.5, static_head=5.0, resistance=2000.0))
        self.assertEqual(result.status, "ok")
        # 缩放后曲线 H = 0.25 * H_base(Q/0.5)
        q = result.flow
        assert_close(self, result.head, 5.0 + 2000.0 * q * q)
        assert_close(self, result.head, 0.25 * CURVE.head_at(q / 0.5))
        assert_close(self, result.efficiency, CURVE.efficiency_at(q / 0.5))

    def test_series_doubles_head(self):
        result = evaluate(CURVE, plan(arrangement="series", pumps=2,
                                      static_head=30.0, resistance=4000.0))
        self.assertEqual(result.status, "ok")
        assert_close(self, result.head, 2.0 * CURVE.head_at(result.flow))
        assert_close(self, result.head, 30.0 + 4000.0 * result.flow**2)

    def test_parallel_doubles_flow(self):
        result = evaluate(CURVE, plan(arrangement="parallel", pumps=2,
                                      static_head=10.0, resistance=1000.0))
        self.assertEqual(result.status, "ok")
        assert_close(self, result.head, CURVE.head_at(result.flow / 2.0))
        assert_close(self, result.efficiency, CURVE.efficiency_at(result.flow / 2.0))

    def test_no_flow_when_static_covers_shutoff(self):
        result = evaluate(CURVE, plan(static_head=40.0, resistance=0.0))
        self.assertEqual(result.status, "no_flow")
        self.assertIsNone(result.flow)

    def test_out_of_range(self):
        result = evaluate(CURVE, plan(static_head=0.0, resistance=0.0))
        self.assertEqual(result.status, "out_of_range")
        self.assertIsNone(result.flow)

    def test_sorting_ok_then_failed(self):
        plans = [
            plan(name="z-slow", speed_ratio=0.5, static_head=5.0, resistance=2000.0),
            plan(name="a-fast"),
            plan(name="m-stall", static_head=99.0, resistance=0.0),
        ]
        results = evaluate_all(CURVE, plans)
        self.assertEqual([r.name for r in results], ["z-slow", "a-fast", "m-stall"])
        self.assertEqual(results[-1].status, "no_flow")


class CliTest(unittest.TestCase):
    def _run(self, tmp, curve_text, plans_payload):
        curve_path = os.path.join(tmp, "curve.csv")
        plans_path = os.path.join(tmp, "plans.json")
        out_csv = os.path.join(tmp, "out.csv")
        out_json = os.path.join(tmp, "out.json")
        with open(curve_path, "w", encoding="utf-8") as fh:
            fh.write(curve_text)
        with open(plans_path, "w", encoding="utf-8") as fh:
            json.dump(plans_payload, fh)
        proc = subprocess.run(
            [sys.executable, "-m", "pumpcalc", curve_path, plans_path, out_csv, out_json],
            capture_output=True, text=True,
        )
        return proc, out_csv, out_json

    CURVE_CSV = "flow,head,efficiency\n0,40,0.1\n0.05,30,0.7\n"
    GOOD_PLAN = {"name": "a", "pumps": 1, "speed_ratio": 1.0, "arrangement": "parallel",
                 "static_head": 10.0, "resistance": 10000.0, "hours": 2.0}

    def test_success_writes_both_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc, out_csv, out_json = self._run(tmp, self.CURVE_CSV, [self.GOOD_PLAN])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            with open(out_csv, newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual(rows[0]["name"], "a")
            self.assertEqual(rows[0]["status"], "ok")
            with open(out_json, encoding="utf-8") as fh:
                summary = json.load(fh)
            self.assertEqual(summary["plans"][0]["name"], "a")

    def test_invalid_input_leaves_no_partial_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = dict(self.GOOD_PLAN, pumps=-1)
            proc, out_csv, out_json = self._run(tmp, self.CURVE_CSV, [self.GOOD_PLAN, bad])
            self.assertEqual(proc.returncode, 1)
            self.assertFalse(os.path.exists(out_csv))
            self.assertFalse(os.path.exists(out_json))

    def test_invalid_curve_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad_csv = "flow,head,efficiency\n0,40,0.5\n0.05,50,0.6\n"
            proc, out_csv, out_json = self._run(tmp, bad_csv, [self.GOOD_PLAN])
            self.assertEqual(proc.returncode, 1)
            self.assertFalse(os.path.exists(out_csv))


if __name__ == "__main__":
    unittest.main()
