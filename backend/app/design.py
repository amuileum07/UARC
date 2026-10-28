"""Convert axis-centered component designs into mass properties and solver inputs."""

from functools import cache
from math import cos, pi, radians, sin

import numpy as np

from app.schemas import (
    BodyTubeDesign,
    DesignReport,
    EllipticalFinsConfig,
    LineDesign,
    MassComponentDesign,
    NoseConeConfig,
    ParachuteConfig,
    ParachuteDesign,
    RocketConfig,
    RocketDesign,
    SimulationConfig,
    SurfaceDesign,
    TrapezoidalFinsConfig,
)


@cache
def _quadrature():
    # Smooth axial shells use 128-point Gauss-Legendre integration. Split the
    # inner-wall cutoff; use adaptive integration if localized features are added.
    return np.polynomial.legendre.leggauss(128)


def _cylinder(mass, radius, length):
    transverse = mass * (3 * radius**2 + length**2) / 12
    return np.array([transverse, transverse, mass * radius**2 / 2, 0, 0, 0])


def _shell(profile, length, thickness, density, position, direction):
    breaks = [0.0, length]
    if profile(0) < thickness < profile(length):
        low, high = 0.0, length
        for _ in range(60):
            middle = (low + high) / 2
            if profile(middle) < thickness:
                low = middle
            else:
                high = middle
        breaks.insert(1, (low + high) / 2)
    nodes, weights = _quadrature()
    coordinates, masses, radial_moments = [], [], []
    for left, right in zip(breaks, breaks[1:], strict=False):
        local = (left + right) / 2 + nodes * (right - left) / 2
        integration_weights = weights * (right - left) / 2
        outer = np.array([float(profile(float(x))) for x in local])
        inner = np.maximum(outer - thickness, 0)
        area = pi * (outer**2 - inner**2)
        coordinates.append(position + direction * local)
        masses.append(density * area * integration_weights)
        radial_moments.append(
            density * pi * (outer**4 - inner**4) * integration_weights / 4
        )
    z, dm, radial = map(np.concatenate, (coordinates, masses, radial_moments))
    mass = float(np.sum(dm))
    if not np.isfinite(mass) or mass <= 0:
        raise ValueError("Component mass is outside the supported numerical range.")
    center = float(np.sum(z * dm) / mass)
    transverse = float(np.sum((z - center) ** 2 * dm + radial))
    axial = float(2 * np.sum(radial))
    return mass, center, np.array([transverse, transverse, axial, 0, 0, 0])


def _fin_properties(surface, thickness, density):
    if isinstance(surface, EllipticalFinsConfig):
        area = pi * surface.span * surface.root_chord / 4
        mean_r = 4 * surface.span / (3 * pi)
        mean_r2 = surface.span**2 / 4
        mean_z = -surface.root_chord / 2
        mean_z2 = 5 * surface.root_chord**2 / 16
        outline = [
            (
                surface.span * sin(theta),
                -surface.root_chord / 2 + surface.root_chord * cos(theta) / 2,
            )
            for theta in np.linspace(0, pi, 65)
        ]
    else:
        sweep = surface.sweep_length
        if sweep is None:
            sweep = (
                surface.span * np.tan(radians(surface.sweep_angle))
                if surface.sweep_angle is not None
                else surface.root_chord - surface.tip_chord
            )
        outline = [
            (0, 0),
            (0, -surface.root_chord),
            (surface.span, -sweep - surface.tip_chord),
            (surface.span, -sweep),
        ]
        points = np.array(outline)
        following = np.roll(points, -1, axis=0)
        cross = points[:, 0] * following[:, 1] - following[:, 0] * points[:, 1]
        area = float(np.sum(cross) / 2)
        means = np.sum((points + following) * cross[:, None], axis=0) / (6 * area)
        second = np.sum(
            (points**2 + points * following + following**2) * cross[:, None], axis=0
        ) / (12 * area)
        mean_r, mean_z = means
        mean_r2, mean_z2 = second
    mass = float(density * area * thickness * surface.n)
    angle = radians(surface.cant_angle)
    c, s = cos(angle), sin(angle)
    radial2 = (
        surface.rocket_radius**2
        + 2 * surface.rocket_radius * mean_r
        + mean_r2
        + mean_z2 * s**2
        + thickness**2 * c**2 / 12
    )
    variance_z = max(0, mean_z2 - mean_z**2) * c**2 + thickness**2 * s**2 / 12
    transverse = mass * (radial2 / 2 + variance_z)
    # Equally spaced n>=3 fins cancel transverse CG offsets and products of inertia.
    inertia = np.array([transverse, transverse, mass * radial2, 0, 0, 0])
    center = float(surface.position + mean_z * c)
    profile = [
        [float(surface.position + z * c), float(surface.rocket_radius + r)]
        for r, z in outline
    ]
    return mass, center, inertia, profile, [[float(r), float(z)] for r, z in outline]


def _component_properties(component, design):
    # Runtime assembly stays in the engine; no native object leaves this function.
    from app.simulation.engine import build_surface

    radius = 0.0
    profile = []
    fin_outline = None
    effective_length = None
    if isinstance(component, MassComponentDesign):
        mass, center = component.mass, component.position
        inertia = (
            _cylinder(mass, component.radius, component.length)
            if component.inertia is None
            else np.array((*component.inertia, 0, 0, 0)[:6])
        )
    else:
        material = design.materials[component.material]
        density = material.density
        if isinstance(component, BodyTubeDesign):
            radius = component.outer_radius
            mass, center, inertia = _shell(
                lambda _: radius,
                component.length,
                component.thickness,
                density,
                component.position,
                1,
            )
            profile = [
                [component.position, radius],
                [component.position + component.length, radius],
            ]
        elif isinstance(component, ParachuteDesign):
            line_mass = component.line_mass
            if component.line_material is not None:
                line_mass = (
                    design.materials[component.line_material].density
                    * component.line_length
                )
            mass = (
                density
                * component.canopy_area
                * (component.thickness if material.density_type == "bulk" else 1)
                + line_mass
            )
            center = component.position
            # Packed canopy/lines are a uniform cylinder; supply measured mass
            # or a measured assembly inertia when packing geometry matters.
            inertia = _cylinder(mass, component.packed_radius, component.packed_length)
            profile = [
                [center - component.packed_length / 2, component.packed_radius],
                [center + component.packed_length / 2, component.packed_radius],
            ]
        elif isinstance(component, LineDesign):
            mass = density * component.line_length
            center = component.position
            inertia = _cylinder(mass, component.packed_radius, component.packed_length)
            profile = [
                [center - component.packed_length / 2, component.packed_radius],
                [center + component.packed_length / 2, component.packed_radius],
            ]
        else:
            surface = component.surface
            if isinstance(surface, (TrapezoidalFinsConfig, EllipticalFinsConfig)):
                radius = surface.rocket_radius
                mass, center, inertia, profile, fin_outline = _fin_properties(
                    surface, component.thickness, density
                )
            elif isinstance(surface, NoseConeConfig):
                native = build_surface(surface)
                radius = native.base_radius
                effective_length = native.length
                if surface.bluffness in (None, 0):

                    def outer(x):
                        return float(native.y_nosecone(x))
                else:
                    # Blunted tips use RocketPy's sampled outline; refine the
                    # native outline if tighter geometric mass accuracy is needed.
                    def outer(x):
                        return float(np.interp(x, *native.shape_vec))

                mass, center, inertia = _shell(
                    outer,
                    native.length,
                    component.thickness,
                    density,
                    surface.position,
                    -1,
                )
                profile = [
                    [float(surface.position - x), outer(x)]
                    for x in native.length * np.linspace(0, 1, 129) ** 2
                ]
            else:
                radius = max(surface.top_radius, surface.bottom_radius)

                def outer(x):
                    return (
                        surface.top_radius
                        + (surface.bottom_radius - surface.top_radius)
                        * x
                        / surface.length
                    )

                mass, center, inertia = _shell(
                    outer,
                    surface.length,
                    component.thickness,
                    density,
                    surface.position,
                    -1,
                )
                profile = [
                    [surface.position, surface.top_radius],
                    [surface.position - surface.length, surface.bottom_radius],
                ]
        if component.mass_override is not None:
            inertia *= component.mass_override / mass
            mass = component.mass_override
    if not np.isfinite([mass, center, *inertia]).all() or mass <= 0:
        raise ValueError(f"Invalid mass properties for component {component.id}.")
    return {
        "id": component.id,
        "name": component.name,
        "mass_kg": float(mass),
        "mass_source": (
            "provided"
            if isinstance(component, MassComponentDesign)
            else "measured"
            if component.mass_override is not None
            else "computed"
        ),
        "center_of_mass_m": float(center),
        "inertia_kg_m2": inertia.tolist(),
        "outline_z_radius_m": profile,
        "effective_length_m": effective_length,
        "fin_outline_m": fin_outline,
    }, radius


def compile_design(design: RocketDesign) -> tuple[SimulationConfig, dict]:
    """Compute airframe properties; motor and propellant are added by RocketPy."""
    components, radii = [], []
    drag_geometry = drag_report = None
    try:
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            for component in design.components:
                properties, radius = _component_properties(component, design)
                components.append(properties)
                radii.append(radius)
            mass = sum(component["mass_kg"] for component in components)
            center = (
                sum(c["mass_kg"] * c["center_of_mass_m"] for c in components) / mass
            )
            inertia = np.zeros(6)
            for component in components:
                inertia += component["inertia_kg_m2"]
                inertia[:2] += (
                    component["mass_kg"] * (component["center_of_mass_m"] - center) ** 2
                )
            if not np.isfinite([mass, center, *inertia]).all():
                raise ValueError(
                    "Assembly mass properties exceed the supported numerical range."
                )
            automatic = {
                "mass_kg": mass,
                "center_of_mass_m": center,
                "inertia_kg_m2": inertia.tolist(),
            }
            if design.overrides.mass is not None:
                inertia *= design.overrides.mass / mass
                mass = design.overrides.mass
            if design.overrides.center_of_mass is not None:
                center = design.overrides.center_of_mass
            if design.overrides.inertia is not None:
                inertia = np.array((*design.overrides.inertia, 0, 0, 0)[:6])
            if design.automatic_drag is not None:
                from app.aerodynamics import compile_drag

                drag_geometry, drag_report = compile_drag(
                    design, components, max(radii)
                )
            config = SimulationConfig(
                environment=design.environment,
                flight=design.flight,
                motor=design.motor,
                tanks=design.tanks,
                surfaces=[
                    c.surface for c in design.components if isinstance(c, SurfaceDesign)
                ],
                rocket=RocketConfig(
                    radius=max(radii),
                    mass=mass,
                    center_of_mass_without_motor=center,
                    inertia=tuple(float(x) for x in inertia),
                    power_off_drag=design.power_off_drag,
                    power_on_drag=design.power_on_drag,
                    automatic_drag=drag_geometry,
                    motor_position=design.motor_position,
                    rail_buttons=design.rail_buttons,
                    parachutes=[
                        ParachuteConfig(
                            **c.deployment.model_dump(exclude={"cd_s"}),
                            cd_s=(
                                c.deployment.cd_s
                                if c.deployment.cd_s is not None
                                else c.deployment.drag_coefficient
                                * pi
                                * c.deployment.radius**2
                            ),
                        )
                        for c in design.components
                        if isinstance(c, ParachuteDesign)
                    ],
                ),
            )
    except ArithmeticError as error:
        raise ValueError(
            "Design dimensions exceed the supported numerical range."
        ) from error
    report = {
        "schema_version": 1,
        "scope": "airframe_without_motor",
        "coordinate_system": "tail_to_nose",
        "automatic": automatic,
        "effective": {
            "mass_kg": config.rocket.mass,
            "center_of_mass_m": config.rocket.center_of_mass_without_motor,
            "inertia_kg_m2": list(config.rocket.inertia),
        },
        "sources": {
            key: "measured"
            if getattr(design.overrides, key) is not None
            else "computed"
            for key in ("mass", "center_of_mass", "inertia")
        },
        "components": components,
        "aerodynamics": drag_report,
        "notes": [
            f"Automatic Cd0 ({drag_geometry.model}) uses geometry and local Reynolds number."
            if drag_geometry is not None
            else "Drag curves are user inputs; geometry/material changes do not estimate drag.",
            "Parachute attachment_position is design metadata; attachment torque is not modeled.",
            "A CG override shifts the effective CG without reconstructing component masses.",
        ],
    }
    return config, DesignReport.model_validate(report).model_dump(mode="json")
