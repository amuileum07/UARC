"""Read-only bridge reports and bounded GUI supervision without a native GUI."""

import io
import json
import runpy
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from time import monotonic
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
        process = Mock(pid=1234, returncode=None)
        process.poll.return_value = None
        process.wait.return_value = 0
        output = io.StringIO()
        started = monotonic()
        with (
            patch("sys.argv", ["smoke_gui.py", "fake-uarc"]),
            patch.dict(SMOKE["main"].__globals__, {"GUI_TIMEOUT_SECONDS": 0.2}),
            patch("subprocess.Popen", return_value=process),
            redirect_stdout(output),
            redirect_stderr(output),
            self.assertRaisesRegex(RuntimeError, "No final bridge report"),
        ):
            SMOKE["main"]()
        self.assertLess(monotonic() - started, 2)
        self.assertIn("no committed bridge report", output.getvalue())
        process.terminate.assert_called_once()
        process.wait.assert_called_once_with(timeout=10)


if __name__ == "__main__":
    unittest.main()
