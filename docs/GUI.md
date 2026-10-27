# GUI and terrain requirements

This document records workspace requirements and implementation guidance. The
desktop now includes component editors, 2D/3D previews, environment/weather
editors, a terrain map, jobs, and results. See [frontend usage](../frontend/README.md)
for implemented controls and [validation](./VALIDATION.md) for tested behavior
and remaining physical/model limitations.

## Workspace and visual design

Use `dockview-react` for tabs, docking, and resizing. Keep the default workspace
simple; extra plots and diagnostics open on demand.

| Area | Contents |
| --- | --- |
| Top | File/edit/view menus, save, run, cancel, workspace preset |
| Left | Component tree, saved designs, run history |
| Center | Rocket preview, site/trajectory map, result plots as dockable tabs |
| Right | Numeric properties of the selected component, site, or plot |
| Bottom | Collapsible problems, job queue, logs |
| Status bar | Units, coordinate reference, save state, current run |

Provide design and analysis presets plus layout reset. The rocket preview has a
`2D / 3D` selector in its toolbar; changing view retains the design and selection.
The map may switch between plan and terrain views independently. A selected part
is shared by the tree, preview, and property editor. Use neutral surfaces, thin
borders, restrained typography, and one accent; avoid decorative cards, textures,
gradients, or unnecessary animation. Keep units next to values. Controls remain
usable by keyboard, and coordinates/mass/results have a text or table equivalent.

## Numeric editing and live rocket preview

The editable `RocketDesign` is the source of truth. Reuse `preview_design` and its
`DesignReport`; do not implement a second Haack profile or mass calculator in JS.

1. Keep intermediate input text local to the field. A blank or partially typed
   number must not become zero or corrupt the last valid design.
2. Commit valid numeric edits to a new design revision. Coalesce preview requests
   with a short trailing delay; allow at most one request in flight and retain
   only the newest pending revision. The backend currently permits one preview.
3. Render only the response matching the latest revision. Keep the last valid
   preview visible with an explicit pending/invalid state, rather than showing
   an old calculation as if it matched the current fields.
4. Derive both views from the same canonical geometry and component IDs. Camera
   movement, selection, visibility, and switching views do not request a new
   physics calculation. Editing does not automatically start a flight.

| View | Rendering approach |
| --- | --- |
| 2D | Native SVG: outlines, fins, axis/dimensions, selection, packed hardware, and labelled CG |
| 3D | Three.js: revolve nose/body/tail profiles; extrude fin outlines and repeat by count/angle; simple solids for packed hardware |

The report's `outline_z_radius_m` supplies bounded profiles, not a complete 3D
mesh. Combine it with typed component metadata for thickness, fin count/cant,
transforms, and interior placement. Motor/propellant/tank geometry needs an explicit
preview representation derived from the existing input models; do not represent
those as extra airframe mass. Indicate omitted/approximate geometry visibly.
Support an interior-visibility toggle for fuel, hardware, and packed parachutes.

Preserve the documented [position conventions](./DESIGN.md#coordinate-convention).
Convert axes once at the renderer boundary: e.g. Three.js `LatheGeometry` revolves
about Y while the design uses axial Z. View transformations must never change
solver coordinates. Label preview CG as **airframe without motor** until a complete
motor-inclusive mass report exists; do not present it as the loaded rocket CG.
Material appearance is a display choice, not evidence of structural analysis.

Rebuild only changed geometry, dispose replaced GPU resources, and render on
change. Pause hidden panels and release viewers when closed. Handle docking
resizes, unavailable WebGL, and context loss without losing the editable design;
retain a usable 2D fallback. Measure latency on supported desktop WebEngine builds
before setting a guaranteed frame rate or response target.

## Launch site, maps, and terrain data

Use environment latitude/longitude as the launch marker and initial map center.
Changing coordinates updates the marker and requests the relevant map/elevation
data. Panning alone must not edit the site; choosing a new launch point is explicit.
Keep atmosphere/date/wind controls in the same environment editor, but do not
replace weather merely because a map tile changed.

CesiumJS is the candidate for 2D maps and a 3D globe with terrain and trajectories.
Three.js remains the local rocket geometry viewer. Avoid adding a second map
engine or React-specific renderer wrapper unless it solves a demonstrated need.
The renderer is not a data service: select and document imagery and elevation
providers, coverage, resolution, attribution, access requirements, and permitted
caching before enabling downloads. Do not assume a free renderer supplies free,
unlimited terrain. The implemented default automatically loads AWS public Terrain Tiles for the launch site and streams surrounding visual terrain; offline DEM import and optional OpenTopography acquisition share the calculation grid. VWorld is a separately keyed satellite-imagery option.

Distinguish base-map imagery from numeric elevation data. Images alone cannot
validate elevation or provide ground-contact heights. Use a DEM with a declared
surface type; a DSM may include trees/buildings and must not silently stand in
for bare-earth terrain. Water/sea coverage and missing values need explicit rules.

Python should own the terrain dataset used for checks and impact calculations:
fetch/import it outside the GUI thread, validate bounds/size/CRS/nodata, and freeze
the required coverage before submitting a terrain-aware run. Extend the existing
file-authorization and snapshot paths instead of accepting arbitrary bridge
paths or URLs. Bound downloads, timeouts, disk cache, and memory use. Keep data
credentials outside designs, logs, and source control; load no remote app code
into the privileged desktop bridge context.

The map and solver must use the same elevation dataset/version and compatible
interpolation, even if the display mesh is simplified. Camera zoom/LOD must not
change a computed landing position. If a separate background terrain is shown,
identify it as visual context and overlay the calculation terrain/coverage rather
than claiming they match. A browser-only terrain sample is not a solver input.

Proposed storage extends the existing user data root with `terrain/` for bounded
cached datasets. Runs snapshot the used data or retain immutable content-addressed
assets with reference tracking so cache cleanup cannot invalidate saved runs.
Save source/version/hash, extent, horizontal/vertical references, units,
resolution, nodata policy, interpolation, and any conversion grids with each run.
Continue publishing completion only after required assets/results are stored.
Nothing in this section currently creates runtime files.

## Elevation consistency checks

`EnvironmentConfig.elevation` is a launch elevation interpreted as ASL by current
results. Its `datum` field does not define a vertical height reference. Cesium's
sampled terrain heights are relative to its reference ellipsoid; incoming DEMs
can use other references. Do not compare raw heights until both horizontal and
vertical references, units, and surface meanings agree.

For ellipsoidal height `h`, orthometric height `H`, and geoid undulation `N`, use
`h = H + N` with the appropriate named geoid model. If a required conversion is
unavailable, report **not verified**, not an elevation mismatch or an automatic
correction. Convert supported source datums explicitly; never relabel coordinates
as WGS84. Preserve the current configuration default when loading old designs.

| Condition | UI behavior |
| --- | --- |
| Comparable terrain data | Show input elevation, sampled ground elevation, difference, source/resolution, and tolerance |
| Difference exceeds tolerance | Nonmodal warning beside elevation and in the problems panel |
| Launch pad/platform above terrain | Compare the expected pad offset separately; do not force the launch point onto bare ground |
| Reference unknown or conversion unavailable | Not verified; explain the missing reference/conversion |
| Coverage missing, nodata, offline without cache | Data unavailable; never substitute a height of zero |

Make tolerance explicit/configurable and account for the dataset's documented
accuracy; pixel spacing alone is not an accuracy estimate. Never silently overwrite
an entered elevation. Offer **use terrain elevation** only after a valid conversion,
preserve the pad offset, and support undo. For example, comparable ground height
80 m plus a declared 2 m pad offset is consistent with an 82 m launch elevation.
Coordinate changes invalidate previous checks; discard stale network responses.

## Trajectory and predicted ground contact

Flat-ground mode uses RocketPy's launch-elevation plane. Terrain mode attaches
the frozen DEM to `GroundSurface` and uses the isolated `TerrainFlight` event
adapter verified against RocketPy 1.13.0. It detects the first trajectory/terrain
crossing, supports valleys below launch elevation, and stops with an error on
missing coverage or an incompatible height reference. Surrounding AWS display
tiles do not extend the solver's frozen coverage. Terrain changes ground contact;
it does not add terrain-induced winds or aerodynamic forces.

Terrain-aware impact needs an engine-level event for the first valid airborne
crossing of `z(t) - ground_height(x(t), y(t)) = 0`, using a common height reference.
Exclude initial launch contact without missing collisions with rising terrain.
Refine contact on the integration trajectory with bounded steps/root tolerance;
do not use decimated chart points. A sloping-ground crossing may occur while the
rocket's vertical velocity is positive. Update the termination reason, impact
state, summary, and saved trajectory consistently at first contact.

The engine must also support descent below the launch elevation when landing in
a valley. Postprocessing an already truncated flat-plane flight cannot recover
that segment. Choose and verify a supported integration/event extension before
advertising terrain-aware results; avoid monkey-patching RocketPy internals or
changing launch elevation just to move the termination plane.

Convert local flight east/north coordinates and altitude to map coordinates via
one documented geodetic transform consistent with RocketPy's local-earth model.
Test zero displacement and cardinal directions. Distinguish design-local axes,
flight coordinates, map projection, and display axes. Set an explicit validity
range for the local-earth approximation; do not hard-code metres per degree.

Display launch/ground-contact markers, trajectory, contact time, predicted
latitude/longitude/elevation, and distance/bearing from launch. Keep the selected
run snapshot separate from the edited environment. Synchronize map and plots
through selected simulation time. Replay uses saved results and is not a new
live solve. A max-time/apogee stop without contact has **no landing estimate**.

Submitting or selecting an execution opens the result plot and map together in
separate dock groups, reopening closed panels. Existing separate placements are
retained. Re-selecting the same execution also focuses both views and restores
3D. The map frames the complete saved flight at its actual scale; short flights
must remain visible rather than inheriting the site's wide minimum camera range.
The flight line retains absolute heights above the terrain with an outlined
monochrome stroke. Pending/failed selections show their state without presenting
an earlier flight. The full map trajectory remains independent of plot query
filters, with selected time shared by both views.

If terrain becomes unavailable along the path, mark terrain impact as unresolved.
Do not extrapolate silently or relabel a flat-plane result as terrain-aware.
An explicitly selected flat-ground run may still complete and must retain its
model label. Terrain-aware mode must not depend on live HTTP inside ODE steps.

Label contact as a **predicted landing/impact position**, not an exact location.
Terrain improves the contact surface, but wind, drag/recovery parameters, initial
conditions, terrain quality, and model assumptions still affect the result.
Show data resolution and model status; later dispersion runs can supply a stated
uncertainty region. Decimal coordinate precision alone is not physical accuracy.

## Implementation order and verification

1. Build the numeric editor, shared geometry, SVG/Three.js previews, and docking.
   Verify a Haack/fin edit changes both views consistently; part moves preserve
   reference points and update computed CG. Test invalid text, stale previews,
   selection, view switching, and cleanup without starting a flight.
2. Add the site map and Python-owned DEM ingestion/checks. Use offline fixtures
   for known elevations, datum/reference mismatches, nodata, pad offsets, late
   responses, missing credentials, and stored-data replay.
3. Extend the flight contract/events for terrain contact. Compare flat terrain
   against current results; test an analytic slope, a valley below launch height,
   rising-ground collision, initial contact exclusion, missing coverage, and
   time-limited runs. Verify saved summaries match the final contact state.
4. Connect map/plots/playback and measure edit latency, hidden-panel CPU/GPU use,
   memory, and cancellation while terrain is loading. Test keyboard navigation,
   WebGL fallback, and the packaged Qt/WebEngine application, not just a browser.

Use feature-local modules under the existing `rocket`, `environment`, `simulation`,
and `results` directories. Add backend terrain responsibilities only when these
features are implemented. Complete concrete TypeScript bridge contracts alongside
each feature; do not rely on the current broad `JsonObject` types for new UI code.
Follow [frontend conventions](../CODING_STYLE.md#6-frontend-conventions).

## References

* [Design coordinates and model limitations](./DESIGN.md)
* [Three.js LatheGeometry](https://threejs.org/docs/pages/LatheGeometry.html)
* [CesiumJS fundamentals](https://cesium.com/learn/cesiumjs-fundamentals/)
* [Cesium terrain rendering](https://cesium.com/learn/cesiumjs-learn/cesiumjs-terrain/)
* [Cesium terrain sampling and height reference](https://cesium.com/learn/cesiumjs/ref-doc/global.html#sampleTerrain)
* [RocketPy Flight source and impact events](https://docs.rocketpy.org/en/latest/_modules/rocketpy/simulation/flight.html)
