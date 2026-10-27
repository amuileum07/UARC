"""Weather requests, frozen profiles, and tabular import settings."""

from datetime import datetime
from itertools import pairwise
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .common import (
    EngineConfig,
    HeightReference,
    NonNegative,
    Number,
    Positive,
    launch_time,
)


class WeatherRequest(EngineConfig):
    """WGS84 site, flight-frame launch elevation, and an explicitly chosen time."""

    latitude: Annotated[Number, Field(ge=-90, le=90)]
    longitude: Annotated[Number, Field(ge=-180, le=180)]
    elevation: Number
    pad_height_m: NonNegative = 0.0
    elevation_reference: HeightReference = "unknown"
    geoid_undulation_m: Number | None = None
    date: datetime
    timezone: Annotated[str, Field(min_length=1, max_length=128)] = "UTC"
    model: Literal["gfs_seamless", "ecmwf_ifs025", "wyoming_sounding", "file"]
    station_id: Annotated[str, Field(pattern=r"^[0-9]{5}$")] | None = None
    observation_time: datetime | None = None

    @model_validator(mode="after")
    def valid_site_time(self):
        launch_time(self.date, self.timezone)
        if self.elevation_reference == "ellipsoid" and self.geoid_undulation_m is None:
            raise ValueError("Ellipsoid weather heights require geoid undulation N.")
        if self.model == "wyoming_sounding":
            if self.station_id is None or self.observation_time is None:
                raise ValueError(
                    "Wyoming requires a station number and observation time."
                )
            observed = launch_time(self.observation_time, "UTC")
            if (
                observed.minute
                or observed.second
                or observed.microsecond
                or observed.hour % 3
            ):
                raise ValueError(
                    "Choose a Wyoming observation at a 3-hour UTC interval."
                )
        elif self.station_id is not None or self.observation_time is not None:
            raise ValueError(
                "Station/time fields are only used with Wyoming observations."
            )
        return self


class WeatherLevel(EngineConfig):
    altitude_m: Number
    pressure_pa: Positive
    temperature_k: Positive
    wind_u_m_s: Number
    wind_v_m_s: Number


class WeatherProfile(EngineConfig):
    request: WeatherRequest
    source: Literal["Open-Meteo", "Wyoming", "File"] = "Open-Meteo"
    retrieved_at: datetime
    grid_latitude: Annotated[Number, Field(ge=-90, le=90)]
    grid_longitude: Annotated[Number, Field(ge=-180, le=180)]
    response_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    levels: Annotated[list[WeatherLevel], Field(min_length=2, max_length=4096)]
    source_name: Annotated[str, Field(max_length=256)] = ""
    source_asset: Annotated[str, Field(min_length=1, max_length=4096)] | None = None
    notes: Annotated[
        list[Annotated[str, Field(max_length=512)]], Field(max_length=8)
    ] = Field(default_factory=list)

    @model_validator(mode="after")
    def ordered_profile(self):
        if any(
            a.altitude_m >= b.altitude_m or a.pressure_pa <= b.pressure_pa
            for a, b in pairwise(self.levels)
        ):
            raise ValueError("Weather heights must increase and pressures decrease.")
        if (
            self.request.model in {"gfs_seamless", "ecmwf_ifs025"}
            and self.levels[0].altitude_m
            != self.request.elevation - self.request.pad_height_m
        ):
            raise ValueError(
                "The weather profile must start at the pad ground elevation."
            )
        source = {
            "gfs_seamless": "Open-Meteo",
            "ecmwf_ifs025": "Open-Meteo",
            "wyoming_sounding": "Wyoming",
            "file": "File",
        }[self.request.model]
        if self.source != source:
            raise ValueError("Weather source and request model do not agree.")
        if (self.source == "File") != (self.source_asset is not None):
            raise ValueError("Only file profiles require an authorized input asset.")
        return self


class WeatherColumns(EngineConfig):
    altitude: Annotated[str, Field(min_length=1, max_length=128)]
    pressure: Annotated[str, Field(min_length=1, max_length=128)]
    temperature: Annotated[str, Field(min_length=1, max_length=128)]
    wind_u: Annotated[str, Field(max_length=128)] | None = None
    wind_v: Annotated[str, Field(max_length=128)] | None = None
    wind_speed: Annotated[str, Field(max_length=128)] | None = None
    wind_direction: Annotated[str, Field(max_length=128)] | None = None


class WeatherImportOptions(EngineConfig):
    request: WeatherRequest
    columns: WeatherColumns
    expected_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    source_name: Annotated[str, Field(min_length=1, max_length=256)]
    sheet: Annotated[str, Field(max_length=128)] | None = None
    height_unit: Literal["m", "ft"] = "m"
    height_reference: Literal["ASL", "AGL", "geopotential"] = "ASL"
    pressure_unit: Literal["Pa", "hPa"] = "Pa"
    temperature_unit: Literal["K", "C"] = "K"
    wind_format: Literal["uv", "speed_direction"] = "uv"
    wind_unit: Literal["m/s", "km/h", "knots"] = "m/s"

    @model_validator(mode="after")
    def valid_columns(self):
        if self.request.model != "file":
            raise ValueError("A local file requires model='file'.")
        fields = [
            self.columns.altitude,
            self.columns.pressure,
            self.columns.temperature,
        ]
        fields += (
            [self.columns.wind_u, self.columns.wind_v]
            if self.wind_format == "uv"
            else [self.columns.wind_speed, self.columns.wind_direction]
        )
        if any(not value for value in fields) or len(set(fields)) != len(fields):
            raise ValueError("Select five distinct required data columns.")
        return self


class WeatherTable(EngineConfig):
    sheets: Annotated[list[str], Field(max_length=16)]
    sheet: str | None
    columns: Annotated[list[str], Field(min_length=5, max_length=32)]
    rows: Annotated[list[list[str | None]], Field(max_length=5)]
    row_count: Annotated[int, Field(ge=2, le=4096)]
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
