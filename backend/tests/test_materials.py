"""Density dimensions, catalogue provenance, and portable material snapshots."""

import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from pydantic import ValidationError
from test_design import compile_payload, design_payload
from test_importers import FIXTURE, import_options

from app.bridge import DesktopBridge
from app.design_files import read_design_file, write_design_file
from app.importers.openrocket import import_openrocket
from app.materials import material_catalog
from app.schemas import MaterialConfig, RocketDesign, SurfaceFinishConfig


class MaterialTests(unittest.TestCase):
    def test_catalogue_contains_only_independent_product_facts_with_sources(self):
        catalog = material_catalog()
        self.assertEqual(len(catalog["materials"]), 6)
        self.assertEqual(len({m["id"] for m in catalog["materials"]}), 6)
        self.assertEqual(catalog["surface_finishes"], [])
        sources = catalog["sources"]
        for item in catalog["materials"]:
            self.assertEqual(item["evidence"], "manufacturer_typical")
            self.assertFalse(item["id"].startswith(("or_", "ras_")))
            MaterialConfig.model_validate(
                {k: item[k] for k in ("name", "density", "density_type")}
            )
            self.assertIn(item["group"], catalog["groups"])
            self.assertTrue(item["notes"])
            self.assertTrue(item["source_ids"])
            self.assertTrue(set(item["source_ids"]) <= sources.keys())
            self.assertTrue(
                all(
                    sources[key]["kind"] == "manufacturer_tds"
                    for key in item["source_ids"]
                )
            )
        for source in sources.values():
            self.assertEqual(urlsplit(source["url"]).scheme, "https")
            self.assertTrue(source["locator"])
            self.assertNotEqual(source["kind"], "software_reference")
        for group in catalog["groups"].values():
            self.assertTrue(set(group["source_ids"]) <= sources.keys())
        densities = {item["id"]: item["density"] for item in catalog["materials"]}
        self.assertEqual(densities["prusa_petg"], 1.27 * 1000)
        self.assertEqual(densities["hexcel_8552_as4"], 1.58 * 1000)

    def test_surface_and_line_density_compute_mass_without_volume_conversion(self):
        payload = design_payload()
        payload["materials"]["fabric"] = {
            "name": "Measured fabric",
            "density": 0.083,
            "density_type": "surface",
        }
        payload["materials"]["cord"] = {
            "name": "Measured cord",
            "density": 0.002,
            "density_type": "line",
        }
        chute = payload["components"][-1]
        chute.update(line_material="cord", line_length=5.0, line_mass=99.0)
        config, report = compile_payload(payload)
        self.assertAlmostEqual(report["components"][-1]["mass_kg"], 0.083 * 0.3 + 0.01)
        chute["thickness"] *= 10
        same, same_report = compile_payload(payload)
        self.assertEqual(report, same_report)
        self.assertEqual(config.rocket, same.rocket)
        chute["line_material"] = None
        chute["line_mass"] = 0.005
        _, manual = compile_payload(payload)
        self.assertAlmostEqual(manual["components"][-1]["mass_kg"], 0.083 * 0.3 + 0.005)

    def test_cord_mass_cg_inertia_overrides_and_portable_snapshot(self):
        payload = design_payload()
        payload["materials"]["cord"] = {
            "name": "Cord snapshot",
            "density": 0.006,
            "density_type": "line",
            "catalog_id": "user_cord",
        }
        payload["components"].append(
            {
                "id": "shock",
                "component_type": "line",
                "material": "cord",
                "position": 0.3,
                "line_length": 4.0,
                "packed_radius": 0.02,
                "packed_length": 0.05,
            }
        )
        payload["components"][0]["surface_finish"] = {
            "name": "Measured Ra",
            "roughness_m": 3.2e-6,
            "roughness_type": "ra",
        }
        before, report = compile_payload(payload)
        part = report["components"][-1]
        self.assertAlmostEqual(part["mass_kg"], 0.024)
        self.assertEqual(part["center_of_mass_m"], 0.3)
        self.assertAlmostEqual(part["inertia_kg_m2"][2], 0.024 * 0.02**2 / 2)
        self.assertEqual(before.rocket.power_off_drag, payload["power_off_drag"])
        self.assertEqual(before.rocket.power_on_drag, payload["power_on_drag"])
        payload["components"][-1]["mass_override"] = 0.048
        _, measured = compile_payload(payload)
        self.assertAlmostEqual(
            measured["components"][-1]["inertia_kg_m2"][2], 2 * part["inertia_kg_m2"][2]
        )
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "materials.uarc"
            write_design_file(file, json.dumps(payload))
            restored = read_design_file(file)
        self.assertEqual(
            restored,
            RocketDesign.model_validate_json(json.dumps(payload)).model_dump(
                mode="json"
            ),
        )
        self.assertEqual(compile_payload(restored)[1], measured)

    def test_wrong_density_dimensions_missing_line_and_nonfinite_values_reject(self):
        for bad_kind in ("surface", "line"):
            payload = design_payload()
            payload["materials"]["body_stock"]["density_type"] = bad_kind
            with self.subTest(kind=bad_kind), self.assertRaises(ValidationError):
                compile_payload(payload)
        for line, length in (("missing", 1), ("body_stock", 1), ("fabric", 0)):
            payload = design_payload()
            payload["components"][-1].update(line_material=line, line_length=length)
            with self.subTest(line=line), self.assertRaises(ValidationError):
                compile_payload(payload)
        for value in (-1, float("inf"), float("nan"), True):
            with self.subTest(roughness=value), self.assertRaises(ValidationError):
                SurfaceFinishConfig(
                    name="Invalid", roughness_m=value, roughness_type="ra"
                )
        self.assertEqual(
            MaterialConfig(name="Legacy", density=1200).density_type, "bulk"
        )

    def test_openrocket_import_uses_file_densities_and_warns_without_finish_lookup(
        self,
    ):
        xml = ET.fromstring(FIXTURE.read_bytes())
        body = xml.find(".//bodytube")
        ET.SubElement(body, "finish").text = "finishpolished"
        body.find("subcomponents").append(
            ET.fromstring(
                "<shockcord><name>Cord</name><packedlength>0.05</packedlength>"
                "<packedradius>0.01</packedradius><cordlength>3</cordlength>"
                '<material type="line" density="0.004">Measured line</material></shockcord>'
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "rocket.ork"
            file.write_bytes(ET.tostring(xml))
            imported = import_openrocket(file, import_options())
            design = imported.design
        chute, cord = design.components[-2:]
        self.assertEqual(design.materials[chute.material].density_type, "surface")
        self.assertEqual(design.materials[chute.material].density, 0.1)
        self.assertEqual(design.materials[chute.line_material].density_type, "line")
        self.assertEqual(cord.component_type, "line")
        _, report = compile_payload(design.model_dump(mode="json"))
        self.assertAlmostEqual(report["components"][-1]["mass_kg"], 0.012)
        self.assertIsNone(design.components[1].surface_finish)
        self.assertTrue(
            any("finishpolished" in warning for warning in imported.warnings)
        )

    def test_bridge_offline_catalogue_and_reference_whitelist(self):
        bridge = DesktopBridge()
        catalog = bridge.get_material_catalog()
        catalog["materials"].clear()
        self.assertEqual(len(bridge.get_material_catalog()["materials"]), 6)
        with patch("webbrowser.open", return_value=True) as opened:
            self.assertTrue(bridge.open_material_reference("prusa_petg"))
            self.assertEqual(
                opened.call_args.args[0],
                material_catalog()["sources"]["prusa_petg"]["url"],
            )
            with self.assertRaises(ValueError):
                bridge.open_material_reference("https://unregistered.example/")
            opened.assert_called_once()


if __name__ == "__main__":
    unittest.main()
