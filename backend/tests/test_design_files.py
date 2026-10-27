import json
import tempfile
import unittest
from pathlib import Path

from app.design_files import design_filename, read_design_file, write_design_file
from app.schemas import RocketDesign


class DesignFileTests(unittest.TestCase):
    def test_project_name_produces_a_safe_unicode_filename(self):
        for name, expected in (
            ("유니스트 액체 2호", "유니스트 액체 2호.uarc"),
            ("  Test rocket  ", "Test rocket.uarc"),
            ("Demo.UARC", "Demo.uarc"),
            ("../A:B\\C?*", "_A_B_C__.uarc"),
            ("a\n\tb", "a__b.uarc"),
            ("CON", "_CON.uarc"),
            ("COM¹", "_COM¹.uarc"),
            ("CON .test", "_CON .test.uarc"),
            ("...", "rocket.uarc"),
        ):
            with self.subTest(name=name):
                self.assertEqual(design_filename(name), expected)
        filename = design_filename("가" * 128)
        self.assertLessEqual(len(filename.encode("utf-8")), 255)
        self.assertTrue(filename.endswith(".uarc"))

    def test_round_trip_and_existing_destination_survives(self):
        payload = Path("../examples/design.json").read_text()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rocket.uarc"
            write_design_file(path, payload)
            self.assertEqual(
                read_design_file(path),
                RocketDesign.model_validate_json(payload).model_dump(mode="json"),
            )
            before = path.read_bytes()
            with self.assertRaises(FileExistsError):
                write_design_file(path, payload)
            self.assertEqual(path.read_bytes(), before)
            invalid = json.loads(payload)
            invalid["schema_version"] = 999
            with self.assertRaises(ValueError):
                write_design_file(Path(directory) / "invalid.uarc", json.dumps(invalid))
            self.assertFalse((Path(directory) / "invalid.uarc").exists())

    def test_external_references_and_oversized_files_are_rejected(self):
        from app.design_files import validate_design_file
        from app.storage import MAX_PAYLOAD_BYTES

        payload = json.loads(Path("../examples/design.json").read_text())
        payload["motor"]["thrust_source"] = "/tmp/private.csv"
        with self.assertRaisesRegex(ValueError, "외부 파일"):
            validate_design_file(json.dumps(payload))
        with self.assertRaisesRegex(ValueError, "2 MiB"):
            validate_design_file(b" " * (MAX_PAYLOAD_BYTES + 1))

    def test_native_dialog_cancel_and_file_round_trip(self):
        import sys
        from types import SimpleNamespace
        from unittest.mock import Mock, patch

        from app.bridge import DesktopBridge

        dialog = Mock(return_value=None)
        webview = SimpleNamespace(
            windows=[SimpleNamespace(create_file_dialog=dialog)],
            FileDialog=SimpleNamespace(OPEN=1, SAVE=2),
        )
        payload = Path("../examples/design.json").read_text()
        bridge = DesktopBridge()
        with (
            patch.dict(sys.modules, webview=webview),
            tempfile.TemporaryDirectory() as directory,
        ):
            self.assertIsNone(bridge.import_design_file())
            self.assertIsNone(bridge.export_design_file(payload))
            self.assertEqual(
                dialog.call_args.kwargs["save_filename"],
                "Synthetic parametric rocket.uarc",
            )
            renamed = json.loads(payload)
            renamed["name"] = "유니스트 / 새 로켓"
            payload = json.dumps(renamed)
            path = Path(directory) / "test.uarc"
            dialog.return_value = [str(path)]
            self.assertEqual(bridge.export_design_file(payload), str(path))
            self.assertEqual(
                dialog.call_args.kwargs["save_filename"], "유니스트 _ 새 로켓.uarc"
            )
            self.assertEqual(
                bridge.import_design_file()["name"], json.loads(payload)["name"]
            )
