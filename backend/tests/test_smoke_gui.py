"""Committed bridge proof and launcher regressions without a native GUI."""

import io
import json
import os
import runpy
import shlex
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from app.bridge import DesktopBridge
from app.simulation.jobs import JobManager

SMOKE = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts/smoke_gui.py")
)


class GUIReportTests(unittest.TestCase):
    def test_real_bridge_save_proves_only_valid_reports_from_this_launch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with JobManager(root) as jobs:
                bridge = DesktopBridge(jobs)
                design = bridge.get_example_design()
                design["environment"]["elevation_mode"] = "manual"
                valid = [
                    {"token": "this-launch", "stage": "bridge-ready"},
                    {"token": "this-launch", "ok": True},
                ]
                names = ["ordinary design", "[]", '{"token":"another","ok":true}']
                names += [json.dumps(value) for value in valid]
                for name in names:
                    design["name"] = name
                    bridge.save_design(json.dumps(design))
                before = (root / "uarc.sqlite3").stat().st_mtime_ns
                self.assertCountEqual(
                    SMOKE["saved_reports"](root, "this-launch"), valid
                )
                self.assertEqual((root / "uarc.sqlite3").stat().st_mtime_ns, before)
                self.assertEqual(len(bridge.list_designs()), len(names))

    def test_early_exit_keeps_native_logs_and_failure_stage(self):
        threads_before = set(threading.enumerate())

        def start(*args, **kwargs):
            self.assertEqual(set(threading.enumerate()), threads_before)
            kwargs["stdout"].write("native loader failure marker\n")
            kwargs["stdout"].flush()
            process = launch.return_value
            process.returncode = 17
            process.poll.return_value = 17
            process.wait.return_value = 17
            return process

        for platform in ("linux", "win32", "darwin"):
            output = io.StringIO()
            with (
                self.subTest(platform=platform),
                patch("sys.platform", platform),
                patch("sys.argv", ["smoke_gui.py", sys.executable]),
                patch("subprocess.Popen", side_effect=start) as launch,
                redirect_stdout(output),
                redirect_stderr(output),
                self.assertRaisesRegex(RuntimeError, r"Webview exited \(17\)"),
            ):
                SMOKE["main"]()
            self.assertIn("native loader failure marker", output.getvalue())
            self.assertIn("no committed bridge report", output.getvalue())
            self.assertIn("GUI stopping desktop process", output.getvalue())
            self.assertEqual(launch.call_args.kwargs["env"]["PYTHONUTF8"], "1")
            launch.assert_called_once()
            launch.return_value.terminate.assert_not_called()

    @unittest.skipUnless(
        hasattr(os, "posix_spawn"), "Requires a POSIX process launcher"
    )
    def test_darwin_launch_uses_real_posix_spawn_and_preserves_cwd_and_fds(self):
        before = Path.cwd()
        with tempfile.TemporaryDirectory(prefix="uarc spawn 한글 ") as temporary:
            root = Path(temporary)
            launcher = root / "installed uarc"
            code = "import json, os; print(json.dumps({'cwd': os.getcwd()}))"
            launcher.write_text(
                f"#!/bin/sh\nexec {shlex.quote(sys.executable)} -c {shlex.quote(code)}\n",
                encoding="utf-8",
            )
            launcher.chmod(0o755)
            with (
                (root / "child.log").open("w", encoding="utf-8") as log,
                patch("sys.platform", "darwin"),
                patch("os.posix_spawn", wraps=os.posix_spawn) as spawn,
            ):
                self.assertFalse(os.get_inheritable(log.fileno()))
                process = SMOKE["launch_desktop"](
                    [str(launcher)], root, dict(os.environ), log
                )
                self.assertEqual(process.wait(timeout=5), 0)
                spawn.assert_called_once()
            self.assertEqual(Path.cwd(), before)
            result = json.loads((root / "child.log").read_text(encoding="utf-8"))
            self.assertEqual(Path(result["cwd"]).resolve(), root.resolve())

    def test_darwin_failed_spawn_restores_the_parent_cwd(self):
        before = Path.cwd()
        with (
            tempfile.TemporaryDirectory() as temporary,
            (Path(temporary) / "child.log").open("w", encoding="utf-8") as log,
            patch("sys.platform", "darwin"),
            patch("subprocess.Popen", side_effect=OSError("launch failed")),
            self.assertRaisesRegex(OSError, "launch failed"),
        ):
            SMOKE["launch_desktop"](
                [sys.executable], Path(temporary), dict(os.environ), log
            )
        self.assertEqual(Path.cwd(), before)


if __name__ == "__main__":
    unittest.main()
