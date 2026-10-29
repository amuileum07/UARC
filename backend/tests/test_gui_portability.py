"""Read-only bridge reports and bounded GUI supervision without a native GUI."""

import io
import json
import runpy
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from time import monotonic, sleep
from types import SimpleNamespace
from unittest.mock import Mock, patch

SMOKE = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts/smoke_gui.py")
)


class GUIPortabilityTests(unittest.TestCase):
    def test_missing_database_is_never_created_by_the_observer(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertEqual(SMOKE["saved_reports"](root, "token"), [])
            self.assertEqual(list(root.iterdir()), [])

    def test_uncommitted_or_malformed_reports_cannot_pass(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with sqlite3.connect(root / "uarc.sqlite3") as writer:
                writer.execute("CREATE TABLE designs (name TEXT)")
                writer.commit()
                proof = {"token": "token", "ok": True}
                writer.execute("INSERT INTO designs VALUES (?)", (json.dumps(proof),))
                self.assertEqual(SMOKE["saved_reports"](root, "token"), [])
                writer.commit()
                self.assertEqual(SMOKE["saved_reports"](root, "token"), [proof])
                self.assertEqual(SMOKE["saved_reports"](root, "wrong-token"), [])
                writer.execute("DELETE FROM designs")
                for name in (
                    "broken",
                    "[]",
                    '{"token":"token","ok":1}',
                    '{"token":"token","ok":"true"}',
                    '{"token":"token"}',
                ):
                    writer.execute("INSERT INTO designs VALUES (?)", (name,))
                writer.commit()
                self.assertEqual(SMOKE["saved_reports"](root, "token"), [])

    def test_locked_database_has_a_finite_wait(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with sqlite3.connect(root / "uarc.sqlite3") as writer:
                writer.execute("CREATE TABLE designs (name TEXT)")
                writer.commit()
                writer.execute("BEGIN EXCLUSIVE")
                started = monotonic()
                self.assertEqual(SMOKE["saved_reports"](root, "token"), [])
                self.assertLess(monotonic() - started, 1)
                writer.rollback()

    def test_corrupt_database_is_reported_instead_of_ignored(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "uarc.sqlite3").write_bytes(b"broken SQLite database")
            with self.assertRaises(sqlite3.DatabaseError):
                SMOKE["saved_reports"](root, "token")

    def test_missing_report_cannot_override_gui_deadline(self):
        for platform in ("linux", "win32", "darwin"):
            process = Mock(pid=1234, returncode=None)
            process.poll.return_value = None
            process.wait.return_value = 0
            output = io.StringIO()
            stop = Mock()
            started = monotonic()
            with (
                self.subTest(platform=platform),
                patch("sys.platform", platform),
                # Darwin resolves the command before Popen. Use a real path;
                # Popen remains mocked, so no interpreter is actually launched.
                patch("sys.argv", ["smoke_gui.py", sys.executable]),
                patch.dict(SMOKE["main"].__globals__, {"GUI_TIMEOUT_SECONDS": 0.2}),
                patch("subprocess.Popen", return_value=process) as launch,
                patch.dict(SMOKE["main"].__globals__, {"stop_desktop": stop}),
                redirect_stdout(output),
                redirect_stderr(output),
                self.assertRaisesRegex(RuntimeError, "No final bridge report"),
            ):
                SMOKE["main"]()
            self.assertLess(monotonic() - started, 2)
            self.assertIn("no committed bridge report", output.getvalue())
            launch.assert_called_once()
            stop.assert_called_once_with(process)

    def test_windows_stops_tree_before_killing_launcher(self):
        process = Mock(pid=1234)
        process.poll.return_value = None
        result = SimpleNamespace(returncode=0, stdout="terminated", stderr="")
        with (
            patch("sys.platform", "win32"),
            patch("subprocess.run", return_value=result) as taskkill,
        ):
            SMOKE["stop_desktop"](process)
        taskkill.assert_called_once_with(
            ["taskkill", "/PID", "1234", "/T", "/F"],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
        process.terminate.assert_not_called()
        process.wait.assert_called_once_with(timeout=10)

    def test_failed_tree_termination_is_never_ignored(self):
        process = Mock(pid=1234)
        process.poll.return_value = None
        with (
            patch("sys.platform", "win32"),
            patch(
                "subprocess.run",
                return_value=SimpleNamespace(returncode=1, stdout="", stderr="denied"),
            ),
            self.assertRaisesRegex(RuntimeError, "denied"),
        ):
            SMOKE["stop_desktop"](process)

    @unittest.skipUnless(sys.platform == "win32", "Requires native Windows file locks")
    def test_native_windows_launcher_child_releases_its_open_owner_file(self):
        child = """
import os, sys, time
from pathlib import Path
with open(sys.argv[1], 'w'):
    Path(sys.argv[2]).write_text(str(os.getpid()))
    time.sleep(60)
"""
        parent = """
import subprocess, sys
process = subprocess.Popen([sys.executable, '-c', sys.argv[1], *sys.argv[2:]])
process.wait()
"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            owner = root / ".owner.lock"
            ready = root / "ready"
            process = subprocess.Popen(
                [sys.executable, "-c", parent, child, str(owner), str(ready)]
            )
            child_pid = None
            try:
                deadline = monotonic() + 10
                while monotonic() < deadline:
                    if ready.is_file() and (value := ready.read_text()).isdigit():
                        child_pid = value
                        break
                    sleep(0.05)
                self.assertIsNotNone(child_pid, "Launcher child did not start")
                with self.assertRaises(PermissionError):
                    owner.unlink()
                SMOKE["stop_desktop"](process)
                owner.unlink()  # The old parent-only termination leaves this locked.
            finally:
                if child_pid is not None and owner.exists():
                    subprocess.run(
                        ["taskkill", "/PID", child_pid, "/T", "/F"],
                        capture_output=True,
                        timeout=5,
                    )
                if process.poll() is None:
                    SMOKE["stop_desktop"](process)


if __name__ == "__main__":
    unittest.main()
