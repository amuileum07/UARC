"""Offline process, lifecycle, storage, and bounded telemetry integration tests."""

import json
import multiprocessing
import os
import selectors
import signal
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from time import monotonic, sleep
from unittest.mock import patch

import numpy as np
from pydantic import ValidationError
from test_engine import motor_parameters, rocket_parameters

from app.bridge import DesktopBridge
from app.schemas import (
    TELEMETRY_COLUMNS,
    EllipticalFinsConfig,
    EnvironmentConfig,
    FlightConfig,
    GenericMotorConfig,
    HybridMotorConfig,
    LiquidMotorConfig,
    MassBasedTankConfig,
    NoseConeConfig,
    RocketConfig,
    SimulationConfig,
    SolidMotorConfig,
    TailConfig,
    TelemetryQuery,
    TrapezoidalFinsConfig,
)
from app.simulation.engine import build_simulation
from app.simulation.jobs import JobManager
from app.storage import TERMINAL_STATES, RunStore, atomic_json, read_json, save_result


def simulation_config(kind="generic", *, dense=False):
    models = {
        "generic": GenericMotorConfig,
        "solid": SolidMotorConfig,
        "liquid": LiquidMotorConfig,
        "hybrid": HybridMotorConfig,
    }
    tanks = []
    if kind in {"liquid", "hybrid"}:
        tanks = [
            MassBasedTankConfig.model_validate_json(
                json.dumps(
                    {
                        "name": "synthetic tank",
                        "position": 0.1,
                        "radius": 0.02,
                        "height": 0.2,
                        "flux_time": 1,
                        "liquid": {"name": "liquid", "density": 1000},
                        "gas": {"name": "gas", "density": 1.2},
                        "liquid_mass": [[0, 0.08], [1, 0.01]],
                        "gas_mass": [
                            [0, (np.pi * 0.02**2 * 0.2 - 0.08 / 1000) * 1.2],
                            [1, (np.pi * 0.02**2 * 0.2 - 0.01 / 1000) * 1.2],
                        ],
                    }
                )
            )
        ]
    return SimulationConfig(
        environment=EnvironmentConfig(latitude=0, longitude=0, elevation=120),
        motor=models[kind](**motor_parameters(kind)),
        rocket=RocketConfig(**rocket_parameters()),
        flight=FlightConfig(
            rail_length=1.5,
            inclination=85,
            heading=0,
            max_time=60,
            max_time_step=1e-6 if dense else 0.05,
        ),
        surfaces=[
            NoseConeConfig(position=0.7, length=0.2, rocket_radius=0.025),
            TrapezoidalFinsConfig(
                position=-0.35,
                n=4,
                root_chord=0.12,
                tip_chord=0.05,
                span=0.08,
                rocket_radius=0.025,
            ),
        ],
        tanks=tanks,
    )


def wait_for(manager, run_id, states=TERMINAL_STATES, *, stage=None, timeout=20):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        record = manager.get_run(run_id)
        if record["state"] in states and (stage is None or record["stage"] == stage):
            return record
        if record["state"] in TERMINAL_STATES:
            raise AssertionError(f"Run ended before the expected state: {record}")
        sleep(0.02)
    raise AssertionError(f"Run did not reach {states}: {manager.get_run(run_id)}")


class SimulationConfigTests(unittest.TestCase):
    def test_all_motor_configs_round_trip_and_build_in_process(self):
        for kind in ("generic", "solid", "liquid", "hybrid"):
            with self.subTest(kind=kind):
                config = simulation_config(kind)
                encoded = config.model_dump_json()
                restored = SimulationConfig.model_validate_json(encoded)
                self.assertEqual(encoded, restored.model_dump_json())
                rocket, environment = build_simulation(restored)
                self.assertEqual(len(rocket.aerodynamic_surfaces), 2)
                self.assertEqual(environment.elevation, 120)
        self.assertIn("$defs", SimulationConfig.model_json_schema())

    def test_additional_surfaces_build_and_tank_mismatches_are_rejected(self):
        config = simulation_config()
        config.surfaces.extend(
            [
                EllipticalFinsConfig(
                    position=-0.3, n=4, root_chord=0.12, span=0.08, rocket_radius=0.025
                ),
                TailConfig(
                    position=-0.4,
                    top_radius=0.025,
                    bottom_radius=0.02,
                    length=0.1,
                    rocket_radius=0.025,
                ),
            ]
        )
        rocket, _ = build_simulation(config)
        self.assertEqual(len(rocket.aerodynamic_surfaces), 4)
        for kind in ("liquid", "hybrid"):
            payload = simulation_config(kind).model_dump(mode="json")
            payload["tanks"] = []
            with self.subTest(kind=kind), self.assertRaises(ValidationError):
                SimulationConfig.model_validate_json(json.dumps(payload))
        payload = simulation_config("liquid").model_dump(mode="json")
        payload["motor"] = simulation_config().motor.model_dump(mode="json")
        with self.assertRaises(ValidationError):
            SimulationConfig.model_validate_json(json.dumps(payload))
        for settings in (
            {"kind": "powerseries"},
            {"kind": "powerseries", "power": 0.5, "bluffness": 0.2},
        ):
            with self.subTest(settings=settings), self.assertRaises(ValidationError):
                NoseConeConfig(position=0, length=0.2, rocket_radius=0.025, **settings)

    def test_bridge_and_telemetry_boundaries(self):
        bridge = DesktopBridge()
        self.assertIn("$defs", bridge.get_config_schema("simulation"))
        encoded = simulation_config().model_dump_json()
        self.assertEqual(
            bridge.validate_config("simulation", encoded)["motor"]["motor_type"],
            "generic",
        )
        with self.assertRaisesRegex(RuntimeError, "not configured"):
            bridge.submit_simulation(encoded)
        for value in (None, {}, 1):
            with self.subTest(value=value), self.assertRaises(TypeError):
                bridge.validate_config("flight", value)
        with self.assertRaisesRegex(ValueError, "2 MiB"):
            bridge.submit_simulation(" " * (2 * 1024**2 + 1))
        for query in (
            {"columns": ["unknown"]},
            {"columns": ["x_m", "x_m"]},
            {"max_points": 10_001},
            {"max_points": True},
            {"start_time": 2, "end_time": 1},
        ):
            with self.subTest(query=query), self.assertRaises(ValidationError):
                TelemetryQuery.model_validate_json(json.dumps(query))


class RunStoreTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = RunStore(self.root)
        self.addCleanup(self.store.close)

    def test_single_owner_recovery_and_history_survive_reopening(self):
        with self.assertRaisesRegex(RuntimeError, "already in use"):
            RunStore(self.root)
        run_id = self.store.create(simulation_config())
        self.store.update(run_id, "running", pid=123)
        self.store.close()
        self.store = RunStore(self.root)
        self.addCleanup(self.store.close)
        self.assertEqual(self.store.get(run_id)["state"], "interrupted")
        self.assertEqual(self.store.list_runs()[0]["run_id"], run_id)
        for run in ("../escape", "x" * 32, "0" * 31):
            with self.subTest(run=run), self.assertRaises(ValueError):
                self.store.get(run)
        for limit, offset in ((True, 0), (1001, 0), (1, -1)):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                self.store.list_runs(limit, offset)

    def test_input_files_are_snapshotted_and_confined(self):
        curve = self.store.inputs / "wind.csv"
        curve.write_text("0,0\n1000,10\n")
        payload = simulation_config().model_dump(mode="json")
        payload["environment"]["wind_u"] = "wind.csv"
        payload["environment"]["atmosphere_type"] = "custom_atmosphere"
        run_id = self.store.create(
            SimulationConfig.model_validate_json(json.dumps(payload))
        )
        saved = read_json(self.store.run_directory(run_id) / "input.json")
        copied = Path(saved["environment"]["wind_u"])
        curve.write_text("changed")
        self.assertEqual(copied.read_text(), "0,0\n1000,10\n")
        outside = self.root / "outside.csv"
        outside.write_text("0,0\n1000,10\n")
        for path in (str(outside), "../outside.csv"):
            payload["environment"]["wind_u"] = path
            with (
                self.subTest(path=path),
                self.assertRaisesRegex(ValueError, "under data-dir/inputs"),
            ):
                self.store.create(
                    SimulationConfig.model_validate_json(json.dumps(payload))
                )
        self.assertEqual(len(self.store.list_runs()), 1)
        payload["environment"]["wind_u"] = "wind.csv"
        with (
            patch("app.storage.MAX_INPUT_FILE_BYTES", 1),
            self.assertRaisesRegex(ValueError, "snapshot limit"),
        ):
            self.store.create(SimulationConfig.model_validate_json(json.dumps(payload)))

    def test_failed_writes_do_not_publish_or_overwrite_results(self):
        directory = self.store.run_directory(self.store.create(simulation_config()))
        with (
            patch("app.storage.np.save", side_effect=OSError("disk full")),
            self.assertRaises(OSError),
        ):
            save_result(directory, np.zeros((2, 14)), {})
        self.assertFalse((directory / "complete.json").exists())
        self.assertFalse(list(directory.glob("*.tmp")))
        path = directory / "example.json"
        atomic_json(path, {"old": 1})
        with self.assertRaises(ValueError):
            atomic_json(path, {"bad": float("nan")})
        self.assertEqual(read_json(path), {"old": 1})
        save_result(directory, np.zeros((2, 14)), {"old": 1})
        with self.assertRaises(FileExistsError):
            save_result(directory, np.ones((2, 14)), {"new": 1})
        self.assertEqual(read_json(directory / "summary.json"), {"old": 1})

    def test_bounded_telemetry_preserves_extrema_events_and_time_range(self):
        run_id = self.store.create(simulation_config())
        data = np.zeros((10_001, 14))
        data[:, 0] = np.arange(len(data)) * 0.01
        data[:, 3] = np.sin(data[:, 0])
        data[1234, 3] = 1000
        data[5678, 4] = -1000
        summary = {
            "apogee_time_s": data[1234, 0],
            "parachute_events": [{"trigger_time_s": data[7777, 0]}],
        }
        save_result(self.store.run_directory(run_id), data, summary)
        with self.assertRaisesRegex(ValueError, "succeeded"):
            self.store.get_telemetry(run_id, TelemetryQuery())
        self.store.update(run_id, "succeeded")
        query = TelemetryQuery(columns=list(TELEMETRY_COLUMNS), max_points=32)
        result = self.store.get_telemetry(run_id, query)
        self.assertLessEqual(result["returned_rows"], 32)
        selected = np.asarray(result["data"])
        self.assertEqual(selected[:, 3].max(), 1000)
        self.assertEqual(selected[:, 4].min(), -1000)
        self.assertIn(data[7777, 0], selected[:, 0])
        self.assertEqual((selected[0, 0], selected[-1, 0]), (0, 100))
        result = self.store.get_telemetry(
            run_id,
            TelemetryQuery(
                start_time=20,
                end_time=40,
                max_points=32,
            ),
        )
        self.assertTrue(all(20 <= row[0] <= 40 for row in result["data"]))
        self.assertLessEqual(result["returned_rows"], 32)
        result = self.store.get_telemetry(run_id, TelemetryQuery(start_time=200))
        self.assertEqual(result["data"], [])


class JobManagerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def manager(self, **options):
        manager = JobManager(self.root, **options)
        self.addCleanup(manager.close)
        return manager

    def test_real_spawn_run_bridge_results_and_reopen(self):
        manager = self.manager()
        bridge = DesktopBridge(manager)
        start = monotonic()
        record = bridge.submit_simulation(simulation_config().model_dump_json())
        self.assertLess(monotonic() - start, 2)
        run_id = record["run_id"]
        record = wait_for(manager, run_id)
        self.assertEqual(record["state"], "succeeded", record)
        self.assertNotEqual(record["worker_pid"], os.getpid())
        self.assertEqual(bridge.get_summary(run_id)["termination_reason"], "impact")
        rows = bridge.get_telemetry(run_id, '{"max_points":32}')
        self.assertLessEqual(rows["returned_rows"], 32)
        self.assertEqual(bridge.list_runs()[0]["run_id"], run_id)
        self.assertEqual(bridge.cancel_run(run_id)["state"], "succeeded")
        self.assertTrue((self.root / "runs" / run_id / "complete.json").exists())
        manager.close()
        with JobManager(self.root) as reopened:
            self.assertEqual(reopened.get_run(run_id)["state"], "succeeded")
            self.assertEqual(
                reopened.get_summary(run_id)["termination_reason"], "impact"
            )

    def test_queue_limit_and_queued_and_running_cancellation(self):
        manager = self.manager(max_workers=1, max_pending=1)
        first = manager.submit(simulation_config(dense=True))["run_id"]
        first_record = wait_for(manager, first, {"running"}, stage="simulating")
        second = manager.submit(simulation_config())["run_id"]
        with self.assertRaisesRegex(RuntimeError, "queue is full"):
            manager.submit(simulation_config())
        self.assertEqual(manager.cancel(second)["state"], "cancelled")
        self.assertEqual(manager.cancel(first)["state"], "cancelling")
        self.assertEqual(wait_for(manager, first)["state"], "cancelled")
        third = manager.submit(simulation_config())["run_id"]
        self.assertEqual(wait_for(manager, third)["state"], "succeeded")
        self.assertNotEqual(
            first_record["worker_pid"], manager.get_run(third)["worker_pid"]
        )

    def test_all_motor_types_finish_in_spawn_workers(self):
        manager = self.manager()
        for kind in ("solid", "liquid", "hybrid"):
            with self.subTest(kind=kind):
                run_id = manager.submit(simulation_config(kind))["run_id"]
                record = wait_for(manager, run_id)
                self.assertEqual(record["state"], "succeeded", record)
                self.assertTrue(manager.get_summary(run_id)["apogee_reached"])

    def test_two_workers_are_separate_and_close_reaps_them(self):
        manager = self.manager(max_workers=2, max_pending=0)
        ids = [
            manager.submit(simulation_config(dense=True))["run_id"] for _ in range(2)
        ]
        records = [
            wait_for(manager, run_id, {"running"}, stage="simulating") for run_id in ids
        ]
        self.assertEqual(len({record["worker_pid"] for record in records}), 2)
        with self.assertRaisesRegex(RuntimeError, "queue is full"):
            manager.submit(simulation_config())
        manager.close()
        active = {child.pid for child in multiprocessing.active_children()}
        self.assertTrue(all(record["worker_pid"] not in active for record in records))
        store = RunStore(self.root)
        self.addCleanup(store.close)
        self.assertTrue(
            all(store.get(run_id)["state"] == "cancelled" for run_id in ids)
        )

    def test_wall_clock_timeout(self):
        manager = self.manager(timeout_seconds=0.01)
        run_id = manager.submit(simulation_config(dense=True))["run_id"]
        record = wait_for(manager, run_id)
        self.assertEqual(record["state"], "timed_out", record)
        self.assertIn("wall-clock", record["error"])

    @unittest.skipUnless(sys.platform == "linux", "Linux /proc RSS monitor")
    def test_memory_limit(self):
        manager = self.manager(memory_limit_mb=1)
        run_id = manager.submit(simulation_config(dense=True))["run_id"]
        record = wait_for(manager, run_id)
        self.assertEqual(record["state"], "failed", record)
        self.assertIn("memory limit", record["error"])

    def test_solver_failure_does_not_prevent_the_next_run(self):
        manager = self.manager()
        (self.root / "inputs" / "broken.csv").write_text(
            "time,thrust\n0,broken\n1,broken\n"
        )
        payload = simulation_config().model_dump(mode="json")
        payload["motor"]["thrust_source"] = "broken.csv"
        run_id = manager.submit(
            SimulationConfig.model_validate_json(json.dumps(payload))
        )["run_id"]
        record = wait_for(manager, run_id)
        self.assertEqual(record["state"], "failed", record)
        self.assertTrue(record["error"])
        with self.assertRaises(ValueError):
            manager.get_summary(run_id)
        next_id = manager.submit(simulation_config())["run_id"]
        self.assertEqual(wait_for(manager, next_id)["state"], "succeeded")

    def test_crashed_worker_is_reaped(self):
        manager = self.manager()
        run_id = manager.submit(simulation_config(dense=True))["run_id"]
        record = wait_for(manager, run_id, {"running"}, stage="simulating")
        os.kill(record["worker_pid"], signal.SIGTERM)
        self.assertEqual(wait_for(manager, run_id)["state"], "failed")

    def test_invalid_settings_and_closed_manager(self):
        for options in (
            {"max_workers": 0},
            {"max_workers": True},
            {"max_pending": -1},
            {"timeout_seconds": float("nan")},
            {"timeout_seconds": True},
            {"memory_limit_mb": -1},
        ):
            with self.subTest(options=options), self.assertRaises(ValueError):
                JobManager(self.root, **options)
        manager = self.manager()
        manager.close()
        with self.assertRaisesRegex(RuntimeError, "closed"):
            manager.submit(simulation_config())

    def test_supervisor_failure_marks_active_and_pending_runs_failed(self):
        manager = self.manager(max_pending=1)
        first = manager.submit(simulation_config(dense=True))["run_id"]
        wait_for(manager, first, {"running"}, stage="simulating")
        second = manager.submit(simulation_config())["run_id"]
        with (
            self.assertLogs(level="ERROR"),
            patch.object(manager, "_rss_bytes", side_effect=OSError("monitor failed")),
        ):
            self.assertEqual(wait_for(manager, first)["state"], "failed")
            self.assertEqual(wait_for(manager, second)["state"], "failed")
        with self.assertRaisesRegex(RuntimeError, "supervisor failed"):
            manager.close()


class SimulationCommandTests(unittest.TestCase):
    def test_example_runs_headlessly_and_rejects_invalid_inputs(self):
        example = Path(__file__).resolve().parents[2] / "examples" / "simulation.json"
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary) / "data"
            command = [
                sys.executable,
                "-m",
                "app.simulation",
                str(example),
                "--data-dir",
                str(data),
            ]
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=30, check=True
            )
            output = json.loads(result.stdout)
            self.assertEqual(output["summary"]["termination_reason"], "impact")
            store = RunStore(data)
            self.addCleanup(store.close)
            self.assertEqual(store.get(output["run_id"])["state"], "succeeded")
            invalid = Path(temporary) / "invalid.json"
            invalid.write_text('{"unexpected": true}')
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "app.simulation",
                    str(invalid),
                    "--data-dir",
                    str(Path(temporary) / "unused"),
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 2)
            self.assertFalse((Path(temporary) / "unused").exists())

    @unittest.skipUnless(sys.platform == "linux", "Linux process exit observation")
    def test_interrupt_and_host_death_leave_no_running_worker(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "input.json"
            source.write_text(simulation_config(dense=True).model_dump_json())
            for interrupt in (signal.SIGINT, signal.SIGTERM):
                with self.subTest(interrupt=interrupt):
                    data = root / str(interrupt.value)
                    process = subprocess.Popen(
                        [
                            sys.executable,
                            "-m",
                            "app.simulation",
                            str(source),
                            "--data-dir",
                            str(data),
                        ],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE,
                    )
                    child_pid = None
                    selector = selectors.DefaultSelector()
                    selector.register(process.stderr, selectors.EVENT_READ)
                    try:
                        deadline = monotonic() + 15
                        output = b""
                        while b"simulating" not in output:
                            if monotonic() >= deadline:
                                self.fail(f"CLI did not start the solver: {output!r}")
                            if selector.select(0.2):
                                chunk = os.read(process.stderr.fileno(), 4096)
                                self.assertTrue(chunk, f"CLI exited early: {output!r}")
                                output += chunk
                        connection = sqlite3.connect(data / "uarc.sqlite3")
                        try:
                            run_id, child_pid = connection.execute(
                                "SELECT run_id, worker_pid FROM runs"
                            ).fetchone()
                        finally:
                            connection.close()
                        process.send_signal(interrupt)
                        self.assertEqual(
                            process.wait(timeout=5),
                            130 if interrupt == signal.SIGINT else -signal.SIGTERM,
                        )
                        deadline = monotonic() + 5
                        while monotonic() < deadline:
                            try:
                                state = Path(f"/proc/{child_pid}/status").read_text()
                            except FileNotFoundError:
                                break
                            if "State:\tZ" in state:
                                break
                            sleep(0.05)
                        else:
                            os.kill(child_pid, signal.SIGKILL)
                            self.fail("Worker survived host exit.")
                        store = RunStore(data)
                        try:
                            self.assertEqual(
                                store.get(run_id)["state"],
                                "cancelled"
                                if interrupt == signal.SIGINT
                                else "interrupted",
                            )
                        finally:
                            store.close()
                    finally:
                        selector.close()
                        if process.poll() is None:
                            process.kill()
                        process.wait(timeout=5)
                        process.stderr.close()


if __name__ == "__main__":
    unittest.main()
