"""Public NACA references, compressible boundaries, actual flights and replay."""

import copy
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from pydantic import ValidationError
from test_design import compile_payload, design_payload
from test_jobs import wait_for

from app.aerodynamics import drag_coefficients
from app.compressible_drag import cone_pressure, wedge_pressure_drag
from app.design_files import read_design_file, write_design_file
from app.schemas import RocketDesign, SimulationConfig
from app.simulation.engine import build_simulation, run_simulation
from app.simulation.jobs import JobManager


def compressible_payload():
    payload = design_payload()
    payload["automatic_drag"] = {"model": "compressible_v1"}
    payload["components"][1]["surface"].update(kind="conical")
    payload["components"][1]["surface"].pop("haack_c")
    return payload


class CompressibleDragTests(unittest.TestCase):
    def test_cone_solver_matches_published_naca_table(self):
        # NACA TN 3219 (1954), Table I, p. 23, ideal 5-degree cone.
        # p2/p1 is rounded to 0.001; the solver does not use these table entries.
        for mach, pressure in ((1.2, 1.048), (1.5, 1.062), (2.0, 1.096), (3.0, 1.178)):
            with self.subTest(mach=mach):
                calculated = 1 + 0.7 * mach**2 * cone_pressure(mach, math.radians(5))
                self.assertAlmostEqual(calculated, pressure, delta=0.0012)

    def test_cone_pressure_against_separate_supersonic_experimental_points(self):
        # NACA RM L53K17 Fig. 5 (1954), L_n/D=3, circles from reference 1.
        # Approximate readings ±0.005; these are NOT transonic fit anchors.
        # This checks only nose pressure, not whole-rocket/plume accuracy.
        payload = compressible_payload()
        payload["components"][1]["surface"].update(length=0.15, position=0.75)
        config, _ = compile_payload(payload)
        for mach, observed in ((1.24, 0.135), (1.44, 0.118), (1.96, 0.103)):
            with self.subTest(mach=mach):
                self.assertAlmostEqual(
                    cone_pressure(mach, math.atan(1 / 6)), observed, delta=0.012
                )
                self.assertAlmostEqual(
                    drag_coefficients(
                        config.rocket.automatic_drag, mach, 1e6
                    ).nose_pressure,
                    observed,
                    delta=0.012,
                )

    def test_cone_and_frozen_flight_tables_match_nasa_sp3004(self):
        # NASA SP-3004 (Sims, 1964), Table 9, printed p. 14 / PDF p. 20.
        # Ideal-gas theoretical Cp, NOT experimental whole-rocket Cd. Both
        # angles lie inside the supported nose-fineness range. This also checks
        # the compiled table and flight callback path, not just the cone ODE.
        references = {
            5.0: (0.0396615, 0.0363287, 0.0339457, 0.03058576, 0.02824024),
            7.5: (0.0773864, 0.0704289, 0.0655812, 0.0589952, 0.05451919),
        }
        for angle, pressures in references.items():
            payload = compressible_payload()
            length = 0.025 / math.tan(math.radians(angle))
            payload["components"][1]["surface"].update(
                length=length, position=0.6 + length
            )
            config, _ = compile_payload(payload)
            for mach, reference in zip(
                (1.5, 1.75, 2.0, 2.5, 3.0), pressures, strict=True
            ):
                with self.subTest(angle_deg=angle, mach=mach):
                    direct = cone_pressure(mach, math.radians(angle))
                    frozen = drag_coefficients(
                        config.rocket.automatic_drag, mach, 1e6
                    ).nose_pressure
                    # 0.1% computational benchmark tolerance, not a claim of
                    # aerodynamic accuracy. Published-table residuals <0.06%.
                    self.assertAlmostEqual(direct / reference, 1, delta=0.001)
                    self.assertAlmostEqual(frozen / reference, 1, delta=0.001)

    def test_double_wedge_matches_naca_tn1371_pressure_table(self):
        # Ivey & Klunker (1947), NACA TN 1371, printed p. 6 / PDF p. 7.
        # Rounded theoretical pressure Cd on chord area, zero lift, 6% thickness.
        # This verifies only the 2D building block; 6% is outside UARC's complete
        # finite-fin geometry envelope (<=5%), which remains unchanged.
        for mach, reference in ((1.35, 0.0160), (1.6, 0.0116)):
            with self.subTest(mach=mach):
                self.assertAlmostEqual(
                    wedge_pressure_drag(mach, 0.06) / reference, 1, delta=0.01
                )

    def test_double_wedge_thin_airfoil_limit_and_shock_detachment(self):
        for mach in (1.2, 1.5, 2.0, 3.0):
            with self.subTest(mach=mach):
                expected = 4 * 1e-8 / math.sqrt(mach**2 - 1)
                self.assertAlmostEqual(
                    wedge_pressure_drag(mach, 1e-4) / expected, 1, places=5
                )
        with self.assertRaisesRegex(ValueError, "detaches"):
            wedge_pressure_drag(1.2, 0.1)

    def test_base_drag_matches_independently_published_fleeman_correlation(self):
        # Orgeira-Crespo et al., Aerospace 9(6), 286 (2022), Eq. 17.
        # Reference values come from the paper, not another simulator's output.
        config, _ = compile_payload(compressible_payload())
        for mach, expected in ((0, 0.12), (0.3, 0.1317), (1, 0.25), (2, 0.125)):
            with self.subTest(mach=mach):
                values = drag_coefficients(config.rocket.automatic_drag, mach, 1e6)
                self.assertAlmostEqual(values.base_off, expected, places=12)

    def test_closed_base_against_herrin_dutton_measurement(self):
        # Herrin & Dutton (1994), DOI 10.2514/3.11953, p. 79 / PDF p. 3,
        # Fig. 3: area-averaged Cp=-0.102; measured approach Mach=2.46 ±1%.
        # A closed base has Cd_base=-Cp on the same area. Local base component
        # only: no nozzle, fins, support or forebody drag is being validated.
        payload = compressible_payload()
        payload["components"] = payload["components"][:2]
        payload["motor"] = None
        config, _ = compile_payload(payload)
        body = config.rocket.automatic_drag
        reference = 0.102
        nominal = drag_coefficients(body, 2.46, 52e6 * 0.0635).base_off
        # Agreement with the printed three-decimal value; this is NOT a bound
        # on experimental pressure uncertainty or general prediction error.
        self.assertAlmostEqual(nominal, reference, delta=0.0005)
        low = drag_coefficients(body, 2.46 * 1.01, 52e6 * 0.0635).base_off
        high = drag_coefficients(body, 2.46 * 0.99, 52e6 * 0.0635).base_off
        self.assertLess(low, reference)
        self.assertGreater(high, reference)

    def test_mach_range_is_finite_positive_and_continuous(self):
        config, report = compile_payload(compressible_payload())
        geometry = config.rocket.automatic_drag
        self.assertEqual(report["aerodynamics"]["max_mach"], 3)
        for mach in np.linspace(0, 3, 301):
            result = drag_coefficients(geometry, float(mach), 1e6 * float(mach))
            with self.subTest(mach=mach):
                self.assertTrue(math.isfinite(result.total_off))
                self.assertGreater(result.total_off, 0)
                self.assertGreaterEqual(result.nose_pressure, 0)
                self.assertGreaterEqual(result.fin_pressure, 0)
                self.assertLessEqual(result.total_on, result.total_off)
        for boundary in (0.7, 0.8, 0.9, 1.0, 1.05, 1.1, 1.2, 1.25, 2.08):
            left = drag_coefficients(geometry, boundary - 1e-7, 1e6 * (boundary - 1e-7))
            right = drag_coefficients(
                geometry, boundary + 1e-7, 1e6 * (boundary + 1e-7)
            )
            self.assertAlmostEqual(left.total_off, right.total_off, delta=1e-5)
        with self.assertRaisesRegex(ValueError, "Mach"):
            drag_coefficients(geometry, 3.0001, 1e6)
        middle = drag_coefficients(geometry, 1.375, 1e6).nose_pressure
        exact = cone_pressure(1.375, math.atan(0.025 / 0.2))
        self.assertAlmostEqual(middle / exact, 1, delta=0.001)

    def test_invalid_shapes_and_pressure_snapshots_fail_before_solving(self):
        cases = []
        nose = compressible_payload()
        nose["components"][1]["surface"].update(kind="ogive")
        cases.append(nose)
        for key, value in (
            ("n", 5),
            ("tip_chord", 0),
            ("sweep_length", 0.1),
            ("cant_angle", 1),
        ):
            payload = compressible_payload()
            payload["components"][2]["surface"][key] = value
            cases.append(payload)
        payload = compressible_payload()
        payload["components"][2]["thickness"] = 0.005
        cases.append(payload)
        payload = compressible_payload()
        payload["components"][2]["surface"]["span"] = 0.0001
        cases.append(payload)
        for payload in cases:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                compile_payload(payload)
        config, _ = compile_payload(compressible_payload())
        encoded = config.model_dump_json()
        self.assertEqual(
            SimulationConfig.model_validate_json(encoded).model_dump_json(), encoded
        )
        for mutation in ("missing", "duplicate", "gap"):
            raw = config.model_dump(mode="json")
            if mutation == "missing":
                raw["rocket"]["automatic_drag"]["compressible"] = None
            elif mutation == "duplicate":
                rows = raw["rocket"]["automatic_drag"]["compressible"]["pressure"]
                rows[1]["mach"] = rows[0]["mach"]
            else:
                raw["rocket"]["automatic_drag"]["compressible"]["pressure"][0][
                    "mach"
                ] = 1.3
            with self.subTest(mutation=mutation), self.assertRaises(ValidationError):
                SimulationConfig.model_validate_json(json.dumps(raw))

    def test_cone_fineness_endpoints_tolerate_roundoff(self):
        for nose_length in (0.15, 0.5):
            payload = compressible_payload()
            payload["components"] = payload["components"][:2]
            payload["components"][1]["surface"].update(
                length=nose_length, position=0.6 + nose_length
            )
            config, _ = compile_payload(payload)
            with self.subTest(nose_length=nose_length):
                self.assertTrue(
                    math.isfinite(
                        drag_coefficients(
                            config.rocket.automatic_drag, 3, 1e6
                        ).total_off
                    )
                )

    def test_segmentation_and_mass_do_not_change_drag(self):
        payload = compressible_payload()
        first, _ = compile_payload(payload)
        payload["materials"]["body_stock"]["density"] *= 2
        tube = payload["components"][0]
        tube["length"] = 0.3
        second = copy.deepcopy(tube)
        second.update(id="body2", position=0.3)
        payload["components"].append(second)
        changed, _ = compile_payload(payload)
        for mach in (0.3, 1.0, 1.5, 3.0):
            a = drag_coefficients(first.rocket.automatic_drag, mach, 1e6)
            b = drag_coefficients(changed.rocket.automatic_drag, mach, 1e6)
            self.assertAlmostEqual(a.total_off, b.total_off, places=12)

    def test_actual_flights_cross_sonic_speed_without_recomputing_tables(self):
        for mode in ("6 DOF", "3 DOF"):
            payload = compressible_payload()
            payload["motor"] = None
            payload["overrides"] = {"mass": 0.4}
            payload["flight"].update(
                initial_solution=[0, 0, 0, 130, 0, 0, 450, 1, 0, 0, 0, 0, 0, 0],
                max_time=5,
                simulation_mode=mode,
            )
            config, _ = compile_payload(payload)
            rocket, environment = build_simulation(config)
            with (
                self.subTest(mode=mode),
                patch(
                    "app.compressible_drag.cone_pressure",
                    side_effect=AssertionError("ODE during flight"),
                ),
            ):
                flight = run_simulation(rocket, environment, config.flight)
                speeds = np.linalg.norm(flight.solution_array[:, 4:7], axis=1)
                self.assertGreater(flight.max_mach_number, 1.2)
                self.assertLess(speeds[-1], 300)

    def test_export_spawn_replay_and_failure_are_reproducible(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = compressible_payload()
            payload["flight"].update(
                initial_solution=[0, 0, 0, 130, 0, 0, 450, 1, 0, 0, 0, 0, 0, 0],
                max_time=0.3,
            )
            path = write_design_file(root / "compressible.uarc", json.dumps(payload))
            imported = read_design_file(path)
            self.assertEqual(imported["automatic_drag"], {"model": "compressible_v1"})
            self.assertEqual(imported["power_off_drag"], 0.5)
            with JobManager(root / "data") as jobs:
                design = RocketDesign.model_validate_json(json.dumps(imported))
                first = jobs.submit_design(design)["run_id"]
                self.assertEqual(wait_for(jobs, first)["state"], "succeeded")
                frozen = SimulationConfig.model_validate_json(
                    (root / "data" / "runs" / first / "input.json").read_text()
                )
                self.assertEqual(frozen.rocket.automatic_drag.model, "compressible_v1")
                second = jobs.rerun(first)["run_id"]
                self.assertEqual(wait_for(jobs, second)["state"], "succeeded")
                self.assertEqual(jobs.get_summary(first), jobs.get_summary(second))
                payload["flight"]["initial_solution"][6] = 1100
                bad = jobs.submit_design(
                    RocketDesign.model_validate_json(json.dumps(payload))
                )["run_id"]
                result = wait_for(jobs, bad)
                self.assertEqual(result["state"], "failed")
                self.assertIn("Mach", result["error"])


if __name__ == "__main__":
    unittest.main()
