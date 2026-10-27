"""Location search and launch environments with matching weather and terrain."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from .common import (
    Curve,
    EngineConfig,
    HeightReference,
    NonNegative,
    Number,
    Positive,
    PositiveCurve,
    launch_time,
)
from .terrain import TerrainGrid
from .weather import WeatherProfile


class LocationSearch(EngineConfig):
    query: Annotated[str, Field(min_length=2, max_length=120)]
    country: Literal["KR", "all"] = "KR"

    @field_validator("query")
    @classmethod
    def strip_query(cls, value):
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Enter at least two characters.")
        return value


class LocationResult(EngineConfig):
    id: int | Annotated[str, Field(pattern=r"^osm:[NWR]:[1-9][0-9]{0,18}$")]
    name: Annotated[str, Field(min_length=1, max_length=256)]
    latitude: Annotated[Number, Field(ge=-90, le=90)]
    longitude: Annotated[Number, Field(ge=-180, le=180)]
    region: Annotated[str, Field(max_length=512)] = ""
    timezone: Annotated[str, Field(max_length=128)] = "UTC"
    source: Literal["OpenStreetMap", "GeoNames"] = "GeoNames"
    category: Annotated[str, Field(max_length=128)] = ""


class EnvironmentConfig(EngineConfig):
    latitude: Annotated[Number, Field(ge=-90, le=90)]
    longitude: Annotated[Number, Field(ge=-180, le=180)]
    elevation: Number
    # Missing fields in existing designs keep their explicitly entered altitude.
    elevation_mode: Literal["manual", "terrain"] = "manual"
    elevation_reference: HeightReference = "unknown"
    geoid_undulation_m: Number | None = None
    pad_height_m: NonNegative = 0.0
    elevation_tolerance_m: NonNegative = 15.0
    terrain: TerrainGrid | None = None
    terrain_mode: Literal["flat", "terrain"] = "flat"
    date: datetime | tuple[int, int, int, int] | None = None
    timezone: str = "UTC"
    gravity: Positive | None = None
    datum: Literal["SIRGAS2000", "WGS84", "NAD83", "SAD69"] = "SIRGAS2000"
    max_expected_height: Number = 80000.0
    pressure: PositiveCurve | None = None
    temperature: PositiveCurve | None = None
    wind_u: Curve = 0.0
    wind_v: Curve = 0.0
    atmosphere_type: (
        Literal[
            "standard_atmosphere",
            "custom_atmosphere",
            "forecast",
            "reanalysis",
            "ensemble",
            "windy",
            "wyoming_sounding",
        ]
        | None
    ) = None
    atmosphere_file: str | None = None
    atmosphere_dictionary: dict[str, str | None] | str | None = None
    pressure_conversion_factor: Literal["Pa", "hPa", "mbar"] | Positive | None = None
    ensemble_member: Annotated[int, Field(ge=0)] = 0
    weather_profile: WeatherProfile | None = None

    @field_validator("atmosphere_type", mode="before")
    @classmethod
    def normalize_model(cls, value):
        return value.lower() if isinstance(value, str) else value

    @field_validator("date")
    @classmethod
    def valid_date(cls, value):
        if isinstance(value, tuple):
            datetime(*value)
        return value

    @model_validator(mode="after")
    def compatible_weather(self):
        if self.date is not None:
            launch_time(self.date, self.timezone)
        profile = self.weather_profile
        if profile is not None:
            request = profile.request
            if (
                self.datum != "WGS84"
                or any(
                    getattr(self, key) != getattr(request, key)
                    for key in (
                        "latitude",
                        "longitude",
                        "elevation",
                        "pad_height_m",
                        "elevation_reference",
                        "geoid_undulation_m",
                    )
                )
                or self.date is None
                or self.timezone != request.timezone
                or launch_time(self.date, self.timezone)
                != launch_time(request.date, request.timezone)
            ):
                raise ValueError("Site/time changed; fetch and apply weather again.")
            if (
                not profile.levels[0].altitude_m
                <= self.elevation
                <= profile.levels[-1].altitude_m
            ):
                raise ValueError(
                    "The imported weather does not cover the launch elevation."
                )
            if (
                self.pressure is not None
                or self.temperature is not None
                or self.wind_u != 0
                or self.wind_v != 0
            ):
                raise ValueError("Frozen weather cannot be mixed with manual profiles.")
        if self.terrain_mode == "terrain":
            if self.terrain is None or self.datum != "WGS84":
                raise ValueError(
                    "Terrain flights require a grid and WGS84 coordinates."
                )
            if "unknown" in (self.elevation_reference, self.terrain.reference):
                raise ValueError("Terrain flights require known vertical references.")
            if (
                self.elevation_reference != self.terrain.reference
                and self.geoid_undulation_m is None
            ):
                raise ValueError(
                    "Different height references require geoid undulation."
                )
            if (
                self.elevation_reference != self.terrain.reference
                and "ellipsoid"
                not in (self.elevation_reference, self.terrain.reference)
            ):
                raise ValueError(
                    "Different orthometric datums require an explicit vertical transformation."
                )
        if self.max_expected_height <= self.elevation:
            raise ValueError("max_expected_height must be above the launch elevation.")
        custom = (
            self.pressure is not None
            or self.temperature is not None
            or self.wind_u != 0
            or self.wind_v != 0
            or profile is not None
        )
        self.atmosphere_type = self.atmosphere_type or (
            "custom_atmosphere" if custom else "standard_atmosphere"
        )
        if self.atmosphere_type != "custom_atmosphere" and custom:
            raise ValueError("Weather overrides require custom_atmosphere.")
        local = self.atmosphere_type in {"standard_atmosphere", "custom_atmosphere"}
        if local and any(
            v is not None
            for v in (
                self.atmosphere_file,
                self.atmosphere_dictionary,
                self.pressure_conversion_factor,
            )
        ):
            raise ValueError("Local atmospheres do not use an external weather source.")
        if not local and self.atmosphere_file is None:
            raise ValueError("An external atmosphere requires atmosphere_file.")
        if (
            self.atmosphere_type in {"forecast", "reanalysis", "ensemble", "windy"}
            and self.date is None
        ):
            raise ValueError("This atmosphere model requires a launch date.")
        if self.atmosphere_type != "ensemble" and self.ensemble_member != 0:
            raise ValueError(
                "ensemble_member is only used with an ensemble atmosphere."
            )
        return self
