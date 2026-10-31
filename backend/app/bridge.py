"""Small JSON boundary exposed to the desktop UI through pywebview."""

import json
import logging
from functools import wraps
from inspect import signature
from pathlib import Path
from threading import BoundedSemaphore, Lock
from time import monotonic
from typing import Literal
from uuid import uuid4

from pydantic import TypeAdapter

from app.config import bundled_file
from app.design import compile_design
from app.desktop_runtime import open_external_url
from app.schemas import (
    DesignPreview,
    DesignReport,
    EnvironmentConfig,
    FlightConfig,
    FlightSummary,
    ImportedFile,
    LocationResult,
    LocationSearch,
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
    TerrainImportOptions,
    TerrainRequest,
    WeatherImportOptions,
    WeatherProfile,
    WeatherRequest,
    WeatherTable,
)
from app.schemas.diagnostics import FrontendError
from app.simulation.jobs import JobManager
from app.storage import MAX_PAYLOAD_BYTES
from app.terrain import check_elevation, fetch_terrain
from app.weather import fetch_weather, search_locations

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
    "location": LocationResult,
    "weather": WeatherProfile,
    "weather_table": WeatherTable,
}


_LOGGER = logging.getLogger(__name__)


def _logged_call(method):
    call_signature = signature(method)

    @wraps(method)
    def call(self, *args, **kwargs):
        call_id = uuid4().hex[:12]
        started = monotonic()
        try:
            # Keep payload contents and file paths out of the application log.
            parameters = {
                name: {"type": type(value).__name__, "length": len(value)}
                if isinstance(value, (str, list, dict))
                else {"type": type(value).__name__}
                for name, value in call_signature.bind(
                    self, *args, **kwargs
                ).arguments.items()
                if name != "self"
            }
            _LOGGER.info(
                "Bridge started method=%s call=%s parameters=%s",
                method.__name__,
                call_id,
                json.dumps(parameters),
            )
            result = method(self, *args, **kwargs)
        except Exception:
            _LOGGER.exception(
                "Bridge failed method=%s call=%s elapsed_ms=%.1f",
                method.__name__,
                call_id,
                (monotonic() - started) * 1000,
            )
            raise
        run_id = result.get("run_id") if isinstance(result, dict) else None
        _LOGGER.info(
            "Bridge completed method=%s call=%s elapsed_ms=%.1f run_id=%s",
            method.__name__,
            call_id,
            (monotonic() - started) * 1000,
            run_id,
        )
        return result

    # pywebview 6.2 uses getfullargspec(), which ignores functools.wraps alone.
    call.__signature__ = call_signature
    return call


class DesktopBridge:
    """Public methods are exposed as window.pywebview.api methods.

    Calls validate or submit work promptly; solvers run in disposable processes.
    """

    def __init__(
        self,
        jobs: JobManager | None = None,
        *,
        initial_design: RocketDesign | None = None,
    ):
        self._jobs = jobs
        self._initial_design = initial_design
        self._preview_slots = BoundedSemaphore(1)
        self._site_slots = BoundedSemaphore(2)
        self._error_lock = Lock()
        self._error_window = monotonic()
        self._error_count = 0

    def report_frontend_error(self, payload_json: str) -> bool:
        """Accept bounded diagnostics without accepting a destination path."""
        if not isinstance(payload_json, str) or len(payload_json) > 32_768:
            raise ValueError("Frontend diagnostic exceeds 32 KiB.")
        if len(payload_json.encode("utf-8")) > 32_768:
            raise ValueError("Frontend diagnostic exceeds 32 KiB.")
        report = FrontendError.model_validate_json(payload_json)
        with self._error_lock:
            now = monotonic()
            if now - self._error_window >= 60:
                self._error_window, self._error_count = now, 0
            self._error_count += 1
            if self._error_count > 60:
                if self._error_count == 61:
                    _LOGGER.warning(
                        "Frontend diagnostics rate limit reached (60/minute)"
                    )
                return False
            _LOGGER.error("Frontend error %s", report.model_dump_json())
        return True

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

    @_logged_call
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

    @_logged_call
    def get_config_schema(self, kind: ConfigKind) -> dict:
        try:
            return _CONFIG_ADAPTERS[kind].json_schema()
        except KeyError as error:
            raise ValueError(f"Unknown configuration kind: {kind}") from error

    @_logged_call
    def get_result_schema(self, kind: str) -> dict:
        try:
            return _RESULT_MODELS[kind].model_json_schema()
        except KeyError as error:
            raise ValueError(f"Unknown result kind: {kind}") from error

    @_logged_call
    def get_example_design(self) -> dict:
        """Bundled starting design with terrain-following enabled for the editor."""
        if self._initial_design is not None:
            return self._initial_design.model_dump(mode="json")
        design = RocketDesign.model_validate_json(
            bundled_file("examples/design.json").read_text(encoding="utf-8")
        )
        design.environment.elevation_mode = "terrain"
        return design.model_dump(mode="json")

    @_logged_call
    def get_material_catalog(self) -> dict:
        from app.materials import material_catalog

        return material_catalog()

    @_logged_call
    def open_material_reference(self, reference_id: str) -> bool:
        from app.materials import material_catalog

        sources = material_catalog()["sources"]
        if reference_id not in sources:
            raise ValueError("등록되지 않은 재질 자료입니다.")
        if not open_external_url(sources[reference_id]["url"]):
            raise RuntimeError("기본 브라우저에서 자료를 열 수 없습니다.")
        return True

    @_logged_call
    def get_terrain(self, payload_json: str) -> dict:
        self._check_payload(payload_json)
        request = TerrainRequest.model_validate_json(payload_json)
        if not self._site_slots.acquire(blocking=False):
            raise RuntimeError(
                "장소·기상·지형 요청이 진행 중입니다. 잠시 후 다시 요청하세요."
            )
        try:
            return fetch_terrain(request).model_dump(mode="json")
        finally:
            self._site_slots.release()

    @_logged_call
    def open_terrain_portal(self, provider: str) -> bool:
        from app.terrain_sources import PORTALS

        if provider not in PORTALS:
            raise ValueError("지원하지 않는 데이터 발급 사이트입니다.")
        if not open_external_url(PORTALS[provider]):
            raise RuntimeError(
                "기본 브라우저를 열 수 없습니다. 표시된 사이트 주소를 직접 여세요."
            )
        return True

    @_logged_call
    def select_terrain_file(self, payload_json: str) -> dict | None:
        """Read only a native-dialog-authorized raster; freeze the sampled window."""
        import webview

        from app.terrain_sources import import_dem

        self._check_payload(payload_json)
        options = TerrainImportOptions.model_validate_json(payload_json)
        if not self._site_slots.acquire(blocking=False):
            raise RuntimeError("지형 요청이 진행 중입니다. 잠시 후 다시 요청하세요.")
        try:
            selected = webview.windows[0].create_file_dialog(
                webview.FileDialog.OPEN, allow_multiple=False
            )
            return (
                import_dem(Path(selected[0]), options).model_dump(mode="json")
                if selected
                else None
            )
        finally:
            self._site_slots.release()

    @_logged_call
    def check_elevation(self, payload_json: str) -> dict:
        self._check_payload(payload_json)
        return check_elevation(EnvironmentConfig.model_validate_json(payload_json))

    @_logged_call
    def search_locations(self, payload_json: str) -> list[dict]:
        self._check_payload(payload_json)
        request = LocationSearch.model_validate_json(payload_json)
        if not self._site_slots.acquire(blocking=False):
            raise RuntimeError(
                "장소·기상 요청이 진행 중입니다. 잠시 후 다시 요청하세요."
            )
        try:
            return [item.model_dump(mode="json") for item in search_locations(request)]
        finally:
            self._site_slots.release()

    @_logged_call
    def get_weather(self, payload_json: str) -> dict:
        self._check_payload(payload_json)
        request = WeatherRequest.model_validate_json(payload_json)
        if not self._site_slots.acquire(blocking=False):
            raise RuntimeError(
                "장소·기상 요청이 진행 중입니다. 잠시 후 다시 요청하세요."
            )
        try:
            return fetch_weather(request).model_dump(mode="json")
        finally:
            self._site_slots.release()

    @_logged_call
    def preview_weather_file(self, asset_path: str, sheet: str | None = None) -> dict:
        if sheet is not None and (not isinstance(sheet, str) or len(sheet) > 128):
            raise ValueError("Invalid sheet name.")
        if not self._site_slots.acquire(blocking=False):
            raise RuntimeError("기상 요청이 진행 중입니다.")
        try:
            return self._manager().preview_weather_file(asset_path, sheet)
        finally:
            self._site_slots.release()

    @_logged_call
    def import_weather_file(self, asset_path: str, options_json: str) -> dict:
        self._check_payload(options_json)
        options = WeatherImportOptions.model_validate_json(options_json)
        if not self._site_slots.acquire(blocking=False):
            raise RuntimeError("기상 요청이 진행 중입니다.")
        try:
            return self._manager().import_weather_file(asset_path, options)
        finally:
            self._site_slots.release()

    @_logged_call
    def submit_simulation(self, payload_json: str) -> dict:
        self._check_payload(payload_json)
        config = SimulationConfig.model_validate_json(payload_json)
        return self._manager().submit(config)

    @_logged_call
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

    @_logged_call
    def submit_design(self, payload_json: str) -> dict:
        self._check_payload(payload_json)
        return self._manager().submit_design(
            RocketDesign.model_validate_json(payload_json)
        )

    @_logged_call
    def get_design(self, run_id: str) -> dict:
        return self._manager().get_design(run_id)

    @_logged_call
    def get_design_report(self, run_id: str) -> dict:
        return self._manager().get_design_report(run_id)

    @_logged_call
    def save_design(self, payload_json: str) -> dict:
        self._check_payload(payload_json)
        return self._manager().save_design(
            RocketDesign.model_validate_json(payload_json)
        )

    @_logged_call
    def get_saved_design(self, design_id: str) -> dict:
        return self._manager().get_saved_design(design_id)

    @_logged_call
    def list_designs(self, limit: int = 50, offset: int = 0) -> list[dict]:
        return self._manager().list_designs(limit, offset)

    @_logged_call
    def import_design_file(self) -> dict | None:
        import webview

        from app.design_files import read_design_file

        selected = webview.windows[0].create_file_dialog(
            webview.FileDialog.OPEN,
            allow_multiple=False,
            file_types=("UARC design (*.uarc;*.json)",),
        )
        return read_design_file(Path(selected[0])) if selected else None

    @_logged_call
    def export_design_file(self, payload_json: str) -> str | None:
        import webview

        from app.design_files import (
            design_filename,
            validate_design_file,
            write_design_file,
        )

        self._check_payload(payload_json)
        design = validate_design_file(payload_json)
        selected = webview.windows[0].create_file_dialog(
            webview.FileDialog.SAVE,
            save_filename=design_filename(design.name),
            file_types=("UARC design (*.uarc)",),
        )
        return (
            str(write_design_file(Path(selected[0]), payload_json))
            if selected
            else None
        )

    @_logged_call
    def select_input_file(self) -> dict | None:
        """Only a file explicitly selected in the native dialog may enter inputs/."""
        import webview

        selected = webview.windows[0].create_file_dialog(
            webview.FileDialog.OPEN, allow_multiple=False
        )
        return self._manager().import_file(Path(selected[0])) if selected else None

    @_logged_call
    def import_openrocket(self, asset_path: str, options_json: str) -> dict:
        self._check_payload(options_json)
        options = OpenRocketOptions.model_validate_json(options_json)
        return self._manager().import_openrocket(asset_path, options)

    @_logged_call
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

    @_logged_call
    def rerun(self, run_id: str) -> dict:
        return self._manager().rerun(run_id)

    @_logged_call
    def get_run(self, run_id: str) -> dict:
        return self._manager().get_run(run_id)

    @_logged_call
    def list_runs(self, limit: int = 50, offset: int = 0) -> list[dict]:
        return self._manager().list_runs(limit, offset)

    @_logged_call
    def cancel_run(self, run_id: str) -> dict:
        return self._manager().cancel(run_id)

    @_logged_call
    def get_summary(self, run_id: str) -> dict:
        return self._manager().get_summary(run_id)

    @_logged_call
    def get_telemetry(self, run_id: str, query_json: str = "{}") -> dict:
        self._check_payload(query_json)
        return self._manager().get_telemetry(
            run_id, TelemetryQuery.model_validate_json(query_json)
        )
