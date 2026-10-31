"""Keep native command output and worker stages when a frozen smoke run times out."""

import json
import runpy
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SMOKE = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts/smoke_bundle.py")
)


class BundleSmokeTests(unittest.TestCase):
    def test_timeout_preserves_partial_stderr_and_worker_progress_before_cleanup(self):
        def run(command, **kwargs):
            if "--preview" in command:
                return SimpleNamespace(
                    returncode=0,
                    stdout=json.dumps(
                        {"mass_properties": {"effective": {"mass_kg": 1}}}
                    ),
                )
            run_dir = Path(command[command.index("--data-dir") + 1]) / "runs" / "test"
            run_dir.mkdir(parents=True)
            (run_dir / "progress.json").write_text('{"stage":"building"}')
            (run_dir / "runtime.json").write_text('{"python":"test-python"}')
            (run_dir / "solver.log").write_text("solver diagnostic marker")
            (run_dir.parent.parent / "uarc.log").write_text("app diagnostic marker")
            raise subprocess.TimeoutExpired(
                command,
                60,
                output=b"partial stdout",
                stderr=b"worker: running (starting)",
            )

        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "UARC"
            executable.touch()
            diagnostics = Path(temporary) / "diagnostics"
            with (
                patch(
                    "sys.argv",
                    ["smoke_bundle.py", str(executable), "--output", str(diagnostics)],
                ),
                patch("subprocess.run", side_effect=run),
                self.assertRaises(RuntimeError) as failure,
            ):
                SMOKE["main"]()
            self.assertTrue((diagnostics / "data/uarc.log").is_file())
            self.assertTrue((diagnostics / "data/runs/test/solver.log").is_file())
        message = str(failure.exception)
        for expected in (
            "timed out after 60 seconds",
            "partial stdout",
            "running (starting)",
            '"stage":"building"',
            "test-python",
            "app diagnostic marker",
            "solver diagnostic marker",
        ):
            self.assertIn(expected, message)


if __name__ == "__main__":
    unittest.main()
