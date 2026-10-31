"""Persistent diagnostics, bridge compatibility, and native worker output."""

import inspect
import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
import traceback
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from app.bridge import DesktopBridge
from app.logging import application_logging


class LoggingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_rotation_append_and_cleanup_preserve_other_handlers(self):
        root = logging.getLogger()
        previous = list(root.handlers), root.level, threading.excepthook
        with application_logging(self.root, "test"):
            handler = root.handlers[-1]
            self.assertEqual(handler.maxBytes, 5 * 1024**2)
            self.assertEqual(handler.backupCount, 3)
            handler.maxBytes = 512
            for index in range(40):
                logging.info("rotation record %s %s", index, "x" * 80)
        self.assertEqual((root.handlers, root.level, threading.excepthook), previous)
        self.assertEqual(len(list(self.root.glob("uarc.log*"))), 4)
        with application_logging(self.root, "reopened"):
            logging.info("persistent Korean marker 한글")
        content = (self.root / "uarc.log").read_text(encoding="utf-8")
        self.assertIn("persistent Korean marker 한글", content)
        self.assertIn("Z INFO pid=", content)
        # An open file handle would prevent this on Windows.
        (self.root / "uarc.log").rename(self.root / "closed.log")

    def test_bridge_errors_keep_trace_and_signature_without_payload_credentials(self):
        bridge = DesktopBridge()
        self.assertEqual(
            inspect.getfullargspec(bridge.validate_config).args,
            ["self", "kind", "payload_json"],
        )
        invalid_payload = '{"latitude":"private-input"}'
        with application_logging(self.root, "test"):
            bridge.validate_config(
                "environment", '{"latitude":0,"longitude":0,"elevation":0}'
            )
            with self.assertRaises(ValidationError):
                bridge.validate_config("environment", invalid_payload)
            try:
                bridge.validate_config("environment", invalid_payload)
            except ValidationError:
                # pywebview logs a preformatted traceback, without exc_info.
                logging.getLogger("pywebview").error(traceback.format_exc())
            with (
                patch(
                    "app.bridge.fetch_weather",
                    side_effect=ValueError(
                        "request failed https://example.test?api_key=private-key&x=1"
                    ),
                ),
                self.assertRaises(ValueError),
            ):
                bridge.get_weather(
                    json.dumps(
                        {
                            "latitude": 0,
                            "longitude": 0,
                            "elevation": 0,
                            "date": "2026-01-01T00:00:00Z",
                            "model": "gfs_seamless",
                        }
                    )
                )
        content = (self.root / "uarc.log").read_text(encoding="utf-8")
        self.assertIn("Bridge completed method=validate_config", content)
        self.assertIn("Bridge failed method=get_weather", content)
        self.assertIn("bridge.py", content)
        self.assertIn("elapsed_ms=", content)
        self.assertNotIn("private-input", content)
        self.assertNotIn("private-key", content)

    def test_frontend_reports_are_bounded_validated_redacted_and_rate_limited(self):
        bridge = DesktopBridge()
        payload = json.dumps(
            {
                "kind": "react",
                "message": "api_key=private-key https://api.vworld.kr/req/wmts/1.0.0/private-path-key/Satellite/1/1/1.jpeg",
                "stack": "render stack",
                "component_stack": "<App>",
            }
        )
        with application_logging(self.root, "test"):
            for _ in range(60):
                self.assertTrue(bridge.report_frontend_error(payload))
            self.assertFalse(bridge.report_frontend_error(payload))
            with patch("app.bridge.monotonic", return_value=bridge._error_window + 61):
                self.assertTrue(bridge.report_frontend_error(payload))
            for invalid in (
                "{}",
                "[]",
                "x" * 32_769,
                json.dumps({"kind": "react", "message": "x", "path": "/tmp/x"}),
            ):
                with self.subTest(invalid=invalid[:80]), self.assertRaises(ValueError):
                    bridge.report_frontend_error(invalid)
        content = (self.root / "uarc.log").read_text(encoding="utf-8")
        self.assertEqual(content.count("Frontend error"), 61)
        self.assertIn("render stack", content)
        self.assertIn("[redacted]", content)
        self.assertNotIn("private-key", content)
        self.assertNotIn("private-path-key", content)

    def test_unhandled_thread_and_host_failures_are_written_and_hooks_restored(self):
        def fail():
            raise RuntimeError("thread diagnostic marker")

        with (
            patch("threading.excepthook"),
            self.assertRaisesRegex(RuntimeError, "host diagnostic marker"),
            application_logging(self.root, "test"),
        ):
            thread = threading.Thread(target=fail)
            thread.start()
            thread.join()
            raise RuntimeError("host diagnostic marker")
        content = (self.root / "uarc.log").read_text(encoding="utf-8")
        self.assertIn("thread diagnostic marker", content)
        self.assertIn("host diagnostic marker", content)
        self.assertIn("Application stopped", content)

    def test_worker_captures_warnings_python_native_stdio_and_failure(self):
        code = r"""
import ctypes
import os
import sys
import warnings
from pathlib import Path
from unittest.mock import patch
from app.simulation.worker import run_worker
from app.simulation import engine

directory = Path(sys.argv[1])
original = engine.build_simulation
def build(config):
    print("Python stdout marker")
    print("Python stderr marker", file=sys.stderr)
    warnings.warn("numerical warning marker", RuntimeWarning)
    os.write(1, b"native stdout marker\n")
    os.write(2, b"native stderr marker\n")
    ctypes.CDLL("ucrtbase" if os.name == "nt" else None).printf(b"C buffered marker\n")
    if sys.argv[2] == "fail":
        raise RuntimeError("solver failure marker")
    return original(config)
with patch.object(engine, "build_simulation", side_effect=build):
    run_worker(str(directory))
print("outside worker marker")
"""
        example = Path(__file__).resolve().parents[2] / "examples/simulation.json"
        for outcome, exitcode in (("success", 0), ("fail", 1)):
            with self.subTest(outcome=outcome):
                directory = self.root / outcome
                directory.mkdir()
                (directory / "input.json").write_bytes(example.read_bytes())
                result = subprocess.run(
                    [sys.executable, "-B", "-c", code, str(directory), outcome],
                    env=dict(os.environ, MPLBACKEND="Agg"),
                    capture_output=True,
                    encoding="utf-8",
                    timeout=60,
                )
                self.assertEqual(result.returncode, exitcode, result.stderr)
                log = (directory / "solver.log").read_text(encoding="utf-8")
                for marker in (
                    "Python stdout",
                    "Python stderr",
                    "numerical warning",
                    "native stdout",
                    "native stderr",
                    "C buffered",
                ):
                    self.assertIn(marker + " marker", log)
                    self.assertNotIn(marker + " marker", result.stdout + result.stderr)
                if outcome == "success":
                    self.assertTrue((directory / "complete.json").is_file())
                    self.assertIn("Worker succeeded", log)
                    self.assertIn("outside worker marker", result.stdout)
                else:
                    self.assertIn("Traceback", log)
                    self.assertIn("solver failure marker", log)
                    self.assertTrue((directory / "error.json").is_file())
                    self.assertFalse((directory / "complete.json").exists())


if __name__ == "__main__":
    unittest.main()
