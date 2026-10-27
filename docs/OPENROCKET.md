# OpenRocket import

UARC reads the documented OpenRocket XML format directly with Python's standard
library. ZIP `.ork` archives must contain one `rocket.ork`; plain UTF-8 XML and
gzip-compressed XML are also accepted. No archive entries are extracted.
RocketSerializer is not a dependency: it requires Java and an OpenRocket JAR,
which would add another runtime to the desktop application.

## Convert and run

From `backend/`:

```bash
uv run uarc-data --data-dir ../data import-ork tests/fixtures/single-stage.ork --options ../examples/openrocket-options.json --output ../data/imported-design.json
uv run python -m app.simulation ../data/imported-design.json --design --preview
uv run python -m app.simulation ../data/imported-design.json --design --data-dir ../data
```

The example and options describe synthetic hardware. Replace the motor/thrust,
drag curves, environment, and launch conditions with your inputs. The options
are validated as `OpenRocketOptions`; no weather, motor database selection,
flight result, or simulation condition is inferred from the `.ork` file.
File-valued options must refer to imported files under the selected data root.

Without `--output`, the command prints `{ "design": ..., "warnings": [...] }`.
With `--output`, it writes the editable `RocketDesign` and prints conversion
notes to stderr. Existing output files are preserved. `parachute_trigger` in
the options can explicitly replace recovery events that UARC cannot represent.
Without that option, only apogee and descending-altitude deployment are accepted.

For a future UI, call `select_input_file()` first, then
`import_openrocket(asset_path, options_json)`. The bridge accepts only already
authorized assets. The CLI authorizes its explicit source argument and copies
it into `inputs/` before conversion.

## Supported conversion

| Source | UARC representation |
| --- | --- |
| One axial stage | Tail-to-nose stations; OpenRocket tip-to-tail positions are converted |
| Body/inner tubes and tube couplers | Uniform annular cylinders |
| Bulkheads, explicit-radius centering rings and engine blocks | Solid/annular cylinders |
| Conical, ellipsoid, tangent-ogive, full-parabolic noses | Corresponding native RocketPy families |
| Haack and power-series noses | Numeric `haack_c` / `power` |
| Conical transitions with positive end radii | Tail surface and radial wall |
| Square-section trapezoidal/elliptical fins | Fin dimensions, count, sweep, and cant in degrees |
| Axis-centered mass components | Packed cylinders with provided/measured mass |
| Shock cords | Editable line material/length and packed cylinder geometry |
| Parachutes | Packed mass, projected area, line mass, deployment condition/delay |
| Component mass overrides | Measured part mass; geometric CG/inertia conventions remain UARC's |

Axial positioning supports `top`, `middle`, `bottom`, `absolute`, and `after`.
Legacy `<position>` and modern `<axialoffset>` must agree when both appear.
Automatic outer radii are resolved from adjacent components; supported internal
automatic radii use a cylindrical parent's inner radius. Ambiguous automatic
radii must be made explicit in OpenRocket.

OpenRocket surface and line materials retain their native kg/m² and kg/m
densities. Parachute canopy mass uses area without an artificial volume-density
conversion; suspension lines retain their material and total length. Fabric
thickness is retained as an unused placeholder for surface-density canopies,
not a measured property. Body/nose/fin/tail finish labels produce an explicit
warning rather than a numerical conversion: enter independently documented
surface roughness in UARC. No simulator material or finish lookup table is used;
densities come only from values embedded in the selected design file.
See the [material library](./DESIGN.md#material-library-and-surface-data).
Parachute Cd and suspension-line length must be explicit in the source design;
automatic simulator defaults are rejected with an actionable error.
No attachment anchor is present in these inputs: the initial attachment
station is the packed CG and is identified as an assumption in the warnings.

Unsupported physical features raise errors: multiple stages, pods/boosters,
off-axis or repeated/clustered parts, freeform/tube fins, fin tabs/fillets,
non-square fin sections, shoulders, clipped/flipped profiles, curved transitions,
CG/CD/subcomponent overrides, and per-flight recovery configurations. No such
part is silently discarded. Paint, appearance, and stored simulation results do
not affect the imported physical model.

## Limits and validation

The importer accepts format versions 1.0–1.11, archives up to 8 MiB, XML up to
2 MiB, at most 128 archive entries, 4096 XML elements, depth 32, and 64 resulting
components. DTD/entity declarations are rejected before parsing; embedded
scripts and simulation extensions are never executed.

Tests cover plain/ZIP/gzip round trips, analytic tube/recovery masses, coordinates,
cant units, malicious XML, decompression limits, unsupported geometry, and a real
spawned flight from the imported design. Compare imported mass, CG, and flight
results with your reference model before using a converted vehicle. UARC's
geometry/mass approximations and supplied drag curves determine its results;
import does not establish numerical equivalence with OpenRocket.

Format references: [OpenRocket file specification](https://openrocket.readthedocs.io/en/latest/dev_guide/file_specification.html),
[component savers](https://github.com/openrocket/openrocket/tree/unstable/core/src/main/java/info/openrocket/core/file/openrocket/savers),
[parachute model](https://github.com/openrocket/openrocket/blob/unstable/core/src/main/java/info/openrocket/core/rocketcomponent/Parachute.java),
[RocketSerializer requirements](https://github.com/RocketPy-Team/RocketSerializer#requirements).
