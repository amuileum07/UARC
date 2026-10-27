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
| `line` | Line material, total length, packed CG/radius/length, optional measured mass | Line density × length; packed cylinder inertia |
| `parachute` | Packed position/size, fabric area/thickness/material, manual line mass or line material/length, attachment station, deployment settings | Packed canopy and lines approximated as a uniform cylinder |

Changing a material's density updates every component referencing that material.
Changing a part's position updates its contribution to assembly CG and transverse
inertia. Fin/nose dimensions and positions also change the aerodynamic surfaces
passed to RocketPy. Body drag remains an explicit input curve, not an automatic
CFD result of changing geometry or material.

## Material library and surface data

[`backend/app/materials.json`](../backend/app/materials.json) is the shared,
offline source of material values, surface finishes, per-family guidance,
calculation usage, source URLs, document sections, and evidence limitations.
The desktop material editor reads this file through `get_material_catalog()`;
it is included in both Python packages and desktop bundles. No material lookup
requires a network request. Source buttons open the registered document in the
system browser only when selected.

The catalogue contains **86 independently sourced density presets**: 43 bulk,
16 surface and 27 line. Sources include manufacturer technical sheets and product
specifications, industry references, USDA's Wood Handbook and original research.
Each entry identifies its evidence type, source and grade/condition limitations.
Simulator material/finish tables are not bundled. These presets do not overwrite
existing designs or claim to cover every material supported by other programs.

| Family | Examples and scope |
| --- | --- |
| Metals | 6061 aluminum, steel reference, austenitic stainless product-group reference, C26000 brass, C11000 copper, Grade 2 titanium |
| Plastics | PLA, PETG, POM-C/POM-H, PA66, PMMA, PC, ABS, solid GPPS, PVC-U, HDPE/LDPE, PP, regenerated cellulose, PET film and product-specific Quantum Tube estimates |
| Wood/cork | Balsaflex 150, five USDA species at 12% moisture, KoskiPly Standard birch plywood and an NL20 cork research specimen |
| Composites/fibres | Cured HexPly 8552 AS4 UD, NP500A glass/epoxy G-10, NP629 paper/phenolic XX and raw Kevlar 29 filament |
| Foams | Two ROHACELL IG-F grades, two Filcor EPS grades, Terra XPS 300/500 and a specified 3 mm Depron research specimen |
| Paper/fabric/film | Xpression Bright kraft paper, unstretched crepe paper, Habotai silk, DWR ripstop nylon, finished coated nylon/polyester, specified cellulose/LDPE thicknesses and bare Mylar 2/6/13 µm |
| Cord/webbing/thread | Selected HMPE, polyamide, polyester, aramid and polyester-covered Vectran cords, elastic shockcord, tubular/flat webbing and sewing thread |

Conversions retain the source's definitions. USDA Table 5-3a specific gravity
uses oven-dry mass and volume at the stated moisture content: the 12% MC presets
use `density = G12 × 1000 × 1.12`, including water mass. Paper's apparent bulk
density is explicitly `grammage / thickness` for the same product column.
Coated fabrics use finished coated weight. Rope values use kg/100 m or g/m;
thread `tex` is g/1000 m. Shockcord length is its zero-tension reference length.
Specific-gravity conversions use the conventional 1000 kg/m³ water reference.
These are reference estimates, not batch certificates or structural allowables.

Film areal density is `bulk density × nominal thickness`, explicitly labelled
as a conversion rather than measured grammage. Habotai silk uses the supplier's
momme definition: pounds per 45 inch × 100 yard piece; `mm` is not millimetres.
Crepe grade names denote roll mass, so the finished, unstretched g/m² is used.
Quantum QT-2.1/3.0 use `mass / (π × (outer_radius² − inner_radius²) × length)`
from each product's nominal wall dimensions and listed mass. These estimates
are sensitive to wall thickness; actual component mass overrides take priority.

The `research_gaps` list, also shown in the material editor, records unresolved
metallised films, other fabric/cord specifications, finished proprietary tubes,
other foam grades and aerodynamic surface roughness. Blue Tube's engineering
sheet provides a 1300–1450 kg/m³ range; one dealer's 54 mm dimensions/mass imply
about 1208 kg/m³, so no single preset is assigned to that unresolved discrepancy.
A lower bound or range without a representative nominal density is not silently used as a point
value. Research-specimen values are labelled separately from product data.
Only individual property facts, unit conversions and independently written
notes are included; publisher documents, figures and complete tables are not
redistributed. Source documents retain their own terms.

In **재질 → 사용자 재질 추가**, users enter a name, bulk/surface/line density
type and a positive finite density before adding the material. Changing the
type clears the draft value to prevent accidental unit reinterpretation. These
materials belong to the design, are editable, and survive saved snapshots and
`.uarc` export/import. Built-in presets are copied into the design rather than
linked to mutable catalogue values. The existing limit is 64 materials per design.

| `MaterialConfig.density_type` | Unit | Allowed use |
| --- | --- | --- |
| `bulk` (legacy default) | kg/m³ | Body/nose/fins/tail; canopy mass = density × fabric area × thickness |
| `surface` | kg/m² | Canopy mass = density × actual fabric area; thickness is unused |
| `line` | kg/m | Cord/webbing mass = density × total length; also parachute suspension lines |

For parachutes, selecting `line_material` uses its density × `line_length`
(all lines combined) **instead of** `line_mass`. Clearing it restores the saved
manual `line_mass`. Material dimension mismatches and missing line references
are rejected. Measured component mass still takes precedence. Designs embed
their editable numerical values and origin `catalog_id`; reopening never
replaces these with current catalogue defaults. The existing 64-material limit
applies to selected design materials, not the library.

External body/surface parts save an optional `surface_finish` with nonnegative
`roughness_m`, `roughness_type`, name and optional origin ID. Equivalent
sand-grain roughness `ks`, measured arithmetic roughness `Ra`, and legacy model
heights remain distinct. No roughness presets or automatic conversions are
provided. Enter a finished-part measurement or independently documented value.
A missing finish is unknown, not a zero-roughness assumption. Existing design
snapshots, including legacy model-height tags, remain readable without a lookup
table or replacing their stored values.

SDS/MSDS physical-property sections can supply density but do not establish
finished-part aerodynamic roughness. Use TDS for the actual grade/lay-up and
measured surface/process data for skin friction; Ra alone cannot establish ks
(Flack & Schultz, 2010, DOI 10.1115/1.4001492). No universal material-specific Cd,
porosity, elastic modulus or strength is invented. Source notes are explicitly
scoped to their products, not every member of a material family.

**Current solver use:** density affects mass, CG and inertia. Surface finish is
preserved as input metadata for a future validated aerodynamic model; the
explicit `power_on_drag`/`power_off_drag` curves remain authoritative. RocketPy
surface lift/CP use shape and flow; material selection does not assign a new
lift coefficient. No CFD or aeroelastic/flutter solver is introduced.

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

Component mass follows density times modelled volume, area or length according
to the material's density type. Airframe CG is
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

Parachute fabric mass uses actual `canopy_area` and areal density, or bulk
density × thickness for legacy/bulk materials. Lines use manual `line_mass` or
the selected line material × total length. The deployed projected area uses
`pi * deployment.radius²`;
`Cd*A` is derived from this area and `drag_coefficient`, unless an explicit
`deployment.cd_s` measurement overrides it. Fabric area and deployed projected
area describe different quantities and are independent inputs.

Packed position affects airframe mass properties. `attachment_position` is
preserved for the editor and drawing, but the current flight model does not
compute attachment-point torque or a separate suspended-body dynamics model.

## Persistence and replay

`save_design` stores a new immutable design snapshot independently of simulation
history. `list_designs` and `get_saved_design` enumerate/load these snapshots.
Each save creates a new `design_id`; edits never replace earlier snapshots.
Referenced local files are copied into `designs/<design-id>/` and remain usable
after the originals are removed. The file CLI is `uv run uarc-data`; see the
[backend usage guide](../backend/README.md#design-files-external-inputs-and-exports).

`submit_design` compiles the design, snapshots accepted local files, and saves
`design.json`, `design_report.json`, and the derived `input.json` in a new run.
The worker receives only solver inputs and keeps all flight objects locally.

`get_design(run_id)` returns an editable model whose file references point to
saved input assets. Such assets may be copied into a subsequent run; metadata
files and arbitrary paths remain disallowed. Copied assets of known standalone
saved designs can also be reused. Editing/re-submitting never changes
the original run. `rerun(run_id)` reuses frozen solver inputs with a new run ID;
edit and submit the design to recalculate mass properties instead. Live weather
provider responses are not frozen by local-file snapshots.
