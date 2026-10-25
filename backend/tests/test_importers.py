"""Reference geometry, coordinate conversion, and hostile archive boundaries."""

import gzip
import io
import math
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from unittest.mock import patch

from app.design import compile_design
from app.importers.openrocket import import_openrocket
from app.schemas import OpenRocketOptions

FIXTURE = Path(__file__).parent / "fixtures" / "single-stage.ork"
OPTIONS = Path(__file__).resolve().parents[2] / "examples" / "openrocket-options.json"


def import_options():
    return OpenRocketOptions.model_validate_json(OPTIONS.read_bytes())


class OpenRocketTests(unittest.TestCase):
    def test_plain_zip_and_gzip_preserve_geometry_materials_and_coordinates(self):
        xml = FIXTURE.read_bytes()
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as stream:
            stream.writestr("rocket.ork", xml)
            stream.writestr("../ignored-image.png", b"not extracted")
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for index, data in enumerate((xml, archive.getvalue(), gzip.compress(xml))):
                with self.subTest(format=index):
                    path = directory / f"rocket-{index}.ork"
                    path.write_bytes(data)
                    imported = import_openrocket(path, import_options())
                    design = imported.design
                    nose, body, fins, payload, recovery = design.components
                    self.assertAlmostEqual(nose.surface.position, 0.8)
                    self.assertAlmostEqual(nose.surface.haack_c, 0.1)
                    self.assertAlmostEqual(nose.surface.base_radius, 0.025)
                    self.assertAlmostEqual(body.position, 0)
                    self.assertAlmostEqual(fins.surface.position, 0.12)
                    self.assertAlmostEqual(payload.position, 0.4)
                    self.assertAlmostEqual(recovery.position, 0.5)
                    config, report = compile_design(design)
                    parts = report["components"]
                    self.assertAlmostEqual(
                        parts[1]["mass_kg"],
                        1200 * math.pi * (0.025**2 - 0.024**2) * 0.6,
                    )
                    self.assertAlmostEqual(
                        parts[4]["mass_kg"], 0.1 * math.pi * 0.3**2 + 0.01
                    )
                    self.assertAlmostEqual(
                        config.rocket.parachutes[0].cd_s, 1.4 * math.pi * 0.3**2
                    )
                    self.assertTrue(imported.warnings)
                    self.assertFalse((directory.parent / "ignored-image.png").exists())

    def test_position_methods_and_degrees_are_converted_explicitly(self):
        xml = FIXTURE.read_text()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "position.ork"
            for method, offset, expected_cg in (
                ("top", 0.1, 0.425),
                ("middle", 0.1, 0.2),
                ("bottom", 0.0, 0.075),
                ("absolute", 0.1, 0.625),
            ):
                with self.subTest(method=method):
                    path.write_text(
                        xml.replace(
                            '<axialoffset method="top">0.125</axialoffset>',
                            f'<axialoffset method="{method}">{offset}</axialoffset>',
                        ).replace("<cant>0</cant>", "<cant>5</cant>")
                    )
                    design = import_openrocket(path, import_options()).design
                    self.assertAlmostEqual(design.components[3].position, expected_cg)
                    self.assertEqual(design.components[2].surface.cant_angle, 5)

    def test_unsupported_features_reject_instead_of_dropping_parts(self):
        xml = FIXTURE.read_text()
        variants = (
            xml.replace("<stage>", "<parallelstage>").replace(
                "</stage>", "</parallelstage>"
            ),
            xml.replace("<cant>0</cant>", "<cant>0</cant><tabheight>0.01</tabheight>"),
            xml.replace(
                "<shape>haack</shape>",
                "<shape>haack</shape><aftshoulderlength>0.03</aftshoulderlength>",
            ),
            xml.replace(
                "<mass>1</mass>", "<mass>1</mass><radialposition>0.01</radialposition>"
            ),
            xml.replace("<mass>1</mass>", "<mass>1</mass><overridecg>0.1</overridecg>"),
            xml.replace("<masscomponent>", "<unsupportedcomponent>").replace(
                "</masscomponent>", "</unsupportedcomponent>"
            ),
            xml.replace('version="1.10"', 'version="2.0"'),
            xml.replace("<radius>0.025</radius>", "<radius>auto</radius>"),
            xml.replace(
                '<axialoffset method="top">0.125</axialoffset>',
                '<axialoffset method="top">0.125</axialoffset><position type="bottom">0</position>',
            ),
            xml.replace(
                "<linecount>5</linecount>", "<linecount>-5</linecount>"
            ).replace("<linelength>1</linelength>", "<linelength>-1</linelength>"),
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "unsupported.ork"
            for index, data in enumerate(variants):
                with self.subTest(variant=index), self.assertRaises(ValueError):
                    path.write_text(data)
                    import_openrocket(path, import_options())

    def test_automatic_cylinder_radius_uses_the_previous_explicit_component_first(self):
        root = ET.fromstring(FIXTURE.read_bytes())
        parts = root.find("rocket/subcomponents/stage/subcomponents")
        parts.find("nosecone/aftradius").text = "0.025"
        parts.find("bodytube/radius").text = "auto"
        parts.append(
            ET.fromstring(
                '<transition><length>0.1</length><foreradius>0.05</foreradius><aftradius>0.03</aftradius><thickness>0.001</thickness><material type="bulk" density="1200">Synthetic</material></transition>'
            )
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "automatic.ork"
            path.write_bytes(ET.tostring(root))
            design = import_openrocket(path, import_options()).design
            self.assertEqual(design.components[1].outer_radius, 0.025)

    def test_ejection_requires_an_explicit_trigger_and_auto_cd_uses_openrocket_value(
        self,
    ):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "recovery.ork"
            path.write_text(
                FIXTURE.read_text()
                .replace(
                    "<deployevent>apogee</deployevent>",
                    "<deployevent>ejection</deployevent>",
                )
                .replace("<cd>1.4</cd>", "<cd>auto</cd>")
            )
            with self.assertRaisesRegex(ValueError, "parachute_trigger"):
                import_openrocket(path, import_options())
            options = import_options()
            options.parachute_trigger = 150.0
            recovery = import_openrocket(path, options).design.components[-1]
            self.assertEqual(recovery.deployment.trigger, 150)
            self.assertEqual(recovery.deployment.drag_coefficient, 0.8)

    def test_unsafe_and_oversized_xml_archives_are_bounded(self):
        xml = FIXTURE.read_bytes()
        attacks = [
            b'<!DOCTYPE openrocket [<!ENTITY a "x">]>' + xml,
            b"<openrocket>",
            b"<openrocket version='1.10'>"
            + b"<x>" * 40
            + b"</x>" * 40
            + b"</openrocket>",
            gzip.compress(b"x" * (2 * 1024**2 + 1)),
            b"<openrocket version='1.10'>" + b"<x/>" * 4096 + b"</openrocket>",
        ]
        no_design = io.BytesIO()
        with zipfile.ZipFile(no_design, "w") as stream:
            stream.writestr("../rocket.ork", xml)
        attacks.append(no_design.getvalue())
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "unsafe.ork"
            for index, data in enumerate(attacks):
                with self.subTest(attack=index), self.assertRaises(ValueError):
                    path.write_bytes(data)
                    import_openrocket(path, import_options())
            path.write_bytes(xml)
            with (
                patch("app.importers.openrocket.MAX_ARCHIVE_BYTES", 32),
                self.assertRaisesRegex(ValueError, "8 MiB"),
            ):
                import_openrocket(path, import_options())


if __name__ == "__main__":
    unittest.main()
