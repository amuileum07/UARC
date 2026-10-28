"""Independent preliminary Cd0 models; equations and limits: docs/AERODYNAMICS.md.

Gregorek TR-11 body/streamlined-fin form and base drag, with NACA-793
fully turbulent smooth/rough flat-plate friction. No external simulator code.
All coefficients use the full body cross-section and zero-incidence axial drag.
The optional compressible model adds a restricted conical/fin pressure estimate.
"""

from dataclasses import dataclass
from math import atan, degrees, hypot, isclose, isfinite, log10, pi, radians, sqrt, tan

from app.schemas.aerodynamics import DragFin, DragGeometry, DragReport, DragSurface
from app.schemas.design import BodyTubeDesign, RocketDesign, SurfaceDesign
from app.schemas.rocket import (
    EllipticalFinsConfig,
    NoseConeConfig,
    TrapezoidalFinsConfig,
)

MAX_MACH = 0.7


def skin_friction(reynolds: float, length: float, roughness: float) -> float:
    """Plate-average turbulent Cf. Re<1e4 uses a finite low-speed floor."""
    smooth = 0.455 / log10(max(reynolds, 1e4)) ** 2.58
    rough = (1.89 + 1.62 * log10(length / roughness)) ** -2.5 if roughness else 0
    # An envelope between smooth and fully rough limits, not a transition solver.
    return max(smooth, rough)


@dataclass(frozen=True)
class DragValues:
    skin_friction: float
    form: float
    base_off: float
    base_on: float
    nose_pressure: float = 0.0
    fin_pressure: float = 0.0

    @property
    def total_off(self):
        return (
            self.skin_friction
            + self.form
            + self.base_off
            + self.nose_pressure
            + self.fin_pressure
        )

    @property
    def total_on(self):
        return (
            self.skin_friction
            + self.form
            + self.base_on
            + self.nose_pressure
            + self.fin_pressure
        )


def drag_coefficients(
    geometry: DragGeometry, mach: float, reynolds: float
) -> DragValues:
    """Re is based on body DIAMETER, matching RocketPy's seven-input drag API."""
    high_speed = geometry.model == "compressible_v1"
    limit = 3.0 if high_speed else MAX_MACH
    if not isfinite(mach) or not 0 <= mach <= limit:
        raise ValueError(
            f"Automatic Cd0 ({geometry.model}) supports Mach 0–{limit}; received {mach:.4g}. "
            "Use a measured/imported drag curve for faster flight."
        )
    if not isfinite(reynolds) or reynolds < 0:
        raise ValueError("Drag Reynolds number must be finite and non-negative.")
    diameter = 2 * geometry.reference_radius_m
    reference_area = pi * geometry.reference_radius_m**2
    friction = form = forebody = body_skin = body_skin_at_one = 0.0
    for surface in geometry.surfaces:
        local_re = reynolds * surface.length_m / diameter
        cf = (
            _compressible_friction(
                local_re, surface.length_m, surface.roughness_m, mach
            )
            if high_speed
            else skin_friction(local_re, surface.length_m, surface.roughness_m)
        )
        skin = cf * surface.wetted_area_m2 / reference_area
        friction += skin
        form += skin * (surface.form_factor - 1)
        if surface.kind == "body":
            forebody += skin * surface.form_factor
            body_skin += skin
            if high_speed:
                body_skin_at_one += (
                    _compressible_friction(
                        local_re / mach if mach else 0.0,
                        surface.length_m,
                        surface.roughness_m,
                        1.0,
                    )
                    * surface.wetted_area_m2
                    / reference_area
                )
    exposed = 1 - (geometry.nozzle_radius_m / geometry.reference_radius_m) ** 2
    if high_speed:
        from app.compressible_drag import pressure_drag

        nose, fins, base = pressure_drag(geometry, mach, body_skin, body_skin_at_one)
        return DragValues(friction, form, base, base * exposed**1.5, nose, fins)
    # TR-11 Eq. 2, with Eq. 3's equivalent exposed base diameter during thrust.
    base = 0.029 / sqrt(forebody)
    return DragValues(friction, form, base, base * exposed**1.5)


def _compressible_friction(reynolds, length, roughness, mach):
    # Recovery-wall smooth and rough correlations, Barrowman Eqs. 4-12/13.
    # The recovery-wall relation supplies a continuous low-Mach extension.
    smooth = skin_friction(reynolds, length, 0) / (1 + 0.15 * mach**2) ** 0.58
    rough = (
        (1.89 + 1.62 * log10(length / roughness)) ** -2.5 / (1 + 0.18 * mach**2)
        if roughness
        else 0.0
    )
    return max(smooth, rough)


@dataclass(frozen=True)
class DragFunction:
    geometry: DragGeometry
    powered: bool

    def __call__(self, alpha, beta, mach, reynolds, pitch_rate, yaw_rate, roll_rate):
        values = drag_coefficients(self.geometry, mach, reynolds)
        return values.total_on if self.powered else values.total_off


def compile_drag(design: RocketDesign, components: list[dict], radius: float):
    """Validate the supported outer mold line and derive immutable solver geometry."""
    high_speed = design.automatic_drag.model == "compressible_v1"
    tubes = sorted(
        (c for c in design.components if isinstance(c, BodyTubeDesign)),
        key=lambda c: c.position,
    )
    noses = [
        c
        for c in design.components
        if isinstance(c, SurfaceDesign) and isinstance(c.surface, NoseConeConfig)
    ]
    fins = [
        c
        for c in design.components
        if isinstance(c, SurfaceDesign)
        and isinstance(c.surface, (TrapezoidalFinsConfig, EllipticalFinsConfig))
    ]
    other = [
        c
        for c in design.components
        if isinstance(c, SurfaceDesign) and c not in noses and c not in fins
    ]
    if not tubes or len(noses) != 1 or other:
        raise ValueError(
            "Automatic Cd0 requires contiguous equal-radius tubes, one pointed nose, "
            "and optional uncanted fins; tails/transitions require a manual drag curve."
        )
    body_radius = tubes[0].outer_radius
    if not isclose(radius, body_radius, rel_tol=1e-7):
        raise ValueError(
            "Automatic Cd0 requires the reference radius to match the body."
        )
    aft, front = tubes[0].position, tubes[0].position
    for tube in tubes:
        if not isclose(tube.outer_radius, body_radius, rel_tol=1e-7) or not isclose(
            tube.position, front, abs_tol=1e-7
        ):
            raise ValueError(
                "Automatic Cd0 does not support body gaps, overlaps or steps."
            )
        front += tube.length
    nose = noses[0]
    shape = nose.surface
    reports = {c["id"]: c for c in components}
    nose_length = reports[nose.id]["effective_length_m"]
    if high_speed and (
        shape.kind != "conical"
        or not 3 - 1e-9 <= nose_length / (2 * body_radius) <= 10 + 1e-9
        or not isclose(shape.rocket_radius, body_radius, rel_tol=1e-7)
    ):
        raise ValueError(
            "Mach 0–3 automatic Cd0 requires a conical nose with length/diameter 3–10. "
            "Keep the current shape with a manual curve or the subsonic model."
        )
    if (
        shape.bluffness not in (None, 0)
        or nose_length / (2 * body_radius) < 2
        or not isclose(
            shape.base_radius or shape.rocket_radius, body_radius, rel_tol=1e-7
        )
        or not isclose(shape.position - nose_length, front, abs_tol=1e-7)
    ):
        raise ValueError(
            "Automatic Cd0 needs a sharp, flush nose with length/diameter ≥ 2."
        )
    total_length = front - aft + nose_length
    fineness = total_length / (2 * body_radius)
    if fineness < 5:
        raise ValueError("Automatic Cd0 requires overall length/diameter ≥ 5.")
    body_factor = 1 + 60 / fineness**3 + 0.0025 * (front - aft) / (2 * body_radius)
    if high_speed:
        body_factor = 1 + 1 / (2 * fineness)
    fin_geometry = []
    patches, notes = [], []

    def add(component, kind, length, area, factor):
        finish = component.surface_finish
        roughness = 0.0
        if finish is None:
            notes.append(
                f"{component.id}: no measured ks; hydraulically smooth assumed."
            )
        elif finish.roughness_m and finish.roughness_type != "equivalent_sand_grain":
            raise ValueError(
                f"{component.id}: automatic Cd0 needs equivalent sand-grain ks; "
                "Ra/legacy roughness cannot be converted automatically."
            )
        else:
            roughness = finish.roughness_m
        patches.append(
            DragSurface(
                component_id=component.id,
                kind=kind,
                length_m=length,
                wetted_area_m2=area,
                form_factor=factor,
                roughness_m=roughness,
            )
        )

    for tube in tubes:
        add(tube, "body", total_length, 2 * pi * body_radius * tube.length, body_factor)
    # Frustum strips integrate the same outer profile used for mass and rendering.
    profile = reports[nose.id]["outline_z_radius_m"]
    area = sum(
        pi * (r0 + r1) * hypot(z1 - z0, r1 - r0)
        for (z0, r0), (z1, r1) in zip(profile, profile[1:], strict=False)
    )
    add(nose, "body", total_length, area, body_factor)
    for fin in fins:
        surface = fin.surface
        if high_speed:
            if not isinstance(surface, TrapezoidalFinsConfig) or surface.tip_chord <= 0:
                raise ValueError(
                    "Mach 0–3 automatic Cd0 needs trapezoidal fins with positive tip chord."
                )
            sweep = surface.sweep_length
            if sweep is None:
                sweep = (
                    surface.span * tan(radians(surface.sweep_angle))
                    if surface.sweep_angle is not None
                    else surface.root_chord - surface.tip_chord
                )
            fin_geometry.append(
                DragFin(
                    count=surface.n,
                    root_chord_m=surface.root_chord,
                    tip_chord_m=surface.tip_chord,
                    span_m=surface.span,
                    thickness_m=fin.thickness,
                    midchord_sweep_deg=degrees(
                        atan(
                            (sweep + (surface.tip_chord - surface.root_chord) / 2)
                            / surface.span
                        )
                    ),
                )
            )
        outline = reports[fin.id]["outline_z_radius_m"]
        if (
            surface.cant_angle != 0
            or not isclose(surface.rocket_radius, body_radius, rel_tol=1e-7)
            or min(p[0] for p in outline) < aft - 1e-7
            or max(p[0] for p in outline) > front + 1e-7
            or fin.thickness / surface.root_chord > 0.1
        ):
            raise ValueError(
                f"{fin.id}: automatic Cd0 requires thin, uncanted fins on the tube."
            )
        if isinstance(surface, EllipticalFinsConfig):
            planform = pi * surface.root_chord * surface.span / 4
            chord = 8 * surface.root_chord / (3 * pi)
        else:
            planform = (surface.root_chord + surface.tip_chord) * surface.span / 2
            chord = (
                2
                / 3
                * (
                    surface.root_chord**2
                    + surface.root_chord * surface.tip_chord
                    + surface.tip_chord**2
                )
                / (surface.root_chord + surface.tip_chord)
            )
        if fin.thickness / chord > 0.1:
            raise ValueError(f"{fin.id}: fin thickness/MAC must be ≤ 0.1.")
        add(
            fin,
            "fin",
            chord,
            2 * surface.n * planform,
            1.0 if high_speed else 1 + 2 * fin.thickness / chord,
        )
    nozzle_radius = 0.0
    if design.motor is not None:
        motor = design.motor
        sign = (
            1
            if motor.coordinate_system_orientation == "nozzle_to_combustion_chamber"
            else -1
        )
        if not isclose(
            design.motor_position + sign * motor.nozzle_position, aft, abs_tol=1e-7
        ):
            raise ValueError(
                "Automatic Cd0 currently requires a nozzle flush with the body base."
            )
        nozzle_radius = motor.nozzle_radius
    compressible = None
    if high_speed:
        from app.compressible_drag import prepare_compressible

        compressible = prepare_compressible(body_radius, nose_length, fin_geometry)
    geometry = DragGeometry(
        model=design.automatic_drag.model,
        reference_radius_m=body_radius,
        body_length_m=total_length,
        nozzle_radius_m=nozzle_radius,
        surfaces=patches,
        compressible=compressible,
    )
    return geometry, drag_report(geometry, notes)


def drag_report(geometry: DragGeometry, notes: list[str]) -> DragReport:
    """A reproducible reference preview, not the launch-site weather or flight Re."""
    temperature, pressure = 288.15, 101325.0
    density = pressure / (287.05287 * temperature)
    viscosity = 1.458e-6 * temperature**1.5 / (temperature + 110.4)
    speed_of_sound = sqrt(1.4 * 287.05287 * temperature)
    samples = []
    high_speed = geometry.model == "compressible_v1"
    for mach in (
        (0.1, 0.3, 0.7, 0.9, 1.0, 1.1, 1.2, 1.5, 2.0, 2.5, 3.0)
        if high_speed
        else (0.1, 0.3, 0.5, 0.7)
    ):
        reynolds = (
            density
            * speed_of_sound
            * mach
            * 2
            * geometry.reference_radius_m
            / viscosity
        )
        values = drag_coefficients(geometry, mach, reynolds)
        samples.append(
            dict(
                mach=mach,
                reynolds_diameter=reynolds,
                skin_friction=values.skin_friction,
                form=values.form,
                base_off=values.base_off,
                base_on=values.base_on,
                total_off=values.total_off,
                total_on=values.total_on,
                nose_pressure=values.nose_pressure,
                fin_pressure=values.fin_pressure,
            )
        )
    return DragReport(
        model=geometry.model,
        reference_area_m2=pi * geometry.reference_radius_m**2,
        reference_temperature_k=temperature,
        reference_pressure_pa=pressure,
        max_mach=3.0 if high_speed else MAX_MACH,
        samples=samples,
        notes=[
            "Preliminary Cd0: Mach 0–3, conical nose and sharp symmetric double-wedge fins."
            if high_speed
            else "Preliminary Cd0 only: Mach ≤ 0.7, slender sharp-nosed axisymmetric body.",
            "Finite-span/sweep pressure interactions, square edges, protuberances, "
            "angle-of-attack drag and separation are not modeled.",
            "Transonic nose rise is calibrated to NACA RM L53K17 L_n/D=3 flight data; scaling to other fineness ratios is unvalidated."
            if high_speed
            else "No compressibility/wave-drag correction; transonic/supersonic flight is rejected.",
            "Powered base drag uses nozzle-area exclusion only; plume pressure/interactions are not resolved.",
            *(
                [
                    "NASA SP-3004 Table 9 checks cone pressure only (5°/7.5°, Mach 1.5–3); transonic total Cd0 and finite-fin pressure are not independently validated.",
                    "Double-wedge section is an aerodynamic assumption; mass/rendering keep the flat-plate approximation. Use measured fin mass overrides.",
                ]
                if high_speed
                else []
            ),
            "Fully turbulent boundary layer; Re_L < 1e4 is regularized, not validated.",
            "This table uses 288.15 K / 101325 Pa. Flight uses local weather and Reynolds number.",
            *notes,
        ],
    )
