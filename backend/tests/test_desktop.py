"""Desktop boundary and launcher checks that do not open a GUI."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError
from test_engine import motor_parameters, rocket_parameters

from app.bridge import DesktopBridge
from app.config import frontend_entrypoint
from app.main import main
from app.schemas import (
    EnvironmentConfig,
    FlightConfig,
    GenericMotorConfig,
    RocketConfig,
)


class DesktopBridgeTests(unittest.TestCase):
    def test_new_editor_design_follows_terrain_without_changing_legacy_examples(self):
        self.assertEqual(
            DesktopBridge().get_example_design()["environment"]["elevation_mode"],
            "terrain",
        )
        legacy = DesktopBridge().validate_config(
            "environment",
            json.dumps(
                {
                    "latitude": 35,
                    "longitude": 129,
                    "elevation": 123.4,
                }
            ),
        )
        self.assertEqual(legacy["elevation_mode"], "manual")
        self.assertEqual(legacy["elevation"], 123.4)

    def test_javascript_arrays_validate_without_relaxing_dto_types(self):
        configs = {
            "environment": EnvironmentConfig(
                latitude=0,
                longitude=0,
                elevation=120,
                date=(2026, 10, 5, 12),
                wind_u=[(0, 0), (1000, 10)],
            ),
            "motor": GenericMotorConfig(**motor_parameters()),
            "rocket": RocketConfig(**rocket_parameters()),
            "flight": FlightConfig(
                rail_length=1.5,
                inclination=85,
                heading=360,
                initial_solution=(1, 0, 0, 150, 0, 0, 10, 1, 0, 0, 0, 0, 0, 0),
            ),
        }
        bridge = DesktopBridge()
        for kind, config in configs.items():
            with self.subTest(kind=kind):
                payload = json.dumps(json.loads(config.model_dump_json()))
                result = bridge.validate_config(kind, payload)
                self.assertEqual(result, json.loads(config.model_dump_json()))
                json.dumps(result, allow_nan=False)

    def test_invalid_bridge_payloads_raise_errors(self):
        bridge = DesktopBridge()
        for payload in (
            "{broken",
            "{}",
            "[]",
            '{"latitude": true, "longitude": 0, "elevation": 0}',
            '{"latitude": "35", "longitude": 0, "elevation": 0}',
            '{"latitude": 0, "longitude": 0, "elevation": 0, "extra": 1}',
        ):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                bridge.validate_config("environment", payload)
        with self.assertRaisesRegex(ValueError, "Unknown configuration kind"):
            bridge.validate_config("unknown", "{}")


class DesktopLauncherTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        data = patch(
            "app.main.default_data_directory",
            return_value=Path(temporary.name) / "data",
        )
        data.start()
        self.addCleanup(data.stop)

    def test_cancelled_setup_exits_before_creating_jobs_or_webview(self):
        with (
            patch("sys.argv", ["uarc", "--dev-url", "http://localhost:5173"]),
            patch("app.main.ensure_windows_runtime", return_value=False),
            patch("app.main.prepare_desktop_runtime") as prepare,
            patch("webview.create_window") as create,
            patch("app.simulation.jobs.JobManager") as jobs,
        ):
            main()
            prepare.assert_not_called()
            create.assert_not_called()
            jobs.assert_not_called()

    def test_windows_uses_checked_edge_renderer(self):
        with (
            patch("sys.argv", ["uarc", "--dev-url", "http://localhost:5173"]),
            patch("app.main.sys.platform", "win32"),
            patch("app.main.ensure_windows_runtime", return_value=True) as ensure,
            patch("app.main.prepare_desktop_runtime"),
            patch("app.simulation.jobs.JobManager"),
            patch("webview.create_window"),
            patch("webview.start") as start,
        ):
            main()
            ensure.assert_called_once_with()
            start.assert_called_once_with(gui="edgechromium")

    def test_help_exits_without_runtime_checks(self):
        with (
            patch("sys.argv", ["uarc", "--help"]),
            patch("app.main.ensure_windows_runtime") as ensure,
            patch("sys.stdout"),
        ):
            with self.assertRaises(SystemExit) as result:
                main()
            self.assertEqual(result.exception.code, 0)
            ensure.assert_not_called()

    def test_development_url_accepts_only_local_http(self):
        for url in (
            "http://localhost:5173",
            "http://127.0.0.1:5173/",
            "http://[::1]:5173",
        ):
            self.assertEqual(frontend_entrypoint(dev_url=url), url)
        for url in (
            "https://example.com",
            "http://localhost.example.com",
            "file:///tmp/a.html",
            "http://user:password@localhost:5173",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                frontend_entrypoint(dev_url=url)

    def test_missing_frontend_has_an_actionable_error(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "index.html"
            with self.assertRaisesRegex(FileNotFoundError, "--dev-url"):
                frontend_entrypoint(frontend=missing)

    def test_launcher_connects_the_ui_and_bridge(self):
        with tempfile.TemporaryDirectory() as directory:
            entry = Path(directory) / "index.html"
            entry.write_text("<title>UARC test</title>")
            with (
                patch(
                    "sys.argv",
                    [
                        "uarc",
                        "--frontend",
                        str(entry),
                        "--data-dir",
                        str(Path(directory) / "data"),
                    ],
                ),
                patch("app.main.freeze_support") as freeze,
                patch("app.main.prepare_desktop_runtime") as prepare,
                patch("webview.create_window") as create,
                patch("webview.start") as start,
                patch("app.main.sys.platform", "linux"),
            ):
                main()
                freeze.assert_called_once_with()
                prepare.assert_called_once_with()
                self.assertEqual(create.call_args.kwargs["url"], str(entry.resolve()))
                self.assertIsInstance(create.call_args.kwargs["js_api"], DesktopBridge)
                start.assert_called_once_with(gui="qt")


if __name__ == "__main__":
    unittest.main()
