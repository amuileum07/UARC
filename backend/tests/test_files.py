"""Persistent designs, explicit file capabilities, typed results, and CSV exports."""

import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from test_design import design_payload
from test_importers import FIXTURE, OPTIONS, import_options
from test_jobs import wait_for

from app.bridge import DesktopBridge
from app.config import frontend_entrypoint
from app.schemas import (
    DesignPreview,
    DesignReport,
    FlightSummary,
    OpenRocketImport,
    RocketDesign,
    RunRecord,
    SavedDesignRecord,
    TelemetryResult,
)
from app.simulation.jobs import JobManager
from app.storage import RunStore, atomic_json, save_result


class FileWorkflowTests(unittest.TestCase):
    def test_saved_designs_keep_assets_after_original_deletion_and_restart(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "thrust.csv"
            source.write_text("0,0\n0.05,60\n0.9,60\n1,0\n")
            data = directory / "data"
            with JobManager(data) as manager:
                bridge = DesktopBridge(manager)
                imported = manager.import_file(source)
                payload = design_payload()
                payload["motor"]["thrust_source"] = imported["path"]
                first = bridge.save_design(json.dumps(payload))
                SavedDesignRecord.model_validate(first)
                loaded = bridge.get_saved_design(first["design_id"])
                frozen = Path(loaded["motor"]["thrust_source"])
                self.assertEqual(frozen.read_bytes(), source.read_bytes())
                source.unlink()
                (data / "inputs" / imported["path"]).unlink()
                loaded["name"] = "Edited design"
                second = bridge.save_design(json.dumps(loaded))
                self.assertNotEqual(first["design_id"], second["design_id"])
                self.assertEqual(
                    bridge.get_saved_design(first["design_id"])["name"], payload["name"]
                )
                self.assertEqual(len(bridge.list_designs()), 2)
                self.assertEqual(bridge.list_runs(), [])
                for identifier in ("../bad", "f" * 32):
                    with self.assertRaises(ValueError):
                        bridge.get_saved_design(identifier)
                with self.assertRaises(ValueError):
                    bridge.list_designs(limit=True)
            with JobManager(data) as manager:
                self.assertEqual(manager.list_designs()[0]["name"], "Edited design")
                record = manager.submit_design(
                    RocketDesign.model_validate_json(
                        json.dumps(manager.get_saved_design(first["design_id"]))
                    )
                )
                self.assertEqual(
                    wait_for(manager, record["run_id"])["state"], "succeeded"
                )

    def test_import_run_and_export_have_typed_results_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            with JobManager(directory / "data") as manager:
                bridge = DesktopBridge(manager)
                asset = manager.import_file(FIXTURE)
                imported = OpenRocketImport.model_validate_json(
                    json.dumps(
                        bridge.import_openrocket(
                            asset["path"], import_options().model_dump_json()
                        )
                    )
                )
                preview = bridge.preview_design(imported.design.model_dump_json())
                DesignPreview.model_validate_json(json.dumps(preview))
                record = bridge.submit_design(imported.design.model_dump_json())
                RunRecord.model_validate(record)
                run_id = record["run_id"]
                final = wait_for(manager, run_id)
                self.assertEqual(final["state"], "succeeded", final)
                self.assertNotEqual(final["worker_pid"], os.getpid())
                summary = FlightSummary.model_validate(bridge.get_summary(run_id))
                self.assertGreater(summary.initial_mass_kg, summary.final_mass_kg)
                DesignReport.model_validate(bridge.get_design_report(run_id))
                telemetry = TelemetryResult.model_validate(bridge.get_telemetry(run_id))
                self.assertGreater(telemetry.total_rows, 0)
                target = directory / "flight.csv"
                manager.export_csv(run_id, target)
                with target.open(newline="") as stream:
                    rows = list(csv.reader(stream))
                self.assertEqual(len(rows), telemetry.total_rows + 1)
                self.assertEqual(len(rows[0]), 14)
                self.assertAlmostEqual(float(rows[-1][0]), summary.end_time_s)
                original = target.read_bytes()
                with self.assertRaises(FileExistsError):
                    manager.export_csv(run_id, target)
                self.assertEqual(target.read_bytes(), original)
                with self.assertRaises(ValueError):
                    manager.import_openrocket(str(FIXTURE), import_options())
                for kind in (
                    "run",
                    "summary",
                    "telemetry",
                    "design_report",
                    "design_preview",
                    "saved_design",
                    "openrocket",
                    "imported_file",
                ):
                    self.assertEqual(bridge.get_result_schema(kind)["type"], "object")
                with self.assertRaises(ValueError):
                    bridge.get_result_schema("unknown")

    def test_native_dialogs_are_the_only_bridge_file_capability(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "selected.csv"
            source.write_text("0,0\n1,1\n")
            with JobManager(directory / "data") as manager:
                bridge = DesktopBridge(manager)
                window = SimpleNamespace(
                    create_file_dialog=lambda *args, **kwargs: (str(source),)
                )
                with patch("webview.windows", [window]):
                    imported = bridge.select_input_file()
                    self.assertEqual(
                        (directory / "data" / "inputs" / imported["path"]).read_bytes(),
                        source.read_bytes(),
                    )
                window.create_file_dialog = lambda *args, **kwargs: None
                with patch("webview.windows", [window]):
                    self.assertIsNone(bridge.select_input_file())

    def test_failed_copies_and_exports_leave_no_partial_published_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            store = RunStore(directory / "data")
            try:
                source = directory / "too-large.bin"
                source.write_bytes(b"large")
                with (
                    patch("app.storage.MAX_INPUT_FILE_BYTES", 3),
                    self.assertRaises(ValueError),
                ):
                    store.import_file(source)
                self.assertEqual(list(store.inputs.iterdir()), [])
                payload = RocketDesign.model_validate_json(json.dumps(design_payload()))
                from app.design import compile_design

                config, _ = compile_design(payload)
                run_id = store.create(config)
                data = np.zeros((100_001, 14))
                data[:, 0] = np.arange(len(data))
                save_result(store.run_directory(run_id), data, {})
                store.update(run_id, "succeeded")
                destination = directory / "failed.csv"
                with (
                    patch("app.storage.os.link", side_effect=OSError("disk full")),
                    self.assertRaises(OSError),
                ):
                    store.export_csv(run_id, destination)
                self.assertFalse(destination.exists())
                self.assertEqual(
                    sorted(p.name for p in directory.iterdir()),
                    ["data", "too-large.bin"],
                )
                store.export_csv(run_id, destination)
                with destination.open() as stream:
                    self.assertEqual(sum(1 for _ in stream), len(data) + 1)
                with (
                    patch(
                        "app.storage.os.link",
                        side_effect=FileExistsError("racing writer"),
                    ),
                    self.assertRaises(FileExistsError),
                ):
                    atomic_json(
                        directory / "racing.json", {"value": 1}, overwrite=False
                    )
                self.assertFalse((directory / "racing.json").exists())
            finally:
                store.close()

    def test_cli_import_save_load_and_exports_preserve_existing_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            base = [
                sys.executable,
                "-m",
                "app",
                "--data",
                "--data-dir",
                str(directory / "data"),
            ]

            def run(*args):
                return subprocess.run(
                    [*base, *map(str, args)], capture_output=True, text=True, timeout=30
                )

            imported = directory / "design.json"
            process = run(
                "import-ork", FIXTURE, "--options", OPTIONS, "--output", imported
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            RocketDesign.model_validate_json(imported.read_bytes())
            process = run("save-design", imported)
            self.assertEqual(process.returncode, 0, process.stderr)
            record = json.loads(process.stdout)
            loaded = directory / "loaded.json"
            process = run("load-design", record["design_id"], "--output", loaded)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(
                json.loads(loaded.read_bytes()), json.loads(imported.read_bytes())
            )
            process = run("load-design", record["design_id"], "--output", loaded)
            self.assertNotEqual(process.returncode, 0)
            self.assertEqual(len(json.loads(run("list-designs").stdout)), 1)


class PackagingTests(unittest.TestCase):
    def test_only_windows_desktop_bundles_include_the_setup_ui(self):
        import runpy

        root = Path(__file__).resolve().parents[1]
        build = runpy.run_path(str(root / "scripts" / "build_desktop.py"))[
            "build_arguments"
        ]
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "index.html").write_text("<title>UARC</title>")
            for platform in ("win32", "linux", "darwin"):
                for frontend in (directory, None):
                    with (
                        self.subTest(platform=platform, frontend=frontend),
                        patch("sys.platform", platform),
                    ):
                        arguments = build(root, frontend, directory / "output")
                        self.assertIn(
                            ("--hidden-import", "tzdata"),
                            zip(arguments, arguments[1:], strict=False),
                        )
                        self.assertEqual(
                            "tkinter" not in arguments,
                            platform == "win32" and frontend is not None,
                        )
                        if platform == "win32" and frontend is not None:
                            self.assertIn("webview.platforms.edgechromium", arguments)
                        if platform == "darwin" and frontend is not None:
                            self.assertIn("webview.platforms.cocoa", arguments)

    def test_frozen_frontend_paths_and_build_plan(self):
        import runpy

        root = Path(__file__).resolve().parents[1]
        build = runpy.run_path(str(root / "scripts" / "build_desktop.py"))[
            "build_arguments"
        ]
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            arguments = build(root, None, directory / "output")
            self.assertIn("webview", arguments)
            self.assertIn("rocketpy", arguments)
            self.assertIn("scipy._external.array_api_compat.numpy", arguments)
            frontend = directory / "frontend" / "dist"
            with self.assertRaises(ValueError):
                build(root, frontend, directory / "output")
            frontend.mkdir(parents=True)
            entry = frontend / "index.html"
            entry.write_text("<title>Asset path fixture</title>")
            with (
                patch("app.config.sys.frozen", True, create=True),
                patch("app.config.sys._MEIPASS", str(directory), create=True),
            ):
                self.assertEqual(frontend_entrypoint(), str(entry))
            self.assertTrue(
                any(
                    "frontend/dist" in argument
                    for argument in build(root, frontend, directory / "output")
                )
            )
            (directory / "output" / "UARC").mkdir(parents=True)
            with self.assertRaises(FileExistsError):
                build(root, None, directory / "output")


if __name__ == "__main__":
    unittest.main()
