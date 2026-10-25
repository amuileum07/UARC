"""Small JSON boundary exposed to the desktop UI through pywebview."""

import json
from threading import BoundedSemaphore
from typing import Literal

from pydantic import TypeAdapter

from app.design import compile_design
from app.schemas import (
    EnvironmentConfig,
    FlightConfig,
    MotorConfig,
    RocketConfig,
    RocketDesign,
    SimulationConfig,
    TelemetryQuery,
)
from app.simulation.jobs import JobManager
from app.storage import MAX_PAYLOAD_BYTES

ConfigKind = Literal["environment", "motor", "rocket", "flight", "simulation", "design"]
_CONFIG_ADAPTERS = {
    "environment": TypeAdapter(EnvironmentConfig),
    "motor": TypeAdapter(MotorConfig),
    "rocket": TypeAdapter(RocketConfig),
    "flight": TypeAdapter(FlightConfig),
    "simulation": TypeAdapter(SimulationConfig),
    "design": TypeAdapter(RocketDesign),
}


class DesktopBridge:
    """Public methods are exposed as window.pywebview.api methods.

    Calls validate or submit work promptly; solvers run in disposable processes.
    """

    def __init__(self, jobs: JobManager | None = None):
        self._jobs = jobs
        self._preview_slots = BoundedSemaphore(1)

    @staticmethod
    def _check_payload(payload: str) -> None:
        if not isinstance(payload, str):
            raise TypeError("The payload must be JSON text.")
        if (
            len(payload) > MAX_PAYLOAD_BYTES
            or len(payload.encode("utf-8")) > MAX_PAYLOAD_BYTES
        ):
            raise ValueError("JSON payload exceeds the 2 MiB limit.")

    def _manager(self) -> JobManager:
        if self._jobs is None:
            raise RuntimeError("Simulation services are not configured.")
        return self._jobs

    def validate_config(self, kind: ConfigKind, payload_json: str) -> dict[str, object]:
        """Validate JSON from JS without relaxing strict Python DTO validation.

        JSON mode accepts arrays for tuple fields, such as inertia and curves.
        Validation errors propagate as rejected JavaScript promises.
        """
        self._check_payload(payload_json)
        try:
            adapter = _CONFIG_ADAPTERS[kind]
        except KeyError as error:
            raise ValueError(f"Unknown configuration kind: {kind}") from error
        config = adapter.validate_json(payload_json)
        return json.loads(config.model_dump_json())

    def get_config_schema(self, kind: ConfigKind) -> dict:
        try:
            return _CONFIG_ADAPTERS[kind].json_schema()
        except KeyError as error:
            raise ValueError(f"Unknown configuration kind: {kind}") from error

    def submit_simulation(self, payload_json: str) -> dict:
        self._check_payload(payload_json)
        config = SimulationConfig.model_validate_json(payload_json)
        return self._manager().submit(config)

    def preview_design(self, payload_json: str) -> dict:
        self._check_payload(payload_json)
        design = RocketDesign.model_validate_json(payload_json)
        if not self._preview_slots.acquire(blocking=False):
            raise RuntimeError(
                "A design preview is already running; retry after it finishes."
            )
        try:
            config, report = compile_design(design)
            return {
                "simulation": config.model_dump(mode="json"),
                "mass_properties": report,
            }
        finally:
            self._preview_slots.release()

    def submit_design(self, payload_json: str) -> dict:
        self._check_payload(payload_json)
        return self._manager().submit_design(
            RocketDesign.model_validate_json(payload_json)
        )

    def get_design(self, run_id: str) -> dict:
        return self._manager().get_design(run_id)

    def get_design_report(self, run_id: str) -> dict:
        return self._manager().get_design_report(run_id)

    def rerun(self, run_id: str) -> dict:
        return self._manager().rerun(run_id)

    def get_run(self, run_id: str) -> dict:
        return self._manager().get_run(run_id)

    def list_runs(self, limit: int = 50, offset: int = 0) -> list[dict]:
        return self._manager().list_runs(limit, offset)

    def cancel_run(self, run_id: str) -> dict:
        return self._manager().cancel(run_id)

    def get_summary(self, run_id: str) -> dict:
        return self._manager().get_summary(run_id)

    def get_telemetry(self, run_id: str, query_json: str = "{}") -> dict:
        self._check_payload(query_json)
        return self._manager().get_telemetry(
            run_id, TelemetryQuery.model_validate_json(query_json)
        )
