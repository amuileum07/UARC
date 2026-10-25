"""Single-owner run metadata and immutable, atomically published result files."""

import json
import os
import re
import shutil
import sqlite3
import tempfile
from bisect import bisect_left, bisect_right
from datetime import UTC, datetime
from pathlib import Path
from threading import BoundedSemaphore, RLock
from uuid import UUID, uuid4

import numpy as np

from app.schemas import (
    TELEMETRY_COLUMNS,
    RocketDesign,
    SimulationConfig,
    TelemetryQuery,
)

TERMINAL_STATES = frozenset(
    {"succeeded", "failed", "cancelled", "timed_out", "interrupted"}
)
MAX_PAYLOAD_BYTES = 2 * 1024**2
MAX_INPUT_FILE_BYTES = 64 * 1024**2


def atomic_json(path: Path, value: object) -> None:
    """Publish a complete JSON file; failed writes leave the old file intact."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, allow_nan=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def read_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def save_result(directory: Path, solution: np.ndarray, summary: dict) -> None:
    """Publish the completion marker only after both result files are durable."""
    if (directory / "complete.json").exists():
        raise FileExistsError("A published run cannot be overwritten.")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=directory, prefix=".telemetry.", suffix=".tmp", delete=False
        ) as stream:
            temporary = Path(stream.name)
            np.save(stream, solution, allow_pickle=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, directory / "telemetry.npy")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    atomic_json(directory / "summary.json", summary)
    atomic_json(
        directory / "complete.json",
        {
            "version": 1,
            "rows": len(solution),
            "columns": list(TELEMETRY_COLUMNS),
        },
    )


class RunStore:
    def __init__(self, directory: Path):
        self.directory = directory.expanduser().resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.runs = self.directory / "runs"
        self.inputs = self.directory / "inputs"
        self.runs.mkdir(exist_ok=True)
        self.inputs.mkdir(exist_ok=True)
        self._lock = RLock()
        self._read_slots = BoundedSemaphore(2)
        self._closed = False
        self._owner = (self.directory / ".owner.lock").open("a+b")
        try:
            if os.name == "nt":
                import msvcrt

                self._owner.write(b"\0")
                self._owner.flush()
                self._owner.seek(0)
                msvcrt.locking(self._owner.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._owner.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self._owner.close()
            raise RuntimeError("This data directory is already in use.") from error
        try:
            self._db = sqlite3.connect(
                self.directory / "uarc.sqlite3", check_same_thread=False
            )
            self._db.row_factory = sqlite3.Row
            with self._db:
                self._db.execute("""
                    CREATE TABLE IF NOT EXISTS runs (
                        run_id TEXT PRIMARY KEY,
                        state TEXT NOT NULL CHECK (state IN (
                            'queued', 'running', 'cancelling', 'succeeded', 'failed',
                            'cancelled', 'timed_out', 'interrupted'
                        )),
                        stage TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        started_at TEXT,
                        finished_at TEXT,
                        worker_pid INTEGER,
                        peak_rss_bytes INTEGER NOT NULL DEFAULT 0,
                        error TEXT
                    )
                """)
                self._db.execute(
                    "CREATE INDEX IF NOT EXISTS runs_created ON runs (created_at DESC, run_id)"
                )
                self._db.execute(
                    "UPDATE runs SET state='interrupted', stage='interrupted', "
                    "finished_at=?, error='Application exited before completion.' "
                    "WHERE state IN ('queued', 'running', 'cancelling')",
                    (datetime.now(UTC).isoformat(),),
                )
        except Exception:
            if hasattr(self, "_db"):
                self._db.close()
            self._owner.close()
            raise

    def run_directory(self, run_id: str) -> Path:
        if not isinstance(run_id, str) or len(run_id) != 32:
            raise ValueError("Invalid run ID.")
        try:
            if UUID(hex=run_id).hex != run_id:
                raise ValueError("Invalid run ID.")
        except ValueError as error:
            raise ValueError("Invalid run ID.") from error
        path = (self.runs / run_id).resolve()
        if path.parent != self.runs:
            raise ValueError("Run directory must remain inside the data directory.")
        return path

    def create(
        self,
        config: SimulationConfig,
        *,
        design: RocketDesign | None = None,
        report: dict | None = None,
    ) -> str:
        if (design is None) != (report is None):
            raise ValueError(
                "A parametric design and its report must be stored together."
            )
        payload = config.model_dump(mode="json")
        if len(json.dumps(payload).encode("utf-8")) > MAX_PAYLOAD_BYTES:
            raise ValueError("Simulation input exceeds the 2 MiB payload limit.")
        if (
            design is not None
            and len(design.model_dump_json().encode("utf-8")) > MAX_PAYLOAD_BYTES
        ):
            raise ValueError("Design input exceeds the 2 MiB payload limit.")
        run_id = uuid4().hex
        directory = self.run_directory(run_id)
        directory.mkdir()
        try:
            self._snapshot_files(payload, directory)
            atomic_json(directory / "input.json", payload)
            if design is not None:
                editable = design.model_dump(mode="json")
                for field in ("environment", "motor", "tanks"):
                    editable[field] = payload[field]
                for field in ("power_off_drag", "power_on_drag"):
                    editable[field] = payload["rocket"][field]
                atomic_json(directory / "design.json", editable)
                atomic_json(directory / "design_report.json", report)
            with self._lock, self._db:
                self._db.execute(
                    "INSERT INTO runs (run_id, state, stage, created_at) "
                    "VALUES (?, 'queued', 'queued', ?)",
                    (run_id, datetime.now(UTC).isoformat()),
                )
        except Exception:
            shutil.rmtree(directory)
            raise
        return run_id

    def _authorized_input(self, source: Path) -> bool:
        if not source.is_file():
            return False
        if source.is_relative_to(self.inputs):
            return True
        # Permit only copied input assets of known runs, never their metadata or
        # arbitrary files. This keeps saved designs editable after originals move.
        if source.parent.parent == self.runs and re.fullmatch(
            r"input-\d+(?:\.[^/]+)?", source.name
        ):
            self.get(source.parent.name)
            return self.run_directory(source.parent.name) == source.parent
        return False

    def _snapshot_files(self, payload: dict, directory: Path) -> None:
        references = [
            (payload["environment"], key)
            for key in ("pressure", "temperature", "wind_u", "wind_v")
        ] + [(payload["rocket"], key) for key in ("power_off_drag", "power_on_drag")]
        if payload["motor"] is not None:
            references.append((payload["motor"], "thrust_source"))
        for tank in payload["tanks"]:
            references.extend((tank, key) for key in ("liquid_mass", "gas_mass"))
        weather = payload["environment"]
        source = weather["atmosphere_file"]
        if source is not None and (
            weather["atmosphere_type"] not in {"forecast", "ensemble", "windy"}
            or "/" in source
            or "\\" in source
        ):
            references.append((weather, "atmosphere_file"))
        remaining = MAX_INPUT_FILE_BYTES
        copied = {}
        for index, (model, field) in enumerate(references):
            if not isinstance(model[field], str):
                continue
            source = Path(model[field]).expanduser()
            if not source.is_absolute():
                source = self.inputs / source
            source = source.resolve(strict=True)
            if not self._authorized_input(source):
                raise ValueError(
                    "Input files must be under data-dir/inputs or be a known run's copied input asset."
                )
            if source in copied:
                model[field] = str(copied[source])
                continue
            destination = directory / f"input-{index}{source.suffix}"
            with source.open("rb") as reader, destination.open("xb") as writer:
                before = os.fstat(reader.fileno())
                if before.st_size > remaining:
                    raise ValueError("Input files exceed the 64 MiB snapshot limit.")
                while chunk := reader.read(64 * 1024):
                    remaining -= len(chunk)
                    if remaining < 0:
                        raise ValueError(
                            "Input files exceed the 64 MiB snapshot limit."
                        )
                    writer.write(chunk)
                after = os.fstat(reader.fileno())
                if (before.st_size, before.st_mtime_ns) != (
                    after.st_size,
                    after.st_mtime_ns,
                ):
                    raise ValueError("An input file changed while it was being copied.")
                writer.flush()
                os.fsync(writer.fileno())
            model[field] = str(destination)
            copied[source] = destination

    def get(self, run_id: str) -> dict:
        self.run_directory(run_id)
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM runs WHERE run_id=?", (run_id,)
            ).fetchone()
        if row is None:
            raise ValueError("Unknown run ID.")
        return dict(row)

    def list_runs(self, limit: int = 50, offset: int = 0) -> list[dict]:
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("limit must be an integer between 1 and 1000.")
        if type(offset) is not int or not 0 <= offset <= 2**31 - 1:
            raise ValueError("offset must be a nonnegative 32-bit integer.")
        with self._lock:
            # OFFSET scans preceding metadata rows; use cursor pagination if
            # histories grow large enough for deep pages to become expensive.
            rows = self._db.execute(
                "SELECT * FROM runs ORDER BY created_at DESC, run_id LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [dict(row) for row in rows]

    def update(
        self,
        run_id: str,
        state: str,
        *,
        stage: str | None = None,
        error: str | None = None,
        pid: int | None = None,
        peak_rss_bytes: int = 0,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        with self._lock, self._db:
            self._db.execute(
                "UPDATE runs SET state=?, stage=?, error=?, "
                "worker_pid=COALESCE(?, worker_pid), "
                "peak_rss_bytes=MAX(peak_rss_bytes, ?), "
                "started_at=CASE WHEN ?='running' THEN COALESCE(started_at, ?) ELSE started_at END, "
                "finished_at=CASE WHEN ? THEN ? ELSE finished_at END WHERE run_id=?",
                (
                    state,
                    stage or state,
                    error,
                    pid,
                    peak_rss_bytes,
                    state,
                    now,
                    state in TERMINAL_STATES,
                    now,
                    run_id,
                ),
            )

    def get_summary(self, run_id: str) -> dict:
        if self.get(run_id)["state"] != "succeeded":
            raise ValueError("Results are available only for succeeded runs.")
        return read_json(self.run_directory(run_id) / "summary.json")

    def get_design(self, run_id: str) -> dict:
        self.get(run_id)
        path = self.run_directory(run_id) / "design.json"
        if not path.is_file():
            raise ValueError("This run has no parametric design.")
        return read_json(path)

    def get_design_report(self, run_id: str) -> dict:
        self.get_design(run_id)
        return read_json(self.run_directory(run_id) / "design_report.json")

    def get_telemetry(self, run_id: str, query: TelemetryQuery) -> dict:
        summary = self.get_summary(run_id)
        if not self._read_slots.acquire(blocking=False):
            raise RuntimeError(
                "Too many telemetry reads; retry after a request completes."
            )
        try:
            data = np.load(
                self.run_directory(run_id) / "telemetry.npy",
                mmap_mode="r",
                allow_pickle=False,
            )
            if data.ndim != 2 or data.shape[1] != len(TELEMETRY_COLUMNS):
                raise RuntimeError("Stored telemetry has an invalid shape.")

            def key(index):
                return float(data[index, 0])

            left = (
                0
                if query.start_time is None
                else bisect_left(range(len(data)), query.start_time, key=key)
            )
            right = (
                len(data)
                if query.end_time is None
                else bisect_right(range(len(data)), query.end_time, key=key)
            )
            columns = [TELEMETRY_COLUMNS.index(name) for name in query.columns]
            count = right - left
            if count <= query.max_points:
                indices = list(range(left, right))
            else:
                required = {left, right - 1}
                events = [summary.get("apogee_time_s")]
                events.extend(
                    event["trigger_time_s"]
                    for event in summary.get("parachute_events", [])
                )
                for time in events:
                    if time is not None and key(left) <= time <= key(right - 1):
                        index = min(
                            bisect_left(range(len(data)), time, key=key), right - 1
                        )
                        if index > left and abs(key(index - 1) - time) < abs(
                            key(index) - time
                        ):
                            index -= 1
                        required.add(index)
                signals = [column for column in columns if column != 0]
                if not signals:
                    signals = [3]
                buckets = (query.max_points - len(required)) // (2 * len(signals))
                if buckets < 1:
                    raise ValueError(
                        "Increase max_points to preserve events and extrema."
                    )
                # Min/max per bucket preserves envelopes; scans use bounded chunks.
                # Very large interactive histories can later add a disk-backed pyramid.
                boundaries = np.linspace(left, right, buckets + 1, dtype=int)
                for start, stop in zip(boundaries, boundaries[1:], strict=False):
                    for column in signals:
                        low = high = int(start)
                        for chunk_start in range(int(start), int(stop), 65_536):
                            chunk = data[
                                chunk_start : min(chunk_start + 65_536, stop), column
                            ]
                            minimum = chunk_start + int(np.argmin(chunk))
                            maximum = chunk_start + int(np.argmax(chunk))
                            if data[minimum, column] < data[low, column]:
                                low = minimum
                            if data[maximum, column] > data[high, column]:
                                high = maximum
                        required.update((low, high))
                indices = sorted(required)
            return {
                "columns": query.columns,
                "data": data[indices][:, columns].tolist(),
                "total_rows": len(data),
                "matched_rows": count,
                "returned_rows": len(indices),
                "decimated": count > len(indices),
            }
        finally:
            self._read_slots.release()

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._db.close()
                self._owner.close()
                self._closed = True
