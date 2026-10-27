"""Serializable simulation inputs; RocketPy runtime objects belong in the engine."""

from datetime import UTC, datetime
from itertools import pairwise
from math import isclose
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)

Number = Annotated[float, Field(strict=True, allow_inf_nan=False)]
Positive = Annotated[Number, Field(gt=0)]
NonNegative = Annotated[Number, Field(ge=0)]
HeightReference = Literal["EGM96", "EGM2008", "national", "ellipsoid", "unknown"]


def _ordered_curve(value):
    if isinstance(value, list) and any(
        left[0] >= right[0] for left, right in pairwise(value)
    ):
        raise ValueError("Curve coordinates must be strictly increasing.")
    return value


# Paths are data, but resolving/authorizing them belongs to the application.
Curve = Annotated[
    Number | str | Annotated[list[tuple[Number, Number]], Field(min_length=2)],
    AfterValidator(_ordered_curve),
]
PositiveCurve = Annotated[
    Positive | str | Annotated[list[tuple[Number, Positive]], Field(min_length=2)],
    AfterValidator(_ordered_curve),
]
NonNegativeCurve = Annotated[
    NonNegative
    | str
    | Annotated[list[tuple[Number, NonNegative]], Field(min_length=2)],
    AfterValidator(_ordered_curve),
]
Inertia = (
    tuple[Number, Number, Number]
    | tuple[Number, Number, Number, Number, Number, Number]
)
BurnTime = Positive | tuple[NonNegative, Number] | None
Tolerance = (
    Positive | Annotated[tuple[Positive, ...], Field(min_length=13, max_length=13)]
)


def _inertia(value: Inertia, *, allow_zero=False):
    # RocketPy checks component count, not physical principal moments.
    i11, i22, i33, i12, i13, i23 = value if len(value) == 6 else (*value, 0, 0, 0)
    principal = np.linalg.eigvalsh([[i11, i12, i13], [i12, i22, i23], [i13, i23, i33]])
    if principal[0] < 0 or (not allow_zero and principal[0] == 0):
        raise ValueError(
            "Inertia needs positive principal moments (nonnegative for a motor)."
        )
    if principal[2] > principal[0] + principal[1] + 1e-12 * max(1, principal[2]):
        raise ValueError(
            "Inertia principal moments must satisfy the triangle inequality."
        )
    return value


class EngineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def launch_time(value: datetime | tuple[int, int, int, int], timezone: str) -> datetime:
    """Resolve a local launch time; reject missing or ambiguous DST clock times."""
    try:
        zone = ZoneInfo(timezone)
    except (ValueError, ZoneInfoNotFoundError) as error:
        raise ValueError("Unknown IANA time zone.") from error
    local = datetime(*value) if isinstance(value, tuple) else value
    if local.tzinfo is not None:
        return local.astimezone(UTC)
    resolved = local.replace(tzinfo=zone)
    if resolved.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != local:
        raise ValueError("The launch time does not exist in this time zone.")
    if resolved.utcoffset() != local.replace(tzinfo=zone, fold=1).utcoffset():
        raise ValueError("Ambiguous launch time; use UTC or an explicit UTC offset.")
    return resolved.astimezone(UTC)


class LocationSearch(EngineConfig):
    query: Annotated[str, Field(min_length=2, max_length=120)]

    @field_validator("query")
    @classmethod
    def strip_query(cls, value):
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Enter at least two characters.")
        return value


class LocationResult(EngineConfig):
    id: int
    name: Annotated[str, Field(min_length=1, max_length=256)]
    latitude: Annotated[Number, Field(ge=-90, le=90)]
    longitude: Annotated[Number, Field(ge=-180, le=180)]
    region: Annotated[str, Field(max_length=512)] = ""
    timezone: Annotated[str, Field(max_length=128)] = "UTC"


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


class TerrainGrid(EngineConfig):
    """WGS84 geographic grid; rows run south to north, columns west to east."""

    south: Annotated[Number, Field(ge=-85, le=85)]
    north: Annotated[Number, Field(ge=-85, le=85)]
    west: Annotated[Number, Field(ge=-180, le=180)]
    east: Annotated[Number, Field(ge=-180, le=180)]
    heights: Annotated[
        list[Annotated[list[Number | None], Field(min_length=2, max_length=257)]],
        Field(min_length=2, max_length=257),
    ]
    reference: HeightReference
    provider: Literal["aws", "local", "opentopography", "opentopodata", "unknown"] = (
        "unknown"
    )
    source: Annotated[str, Field(min_length=1, max_length=512)]
    retrieved_at: Annotated[str, Field(max_length=64)] = ""
    source_resolution_m: Positive
    sampling_distance_m: Positive

    @model_validator(mode="after")
    def valid_grid(self):
        if not self.south < self.north or not self.west < self.east:
            raise ValueError(
                "Terrain bounds must be ordered without dateline wrapping."
            )
        if len({len(row) for row in self.heights}) != 1:
            raise ValueError("Terrain rows must have equal lengths.")
        if self.north - self.south > 0.2 or self.east - self.west > 0.4:
            raise ValueError("Terrain grids are limited to local launch areas.")
        return self


class TerrainRequest(EngineConfig):
    latitude: Annotated[Number, Field(ge=-80, le=80)]
    longitude: Annotated[Number, Field(ge=-179.8, le=179.8)]
    radius_m: Annotated[Number, Field(ge=100, le=5000)] = 1000.0
    spacing_m: Annotated[Number, Field(ge=5, le=1000)] = 30.0
    provider: Literal["aws", "local", "opentopography", "opentopodata"] = "aws"
    dataset: Literal["SRTMGL1", "SRTMGL3", "COP30"] = "SRTMGL1"
    api_key: SecretStr = Field(
        default_factory=lambda: SecretStr(""), repr=False, exclude=True
    )


class TerrainImportOptions(EngineConfig):
    area: TerrainRequest
    reference: HeightReference = "unknown"
    crs_epsg: Annotated[int, Field(ge=1024, le=100000)] | None = None
    height_scale: Number = Field(default=1.0, json_schema_extra={"enum": [1.0, 0.3048]})

    @field_validator("height_scale")
    @classmethod
    def valid_height_scale(cls, value: float) -> float:
        if value not in (1.0, 0.3048):
            raise ValueError("Height scale must be 1.0 (m) or 0.3048 (ft).")
        return value


class EnvironmentConfig(EngineConfig):
    latitude: Annotated[Number, Field(ge=-90, le=90)]
    longitude: Annotated[Number, Field(ge=-180, le=180)]
    elevation: Number
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


class MotorBase(EngineConfig):
    """Common motor fields; concrete models declare their required inputs."""

    thrust_source: NonNegativeCurve
    nozzle_radius: Positive
    dry_mass: NonNegative | None
    dry_inertia: Inertia
    burn_time: BurnTime = None
    nozzle_position: Number = 0.0
    reshape_thrust_curve: Literal[False] | tuple[Positive, Positive] = False
    interpolation_method: Literal["linear", "akima", "spline"] = "linear"
    coordinate_system_orientation: Literal[
        "nozzle_to_combustion_chamber", "combustion_chamber_to_nozzle"
    ] = "nozzle_to_combustion_chamber"
    reference_pressure: Positive | None = None

    @field_validator("dry_inertia")
    @classmethod
    def dry_tensor(cls, value):
        return _inertia(value, allow_zero=True)

    @field_validator("burn_time")
    @classmethod
    def positive_duration(cls, value):
        if isinstance(value, tuple) and value[1] <= value[0]:
            raise ValueError("burn_time must describe a positive duration.")
        return value


class GrainMotorBase(MotorBase):
    center_of_dry_mass_position: Number
    grain_number: Annotated[int, Field(gt=0)]
    grain_density: Positive
    grain_outer_radius: Positive
    grain_initial_inner_radius: NonNegative
    grain_initial_height: Positive
    grain_separation: NonNegative
    grains_center_of_mass_position: Number
    throat_radius: Positive = 0.01
    only_radial_burn: bool = False

    @model_validator(mode="after")
    def grain_geometry(self):
        if self.grain_initial_inner_radius >= self.grain_outer_radius:
            raise ValueError(
                "The grain inner radius must be smaller than its outer radius."
            )
        return self


class SolidMotorConfig(GrainMotorBase):
    motor_type: Literal["solid"] = "solid"


class LiquidMotorConfig(MotorBase):
    motor_type: Literal["liquid"] = "liquid"
    center_of_dry_mass_position: Number


class HybridMotorConfig(GrainMotorBase):
    motor_type: Literal["hybrid"] = "hybrid"
    only_radial_burn: bool = True


class GenericMotorConfig(MotorBase):
    motor_type: Literal["generic"] = "generic"
    burn_time: BurnTime
    chamber_radius: Positive
    chamber_height: Positive
    chamber_position: Number
    propellant_initial_mass: NonNegative
    dry_mass: NonNegative | None = 0.0
    dry_inertia: Inertia = (0, 0, 0)
    center_of_dry_mass_position: Number | None = None


MotorConfig = Annotated[
    SolidMotorConfig | LiquidMotorConfig | HybridMotorConfig | GenericMotorConfig,
    Field(discriminator="motor_type"),
]


class ParachuteConfig(EngineConfig):
    name: str
    cd_s: Positive
    trigger: Literal["apogee"] | NonNegative
    sampling_rate: Positive = 100.0
    lag: NonNegative = 0.0
    noise: tuple[Number, NonNegative, Annotated[Number, Field(ge=-1, le=1)]] = (0, 0, 0)
    radius: Positive | None = None
    height: Positive | None = None
    porosity: Annotated[Number, Field(ge=0, le=1)] = 0.0432
    drag_coefficient: Positive = 1.4


class RailButtonsConfig(EngineConfig):
    upper_button_position: Number
    lower_button_position: Number
    angular_position: Number = 45.0
    radius: Positive | None = None


class RocketConfig(EngineConfig):
    radius: Positive
    mass: Positive
    inertia: Inertia
    power_off_drag: NonNegativeCurve
    power_on_drag: NonNegativeCurve
    center_of_mass_without_motor: Number
    motor_position: Number = 0.0
    coordinate_system_orientation: Literal["tail_to_nose", "nose_to_tail"] = (
        "tail_to_nose"
    )
    parachutes: list[ParachuteConfig] = Field(default_factory=list)
    rail_buttons: RailButtonsConfig | None = None

    @field_validator("inertia")
    @classmethod
    def body_tensor(cls, value):
        return _inertia(value)


class FlightConfig(EngineConfig):
    rail_length: Positive
    inclination: Number
    heading: Number
    initial_solution: (
        Annotated[tuple[Number, ...], Field(min_length=14, max_length=14)] | None
    ) = None
    terminate_on_apogee: bool = False
    max_time: Positive = 600.0
    # None means no upper step limit; unlike infinity, it round-trips through JSON.
    max_time_step: Positive | None = None
    min_time_step: NonNegative = 0.0
    rtol: Tolerance = 1e-6
    atol: Tolerance | None = None
    time_overshoot: bool = True
    verbose: bool = False
    name: str = "Flight"
    equations_of_motion: Literal["standard", "solid_propulsion"] = "standard"
    ode_solver: Literal["LSODA", "RK23", "RK45", "DOP853", "Radau", "BDF"] = "LSODA"
    simulation_mode: Literal["6 DOF", "3 DOF"] = "6 DOF"

    @model_validator(mode="after")
    def consistent_flight(self):
        self.heading %= 360
        start = 0.0
        if self.initial_solution is None:
            if not 0 < self.inclination <= 90:
                raise ValueError("Rail launch inclination must be in (0, 90] degrees.")
        else:
            state = self.initial_solution
            if not isclose(sum(v * v for v in state[7:11]), 1, rel_tol=0, abs_tol=1e-6):
                raise ValueError("initial_solution needs a unit attitude quaternion.")
            start = state[0]
        if self.max_time <= start:
            raise ValueError("max_time must be later than the initial simulation time.")
        if self.max_time_step is not None and self.min_time_step > self.max_time_step:
            raise ValueError("min_time_step must not exceed max_time_step.")
        return self


Position = Number | tuple[Number, Number, Number]


class SurfaceBase(EngineConfig):
    position: Position
    rocket_radius: Positive


class NoseConeConfig(SurfaceBase):
    surface_type: Literal["nose"] = "nose"
    length: Positive
    kind: Literal[
        "conical",
        "ogive",
        "elliptical",
        "parabolic",
        "lvhaack",
        "vonkarman",
        "powerseries",
        "haack",
    ] = "conical"
    base_radius: Positive | None = None
    bluffness: Annotated[Number, Field(ge=0, lt=1)] | None = None
    power: Annotated[Number, Field(gt=0, le=1)] | None = None
    haack_c: Annotated[Number, Field(ge=0, le=1 / 3)] | None = None

    @model_validator(mode="after")
    def compatible_power_series(self):
        if self.kind == "haack":
            if self.haack_c is None:
                raise ValueError("A Haack nose cone requires haack_c.")
            if self.bluffness not in (None, 0):
                raise ValueError(
                    "Continuous Haack profiles currently require a sharp tip."
                )
        elif self.haack_c is not None:
            raise ValueError("haack_c is only used with kind='haack'.")
        if self.kind == "powerseries":
            if self.power is None:
                raise ValueError("A power-series nose cone requires power.")
            if self.bluffness not in (None, 0):
                raise ValueError("A power-series nose cone cannot use bluffness.")
        return self


class TrapezoidalFinsConfig(SurfaceBase):
    surface_type: Literal["trapezoidal_fins"] = "trapezoidal_fins"
    n: Annotated[int, Field(ge=3)]
    root_chord: Positive
    tip_chord: NonNegative
    span: Positive
    cant_angle: Number = 0.0
    sweep_length: Number | None = None
    sweep_angle: Annotated[Number, Field(gt=-90, lt=90)] | None = None

    @model_validator(mode="after")
    def one_sweep_definition(self):
        if self.sweep_length is not None and self.sweep_angle is not None:
            raise ValueError("Specify sweep_length or sweep_angle, not both.")
        return self


class EllipticalFinsConfig(SurfaceBase):
    surface_type: Literal["elliptical_fins"] = "elliptical_fins"
    n: Annotated[int, Field(ge=3)]
    root_chord: Positive
    span: Positive
    cant_angle: Number = 0.0


class TailConfig(SurfaceBase):
    surface_type: Literal["tail"] = "tail"
    top_radius: Positive
    bottom_radius: Positive
    length: Positive


SurfaceConfig = Annotated[
    NoseConeConfig | TrapezoidalFinsConfig | EllipticalFinsConfig | TailConfig,
    Field(discriminator="surface_type"),
]


class FluidConfig(EngineConfig):
    name: str
    density: Positive


class MassBasedTankConfig(EngineConfig):
    """A cylindrical tank with caller-supplied phase masses, in SI units."""

    name: str
    position: Number
    radius: Positive
    height: Positive
    spherical_caps: bool = False
    flux_time: Positive | tuple[NonNegative, Number]
    liquid: FluidConfig
    gas: FluidConfig
    liquid_mass: NonNegativeCurve
    gas_mass: NonNegativeCurve
    discretize: Annotated[int, Field(ge=2, le=100_000)] = 100

    @field_validator("flux_time")
    @classmethod
    def positive_duration(cls, value):
        if isinstance(value, tuple) and value[1] <= value[0]:
            raise ValueError("flux_time must describe a positive duration.")
        return value


class SimulationConfig(EngineConfig):
    environment: EnvironmentConfig
    motor: MotorConfig | None
    rocket: RocketConfig
    flight: FlightConfig
    surfaces: list[SurfaceConfig] = Field(default_factory=list)
    tanks: list[MassBasedTankConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def compatible_tanks(self):
        needs_tanks = isinstance(self.motor, (LiquidMotorConfig, HybridMotorConfig))
        if needs_tanks and not self.tanks:
            raise ValueError("Liquid and hybrid motors require configured tanks.")
        if not needs_tanks and self.tanks:
            raise ValueError("Tanks are supported only for liquid and hybrid motors.")
        return self


TELEMETRY_COLUMNS = (
    "time_s",
    "x_m",
    "y_m",
    "z_asl_m",
    "vx_m_s",
    "vy_m_s",
    "vz_m_s",
    "e0",
    "e1",
    "e2",
    "e3",
    "w1_rad_s",
    "w2_rad_s",
    "w3_rad_s",
)


class TelemetryQuery(EngineConfig):
    columns: Annotated[list[str], Field(min_length=1, max_length=14)] = Field(
        default_factory=lambda: ["time_s", "x_m", "y_m", "z_asl_m"]
    )
    start_time: Number | None = None
    end_time: Number | None = None
    max_points: Annotated[int, Field(ge=32, le=10_000)] = 2000

    @field_validator("columns")
    @classmethod
    def known_columns(cls, value):
        if len(set(value)) != len(value) or any(
            v not in TELEMETRY_COLUMNS for v in value
        ):
            raise ValueError("Telemetry columns must be unique known column names.")
        return value

    @model_validator(mode="after")
    def ordered_interval(self):
        if (
            self.start_time is not None
            and self.end_time is not None
            and self.start_time > self.end_time
        ):
            raise ValueError("start_time must not exceed end_time.")
        return self


class MaterialConfig(EngineConfig):
    name: Annotated[str, Field(min_length=1, max_length=128)]
    density: Positive


class DesignComponent(EngineConfig):
    id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
    name: Annotated[str, Field(max_length=128)] = ""


class MaterialComponent(DesignComponent):
    material: str
    mass_override: Positive | None = None


class BodyTubeDesign(MaterialComponent):
    component_type: Literal["body_tube"] = "body_tube"
    position: Number = Field(
        description="Aft-end axial position; tube extends in +z, m."
    )
    length: Positive
    outer_radius: Positive
    thickness: Positive = Field(
        description="Radial wall thickness, m; radius gives a solid cylinder."
    )

    @model_validator(mode="after")
    def valid_wall(self):
        if self.thickness > self.outer_radius:
            raise ValueError("Tube thickness cannot exceed its outer radius.")
        return self


class SurfaceDesign(MaterialComponent):
    component_type: Literal["surface"] = "surface"
    surface: SurfaceConfig
    thickness: Positive = Field(
        description="Fin plate thickness or radial nose/tail wall thickness, m."
    )

    @model_validator(mode="after")
    def valid_geometry(self):
        if isinstance(self.surface.position, tuple):
            raise ValueError(
                "Parametric designs currently use axial surface positions."
            )
        if isinstance(self.surface, NoseConeConfig):
            radius = self.surface.base_radius or self.surface.rocket_radius
            if self.thickness > radius:
                raise ValueError("Nose thickness cannot exceed its base radius.")
        if isinstance(self.surface, TailConfig) and self.thickness > min(
            self.surface.top_radius, self.surface.bottom_radius
        ):
            raise ValueError("Tail thickness cannot exceed either end radius.")
        return self


class MassComponentDesign(DesignComponent):
    """Axis-centered payload/hardware; use measured intrinsic inertia when available."""

    component_type: Literal["mass"] = "mass"
    position: Number = Field(description="Component CG in rocket coordinates, m.")
    mass: Positive
    radius: NonNegative = 0.0
    length: NonNegative = 0.0
    inertia: Inertia | None = None

    @field_validator("inertia")
    @classmethod
    def physical_tensor(cls, value):
        return _inertia(value, allow_zero=True) if value is not None else None


class ParachuteDeployment(ParachuteConfig):
    radius: Positive
    cd_s: Positive | None = Field(
        default=None,
        description="Optional measured Cd*A override; default is Cd*pi*radius².",
    )


class ParachuteDesign(MaterialComponent):
    component_type: Literal["parachute"] = "parachute"
    position: Number = Field(description="Packed parachute CG, m.")
    attachment_position: Number = Field(
        description="Design attachment coordinate only; no attachment-point torque model."
    )
    canopy_area: Positive = Field(
        description="Actual fabric area, m²; independent of projected drag area."
    )
    thickness: Positive = Field(description="Fabric thickness, m.")
    line_mass: NonNegative = 0.0
    packed_radius: Positive
    packed_length: Positive
    deployment: ParachuteDeployment


ComponentDesign = Annotated[
    BodyTubeDesign | SurfaceDesign | MassComponentDesign | ParachuteDesign,
    Field(discriminator="component_type"),
]


class MassOverrides(EngineConfig):
    mass: Positive | None = None
    center_of_mass: Number | None = None
    inertia: Inertia | None = None

    @field_validator("inertia")
    @classmethod
    def physical_tensor(cls, value):
        return _inertia(value) if value is not None else None


class RocketDesign(EngineConfig):
    """SI units; axis-centered components, body stations increase tail to nose."""

    schema_version: Literal[1] = 1
    name: Annotated[str, Field(min_length=1, max_length=128)]
    materials: Annotated[dict[str, MaterialConfig], Field(max_length=64)] = Field(
        default_factory=dict
    )
    components: Annotated[list[ComponentDesign], Field(min_length=1, max_length=64)]
    environment: EnvironmentConfig
    flight: FlightConfig
    motor: MotorConfig | None
    motor_position: Number = 0.0
    tanks: list[MassBasedTankConfig] = Field(default_factory=list)
    power_off_drag: NonNegativeCurve
    power_on_drag: NonNegativeCurve
    rail_buttons: RailButtonsConfig | None = None
    overrides: MassOverrides = Field(default_factory=MassOverrides)

    @model_validator(mode="after")
    def consistent_design(self):
        ids = [component.id for component in self.components]
        if len(set(ids)) != len(ids):
            raise ValueError("Component IDs must be unique.")
        for component in self.components:
            if (
                isinstance(component, MaterialComponent)
                and component.material not in self.materials
            ):
                raise ValueError(
                    f"Unknown material for component {component.id}: {component.material}"
                )
        if not any(
            isinstance(c, (BodyTubeDesign, SurfaceDesign)) for c in self.components
        ):
            raise ValueError("A design needs a body tube or aerodynamic surface.")
        needs_tanks = isinstance(self.motor, (LiquidMotorConfig, HybridMotorConfig))
        if needs_tanks != bool(self.tanks):
            raise ValueError("Only liquid/hybrid motors require and accept tanks.")
        return self


RunState = Literal[
    "queued",
    "running",
    "cancelling",
    "succeeded",
    "failed",
    "cancelled",
    "timed_out",
    "interrupted",
]


class RunRecord(EngineConfig):
    run_id: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
    state: RunState
    stage: str
    created_at: str
    started_at: str | None
    finished_at: str | None
    worker_pid: Annotated[int, Field(gt=0)] | None
    peak_rss_bytes: Annotated[int, Field(ge=0)]
    error: str | None


class ParachuteEvent(EngineConfig):
    name: str
    trigger_time_s: Number


class FlightSummary(EngineConfig):
    name: str
    initial_mass_kg: Positive
    final_mass_kg: Positive
    initial_center_of_mass_m: Number
    final_center_of_mass_m: Number
    termination_reason: Literal["impact", "apogee", "time_limit", "stopped"]
    apogee_reached: bool
    landed: bool
    start_time_s: Number
    end_time_s: Number
    duration_s: NonNegative
    apogee_asl_m: Number | None
    apogee_agl_m: Number | None
    apogee_time_s: Number | None
    max_altitude_asl_m: Number
    max_altitude_agl_m: Number
    max_speed_m_s: NonNegative
    max_speed_time_s: Number
    impact_x_m: Number | None
    impact_y_m: Number | None
    impact_speed_m_s: NonNegative | None
    ground_model: Literal["flat", "terrain"] = "flat"
    impact_latitude: Number | None = None
    impact_longitude: Number | None = None
    impact_elevation_m: Number | None = None
    parachute_events: list[ParachuteEvent]


class TelemetryResult(EngineConfig):
    columns: list[str]
    data: list[list[Number]]
    total_rows: Annotated[int, Field(ge=0)]
    matched_rows: Annotated[int, Field(ge=0)]
    returned_rows: Annotated[int, Field(ge=0)]
    decimated: bool

    @model_validator(mode="after")
    def consistent_rows(self):
        if not self.returned_rows <= self.matched_rows <= self.total_rows:
            raise ValueError("Invalid telemetry row counts.")
        if len(self.data) != self.returned_rows or any(
            len(row) != len(self.columns) for row in self.data
        ):
            raise ValueError("Telemetry rows must match the declared dimensions.")
        return self


class MassProperties(EngineConfig):
    mass_kg: Positive
    center_of_mass_m: Number
    inertia_kg_m2: Annotated[list[Number], Field(min_length=6, max_length=6)]


class ComponentMassProperties(MassProperties):
    id: str
    name: str
    mass_source: Literal["computed", "measured", "provided"]
    outline_z_radius_m: list[Annotated[list[Number], Field(min_length=2, max_length=2)]]
    effective_length_m: Positive | None
    fin_outline_m: (
        list[Annotated[list[Number], Field(min_length=2, max_length=2)]] | None
    ) = None


class MassPropertySources(EngineConfig):
    mass: Literal["computed", "measured"]
    center_of_mass: Literal["computed", "measured"]
    inertia: Literal["computed", "measured"]


class DesignReport(EngineConfig):
    schema_version: Literal[1] = 1
    scope: Literal["airframe_without_motor"]
    coordinate_system: Literal["tail_to_nose"]
    automatic: MassProperties
    effective: MassProperties
    sources: MassPropertySources
    components: list[ComponentMassProperties]
    notes: list[str]


class DesignPreview(EngineConfig):
    simulation: SimulationConfig
    mass_properties: DesignReport


class SavedDesignRecord(EngineConfig):
    design_id: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
    name: str
    created_at: str


class ImportedFile(EngineConfig):
    path: str
    original_name: str
    size_bytes: Annotated[int, Field(ge=0)]


class OpenRocketOptions(EngineConfig):
    """Explicit UARC simulation settings, not inferred from an OpenRocket flight."""

    environment: EnvironmentConfig
    flight: FlightConfig
    power_off_drag: NonNegativeCurve
    power_on_drag: NonNegativeCurve
    motor: MotorConfig | None = None
    motor_position: Number = 0.0
    tanks: list[MassBasedTankConfig] = Field(default_factory=list)
    parachute_trigger: Literal["apogee"] | NonNegative | None = None


class OpenRocketImport(EngineConfig):
    design: RocketDesign
    warnings: list[str]
