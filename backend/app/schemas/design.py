"""Editable rocket designs, mass reports, and design import/export models."""

from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from .aerodynamics import AutomaticDrag, DragReport
from .common import (
    EngineConfig,
    Inertia,
    NonNegative,
    NonNegativeCurve,
    Number,
    Positive,
    _inertia,
)
from .environment import EnvironmentConfig
from .propulsion import (
    HybridMotorConfig,
    LiquidMotorConfig,
    MassBasedTankConfig,
    MotorConfig,
)
from .rocket import (
    NoseConeConfig,
    ParachuteConfig,
    RailButtonsConfig,
    SurfaceConfig,
    TailConfig,
)
from .simulation import FlightConfig, SimulationConfig


class MaterialConfig(EngineConfig):
    name: Annotated[str, Field(min_length=1, max_length=128)]
    density: Positive = Field(description="Bulk kg/m³, surface kg/m², or line kg/m.")
    density_type: Literal["bulk", "surface", "line"] = "bulk"
    catalog_id: Annotated[str, Field(max_length=128)] | None = None


class SurfaceFinishConfig(EngineConfig):
    name: Annotated[str, Field(min_length=1, max_length=128)]
    roughness_m: NonNegative
    roughness_type: Literal["openrocket", "equivalent_sand_grain", "ra"]
    catalog_id: Annotated[str, Field(max_length=128)] | None = None


class DesignComponent(EngineConfig):
    id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
    name: Annotated[str, Field(max_length=128)] = ""


class MaterialComponent(DesignComponent):
    material: str
    mass_override: Positive | None = None


class BodyTubeDesign(MaterialComponent):
    component_type: Literal["body_tube"] = "body_tube"
    surface_finish: SurfaceFinishConfig | None = None
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
    surface_finish: SurfaceFinishConfig | None = None
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


class LineDesign(MaterialComponent):
    """Cord/webbing mass at its packed CG; no deployed cord aerodynamic model."""

    component_type: Literal["line"] = "line"
    position: Number
    line_length: Positive = Field(description="Total cord/webbing length, m.")
    packed_radius: NonNegative = 0.0
    packed_length: NonNegative = 0.0


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
    line_material: str | None = None
    line_length: NonNegative = Field(
        default=0.0,
        description="Total suspension line length; replaces line_mass when a line material is selected.",
    )
    packed_radius: Positive
    packed_length: Positive
    deployment: ParachuteDeployment


ComponentDesign = Annotated[
    BodyTubeDesign | SurfaceDesign | MassComponentDesign | ParachuteDesign | LineDesign,
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
    automatic_drag: AutomaticDrag | None = None
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
            if isinstance(component, MaterialComponent):
                kind = self.materials[component.material].density_type
                allowed = (
                    {"bulk", "surface"}
                    if isinstance(component, ParachuteDesign)
                    else {"line"}
                    if isinstance(component, LineDesign)
                    else {"bulk"}
                )
                if kind not in allowed:
                    raise ValueError(
                        f"Material density type {kind} cannot be used for {component.id}."
                    )
            if (
                isinstance(component, ParachuteDesign)
                and component.line_material is not None
            ):
                line = self.materials.get(component.line_material)
                if (
                    line is None
                    or line.density_type != "line"
                    or component.line_length <= 0
                ):
                    raise ValueError(
                        "Parachute lines need a line material and positive total length."
                    )
        if not any(
            isinstance(c, (BodyTubeDesign, SurfaceDesign)) for c in self.components
        ):
            raise ValueError("A design needs a body tube or aerodynamic surface.")
        needs_tanks = isinstance(self.motor, (LiquidMotorConfig, HybridMotorConfig))
        if needs_tanks != bool(self.tanks):
            raise ValueError("Only liquid/hybrid motors require and accept tanks.")
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
    aerodynamics: DragReport | None = None


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
