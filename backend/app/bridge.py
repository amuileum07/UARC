"""Small JSON boundary exposed to the desktop UI through pywebview."""

import json
from pathlib import Path
from threading import BoundedSemaphore
from typing import Literal

from pydantic import TypeAdapter

from app.design import compile_design
from app.schemas import (
    DesignPreview,
    DesignReport,
    EnvironmentConfig,
    FlightConfig,
    FlightSummary,
    ImportedFile,
    MotorConfig,
    OpenRocketImport,
    OpenRocketOptions,
    RocketConfig,
    RocketDesign,
    RunRecord,
    SavedDesignRecord,
    SimulationConfig,
    TelemetryQuery,
    TelemetryResult,
    TerrainRequest,
)
from app.simulation.jobs import JobManager
from app.storage import MAX_PAYLOAD_BYTES
from app.terrain import check_elevation, fetch_terrain

ConfigKind = Literal[
    "environment",
    "motor",
    "rocket",
    "flight",
    "simulation",
    "design",
    "openrocket_options",
]
_CONFIG_ADAPTERS = {
    "environment": TypeAdapter(EnvironmentConfig),
    "motor": TypeAdapter(MotorConfig),
    "rocket": TypeAdapter(RocketConfig),
    "flight": TypeAdapter(FlightConfig),
    "simulation": TypeAdapter(SimulationConfig),
    "design": TypeAdapter(RocketDesign),
    "openrocket_options": TypeAdapter(OpenRocketOptions),
}
_RESULT_MODELS = {
    "run": RunRecord,
    "summary": FlightSummary,
    "telemetry": TelemetryResult,
    "design_report": DesignReport,
    "design_preview": DesignPreview,
    "saved_design": SavedDesignRecord,
    "imported_file": ImportedFile,
    "openrocket": OpenRocketImport,
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

    def get_result_schema(self, kind: str) -> dict:
        try:
            return _RESULT_MODELS[kind].model_json_schema()
        except KeyError as error:
            raise ValueError(f"Unknown result kind: {kind}") from error

    def get_example_design(self) -> dict:
        """Bundled offline starting design, validated through the same DTO."""
        import sys

        root = (
            Path(sys._MEIPASS)
            if getattr(sys, "frozen", False)
            else Path(__file__).resolve().parents[2]
        )
        return RocketDesign.model_validate_json(
            (root / "examples/design.json").read_text()
        ).model_dump(mode="json")

    def get_terrain(self, payload_json: str) -> dict:
        self._check_payload(payload_json)
        return fetch_terrain(
            TerrainRequest.model_validate_json(payload_json)
        ).model_dump(mode="json")

    def check_elevation(self, payload_json: str) -> dict:
        self._check_payload(payload_json)
        return check_elevation(EnvironmentConfig.model_validate_json(payload_json))

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

    def save_design(self, payload_json: str) -> dict:
        self._check_payload(payload_json)
        return self._manager().save_design(
            RocketDesign.model_validate_json(payload_json)
        )

    def get_saved_design(self, design_id: str) -> dict:
        return self._manager().get_saved_design(design_id)

    def list_designs(self, limit: int = 50, offset: int = 0) -> list[dict]:
        return self._manager().list_designs(limit, offset)

    def select_input_file(self) -> dict | None:
        """Only a file explicitly selected in the native dialog may enter inputs/."""
        import webview

        selected = webview.windows[0].create_file_dialog(
            webview.FileDialog.OPEN, allow_multiple=False
        )
        return self._manager().import_file(Path(selected[0])) if selected else None

    def import_openrocket(self, asset_path: str, options_json: str) -> dict:
        self._check_payload(options_json)
        options = OpenRocketOptions.model_validate_json(options_json)
        return self._manager().import_openrocket(asset_path, options)

    def export_csv(self, run_id: str) -> str | None:
        """A native save dialog authorizes the destination; existing files survive."""
        import webview

        self._manager().get_summary(run_id)
        selected = webview.windows[0].create_file_dialog(
            webview.FileDialog.SAVE, save_filename=f"{run_id}.csv"
        )
        if not selected:
            return None
        return str(self._manager().export_csv(run_id, Path(selected[0])))

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
