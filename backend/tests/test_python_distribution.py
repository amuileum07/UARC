"""Wheel asset resolution and transactional staging, without publishing anything."""

import runpy
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.bridge import DesktopBridge
from app.config import bundled_file, frontend_entrypoint

ROOT = Path(__file__).resolve().parents[2]
BUILD = runpy.run_path(str(ROOT / "backend/scripts/build_python.py"))[
    "build_distributions"
]


class PythonDistributionTests(unittest.TestCase):
    def test_wheel_frontend_and_starting_design_resolve_outside_the_checkout(self):
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / "lib/python3.13/site-packages/app"
            assets = package / "_assets"
            frontend = assets / "frontend/dist/index.html"
            frontend.parent.mkdir(parents=True)
            frontend.write_text("<title>Installed UARC</title>", encoding="utf-8")
            (assets / "examples").mkdir()
            shutil.copyfile(
                ROOT / "examples/design.json", assets / "examples/design.json"
            )
            with (
                patch("app.config.__file__", str(package / "config.py")),
                patch("app.config.sys.frozen", False, create=True),
            ):
                self.assertEqual(Path(frontend_entrypoint()), frontend)
                self.assertEqual(
                    bundled_file("examples/design.json"),
                    assets / "examples/design.json",
                )
                self.assertTrue(DesktopBridge().get_example_design()["components"])

    def test_checkout_frontend_takes_precedence_over_staged_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "backend/app"
            package.mkdir(parents=True)
            source = root / "frontend/dist/index.html"
            source.parent.mkdir(parents=True)
            source.write_text("new build", encoding="utf-8")
            with patch("app.config.__file__", str(package / "config.py")):
                self.assertEqual(Path(frontend_entrypoint()), source)

    def test_staging_is_cleaned_after_build_or_failure_and_does_not_replace_assets(
        self,
    ):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "backend/app").mkdir(parents=True)
            for relative in ("frontend/dist", "examples", "Licenses", "docs"):
                (root / relative).mkdir(parents=True, exist_ok=True)
                (root / relative / "fixture.txt").write_text(relative, encoding="utf-8")
            (root / "frontend/dist/index.html").write_text("UI", encoding="utf-8")
            (root / "LICENSE").write_text("license", encoding="utf-8")
            (root / "backend/LICENSE").write_text("license", encoding="utf-8")
            assets = root / "backend/app/_assets"

            def build(*args, **kwargs):
                self.assertTrue((assets / "frontend/dist/index.html").is_file())
                self.assertTrue((assets / "examples/fixture.txt").is_file())
                self.assertTrue((assets / "Licenses/fixture.txt").is_file())

            with patch("subprocess.run", side_effect=build):
                BUILD(root, root / "output")
            self.assertFalse(assets.exists())
            with (
                patch(
                    "subprocess.run",
                    side_effect=subprocess.CalledProcessError(1, "uv build"),
                ),
                self.assertRaises(subprocess.CalledProcessError),
            ):
                BUILD(root, root / "output")
            self.assertFalse(assets.exists())
            assets.mkdir()
            preserved = assets / "keep.txt"
            preserved.write_text("do not replace", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                BUILD(root, root / "output")
            self.assertEqual(preserved.read_text(encoding="utf-8"), "do not replace")


if __name__ == "__main__":
    unittest.main()
