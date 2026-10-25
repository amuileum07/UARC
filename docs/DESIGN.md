# Numeric rocket design

`examples/design.json` is a complete synthetic, editable design. It supplies
dimensions and densities rather than a precomputed airframe mass/CG/inertia.
All dimensions and physical quantities use SI units: m, kg, s, kg/m³, and kg·m²;
angles use degrees. Material values in the example are demonstration inputs,
not a certified material catalogue.

## Data and editing

`RocketDesign` contains a material dictionary, up to 64 uniquely identified
components, environment/flight settings, a motor and optional tanks, motor
position, drag curves, rail buttons, and optional assembly measurements.

| Component | Numeric inputs | Mass representation |
| --- | --- | --- |
| `body_tube` | Position, length, outer radius, radial thickness, material | Uniform annular cylinder; thickness equal to radius is solid |
| `surface` with `surface_type="nose"` | Nose family, dimensions, position, radial wall thickness, material | Axisymmetric shell with a solid tip where radius is below thickness |
| `surface` with trapezoidal/elliptical fins | Count, root/tip chord, span, sweep, cant, position, plate thickness, material | Equally spaced, uniform extruded plates |
| `surface` with `surface_type="tail"` | End radii, length, position, radial thickness, material | Axisymmetric conical-frustum wall |
| `mass` | Measured mass, position, optional cylinder dimensions or intrinsic inertia | Axis-centered hardware/payload; zero dimensions represent a point mass |
| `parachute` | Packed position/size, fabric area/thickness/material, line mass, attachment station, deployment settings | Packed canopy and lines approximated as a uniform cylinder |

Changing a material's density updates every component referencing that material.
Changing a part's position updates its contribution to assembly CG and transverse
inertia. Fin/nose dimensions and positions also change the aerodynamic surfaces
passed to RocketPy. Body drag remains an explicit input curve, not an automatic
CFD result of changing geometry or material.

The TypeScript bridge exports `previewDesign`, `submitDesign`, `getDesign`,
`getDesignReport`, and `rerunSimulation`. Inputs and outputs are JSON-compatible;
`get_config_schema("design")` exposes the validated field definitions. Numeric
form controls can use these endpoints; the React editor itself is still planned.

## Coordinate convention

Designs currently use axis-centered components with station values increasing
from tail toward nose (`tail_to_nose`). Choose one body reference station as zero
and retain it for the whole design; negative stations are allowed. Surface
positions in a parametric design are axial scalars rather than XYZ tuples.

| Position field | Reference point |
| --- | --- |
| Tube `position` | Aft end; the tube extends in +z |
| Nose `surface.position` | Nose tip; the nose extends aft |
| Fin `surface.position` | Root leading edge before cant rotation |
| Tail `surface.position` | Forward end; the transition extends aft |
| Hardware `position` | Component CG |
| Parachute `position` | Packed parachute CG |
| Parachute `attachment_position` | Attachment station, saved as design metadata |
| `motor_position` | Origin of the motor frame in rocket coordinates |

Motor grain/chamber/tank positions retain their motor-local coordinate system
and orientation. They are not added to airframe component masses. RocketPy adds
motor and propellant mass, inertia, and time-dependent CG during flight. The
preview report is explicitly scoped to `airframe_without_motor`; complete
initial/final rocket mass and CG appear in flight summaries.

## Calculation and measured overrides

Component mass follows density times modelled volume. Airframe CG is
`sum(component_mass * component_cg) / total_mass`; central inertias are combined
with the parallel-axis theorem. Fins are equally spaced with `n >= 3`, so their
transverse offsets cancel. Cant rotates the fin plate about its radial leading-
edge axis. Tube/nose/tail walls use radial thickness, not a normal-offset shell
or a full manufacturing mesh. Smooth shells use 128-point Gauss-Legendre
quadrature with the inner-wall cutoff split explicitly; blunted noses follow
RocketPy's sampled outline.

Each material-based part accepts `mass_override`. This scales its intrinsic
inertia with measured mass while retaining its shape and CG. A `mass` component
can instead supply measured intrinsic inertia about its own CG.

Assembly `overrides` accepts `mass`, `center_of_mass`, and `inertia` independently:

* A mass override scales computed central inertia by the mass ratio.
* A CG override changes the effective CG without reconstructing component masses
  or changing computed central inertia. Move/add a mass component when its actual
  distribution should be modelled.
* An inertia override takes precedence over computed/scaled inertia and must be
  expressed about the effective assembly CG, in rocket-frame axes.

The report contains `automatic`, `effective`, per-property `sources`, component
mass properties, and bounded outlines. Its original computed values remain
available when measurements are supplied. Geometry, metadata, and mass inputs
are never silently rewritten during preview.

## Continuous Haack noses and recovery

Set the nose family to `kind="haack"` and vary `haack_c` from 0 to 1/3. C=0 is
the Von Kármán outline and C=1/3 is the LV-Haack outline. Length and base radius
remain independent numeric inputs. The new continuous family currently requires
a sharp tip (`bluffness` absent or zero). Other nose families continue to use
RocketPy's native implementation, including its supported blunt tips.

The continuous profile uses the small-angle body-of-revolution pressure-center
relation `CP_from_tip = L - volume/base_area = L*(1/2 - 3*C/16)`. This is an
explicit aerodynamic approximation, not a CFD pressure result. RocketPy's native
fixed `lvhaack` family retains its own CP coefficient (0.563L), so its CP convention
differs even where the outer outline matches. Existing direct simulation inputs
keep their native family behaviour. Drag curves remain caller-supplied.

Parachute fabric mass uses actual `canopy_area`, density, thickness, and added
`line_mass`. The deployed projected area uses `pi * deployment.radius²`;
`Cd*A` is derived from this area and `drag_coefficient`, unless an explicit
`deployment.cd_s` measurement overrides it. Fabric area and deployed projected
area describe different quantities and are independent inputs.

Packed position affects airframe mass properties. `attachment_position` is
preserved for the editor and drawing, but the current flight model does not
compute attachment-point torque or a separate suspended-body dynamics model.

## Persistence and replay

`submit_design` compiles the design, snapshots accepted local files, and saves
`design.json`, `design_report.json`, and the derived `input.json` in a new run.
The worker receives only solver inputs and keeps all flight objects locally.

`get_design(run_id)` returns an editable model whose file references point to
saved input assets. Such assets may be copied into a subsequent run; metadata
files and arbitrary paths remain disallowed. Editing/re-submitting never changes
the original run. `rerun(run_id)` reuses frozen solver inputs with a new run ID;
edit and submit the design to recalculate mass properties instead. Live weather
provider responses are not frozen by local-file snapshots.
