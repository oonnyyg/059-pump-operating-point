from __future__ import annotations

import json
import math
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pumpcalc.cli import main, results_to_csv  # noqa: E402
from pumpcalc.curve import CurveError, PumpCurve, load_curve_csv  # noqa: E402
from pumpcalc.engine import (  # noqa: E402
    GRAVITY,
    RHO,
    STATUS_NO_FLOW,
    STATUS_OK,
    STATUS_OUT_OF_RANGE,
    analyze_scheme,
)
from pumpcalc.scheme import Scheme, SchemeError, load_schemes_json  # noqa: E402


def make_curve() -> PumpCurve:
    return PumpCurve((0.0, 0.05, 0.1), (50.0, 40.0, 20.0), (0.7, 0.8, 0.75))


def make_scheme(**overrides) -> Scheme:
    defaults = dict(
        name="s",
        pump_count=1,
        connection="parallel",
        speed_ratio=1.0,
        static_head_m=32.0,
        resistance_s2m5=100.0,
        hours=8.0,
    )
    defaults.update(overrides)
    return Scheme(**defaults)


class CurveTests(unittest.TestCase):
    def test_interpolation_midpoint_and_bounds(self):
        curve = make_curve()
        self.assertAlmostEqual(curve.head_at(0.0), 50.0)
        self.assertAlmostEqual(curve.head_at(0.025), 45.0)
        self.assertAlmostEqual(curve.head_at(0.1), 20.0)
        self.assertAlmostEqual(curve.efficiency_at(0.075), 0.775)
        self.assertAlmostEqual(curve.q_at_head(45.0), 0.025)
        self.assertAlmostEqual(curve.q_at_head(20.0), 0.1)

    def test_no_extrapolation(self):
        curve = make_curve()
        with self.assertRaises(CurveError):
            curve.head_at(0.11)
        with self.assertRaises(CurveError):
            curve.head_at(-1e-9)

    def test_invalid_curves(self):
        cases = {
            "one_point.csv": "flow_m3s,head_m,efficiency\n0,50,0.8\n",
            "nonzero_start.csv": "flow_m3s,head_m,efficiency\n0.1,50,0.8\n0.2,40,0.8\n",
            "nonincreasing.csv": "flow_m3s,head_m,efficiency\n0,50,0.8\n0.05,40,0.8\n0.05,30,0.8\n",
            "head_increase.csv": "flow_m3s,head_m,efficiency\n0,50,0.8\n0.05,51,0.8\n",
            "bad_eff.csv": "flow_m3s,head_m,efficiency\n0,50,1.2\n0.05,40,0.8\n",
            "zero_eff.csv": "flow_m3s,head_m,efficiency\n0,50,0\n0.05,40,0.8\n",
            "nan.csv": "flow_m3s,head_m,efficiency\n0,50,0.8\n0.05,nan,0.8\n",
            "missing.csv": "flow_m3s,head_m,efficiency\n0,50,\n0.05,40,0.8\n",
        }
        with tempfile.TemporaryDirectory() as tmp:
            for filename, text in cases.items():
                path = os.path.join(tmp, filename)
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(text)
                with self.assertRaises(CurveError, msg=filename):
                    load_curve_csv(path)


class SchemeTests(unittest.TestCase):
    def _write(self, tmp, data):
        path = os.path.join(tmp, "schemes.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        return path

    BASE = {
        "name": "a",
        "pump_count": 2,
        "connection": "parallel",
        "speed_ratio": 1.0,
        "static_head_m": 10.0,
        "resistance_s2m5": 5.0,
        "hours": 3.0,
    }

    def test_valid_and_default_connection(self):
        with tempfile.TemporaryDirectory() as tmp:
            item = dict(self.BASE)
            del item["connection"]
            path = self._write(tmp, [item])
            schemes = load_schemes_json(path)
            self.assertEqual(schemes[0].connection, "parallel")

    def test_invalid_schemes(self):
        bad_payloads = [
            [],
            [{"name": "a"}],
            [dict(self.BASE, name="")],
            [dict(self.BASE, pump_count=0)],
            [dict(self.BASE, pump_count=1.5)],
            [dict(self.BASE, pump_count=True)],
            [dict(self.BASE, speed_ratio=0.0)],
            [dict(self.BASE, speed_ratio=-1.0)],
            [dict(self.BASE, static_head_m=-0.1)],
            [dict(self.BASE, resistance_s2m5=float("inf"))],
            [dict(self.BASE, hours=float("nan"))],
            [dict(self.BASE, connection="weird")],
            [dict(self.BASE, name="x"), dict(self.BASE, name="x")],
            [dict(self.BASE, hours=None)],
        ]
        with tempfile.TemporaryDirectory() as tmp:
            for payload in bad_payloads:
                path = self._write(tmp, payload)
                with self.assertRaises(SchemeError):
                    load_schemes_json(path)


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.curve = make_curve()

    def test_single_pump_baseline(self):
        scheme = make_scheme()
        result = analyze_scheme(self.curve, scheme)
        self.assertEqual(result.status, STATUS_OK)
        # Root lands on segment 2: H = 60 - 400 Q.
        expected_q = (-400 + math.sqrt(400**2 + 4 * 100 * 28)) / 200
        self.assertAlmostEqual(result.total_flow_m3s, expected_q, places=12)
        self.assertAlmostEqual(result.per_pump_flow_m3s, expected_q, places=12)
        expected_h = 32 + 100 * expected_q**2
        self.assertAlmostEqual(result.total_head_m, expected_h, places=12)
        expected_eff = 0.85 - expected_q
        self.assertAlmostEqual(result.efficiency, expected_eff, places=12)
        p_hyd = RHO * GRAVITY * expected_h * expected_q
        self.assertAlmostEqual(result.hydraulic_power_w, p_hyd, places=6)
        self.assertAlmostEqual(result.input_power_w, p_hyd / expected_eff, places=6)
        self.assertAlmostEqual(
            result.energy_kwh, (p_hyd / expected_eff) / 1000 * 8, places=9
        )

    def test_parallel_combines_flow(self):
        scheme = make_scheme(pump_count=2, static_head_m=30.0)
        result = analyze_scheme(self.curve, scheme)
        self.assertEqual(result.status, STATUS_OK)
        # Parallel: root on second segment, H_total = 60 - 200 Q_total.
        expected_q = (-200 + math.sqrt(200**2 + 4 * 100 * 30)) / 200
        self.assertAlmostEqual(result.total_flow_m3s, expected_q, places=12)
        self.assertAlmostEqual(result.per_pump_flow_m3s, expected_q / 2, places=12)

    def test_series_combines_head(self):
        scheme = make_scheme(
            pump_count=2, connection="series", static_head_m=60.0,
            resistance_s2m5=50.0,
        )
        result = analyze_scheme(self.curve, scheme)
        self.assertEqual(result.status, STATUS_OK)
        # Series, second segment: H = 120 - 800 Q; line 60 + 50 Q^2.
        expected_q = (-800 + math.sqrt(800**2 + 4 * 50 * 60)) / 100
        self.assertAlmostEqual(result.total_flow_m3s, expected_q, places=12)

    def test_speed_ratio_scales_curve_and_efficiency_uses_prescaled_flow(self):
        scheme = make_scheme(pump_count=2, speed_ratio=0.9, static_head_m=30.0)
        result = analyze_scheme(self.curve, scheme)
        self.assertEqual(result.status, STATUS_OK)
        q_total = result.total_flow_m3s
        # Scaled parallel, second segment: H = 48.6 - 180 Q_total.
        expected_q = (-180 + math.sqrt(180**2 + 4 * 100 * 18.6)) / 200
        self.assertAlmostEqual(q_total, expected_q, places=12)
        per_pump_prescale = q_total / 2 / 0.9
        expected_eff = 0.85 - per_pump_prescale
        self.assertAlmostEqual(result.efficiency, expected_eff, places=12)

    def test_no_flow_when_static_head_at_shutoff_and_above(self):
        at_shutoff = analyze_scheme(self.curve, make_scheme(static_head_m=50.0))
        above = analyze_scheme(self.curve, make_scheme(static_head_m=51.0))
        self.assertEqual(at_shutoff.status, STATUS_NO_FLOW)
        self.assertEqual(above.status, STATUS_NO_FLOW)
        self.assertIsNone(at_shutoff.total_flow_m3s)
        self.assertIsNone(above.input_power_w)

    def test_out_of_range_when_intersection_beyond_max_flow(self):
        result = analyze_scheme(
            self.curve, make_scheme(static_head_m=5.0, resistance_s2m5=0.0)
        )
        self.assertEqual(result.status, STATUS_OUT_OF_RANGE)
        self.assertIsNone(result.total_flow_m3s)

    def test_intersection_exactly_at_max_flow_is_ok(self):
        # H(0.1) = 20; pick static = 20, resistance = 0 -> root at endpoint.
        result = analyze_scheme(
            self.curve,
            make_scheme(static_head_m=20.0, resistance_s2m5=0.0),
        )
        self.assertEqual(result.status, STATUS_OK)
        self.assertAlmostEqual(result.total_flow_m3s, 0.1, places=12)
        self.assertAlmostEqual(result.efficiency, 0.75, places=12)

    def test_intersection_exactly_at_zero_is_no_flow(self):
        result = analyze_scheme(
            self.curve,
            make_scheme(static_head_m=50.0, resistance_s2m5=0.0),
        )
        self.assertEqual(result.status, STATUS_NO_FLOW)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.curve_path = os.path.join(self.tmp, "curve.csv")
        with open(self.curve_path, "w", encoding="utf-8") as fh:
            fh.write("flow_m3s,head_m,efficiency\n0,50,0.7\n0.05,40,0.8\n0.1,20,0.75\n")

    def tearDown(self):
        for name in os.listdir(self.tmp):
            os.unlink(os.path.join(self.tmp, name))
        os.rmdir(self.tmp)

    def _schemes(self, schemes):
        path = os.path.join(self.tmp, "schemes.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(schemes, fh)
        return path

    def test_end_to_end_sorting_and_outputs(self):
        scheme_path = self._schemes(
            [
                {"name": "zeta", "pump_count": 2, "connection": "parallel",
                 "speed_ratio": 1.0, "static_head_m": 30.0,
                 "resistance_s2m5": 100.0, "hours": 1.0},
                {"name": "alpha", "pump_count": 1, "connection": "parallel",
                 "speed_ratio": 1.0, "static_head_m": 50.0,
                 "resistance_s2m5": 1.0, "hours": 1.0},
                {"name": "mid", "pump_count": 1, "connection": "parallel",
                 "speed_ratio": 1.0, "static_head_m": 32.0,
                 "resistance_s2m5": 100.0, "hours": 1.0},
            ]
        )
        out_csv = os.path.join(self.tmp, "out.csv")
        out_json = os.path.join(self.tmp, "out.json")
        rc = main([self.curve_path, scheme_path, out_csv, out_json])
        self.assertEqual(rc, 0)

        with open(out_json, encoding="utf-8") as fh:
            payload = json.loads(fh.read())
        self.assertEqual([r["name"] for r in payload], ["mid", "zeta", "alpha"])
        self.assertEqual(payload[1]["status"], "ok")
        self.assertEqual(payload[2]["status"], "no_flow")
        self.assertIsNone(payload[2]["energy_kwh"])

        with open(out_csv, encoding="utf-8") as fh:
            csv_text = fh.read()
        self.assertIn("alpha,no_flow", csv_text)

    def test_invalid_input_leaves_no_results(self):
        bad_curve = os.path.join(self.tmp, "bad.csv")
        with open(bad_curve, "w", encoding="utf-8") as fh:
            fh.write("flow_m3s,head_m,efficiency\n0,50,0.8\n")
        scheme_path = self._schemes(
            [{"name": "a", "pump_count": 1, "connection": "parallel",
              "speed_ratio": 1.0, "static_head_m": 10.0,
              "resistance_s2m5": 1.0, "hours": 1.0}]
        )
        out_csv = os.path.join(self.tmp, "out.csv")
        out_json = os.path.join(self.tmp, "out.json")
        rc = main([bad_curve, scheme_path, out_csv, out_json])
        self.assertEqual(rc, 1)
        self.assertFalse(os.path.exists(out_csv))
        self.assertFalse(os.path.exists(out_json))


if __name__ == "__main__":
    unittest.main()
