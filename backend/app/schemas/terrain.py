"""Terrain grids and online/offline elevation source settings."""

from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator

from .common import EngineConfig, HeightReference, Number, Positive


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
