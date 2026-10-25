"""Analytical mass checks and end-to-end numeric design editing/replay tests."""

import copy
import json
import math
import subprocess
import sys
import tempfile
import unittest
import warnings
from pathlib import Path

import numpy as np
from pydantic import ValidationError
from test_jobs import wait_for

from app.bridge import DesktopBridge
from app.design import compile_design
from app.schemas import NoseConeConfig, RocketDesign
from app.simulation.engine import build_surface
from app.simulation.jobs import JobManager
from app.storage import read_json

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "design.json"


def design_payload():
    return json.loads(EXAMPLE.read_text())


def compile_payload(payload):
    return compile_design(RocketDesign.model_validate_json(json.dumps(payload)))


class DesignMassTests(unittest.TestCase):
    def test_tube_matches_annular_cylinder_mass_cg_and_inertia(self):
        payload = design_payload()
        payload["components"] = [payload["components"][0]]
        config, report = compile_payload(payload)
        radius, inner, length, density = 0.025, 0.024, 0.6, 1200
        mass = density * math.pi * (radius**2 - inner**2) * length
        transverse = mass * (3 * (radius**2 + inner**2) + length**2) / 12
        self.assertAlmostEqual(config.rocket.mass, mass, places=12)
        self.assertAlmostEqual(config.rocket.center_of_mass_without_motor, length / 2)
        np.testing.assert_allclose(
            config.rocket.inertia[:3],
            [transverse, transverse, mass * (radius**2 + inner**2) / 2],
            rtol=1e-12,
        )
        self.assertEqual(report["scope"], "airframe_without_motor")
        payload["materials"]["body_stock"]["density"] *= 2
        doubled, _ = compile_payload(payload)
        self.assertAlmostEqual(doubled.rocket.mass, 2 * mass)
        np.testing.assert_allclose(
            doubled.rocket.inertia, 2 * np.array(config.rocket.inertia)
        )

    def test_solid_cone_matches_analytical_properties(self):
        payload = design_payload()
        nose = payload["components"][1]
        nose["surface"]["kind"] = "conical"
        nose["surface"].pop("haack_c")
        nose["thickness"] = 0.025
        payload["components"] = [nose]
        config, _ = compile_payload(payload)
        radius, length = 0.025, 0.2
        mass = 1200 * math.pi * radius**2 * length / 3
        self.assertAlmostEqual(config.rocket.mass, mass, places=12)
        self.assertAlmostEqual(
            config.rocket.center_of_mass_without_motor, 0.8 - 3 * length / 4
        )
        np.testing.assert_allclose(
            config.rocket.inertia[:3],
            [mass * (3 * radius**2 / 20 + 3 * length**2 / 80)] * 2
            + [3 * mass * radius**2 / 10],
            rtol=1e-11,
        )

    def test_rectangular_fins_and_cant_match_plate_properties(self):
        payload = design_payload()
        fins = payload["components"][2]
        fins["surface"].update(
            root_chord=0.2,
            tip_chord=0.2,
            span=0.1,
            rocket_radius=0.05,
            position=0.3,
            sweep_length=0,
        )
        payload["components"] = [fins]
        for angle in (0, 30):
            with self.subTest(angle=angle):
                fins["surface"]["cant_angle"] = angle
                config, _ = compile_payload(payload)
                mass = 600 * 0.2 * 0.1 * 0.002 * 4
                c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
                radial2 = (
                    0.05**2
                    + 0.05 * 0.1
                    + 0.1**2 / 3
                    + 0.2**2 * s**2 / 3
                    + 0.002**2 * c**2 / 12
                )
                var_z = 0.2**2 * c**2 / 12 + 0.002**2 * s**2 / 12
                self.assertAlmostEqual(config.rocket.mass, mass)
                self.assertAlmostEqual(
                    config.rocket.center_of_mass_without_motor, 0.3 - 0.1 * c
                )
                np.testing.assert_allclose(
                    config.rocket.inertia[:3],
                    [mass * (radial2 / 2 + var_z)] * 2 + [mass * radial2],
                    rtol=1e-12,
                )

    def test_default_sweep_follows_rocketpy_and_elliptical_fins_have_correct_area(self):
        payload = design_payload()
        fins = payload["components"][2]
        payload["components"] = [fins]
        fins["surface"].pop("sweep_length")
        default, _ = compile_payload(payload)
        fins["surface"]["sweep_length"] = 0.12 - 0.05
        explicit, _ = compile_payload(payload)
        np.testing.assert_allclose(default.rocket.inertia, explicit.rocket.inertia)
        self.assertAlmostEqual(
            default.rocket.center_of_mass_without_motor,
            explicit.rocket.center_of_mass_without_motor,
        )
        fins["surface"].update(surface_type="elliptical_fins")
        for key in ("tip_chord", "sweep_length"):
            fins["surface"].pop(key)
        ellipse, _ = compile_payload(payload)
        self.assertAlmostEqual(
            ellipse.rocket.mass, math.pi * 0.12 * 0.08 / 4 * 0.002 * 600 * 4
        )
        self.assertAlmostEqual(
            ellipse.rocket.center_of_mass_without_motor, 0.12 - 0.12 / 2
        )

    def test_hollow_tail_matches_frustum_wall_integrals(self):
        payload = design_payload()
        payload["components"] = [
            {
                "id": "tail",
                "component_type": "surface",
                "material": "body_stock",
                "thickness": 0.002,
                "surface": {
                    "surface_type": "tail",
                    "position": 0.2,
                    "length": 0.1,
                    "rocket_radius": 0.025,
                    "top_radius": 0.025,
                    "bottom_radius": 0.015,
                },
            }
        ]
        config, _ = compile_payload(payload)
        thickness, top, bottom, length = 0.002, 0.025, 0.015, 0.1
        mass = 1200 * math.pi * length * (thickness * (top + bottom) - thickness**2)
        a, b = (
            2 * thickness * top - thickness**2,
            2 * thickness * (bottom - top) / length,
        )
        mean = length * (a / 2 + b * length / 3) / (a + b * length / 2)
        self.assertAlmostEqual(config.rocket.mass, mass, places=12)
        self.assertAlmostEqual(config.rocket.center_of_mass_without_motor, 0.2 - mean)

    def test_moving_hardware_or_fins_updates_assembly_cg_and_parallel_axis_inertia(
        self,
    ):
        payload = design_payload()
        original, report = compile_payload(payload)
        payload["components"][3]["position"] += 0.1
        changed, changed_report = compile_payload(payload)
        mass, center = (
            original.rocket.mass,
            original.rocket.center_of_mass_without_motor,
        )
        new_center = center + 0.1 / mass
        expected = report["automatic"]["inertia_kg_m2"][0]
        expected += (0.4 + 0.1) ** 2 - 0.4**2 - mass * (new_center**2 - center**2)
        self.assertAlmostEqual(changed.rocket.center_of_mass_without_motor, new_center)
        self.assertAlmostEqual(changed.rocket.inertia[0], expected)
        self.assertAlmostEqual(changed.rocket.inertia[2], original.rocket.inertia[2])
        payload["components"][2]["surface"]["position"] += 0.2
        moved, _ = compile_payload(payload)
        fin_mass = changed_report["components"][2]["mass_kg"]
        self.assertAlmostEqual(
            moved.rocket.center_of_mass_without_motor,
            changed.rocket.center_of_mass_without_motor + fin_mass * 0.2 / mass,
        )

    def test_component_and_assembly_measurements_have_explicit_precedence(self):
        payload = design_payload()
        original, report = compile_payload(payload)
        payload["overrides"] = {
            "mass": original.rocket.mass * 2,
            "center_of_mass": 0.45,
        }
        changed, measured = compile_payload(payload)
        self.assertAlmostEqual(changed.rocket.center_of_mass_without_motor, 0.45)
        np.testing.assert_allclose(
            changed.rocket.inertia, 2 * np.array(original.rocket.inertia)
        )
        self.assertEqual(measured["automatic"], report["automatic"])
        self.assertEqual(measured["sources"]["mass"], "measured")
        payload["overrides"]["inertia"] = [0.02, 0.02, 0.001]
        changed, _ = compile_payload(payload)
        self.assertEqual(changed.rocket.inertia[:3], (0.02, 0.02, 0.001))
        payload = design_payload()
        payload["components"][0]["mass_override"] = 0.5
        _, report = compile_payload(payload)
        self.assertEqual(report["components"][0]["mass_kg"], 0.5)
        self.assertEqual(report["components"][0]["mass_source"], "measured")

    def test_parachute_packing_and_drag_area_are_independent_numeric_inputs(self):
        payload = design_payload()
        original, report = compile_payload(payload)
        canopy = payload["components"][4]
        self.assertAlmostEqual(report["components"][4]["mass_kg"], 0.04)
        self.assertAlmostEqual(
            original.rocket.parachutes[0].cd_s, 1.4 * math.pi * 0.3**2
        )
        canopy["position"] += 0.1
        canopy["deployment"]["radius"] *= 2
        moved, _ = compile_payload(payload)
        self.assertAlmostEqual(
            moved.rocket.center_of_mass_without_motor,
            original.rocket.center_of_mass_without_motor
            + 0.04 * 0.1 / original.rocket.mass,
        )
        self.assertAlmostEqual(
            moved.rocket.parachutes[0].cd_s, 4 * original.rocket.parachutes[0].cd_s
        )
        canopy["attachment_position"] += 0.1
        attachment, _ = compile_payload(payload)
        self.assertEqual(attachment.model_dump_json(), moved.model_dump_json())
        canopy["deployment"]["cd_s"] = 0.7
        override, _ = compile_payload(payload)
        self.assertEqual(override.rocket.parachutes[0].cd_s, 0.7)


class DesignGeometryTests(unittest.TestCase):
    def test_continuous_haack_profile_volume_and_pressure_center(self):
        for coefficient, expected_cp in ((0, 0.5), (0.2, 0.4625), (1 / 3, 0.4375)):
            with self.subTest(coefficient=coefficient):
                config = NoseConeConfig(
                    position=0.8,
                    rocket_radius=0.025,
                    length=0.2,
                    kind="haack",
                    haack_c=coefficient,
                )
                nose = build_surface(config)
                x = np.linspace(0, 0.2, 10_001)
                radius = np.asarray(nose.y_nosecone(x))
                self.assertAlmostEqual(radius[0], 0)
                self.assertAlmostEqual(radius[-1], 0.025)
                volume = np.trapezoid(math.pi * radius**2, x)
                self.assertAlmostEqual(
                    volume / (math.pi * 0.025**2 * 0.2),
                    0.5 + 3 * coefficient / 16,
                    places=7,
                )
                self.assertAlmostEqual(nose.cpz, 0.2 * expected_cp)
        native = build_surface(
            NoseConeConfig(
                position=0, rocket_radius=0.025, length=0.2, kind="vonkarman"
            )
        )
        haack = build_surface(
            NoseConeConfig(
                position=0, rocket_radius=0.025, length=0.2, kind="haack", haack_c=0
            )
        )
        for x in (0, 0.03, 0.1, 0.2):
            self.assertAlmostEqual(
                float(native.y_nosecone(x)), float(haack.y_nosecone(x))
            )

    def test_standard_and_blunted_nose_profiles_compile_without_changing_source(self):
        for kind in (
            "conical",
            "ogive",
            "elliptical",
            "parabolic",
            "lvhaack",
            "vonkarman",
            "powerseries",
        ):
            payload = design_payload()
            payload["components"] = [payload["components"][1]]
            surface = payload["components"][0]["surface"]
            surface["kind"] = kind
            surface.pop("haack_c")
            if kind == "powerseries":
                surface["power"] = 0.5
            if kind == "conical":
                surface["bluffness"] = 0.2
            source = RocketDesign.model_validate_json(json.dumps(payload))
            encoded = source.model_dump_json()
            with self.subTest(kind=kind), warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                config, report = compile_design(source)
                self.assertGreater(config.rocket.mass, 0)
                self.assertEqual(source.model_dump_json(), encoded)
                self.assertGreater(
                    len(report["components"][0]["outline_z_radius_m"]), 2
                )

    def test_schema_validation_and_preview_error_recovery(self):
        base = design_payload()
        cases = []
        invalid = copy.deepcopy(base)
        invalid["components"][0]["material"] = "missing"
        cases.append(invalid)
        invalid = copy.deepcopy(base)
        invalid["components"][1]["id"] = "body"
        cases.append(invalid)
        invalid = copy.deepcopy(base)
        invalid["components"][0]["thickness"] = 1
        cases.append(invalid)
        invalid = copy.deepcopy(base)
        invalid["components"][1]["surface"]["position"] = [0, 0, 0.8]
        cases.append(invalid)
        invalid = copy.deepcopy(base)
        invalid["components"][1]["surface"]["haack_c"] = 1
        cases.append(invalid)
        invalid = copy.deepcopy(base)
        invalid["materials"]["body_stock"]["density"] = -1
        cases.append(invalid)
        invalid = copy.deepcopy(base)
        invalid["components"] = invalid["components"] * 13
        cases.append(invalid)
        for payload in cases:
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                RocketDesign.model_validate_json(json.dumps(payload))
        bridge = DesktopBridge()
        self.assertIn("$defs", bridge.get_config_schema("design"))
        overflow = copy.deepcopy(base)
        overflow["components"][0].update(outer_radius=1e200, thickness=1e199)
        with self.assertRaises(ValueError):
            bridge.preview_design(json.dumps(overflow))
        preview = bridge.preview_design(json.dumps(base))
        self.assertEqual(preview["mass_properties"]["sources"]["mass"], "computed")


class DesignWorkflowTests(unittest.TestCase):
    def test_spawn_execution_snapshot_edit_and_rerun_after_original_file_is_deleted(
        self,
    ):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with JobManager(root) as jobs:
                (root / "inputs" / "wind.csv").write_text("0,0\n1000,10\n")
                payload = design_payload()
                payload["environment"].update(
                    wind_u="wind.csv", atmosphere_type="custom_atmosphere"
                )
                bridge = DesktopBridge(jobs)
                first = bridge.submit_design(json.dumps(payload))["run_id"]
                (root / "inputs" / "wind.csv").unlink()
                self.assertEqual(wait_for(jobs, first)["state"], "succeeded")
                saved = bridge.get_design(first)
                self.assertTrue(Path(saved["environment"]["wind_u"]).is_file())
                report = bridge.get_design_report(first)
                original = read_json(root / "runs" / first / "input.json")
                self.assertAlmostEqual(
                    original["rocket"]["mass"], report["effective"]["mass_kg"]
                )
                summary = jobs.get_summary(first)
                self.assertAlmostEqual(
                    summary["initial_mass_kg"], report["effective"]["mass_kg"] + 0.25
                )
                self.assertNotEqual(
                    summary["initial_center_of_mass_m"],
                    summary["final_center_of_mass_m"],
                )
                repeated = bridge.rerun(first)["run_id"]
                self.assertNotEqual(first, repeated)
                self.assertEqual(wait_for(jobs, repeated)["state"], "succeeded")
                self.assertAlmostEqual(
                    jobs.get_summary(repeated)["apogee_asl_m"], summary["apogee_asl_m"]
                )
                saved["components"][3]["position"] += 0.1
                edited = bridge.submit_design(json.dumps(saved))["run_id"]
                self.assertEqual(wait_for(jobs, edited)["state"], "succeeded")
                self.assertNotEqual(
                    jobs.get_design_report(edited)["effective"]["center_of_mass_m"],
                    report["effective"]["center_of_mass_m"],
                )
                self.assertEqual(
                    bridge.get_design(first)["components"][3]["position"], 0.4
                )
                saved["environment"]["wind_u"] = str(
                    root / "runs" / first / "input.json"
                )
                with self.assertRaisesRegex(ValueError, "copied input asset"):
                    bridge.submit_design(json.dumps(saved))

    def test_design_cli_preview_and_flight(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary) / "data"
            command = [
                sys.executable,
                "-m",
                "app.simulation",
                str(EXAMPLE),
                "--design",
                "--data-dir",
                str(data),
            ]
            preview = subprocess.run(
                [*command, "--preview"],
                capture_output=True,
                text=True,
                timeout=20,
                check=True,
            )
            self.assertIn("mass_properties", json.loads(preview.stdout))
            self.assertFalse(data.exists())
            flight = subprocess.run(
                command, capture_output=True, text=True, timeout=30, check=True
            )
            run_id = json.loads(flight.stdout)["run_id"]
            self.assertTrue((data / "runs" / run_id / "design.json").is_file())


if __name__ == "__main__":
    unittest.main()
