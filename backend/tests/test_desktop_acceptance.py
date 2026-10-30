"""Archive safety, real UI-check wiring, and normal-exit acceptance boundaries."""

import io
import json
import os
import runpy
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from threading import Event, get_ident
from unittest.mock import MagicMock, Mock, patch

from webview.errors import JavascriptException

from app.bridge import DesktopBridge
from app.desktop_runtime import attach_ui_check
from app.main import main
from app.schemas import RocketDesign

ROOT = Path(__file__).resolve().parents[2]
with patch.object(sys, "path", [str(ROOT / "backend/scripts"), *sys.path]):
    SMOKE = runpy.run_path(str(ROOT / "backend/scripts/smoke_desktop.py"))


class DesktopAcceptanceTests(unittest.TestCase):
    def test_zip_relocation_keeps_launcher_and_shipping_frontend(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            name = "UARC.exe" if sys.platform == "win32" else "UARC"
            archive = root / "desktop.zip"
            with zipfile.ZipFile(archive, "w") as stream:
                stream.writestr(f"UARC/{name}", "launcher")
                stream.writestr(
                    "UARC/_internal/frontend/dist/index.html", "shipping UI"
                )
            executable = SMOKE["extract_archive"](archive, root / "한글 설치 경로")
            self.assertEqual(executable.read_text(), "launcher")
            self.assertEqual(
                (executable.parent / "_internal/frontend/dist/index.html").read_text(),
                "shipping UI",
            )

    def test_archive_relocation_preserves_unix_launcher_and_internal_links(self):
        if sys.platform == "win32":
            self.skipTest("Unix archive permissions and links")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = root / "source/UARC"
            bundle.mkdir(parents=True)
            (bundle / "UARC").write_text("#!/bin/sh\nexit 0\n")
            (bundle / "UARC").chmod(0o755)
            assets = bundle / "_internal/frontend/dist"
            assets.mkdir(parents=True)
            (assets / "index.html").write_text("<title>UARC</title>")
            (bundle / "_internal/link").symlink_to("frontend/dist/index.html")
            archive = root / "desktop.tar.gz"
            with tarfile.open(archive, "w:gz") as stream:
                stream.add(bundle, arcname="UARC")
            executable = SMOKE["extract_archive"](archive, root / "한글 설치 경로")
            self.assertTrue(os.access(executable, os.X_OK))
            link = executable.parent / "_internal/link"
            self.assertTrue(link.is_symlink())
            self.assertIn("UARC", link.read_text())

    def test_archive_path_traversal_and_external_symlinks_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index, name in enumerate(
                ("../outside", "/UARC/file", "UARC/../../outside", "C:/file")
            ):
                archive = root / f"bad-{index}.zip"
                with zipfile.ZipFile(archive, "w") as stream:
                    stream.writestr(name, "bad")
                with self.subTest(name=name), self.assertRaises(ValueError):
                    SMOKE["extract_archive"](archive, root / f"extract-{index}")
            archive = root / "bad-link.tar.gz"
            with tarfile.open(archive, "w:gz") as stream:
                link = tarfile.TarInfo("UARC/link")
                link.type, link.linkname = tarfile.SYMTYPE, "../../outside"
                stream.addfile(link)
            with self.assertRaises(tarfile.FilterError):
                SMOKE["extract_archive"](archive, root / "link-extract")
            self.assertFalse((root / "outside").exists())
            with self.assertRaises(FileExistsError):
                SMOKE["extract_archive"](archive, root)

    def test_ui_fixture_is_valid_local_terrain_and_bridge_returns_copies(self):
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary)
            path = bundle / "_internal/examples/design.json"
            path.parent.mkdir(parents=True)
            path.write_bytes((ROOT / "examples/design.json").read_bytes())
            design = RocketDesign.model_validate_json(
                json.dumps(SMOKE["local_design"](bundle))
            )
            bridge = DesktopBridge(initial_design=design)
            example = bridge.get_example_design()
            self.assertEqual(example["environment"]["terrain"]["provider"], "local")
            self.assertEqual(example["environment"]["terrain_mode"], "terrain")
            example["components"][0]["name"] = "changed"
            self.assertNotEqual(
                bridge.get_example_design()["components"][0]["name"], "changed"
            )

    def test_ui_script_result_is_written_before_normal_window_close(self):
        with tempfile.TemporaryDirectory() as temporary:
            report = Path(temporary) / "result.json"
            window = MagicMock()
            event = window.events.loaded
            window.evaluate_js.side_effect = lambda script, callback: callback(
                {"ok": True}
            )
            closed = Event()
            close_threads = []

            def close():
                self.assertTrue(report.is_file())
                close_threads.append(get_ident())
                closed.set()

            window.destroy.side_effect = close
            result = attach_ui_check(window, "Promise.resolve({ok: true})", report)
            loaded = event.__iadd__.call_args.args[0]
            loaded()
            loaded()  # A second document event must not run the scenario twice.
            self.assertTrue(closed.wait(1))
            self.assertNotEqual(close_threads, [get_ident()])
            window.evaluate_js.assert_called_once()
            window.destroy.assert_called_once()
            self.assertEqual(result, {"ok": True})
            self.assertEqual(json.loads(report.read_bytes()), result)

    def test_invalid_or_throwing_scripts_cannot_pass_or_leave_window_open(self):
        for value in (None, {"ok": 1}, {"ok": "true"}, JavascriptException("bad JS")):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as temporary:
                window = MagicMock()
                event = window.events.loaded
                closed = Event()
                window.destroy.side_effect = closed.set
                if isinstance(value, Exception):
                    window.evaluate_js.side_effect = value
                else:
                    window.evaluate_js.side_effect = (
                        lambda script, callback, value=value: callback(value)
                    )
                result = attach_ui_check(
                    window, "script", Path(temporary) / "report.json"
                )
                event.__iadd__.call_args.args[0]()
                self.assertTrue(closed.wait(1))
                self.assertIs(result["ok"], False)
                window.destroy.assert_called_once()

    def test_check_ui_refuses_default_user_data_and_existing_reports_before_gui(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report = root / "report.json"
            report.write_text("keep")
            for extra in ([], ["--data-dir", str(root / "test-data")]):
                with (
                    self.subTest(extra=extra),
                    patch(
                        "sys.argv",
                        ["uarc", *extra, "--check-ui", "design", "script", str(report)],
                    ),
                    patch("sys.stderr", new_callable=io.StringIO),
                    patch("app.main.ensure_windows_runtime") as ensure,
                    self.assertRaises(SystemExit) as error,
                ):
                    main()
                self.assertEqual(error.exception.code, 2)
                ensure.assert_not_called()
                self.assertEqual(report.read_text(), "keep")

    def test_forced_cleanup_is_a_failure_even_if_script_report_says_ok(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            (output / "first.json").write_text('{"ok":true,"phase":"first"}')
            process = Mock()
            stop = Mock()
            process.wait.side_effect = subprocess.TimeoutExpired("UARC", 180)
            with (
                patch.dict(
                    SMOKE["run_ui"].__globals__,
                    launch_desktop=Mock(return_value=process),
                    stop_desktop=stop,
                ),
                self.assertRaisesRegex(RuntimeError, "did not close normally"),
            ):
                SMOKE["run_ui"](output / "UARC", output, {"phase": "first"})
            stop.assert_called_once_with(process)

    def test_report_and_successful_process_exit_are_both_required(self):
        for code in (0, 1):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary)
                proof = {"ok": True, "phase": "first"}
                (output / "first.json").write_text(json.dumps(proof))
                process, stop = Mock(), Mock()
                process.wait.return_value = code
                with patch.dict(
                    SMOKE["run_ui"].__globals__,
                    launch_desktop=Mock(return_value=process),
                    stop_desktop=stop,
                ):
                    if code:
                        with self.assertRaisesRegex(RuntimeError, "exit=1"):
                            SMOKE["run_ui"](
                                Path(sys.executable), output, {"phase": "first"}
                            )
                    else:
                        self.assertEqual(
                            SMOKE["run_ui"](
                                Path(sys.executable), output, {"phase": "first"}
                            ),
                            proof,
                        )
                stop.assert_not_called()

    def test_korean_launcher_path_logs_on_strict_windows_stdout(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            (output / "first.json").write_text('{"ok":true,"phase":"first"}')
            process = Mock()
            process.wait.return_value = 0
            captured = io.BytesIO()
            with (
                io.TextIOWrapper(
                    captured, encoding="cp1252", errors="strict"
                ) as stdout,
                patch("sys.stdout", stdout),
                patch.dict(
                    SMOKE["run_ui"].__globals__,
                    launch_desktop=Mock(return_value=process),
                ),
            ):
                proof = SMOKE["run_ui"](
                    output / "한글 경로/UARC.exe", output, {"phase": "first"}
                )
                stdout.flush()
                self.assertIn(b"Desktop UI: first", captured.getvalue())
                self.assertIn(b"UARC.exe", captured.getvalue())
                self.assertIs(proof["ok"], True)

    def test_graphics_probe_is_isolated_and_a_failed_gpu_cannot_pass(self):
        for ok in (True, False):
            with self.subTest(ok=ok), tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary)
                proof = {"ok": ok, "phase": "graphics"}
                (output / "graphics.json").write_text(json.dumps(proof))
                process, launch = Mock(), Mock()
                process.wait.return_value = 0
                launch.return_value = process
                with patch.dict(SMOKE["run_ui"].__globals__, launch_desktop=launch):
                    if ok:
                        self.assertEqual(
                            SMOKE["run_ui"](
                                Path(sys.executable), output, {"phase": "graphics"}
                            ),
                            proof,
                        )
                    else:
                        with self.assertRaisesRegex(RuntimeError, "graphics: exit=0"):
                            SMOKE["run_ui"](
                                Path(sys.executable), output, {"phase": "graphics"}
                            )
                command = launch.call_args.args[0]
                self.assertIn("--frontend", command)
                self.assertEqual(
                    command[command.index("--data-dir") + 1],
                    str(output / "graphics-data"),
                )
                self.assertNotIn("<script", (output / "graphics.html").read_text())

    def test_launcher_checks_json_fixture_and_requires_success_after_jobs_close(self):
        for ok in (True, False):
            with self.subTest(ok=ok), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                design, script, page, report = [
                    root / name
                    for name in ("design.json", "check.js", "index.html", "report.json")
                ]
                design.write_bytes((ROOT / "examples/design.json").read_bytes())
                script.write_text("Promise.resolve({ok: true})")
                page.write_text("<title>UARC</title>")
                with (
                    patch(
                        "sys.argv",
                        [
                            "uarc",
                            "--frontend",
                            str(page),
                            "--data-dir",
                            str(root / "data"),
                            "--check-ui",
                            str(design),
                            str(script),
                            str(report),
                        ],
                    ),
                    patch("app.main.ensure_windows_runtime", return_value=True),
                    patch("app.main.prepare_desktop_runtime"),
                    patch(
                        "app.main.attach_ui_check", return_value={"ok": ok}
                    ) as attach,
                    patch("app.simulation.jobs.JobManager") as jobs,
                    patch("webview.create_window") as create,
                    patch("webview.start"),
                    patch("sys.stderr", new_callable=io.StringIO),
                ):
                    if ok:
                        main()
                    else:
                        with self.assertRaises(SystemExit) as error:
                            main()
                        self.assertEqual(error.exception.code, 1)
                    jobs.return_value.close.assert_called_once()
                    attach.assert_called_once_with(
                        create.return_value, script.read_text(), report
                    )
                    example = create.call_args.kwargs["js_api"].get_example_design()
                    self.assertEqual(
                        example["name"], json.loads(design.read_bytes())["name"]
                    )


if __name__ == "__main__":
    unittest.main()
