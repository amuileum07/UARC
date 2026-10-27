"""Shared serializable types and validation helpers; no runtime engine objects."""

from datetime import UTC, datetime
from itertools import pairwise
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np
from pydantic import AfterValidator, BaseModel, ConfigDict, Field

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
