"""Independent conical-body / double-wedge-fin engineering estimate, Mach 0–3.

Sources, adaptations and validation limits are recorded in docs/AERODYNAMICS.md.
Taylor–Maccoll solves inviscid cone flow; fin strips use oblique shocks and
Prandtl–Meyer expansion. Sonic anchors follow the NASA-hosted Barrowman (1967)
thesis; base drag uses Fleeman's correlation as published by Orgeira-Crespo
et al. (2022), Eq. 17. No external simulator implementation is incorporated.
"""

from bisect import bisect_right
from functools import lru_cache
from math import asin, atan, cos, pi, sin, sqrt, tan

import numpy as np
from scipy.integrate import solve_ivp
from scipy.interpolate import PchipInterpolator
from scipy.optimize import brentq, minimize_scalar

from app.schemas.aerodynamics import (
    CompressibleGeometry,
    DragFin,
    DragGeometry,
    SupersonicPressure,
)

GAMMA = 1.4
MAX_MACH = 3.0

# NACA RM L53K17 Fig. 5, cone L_n/D=3, read to about ±0.005 in Cd_p.
# These points calibrate the transonic rise; they are not independent validation.
# Scaling to other fineness ratios uses the 1967 sonic correlation and remains
# an engineering approximation. Replace with a multi-fineness experimental model
# before claiming general transonic accuracy.
_TRANSONIC_CONE = (
    (0.8, 0.020),
    (0.9, 0.040),
    (1.0, 0.115),
    (1.05, 0.163),
    (1.1, 0.157),
    (1.15, 0.150),
)


@lru_cache(maxsize=128)
def _nose_transonic(sonic_nose, first_supersonic, second_mach, second_supersonic):
    scale = sonic_nose / (0.88 / 3.7**1.29)
    return PchipInterpolator(
        [0.6, 0.7, *(m for m, _ in _TRANSONIC_CONE), 1.2, second_mach],
        [
            0,
            0,
            *(cd * scale for _, cd in _TRANSONIC_CONE),
            first_supersonic,
            second_supersonic,
        ],
    )


@lru_cache(maxsize=128)
def _fin_transonic(sonic, first_supersonic, second_mach, second_supersonic):
    return PchipInterpolator(
        [0.6, 0.7, 1.0, 1.2, second_mach],
        [0, 0, sonic, first_supersonic, second_supersonic],
    )


@lru_cache(maxsize=512)
def cone_pressure(mach: float, angle: float) -> float:
    """Cone Cp, angle in radians. Weak attached shock, perfect gas gamma=1.4."""
    velocity = sqrt((GAMMA - 1) * mach**2 / (2 + (GAMMA - 1) * mach**2))

    def rhs(theta, state):
        radial, polar = state
        sound2 = (GAMMA - 1) / 2 * (1 - radial**2 - polar**2)
        return polar, (
            polar**2 * radial - sound2 * (2 * radial + polar / tan(theta))
        ) / (sound2 - polar**2)

    def wall(theta, state):
        return state[1]

    wall.terminal = True
    wall.direction = 1

    def solution(beta):
        normal_mach2 = (mach * sin(beta)) ** 2
        density_ratio = (GAMMA + 1) * normal_mach2 / ((GAMMA - 1) * normal_mach2 + 2)
        radial = velocity * cos(beta)
        polar = -velocity * sin(beta) / density_ratio
        result = solve_ivp(
            rhs,
            (beta, 1e-5),
            (radial, polar),
            events=wall,
            rtol=1e-8,
            atol=1e-10,
            max_step=0.02,
        )
        if not result.success or not result.t_events[0].size:
            raise ValueError(
                "Taylor–Maccoll integration failed; use a measured drag curve."
            )
        return result.t_events[0][0], result.y_events[0][0], radial, polar, normal_mach2

    low = asin(1 / mach) + 1e-4
    # Stop at the first crossing to select the weak shock, not the strong branch.
    for high in np.arange(low + 0.01, pi / 2 - 0.01, 0.01):
        if solution(float(high))[0] >= angle:
            break
    else:
        raise ValueError("No attached cone shock in the supported Mach/angle range.")
    beta = brentq(lambda value: solution(value)[0] - angle, low, float(high), xtol=1e-9)
    _, (radial_wall, polar_wall), radial, polar, normal_mach2 = solution(beta)
    pressure_ratio = (1 + 2 * GAMMA / (GAMMA + 1) * (normal_mach2 - 1)) * (
        (1 - radial_wall**2 - polar_wall**2) / (1 - radial**2 - polar**2)
    ) ** (GAMMA / (GAMMA - 1))
    return float((pressure_ratio - 1) / (0.5 * GAMMA * mach**2))


def _prandtl_meyer(mach):
    root = sqrt(mach**2 - 1)
    scale = sqrt((GAMMA + 1) / (GAMMA - 1))
    return scale * atan(root / scale) - atan(root)


@lru_cache(maxsize=4096)
def wedge_pressure_drag(mach: float, thickness_ratio: float) -> float:
    """2D sharp symmetric double wedge Cd based on chord area, zero incidence."""
    theta = atan(thickness_ratio)

    def turning(beta):
        return atan(
            2
            / tan(beta)
            * (mach**2 * sin(beta) ** 2 - 1)
            / (mach**2 * (GAMMA + cos(2 * beta)) + 2)
        )

    lower = asin(1 / mach) + 1e-10
    peak = minimize_scalar(
        lambda beta: -turning(beta), bounds=(lower, pi / 2 - 1e-8), method="bounded"
    ).x
    if turning(peak) <= theta:
        raise ValueError("Fin wedge shock detaches; use thinner fins or measured drag.")
    beta = brentq(lambda value: turning(value) - theta, lower, peak, xtol=1e-11)
    normal2 = (mach * sin(beta)) ** 2
    front_pressure = 1 + 2 * GAMMA / (GAMMA + 1) * (normal2 - 1)
    downstream_mach = sqrt(
        (1 + (GAMMA - 1) / 2 * normal2) / (GAMMA * normal2 - (GAMMA - 1) / 2)
    ) / sin(beta - theta)
    if downstream_mach <= 1:
        raise ValueError("Fin shock leaves subsonic flow; the strip model is invalid.")
    expanded_angle = _prandtl_meyer(downstream_mach) + 2 * theta
    expanded_mach = brentq(
        lambda value: _prandtl_meyer(value) - expanded_angle,
        downstream_mach,
        50,
        xtol=1e-10,
    )
    rear_pressure = front_pressure * (
        (1 + (GAMMA - 1) / 2 * downstream_mach**2)
        / (1 + (GAMMA - 1) / 2 * expanded_mach**2)
    ) ** (GAMMA / (GAMMA - 1))
    # Upper/lower surfaces each have half-chord front and rear facets.
    return (front_pressure - rear_pressure) * thickness_ratio / (0.5 * GAMMA * mach**2)


def prepare_compressible(
    radius: float, nose_length: float, fins: list[DragFin]
) -> CompressibleGeometry:
    """Freeze pressure tables once per design; no shock/ODE solve during flight."""
    nodes, weights = np.polynomial.legendre.leggauss(8)
    angle, reference_area = atan(radius / nose_length), pi * radius**2
    rows = []
    for mach in np.linspace(1.2, MAX_MACH, 37):
        fin_drag = 0.0
        for fin in fins:
            chords = (fin.root_chord_m + fin.tip_chord_m) / 2 + nodes * (
                fin.tip_chord_m - fin.root_chord_m
            ) / 2
            # Independent 2D strips neglect tip Mach-cone and sweep interactions.
            # Restrict midchord sweep to ±10°; upgrade to a finite-wing method for
            # broader geometry. Constant plate thickness applies across the span.
            fin_drag += (
                fin.count
                * fin.span_m
                / (2 * reference_area)
                * sum(
                    float(weight * chord)
                    * wedge_pressure_drag(float(mach), float(fin.thickness_m / chord))
                    for weight, chord in zip(weights, chords, strict=True)
                )
            )
        rows.append(
            SupersonicPressure(
                mach=float(mach),
                nose=cone_pressure(float(mach), angle),
                fins=fin_drag,
            )
        )
    return CompressibleGeometry(nose_length_m=nose_length, fins=fins, pressure=rows)


def _interpolate_pressure(geometry: CompressibleGeometry, mach: float, key: str):
    rows = geometry.pressure
    index = max(
        0, min(bisect_right(rows, mach, key=lambda row: row.mach) - 1, len(rows) - 2)
    )
    left, right = rows[index : index + 2]
    return getattr(left, key) + (getattr(right, key) - getattr(left, key)) * (
        mach - left.mach
    ) / (right.mach - left.mach)


def pressure_drag(
    geometry: DragGeometry, mach: float, body_skin: float, body_skin_at_one: float
) -> tuple[float, float, float]:
    """Return nose pressure, fin pressure and coasting base Cd, all on body area."""
    compressible = geometry.compressible
    radius, length = geometry.reference_radius_m, geometry.body_length_m
    fineness = length / (2 * radius)
    nose_fineness = compressible.nose_length_m / (2 * radius)
    sonic_nose = 0.88 / (nose_fineness + 0.7) ** 1.29
    if mach <= 0.7:
        # Barrowman Eqs. 4-41, 4-42, 4-44, with the full nose-cylinder afterbody.
        numerator = 6 * body_skin / fineness**3
        constant = (6 * body_skin_at_one / (fineness**3 * sonic_nose)) ** (5 / 3)
        nose = numerator / (1 - mach**2 + constant) ** 0.6
    elif mach < 1.2:
        # NACA measured cone rise + inviscid cone anchors. This is a UARC
        # adaptation, not Drew–Jenn's complete arbitrary-moldline method.
        rows = compressible.pressure
        nose = float(
            _nose_transonic(sonic_nose, rows[0].nose, rows[1].mach, rows[1].nose)(mach)
        )
        if mach < 0.8:
            # Fade out the small viscous form contribution across the first join.
            weight = (mach - 0.7) / 0.1
            low_pressure = (
                6
                * body_skin
                / fineness**3
                / (
                    1
                    - mach**2
                    + (6 * body_skin_at_one / (fineness**3 * sonic_nose)) ** (5 / 3)
                )
                ** 0.6
            )
            nose += low_pressure * (1 - weight**2 * (3 - 2 * weight))
    else:
        nose = _interpolate_pressure(compressible, mach, "nose")
    sonic_fins = 0.0
    for fin in compressible.fins:
        area = (fin.root_chord_m + fin.tip_chord_m) * fin.span_m / 2
        ratio = fin.thickness_m / fin.root_chord_m
        aspect = fin.span_m**2 / area
        parameter = aspect * ratio ** (1 / 3)
        # NASA-hosted thesis Eq. 4-35, summed over individual exposed fins.
        sonic_fins += (
            fin.count
            * 1.15
            * ratio ** (5 / 3)
            * (1.61 + parameter - sqrt((parameter - 1.43) ** 2 + 0.578))
            * area
            / (pi * radius**2)
        )
    if mach <= 0.7:
        fin_pressure = 0.0
    elif mach < 1.2:
        rows = compressible.pressure
        fin_pressure = float(
            _fin_transonic(sonic_fins, rows[0].fins, rows[1].mach, rows[1].fins)(mach)
        )
    else:
        fin_pressure = _interpolate_pressure(compressible, mach, "fins")
    # Fleeman correlation, independently published in Aerospace 9(6), 286 (2022),
    # Eq. 17, DOI 10.3390/aerospace9060286. Full blunt body base, no boat-tail.
    # Both branches give 0.25 at Mach 1; their slopes need not agree.
    base = 0.12 + 0.13 * mach**2 if mach <= 1 else 0.25 / mach
    return nose, fin_pressure, base
