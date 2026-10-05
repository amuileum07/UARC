"""Small JSON boundary exposed to the desktop UI through pywebview."""

import json
from typing import Literal

from pydantic import TypeAdapter

from app.schemas import EnvironmentConfig, FlightConfig, MotorConfig, RocketConfig

ConfigKind = Literal["environment", "motor", "rocket", "flight"]
_CONFIG_ADAPTERS = {
    "environment": TypeAdapter(EnvironmentConfig),
    "motor": TypeAdapter(MotorConfig),
    "rocket": TypeAdapter(RocketConfig),
    "flight": TypeAdapter(FlightConfig),
}


class DesktopBridge:
    """Public methods are exposed as window.pywebview.api methods.

    Only validation is implemented here. Job execution belongs to the future
    process manager, so no simulation blocks a bridge call or the GUI loop.
    """

    def validate_config(self, kind: ConfigKind, payload_json: str) -> dict[str, object]:
        """Validate JSON from JS without relaxing strict Python DTO validation.

        JSON mode accepts arrays for tuple fields, such as inertia and curves.
        Validation errors propagate as rejected JavaScript promises.
        """
        try:
            adapter = _CONFIG_ADAPTERS[kind]
        except KeyError as error:
            raise ValueError(f"Unknown configuration kind: {kind}") from error
        config = adapter.validate_json(payload_json)
        return json.loads(config.model_dump_json())
