"""Independent equation checks, supported geometry, weather coupling and replay."""

import copy
import json
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np
from pydantic import ValidationError
from test_design import compile_payload, design_payload
from test_jobs import wait_for

from app.aerodynamics import DragFunction, drag_coefficients, skin_friction
from app.design_files import read_design_file, write_design_file
from app.schemas import RocketDesign, SimulationConfig
from app.simulation.engine import build_simulation, run_simulation
from app.simulation.jobs import JobManager
from app.storage import read_json


def automatic_payload():
    payload = design_payload()
    payload["automatic_drag"] = {"model": "subsonic_v1"}
    return payload


class AerodynamicsTests(unittest.TestCase):
    def test_manual_design_keeps_existing_drag_and_mass(self):
        manual, report = compile_payload(design_payload())
        automatic, auto_report = compile_payload(automatic_payload())
        self.assertIsNone(manual.rocket.automatic_drag)
        self.assertIsNone(report["aerodynamics"])
        self.assertEqual(manual.rocket.power_off_drag, 0.5)
        self.assertEqual(manual.rocket.power_on_drag, 0.4)
        self.assertEqual(report["effective"], auto_report["effective"])
        self.assertEqual(automatic.rocket.power_off_drag, 0.5)
        self.assertEqual(automatic.rocket.power_on_drag, 0.4)

    def test_naca_plate_values_and_roughness_limit(self):
        # NACA 793 Appendix C: plate-average Cf, not pipe Darcy friction.
        self.assertAlmostEqual(skin_friction(1e6, 1, 0), 0.004470758, places=8)
        self.assertAlmostEqual(skin_friction(1e8, 1, 0.001), 0.00844774, places=7)
        self.assertGreater(skin_friction(1e8, 1, 1e-4), skin_friction(1e8, 1, 0))
        self.assertTrue(math.isfinite(skin_friction(0, 1, 0)))

    def test_conical_wetted_area_and_hand_calculated_tr11_components(self):
        payload = automatic_payload()
        payload["components"] = payload["components"][:2]
        nose = payload["components"][1]["surface"]
        nose.update(kind="conical")
        nose.pop("haack_c")
        config, _ = compile_payload(payload)
        geometry = config.rocket.automatic_drag
        radius, body, nose_length = 0.025, 0.6, 0.2
        area = 2 * math.pi * radius * body + math.pi * radius * math.hypot(
            radius, nose_length
        )
        self.assertAlmostEqual(
            sum(s.wetted_area_m2 for s in geometry.surfaces), area, places=12
        )
        values = drag_coefficients(geometry, 0.3, 1e6 / 16)
        cf = 0.004470758085611552
        expected_skin = cf * area / (math.pi * radius**2)
        factor = 1 + 60 / 16**3 + 0.0025 * 12
        self.assertAlmostEqual(values.skin_friction, expected_skin, places=12)
        self.assertAlmostEqual(values.form, expected_skin * (factor - 1), places=12)
        self.assertAlmostEqual(
            values.base_off, 0.029 / math.sqrt(expected_skin * factor), places=12
        )
        self.assertAlmostEqual(values.base_on / values.base_off, (1 - 0.4**2) ** 1.5)

    def test_reference_geometry_and_material_density_do_not_assign_cd(self):
        payload = automatic_payload()
        first, report = compile_payload(payload)
        payload["materials"]["body_stock"]["density"] *= 2
        changed, other = compile_payload(payload)
        self.assertNotEqual(first.rocket.mass, changed.rocket.mass)
        self.assertEqual(first.rocket.automatic_drag, changed.rocket.automatic_drag)
        self.assertEqual(report["aerodynamics"], other["aerodynamics"])
        self.assertAlmostEqual(
            report["aerodynamics"]["reference_area_m2"], math.pi * 0.025**2
        )

    def test_body_segmentation_preserves_boundary_layer_length(self):
        payload = automatic_payload()
        first, _ = compile_payload(payload)
        tube = payload["components"][0]
        tube["length"] = 0.3
        second = copy.deepcopy(tube)
        second.update(id="tube2", position=0.3)
        payload["components"].append(second)
        split, _ = compile_payload(payload)
        a = drag_coefficients(first.rocket.automatic_drag, 0.3, 3e5)
        b = drag_coefficients(split.rocket.automatic_drag, 0.3, 3e5)
        self.assertAlmostEqual(a.total_off, b.total_off, places=12)

    def test_surface_roughness_semantics_and_supported_geometry(self):
        payload = automatic_payload()
        base, _ = compile_payload(payload)
        payload["components"][0]["surface_finish"] = {
            "name": "Measured",
            "roughness_m": 0.0001,
            "roughness_type": "equivalent_sand_grain",
        }
        rough, _ = compile_payload(payload)
        self.assertGreater(
            drag_coefficients(rough.rocket.automatic_drag, 0.5, 1e7).total_off,
            drag_coefficients(base.rocket.automatic_drag, 0.5, 1e7).total_off,
        )
        payload["components"][0]["surface_finish"]["roughness_type"] = "ra"
        with self.assertRaisesRegex(ValueError, "Ra/legacy"):
            compile_payload(payload)
        cases = []
        for key, value in (("position", 0.01), ("outer_radius", 0.03)):
            invalid = automatic_payload()
            invalid["components"][0][key] = value
            cases.append(invalid)
        for key, value in (
            ("cant_angle", 1),
            ("position", 0.01),
            ("rocket_radius", 0.03),
        ):
            invalid = automatic_payload()
            invalid["components"][2]["surface"][key] = value
            cases.append(invalid)
        invalid = automatic_payload()
        invalid["motor_position"] = -0.01
        cases.append(invalid)
        invalid = automatic_payload()
        invalid["motor"]["nozzle_radius"] = 0.03
        cases.append(invalid)
        for invalid in cases:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                compile_payload(invalid)
        elliptical = automatic_payload()
        fin = elliptical["components"][2]["surface"]
        fin["surface_type"] = "elliptical_fins"
        for key in ("tip_chord", "sweep_length"):
            fin.pop(key)
        self.assertIsNotNone(compile_payload(elliptical)[0].rocket.automatic_drag)

    def test_rocketpy_uses_diameter_reynolds_and_rejects_outside_mach_range(self):
        config, _ = compile_payload(automatic_payload())
        encoded = config.model_dump_json()
        restored = SimulationConfig.model_validate_json(encoded)
        self.assertEqual(encoded, restored.model_dump_json())
        rocket, _ = build_simulation(restored)
        geometry = restored.rocket.automatic_drag
        callback = DragFunction(geometry, powered=False)
        for reynolds in (1e5, 3e5, 1e6):
            expected = drag_coefficients(geometry, 0.3, reynolds).total_off
            self.assertAlmostEqual(
                rocket.power_off_drag_7d(0, 0, 0.3, reynolds, 0, 0, 0), expected
            )
        self.assertGreater(
            callback(0, 0, 0.3, 1e5, 0, 0, 0), callback(0, 0, 0.3, 1e6, 0, 0, 0)
        )
        self.assertTrue(math.isfinite(callback(0, 0, 0, 0, 0, 0, 0)))
        for mach in (0.7001, 1, float("nan")):
            with self.subTest(mach=mach), self.assertRaisesRegex(ValueError, "Mach"):
                callback(0, 0, mach, 1e5, 0, 0, 0)
        invalid = restored.model_dump(mode="json")
        invalid["rocket"]["radius"] *= 2
        with self.assertRaises(ValidationError):
            SimulationConfig.model_validate_json(json.dumps(invalid))

    def test_flight_receives_actual_weather_reynolds(self):
        config, _ = compile_payload(automatic_payload())
        rocket, env = build_simulation(config)
        calls = []
        original = rocket.power_off_drag_7d.source

        def record(alpha, beta, mach, reynolds, pitch_rate, yaw_rate, roll_rate):
            calls.append((mach, reynolds))
            return original(
                alpha, beta, mach, reynolds, pitch_rate, yaw_rate, roll_rate
            )

        rocket.power_off_drag_7d.set_source(record)
        run_simulation(rocket, env, config.flight)
        mach, reynolds = next((m, r) for m, r in calls if m > 0.02)
        self.assertGreater(reynolds, 0)
        # A different real atmosphere at the same Mach yields a different Re and Cd.
        env.set_atmospheric_model(
            type="custom_atmosphere", pressure=70000, temperature=275
        )
        velocity = mach * env.speed_of_sound(env.elevation)
        dry_re = (
            env.density(env.elevation)
            * velocity
            * 2
            * rocket.radius
            / env.dynamic_viscosity(env.elevation)
        )
        self.assertNotAlmostEqual(reynolds, dry_re, delta=1000)
        geom = config.rocket.automatic_drag
        self.assertNotAlmostEqual(
            drag_coefficients(geom, mach, reynolds).total_off,
            drag_coefficients(geom, mach, dry_re).total_off,
            places=4,
        )

    def test_saved_design_export_spawn_and_replay_rebuild_automatic_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = automatic_payload()
            exported = write_design_file(root / "rocket.uarc", json.dumps(payload))
            imported = read_design_file(exported)
            self.assertEqual(imported["automatic_drag"], payload["automatic_drag"])
            with JobManager(root / "data") as jobs:
                design = RocketDesign.model_validate_json(json.dumps(imported))
                saved = jobs.save_design(design)
                self.assertEqual(
                    jobs.get_saved_design(saved["design_id"])["automatic_drag"],
                    payload["automatic_drag"],
                )
                first = jobs.submit_design(design)["run_id"]
                self.assertEqual(wait_for(jobs, first)["state"], "succeeded")
                frozen = read_json(root / "data" / "runs" / first / "input.json")
                self.assertEqual(
                    frozen["rocket"]["automatic_drag"]["model"], "subsonic_v1"
                )
                self.assertEqual(
                    jobs.get_design_report(first)["aerodynamics"]["model"],
                    "subsonic_v1",
                )
                second = jobs.rerun(first)["run_id"]
                self.assertEqual(wait_for(jobs, second)["state"], "succeeded")
                np.testing.assert_allclose(
                    jobs.get_summary(first)["apogee_asl_m"],
                    jobs.get_summary(second)["apogee_asl_m"],
                    rtol=1e-10,
                )
                fast = automatic_payload()
                fast["flight"]["initial_solution"] = [
                    0,
                    0,
                    0,
                    130,
                    0,
                    0,
                    300,
                    1,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                ]
                fast["flight"]["max_time"] = 1
                failure = jobs.submit_design(
                    RocketDesign.model_validate_json(json.dumps(fast))
                )["run_id"]
                record = wait_for(jobs, failure)
                self.assertEqual(record["state"], "failed")
                self.assertIn("Mach", record["error"])


if __name__ == "__main__":
    unittest.main()
