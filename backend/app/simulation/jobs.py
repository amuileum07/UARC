"""Bounded scheduling with one disposable spawn process per running simulation."""

import logging
import math
import multiprocessing
import os
import sqlite3
import sys
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from threading import Condition, Lock, Thread
from time import monotonic

from app.design import compile_design
from app.importers.openrocket import import_openrocket
from app.importers.weather import import_weather_file, preview_weather_file
from app.schemas import (
    OpenRocketOptions,
    RocketDesign,
    SimulationConfig,
    TelemetryQuery,
    WeatherImportOptions,
)
from app.simulation.worker import run_worker
from app.storage import TERMINAL_STATES, RunStore, read_json

_SPAWN_LOCK = Lock()
_THREAD_LIMITS = ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")
_LOGGER = logging.getLogger(__name__)


@dataclass
class _Running:
    process: multiprocessing.Process
    started: float
    stage: str = "starting"
    stop_state: str | None = None
    stop_error: str | None = None
    stopped_at: float | None = None
    peak_rss_bytes: int = 0


class JobManager:
    def __init__(
        self,
        directory: Path,
        *,
        max_workers: int = 1,
        max_pending: int = 8,
        timeout_seconds: float = 300,
        memory_limit_mb: int | None = 1024 if sys.platform == "linux" else None,
    ):
        if type(max_workers) is not int or not 1 <= max_workers <= 64:
            raise ValueError("max_workers must be an integer between 1 and 64.")
        if type(max_pending) is not int or not 0 <= max_pending <= 10_000:
            raise ValueError("max_pending must be an integer between 0 and 10000.")
        if isinstance(timeout_seconds, bool) or not isinstance(
            timeout_seconds, (int, float)
        ):
            raise ValueError("timeout_seconds must be a finite positive number.")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be a finite positive number.")
        if memory_limit_mb is not None:
            if type(memory_limit_mb) is not int or memory_limit_mb <= 0:
                raise ValueError("memory_limit_mb must be a positive integer or None.")
            if sys.platform != "linux":
                raise ValueError("RSS limits currently require Linux /proc.")
        self._max_workers = max_workers
        self._capacity = max_workers + max_pending
        self._timeout = timeout_seconds
        self._memory_limit = (
            None if memory_limit_mb is None else memory_limit_mb * 1024**2
        )
        self._context = multiprocessing.get_context("spawn")
        self._condition = Condition()
        self._pending: deque[str] = deque()
        self._running: dict[str, _Running] = {}
        self._closing = False
        self._closed = False
        self._fatal: Exception | None = None
        self._store = RunStore(directory)
        self._thread = Thread(target=self._monitor, name="simulation-jobs", daemon=True)
        try:
            self._thread.start()
        except Exception:
            self._store.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def submit(self, config: SimulationConfig) -> dict:
        if not isinstance(config, SimulationConfig):
            raise TypeError("submit requires a SimulationConfig.")
        # Detach from a caller's mutable DTO before persisting or starting work.
        config = SimulationConfig.model_validate_json(config.model_dump_json())
        return self._submit(config)

    def submit_design(self, design: RocketDesign) -> dict:
        if not isinstance(design, RocketDesign):
            raise TypeError("submit_design requires a RocketDesign.")
        with self._condition:
            self._check_capacity()
        design = RocketDesign.model_validate_json(design.model_dump_json())
        config, report = compile_design(design)
        return self._submit(config, design=design, report=report)

    def _check_capacity(self) -> None:
        if self._closing or self._closed or self._fatal is not None:
            raise RuntimeError("The simulation manager is closed or unavailable.")
        if len(self._pending) + len(self._running) >= self._capacity:
            raise RuntimeError("Simulation queue is full; wait for a run to finish.")

    def _submit(
        self,
        config: SimulationConfig,
        *,
        design: RocketDesign | None = None,
        report: dict | None = None,
    ) -> dict:
        with self._condition:
            self._check_capacity()
            run_id = self._store.create(config, design=design, report=report)
            self._pending.append(run_id)
            _LOGGER.info("Run queued run_id=%s", run_id)
            self._condition.notify_all()
            return self._store.get(run_id)

    def get_design(self, run_id: str) -> dict:
        return self._store.get_design(run_id)

    def get_design_report(self, run_id: str) -> dict:
        return self._store.get_design_report(run_id)

    def save_design(self, design: RocketDesign) -> dict:
        design = RocketDesign.model_validate_json(design.model_dump_json())
        config, _ = compile_design(design)
        with self._condition:
            if self._closing or self._closed or self._fatal is not None:
                raise RuntimeError("The simulation manager is closed or unavailable.")
            return self._store.save_design(design, config)

    def get_saved_design(self, design_id: str) -> dict:
        return self._store.get_saved_design(design_id)

    def list_designs(self, limit: int = 50, offset: int = 0) -> list[dict]:
        return self._store.list_designs(limit, offset)

    def import_file(self, source: Path) -> dict:
        return self._store.import_file(source)

    def import_openrocket(self, name: str, options: OpenRocketOptions) -> dict:
        source = self._store.input_path(name)
        return import_openrocket(source, options).model_dump(mode="json")

    def preview_weather_file(self, name: str, sheet: str | None = None) -> dict:
        return preview_weather_file(self._store.input_path(name), sheet).model_dump(
            mode="json"
        )

    def import_weather_file(self, name: str, options: WeatherImportOptions) -> dict:
        return import_weather_file(self._store.input_path(name), options).model_dump(
            mode="json"
        )

    def export_csv(self, run_id: str, destination: Path) -> Path:
        return self._store.export_csv(run_id, destination)

    def rerun(self, run_id: str) -> dict:
        if self._store.get(run_id)["state"] not in TERMINAL_STATES:
            raise ValueError("Only finished runs can be submitted again.")
        directory = self._store.run_directory(run_id)
        config = SimulationConfig.model_validate_json(
            (directory / "input.json").read_text(encoding="utf-8")
        )
        design, report = None, None
        if (directory / "design.json").is_file():
            design = RocketDesign.model_validate_json(
                (directory / "design.json").read_text(encoding="utf-8")
            )
            report = self._store.get_design_report(run_id)
        return self._submit(config, design=design, report=report)

    def get_run(self, run_id: str) -> dict:
        with self._condition:
            result = self._store.get(run_id)
            running = self._running.get(run_id)
            if running is not None:
                result["peak_rss_bytes"] = running.peak_rss_bytes
            return result

    def list_runs(self, limit: int = 50, offset: int = 0) -> list[dict]:
        return self._store.list_runs(limit, offset)

    def get_summary(self, run_id: str) -> dict:
        return self._store.get_summary(run_id)

    def get_telemetry(self, run_id: str, query: TelemetryQuery) -> dict:
        return self._store.get_telemetry(run_id, query)

    def cancel(self, run_id: str) -> dict:
        with self._condition:
            record = self._store.get(run_id)
            if record["state"] in TERMINAL_STATES:
                return record
            if run_id in self._pending:
                self._pending.remove(run_id)
                self._store.update(run_id, "cancelled")
            else:
                running = self._running[run_id]
                running.stop_state = "cancelled"
                running.stop_error = "Cancelled by the user."
                self._store.update(run_id, "cancelling")
            self._condition.notify_all()
            return self._store.get(run_id)

    def _start(self, run_id: str) -> None:
        process = self._context.Process(
            target=run_worker,
            args=(str(self._store.run_directory(run_id)),),
            name=f"simulation-{run_id[:8]}",
            daemon=True,
        )
        try:
            # Spawn imports the entry module before its target. Set limits before
            # start(), then restore the host environment under a shared spawn lock.
            with _SPAWN_LOCK:
                original = {name: os.environ.get(name) for name in _THREAD_LIMITS}
                try:
                    for name in _THREAD_LIMITS:
                        os.environ[name] = "1"
                    process.start()
                finally:
                    for name, value in original.items():
                        if value is None:
                            os.environ.pop(name, None)
                        else:
                            os.environ[name] = value
            self._running[run_id] = _Running(process, monotonic())
            self._store.update(run_id, "running", stage="starting", pid=process.pid)
            _LOGGER.info("Worker started run_id=%s pid=%s", run_id, process.pid)
        except Exception as error:
            _LOGGER.exception("Cannot start worker run_id=%s", run_id)
            if process.pid is not None:
                process.terminate()
                process.join(2)
                if process.is_alive():
                    process.kill()
                    process.join()
            process.close()
            self._running.pop(run_id, None)
            self._store.update(
                run_id, "failed", error=f"Cannot start worker: {error}"[:4096]
            )

    @staticmethod
    def _rss_bytes(pid: int) -> int:
        if sys.platform != "linux":
            return 0
        try:
            for line in Path(f"/proc/{pid}/status").read_text().splitlines():
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
        except (FileNotFoundError, ProcessLookupError):
            pass
        return 0

    def _tick(self) -> None:
        now = monotonic()
        for run_id, running in list(self._running.items()):
            process = running.process
            directory = self._store.run_directory(run_id)
            if process.exitcode is not None:
                process.join()
                state, error = running.stop_state, running.stop_error
                if state is None:
                    if (
                        process.exitcode == 0
                        and (directory / "complete.json").is_file()
                    ):
                        state = "succeeded"
                    else:
                        state = "failed"
                        error = f"Worker exited with code {process.exitcode}."
                        if (directory / "error.json").is_file():
                            error = read_json(directory / "error.json")["message"]
                self._store.update(
                    run_id, state, error=error, peak_rss_bytes=running.peak_rss_bytes
                )
                _LOGGER.log(
                    logging.INFO
                    if state in {"succeeded", "cancelled"}
                    else logging.ERROR,
                    "Worker finished run_id=%s pid=%s state=%s exitcode=%s error=%s",
                    run_id,
                    process.pid,
                    state,
                    process.exitcode,
                    error,
                )
                process.close()
                del self._running[run_id]
                continue
            rss = self._rss_bytes(process.pid)
            running.peak_rss_bytes = max(running.peak_rss_bytes, rss)
            if running.stop_state is None:
                if now - running.started >= self._timeout:
                    running.stop_state = "timed_out"
                    running.stop_error = "Worker exceeded the wall-clock time limit."
                elif self._memory_limit is not None and rss > self._memory_limit:
                    running.stop_state = "failed"
                    running.stop_error = "Worker exceeded the RSS memory limit."
            if running.stop_state is not None:
                if running.stopped_at is None:
                    _LOGGER.warning(
                        "Stopping worker run_id=%s pid=%s state=%s reason=%s",
                        run_id,
                        process.pid,
                        running.stop_state,
                        running.stop_error,
                    )
                    self._store.update(run_id, "cancelling", error=running.stop_error)
                    process.terminate()
                    running.stopped_at = now
                elif now - running.stopped_at >= 1:
                    process.kill()
                continue
            progress = directory / "progress.json"
            if progress.is_file():
                stage = read_json(progress)["stage"]
                if stage != running.stage:
                    running.stage = stage
                    self._store.update(run_id, "running", stage=stage)
        while (
            not self._closing
            and self._pending
            and len(self._running) < self._max_workers
        ):
            self._start(self._pending.popleft())

    def _monitor(self) -> None:
        try:
            with self._condition:
                while True:
                    self._tick()
                    if self._closing and not self._running:
                        return
                    self._condition.wait(0.1)
        except Exception as error:
            _LOGGER.exception("Simulation supervisor failed")
            with self._condition:
                self._fatal = error
                self._closing = True
                for run_id, running in self._running.items():
                    process = running.process
                    if process.is_alive():
                        process.kill()
                    process.join()
                    process.close()
                    try:
                        self._store.update(
                            run_id,
                            "failed",
                            error=f"Supervisor failed: {error}"[:4096],
                            peak_rss_bytes=running.peak_rss_bytes,
                        )
                    except sqlite3.Error:
                        _LOGGER.exception("Cannot persist failed run %s", run_id)
                self._running.clear()
                while self._pending:
                    run_id = self._pending.popleft()
                    try:
                        self._store.update(
                            run_id,
                            "failed",
                            error="Supervisor failed before execution.",
                        )
                    except sqlite3.Error:
                        _LOGGER.exception("Cannot persist queued run %s", run_id)

    def close(self) -> None:
        with self._condition:
            if self._closed:
                return
            self._closing = True
            while self._pending:
                self._store.update(
                    self._pending.popleft(),
                    "cancelled",
                    error="Application is closing.",
                )
            for running in self._running.values():
                running.stop_state = "cancelled"
                running.stop_error = "Application is closing."
            self._condition.notify_all()
        self._thread.join(timeout=5)
        if self._thread.is_alive():
            raise RuntimeError("Simulation supervisor did not stop.")
        with self._condition:
            self._store.close()
            self._closed = True
        if self._fatal is not None:
            raise RuntimeError("Simulation supervisor failed.") from self._fatal
