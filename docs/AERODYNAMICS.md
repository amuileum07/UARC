# Independent preliminary drag models

Select the model in **로켓 전체 → 기체 항력 → 항력 계산 방식**:

| Model | Range | Geometry |
| --- | --- | --- |
| Manual (`automatic_drag: null`) | Defined by the input curve | Existing design capabilities |
| `subsonic_v1` | Mach 0–0.7 | Existing pointed-nose / streamlined-fin estimate |
| `compressible_v1` | Mach 0–3 | Conical nose; optional thin sharp double-wedge trapezoidal fins |

Old designs and imports retain their
manual `power_off_drag` / `power_on_drag` inputs. Switching modes preserves those
values. Automatic geometry and its model version are serialized in the worker
input; callbacks are rebuilt inside the worker, including saved-run replay.
Design exports store the model choice and original component values.

This is an engineering **estimate for preliminary design**, not a validated
replacement for measured drag curves. Similarity to another simulator does not
establish accuracy. No CFD, simulator source code or simulator coefficient tables
are incorporated. Material density still changes mass and inertia, not Cd
directly. The boundary layer is assumed fully turbulent from the leading edge.

## Compressible conical model (`compressible_v1`)

The solver still returns zero-incidence axial Cd0 on `A_ref = πR²`:

`Cd0 = skin friction + body friction form correction + nose pressure + fin pressure + body base drag`.

The model is an independent combination of the following public methods, with
explicit UARC adaptations. It is **not** a reproduction of the complete
Drew–Jenn arbitrary-moldline method, the complete Barrowman thesis, or the 2025
KSCFE SEM model. The latter paper's reported 3.0–3.8% errors do not apply here.

### Supersonic pressure and reference checks

- **Cone:** solve the Taylor–Maccoll ordinary differential equations with
  `γ=1.4`, select the weak attached shock and integrate inward to zero polar
  velocity at the cone surface. Normal-shock relations supply the shock jump;
  isentropic compression supplies the cone pressure. Cone pressure drag on its
  own base area is its surface `Cp`. This is a small inviscid cone-flow solve,
  not a Navier–Stokes CFD calculation.
- **Fins:** eight Gauss–Legendre strips across each exposed span. Each strip is
  a symmetric double wedge with maximum thickness at half chord. A weak oblique
  shock at the front and Prandtl–Meyer expansion at mid-chord give front/rear
  pressures; integrate their axial components. These are **2D strips**: finite
  span, tip Mach-cone and sweep interactions are omitted. The midpoint sweep is
  therefore restricted to ±10°. A finite-wing method is needed to expand that
  envelope. This is an approximation even within it.
- Compute pressure samples every 0.05 Mach from 1.2 to 3 **once during design
  compilation**, then serialize the table with the run. Flight callbacks only
  interpolate it; neither shock roots nor the cone ODE are solved inside the
  trajectory integrator. The original manual Cd inputs remain stored unchanged.

The relations are documented in [NACA Report 1135](https://www.grc.nasa.gov/www/k-12/airplane/Images/naca1135.pdf),
[NASA oblique-shock equations](https://www.grc.nasa.gov/WWW/BGH/oblique.html), and
[NASA Prandtl–Meyer relations](https://www1.grc.nasa.gov/beginners-guide-to-aeronautics/prandtl-meyer-angle/).
The independent numerical reference is [NACA TN 3219](https://ntrs.nasa.gov/citations/19930084108),
Table I, printed p. 23: for a 5° cone, `p_surface/p_inf` is approximately 1.048,
1.062, 1.096 and 1.178 at Mach 1.2, 1.5, 2 and 3. The computed pressure ratios
are checked against those values; the table is not used by the solver.

### Transonic nose and fin pressure

[NACA RM L53K17, Stoney (1954)](https://ntrs.nasa.gov/citations/19930087953)
reports actual zero-lift flights of fineness-3 noses, Mach 0.8–1.25, Re based on
body length 8–15 million. Fig. 5 separates nose pressure from friction and tare
drag; that separation has its own estimated/theoretical contributions.

The conical curve is read approximately as `(Mach, Cd_nose_pressure)`:
`(0.8,.020), (.9,.040), (1,.115), (1.05,.163), (1.1,.157), (1.15,.150)`.
Reading uncertainty is about ±0.005. These points **calibrate** the transonic
rise; agreement at those same points is not independent validation.

UARC scales them by the ratio of the sonic cone correlation
`0.88/(L_n/D + 0.7)^1.29` to its fineness-3 value, then uses a shape-preserving
cubic interpolation to the computed cone pressures at Mach 1.2 and above.
Scaling this single shape to other fineness ratios is an **unvalidated engineering
approximation**. The Mach 0.7–0.8 connection fades out the low-speed viscous form
term; no experimental claim is made for that connection.

Below Mach 0.7, forebody pressure uses the regularized expression from
[Barrowman (1967), NASA-hosted original](https://ntrs.nasa.gov/citations/20010047838),
Eqs. 4-41/42/44. Fin pressure joins zero at Mach 0.7, the finite-fin sonic
thickness correlation of Eq. 4-35 at Mach 1, and shock/expansion strips at Mach
1.2. It uses exposed-fin aspect ratio `span²/planform_area`. These joins are
UARC adaptations, not a complete solution of transonic flow or a wing/body
interference calculation.

For a **separate** supersonic nose-pressure check, Fig. 5's circle symbols from
its reference 1 are read approximately as `(1.24,.135), (1.44,.118), (1.96,.103)`.
They are not fit anchors. Tests compare the direct Taylor–Maccoll results with
these readings, allowing 0.012 absolute Cd for model/reading differences. This
does not validate whole-rocket drag, roughness, powered flight or the fin model.
The RM-10 configuration in NACA TN 2944 has a different body shape; it is not
presented as a matched validation case for this conical-only implementation.

### Compressible friction and base drag

The same independently sourced smooth/rough friction envelope is used, with
recovery-wall corrections from Barrowman Eqs. 4-12/13:
`Cf_smooth(M) = Cf_smooth(0)/(1 + .15 M²)^.58`,
`Cf_rough(M) = Cf_rough(0)/(1 + .18 M²)`.
The first relation is extended continuously to subsonic Mach; its low-Mach
expansion approximates Eq. 4-9. Take the larger corrected coefficient.
Body friction uses Eq. 4-16's factor `1 + 1/(2 L_total/D)`.

Coasting base drag uses the Fleeman correlation independently published in
[Orgeira-Crespo et al. (2022), *Aerospace* 9(6), 286, Eq. 17](https://doi.org/10.3390/aerospace9060286):

`Cd_base = .12 + .13 M²` for `M ≤ 1`; `Cd_base = .25/M` for `M > 1`.

Both branches meet at 0.25 at Mach 1; their derivatives are not continuous.
The paper attributes this correlation to E. L. Fleeman, *Tactical Missile
Design*, AIAA Education Series (2001), reference 29. The checked source is the
2022 paper, not the book itself. This is a blunt body-base estimate on the full
body area, with no boat-tail or base-pressure measurement correction. It does
not predict Reynolds-dependent base pressure or plume interactions.

An initial evaluation using Barrowman's friction-coupled base relation gave
substantially lower subsonic base drag. Component comparisons with OpenRocket
prompted a source review; the independently published Fleeman correlation was
selected for this model. Its constants are taken from Eq. 17, not fitted to
OpenRocket outputs. The legacy `subsonic_v1` relation remains unchanged.

Powered base drag retains the TR-11 exposed-nozzle-area factor documented below.
It is a plume approximation; pressure ratio and plume/body coupling are not
resolved. This mode does not infer a jet model from the motor's thrust curve.

### Domain and remaining limitations

- Conical, sharp, flush nose: length/diameter **3–10**. Other nose families use
  manual curves or the existing subsonic model. No silent equivalent-cone mapping.
- Equal-radius contiguous tubes and overall length/diameter ≥ 5. No tail,
  boat-tail, diameter step, gap or overlap.
- Optional **3/4** uncanted trapezoidal fins, positive tip chord, thickness/chord
  ≤ 0.05 over the entire span, midpoint sweep within ±10°, wholly on the tubes.
  Leading/trailing edges are aerodynamically assumed sharp, not square/rounded.
  Extremely small aspect ratios where Eq. 4-35 gives negative sonic drag are
  rejected explicitly rather than clamped to zero.
- Fin **mass and rendering remain flat-plate approximations**. Selecting a drag
  model does not silently change component mass. Use measured component mass for
  beveled fins; this remains independent of the aerodynamic wedge assumption.
- Mach > 3 is rejected in the worker with an actionable error. Limits on the
  subsonic model remain unchanged, preserving its saved-run behavior.
- No angle-of-attack/induced axial drag, fin/body interference, protrusions,
  large-sweep correction, separated flow, heating or aeroelasticity.

Tests cover independent cone values, the thin-airfoil limit of wedge drag,
unsupported geometries, joins/range/finite coefficients, actual 3-DOF and 6-DOF
flights through the sound barrier, immutable tables, `.uarc` export, spawn-worker
execution and saved-run replay. No external simulator implementation or output
table is used by the runtime.

### NASA/NACA verification audit

Run from `backend/` with `uv run python -m unittest discover -s tests -p
'test_compressible_drag.py' -v`. The reference values below are constants in the
tests, independent of the runtime pressure tables. The checks do not fetch the
network. Relative difference means `100 (UARC/reference - 1)`; it is a comparison
of the stated quantity, not an uncertainty bound for whole-rocket Cd0.

**Cone-flow implementation:** [Sims (1964), NASA SP-3004](https://ntrs.nasa.gov/citations/19640009035),
Table 9, printed p. 14 / PDF p. 20, gives theoretical perfect-gas surface `Cp`
for zero-incidence cones. A cone's pressure Cd on its own base area equals `Cp`.
The checked semiangles 5° and 7.5° correspond to nose length/diameter about
5.715 and 3.798, both within UARC's supported geometry. Each case is checked
both directly and through design compilation, frozen pressure tables and the
`drag_coefficients` path used by flight callbacks.

| Semiangle | Mach | NASA Cp | UARC Cp | Difference |
| --- | --- | --- | --- | --- |
| 5° | 1.50 | 0.03966150 | 0.03968308 | +0.0544% |
| 5° | 1.75 | 0.03632870 | 0.03634682 | +0.0499% |
| 5° | 2.00 | 0.03394570 | 0.03395919 | +0.0397% |
| 5° | 2.50 | 0.03058576 | 0.03059443 | +0.0283% |
| 5° | 3.00 | 0.02824024 | 0.02824647 | +0.0221% |
| 7.5° | 1.50 | 0.07738640 | 0.07740652 | +0.0260% |
| 7.5° | 1.75 | 0.07042890 | 0.07044660 | +0.0251% |
| 7.5° | 2.00 | 0.06558120 | 0.06559402 | +0.0196% |
| 7.5° | 2.50 | 0.05899520 | 0.05896761 | −0.0468% |
| 7.5° | 3.00 | 0.05451919 | 0.05452531 | +0.0112% |

Maximum observed difference is **0.0545%**. The regression tolerance is 0.1%.
This verifies the inviscid cone calculation against a separate published
numerical solution. It does not validate boundary layers, base drag or fins.
The existing NACA TN 3219 pressure-ratio check also covers Mach 1.2.

**Double-wedge building block:** [Ivey & Klunker (1947), NACA TN 1371](https://ntrs.nasa.gov/citations/19930081999),
printed p. 6 / PDF p. 7, gives rounded theoretical pressure-drag values for a
zero-lift 6%-thick symmetric double wedge with maximum thickness at half chord.
Its reference area is chord area, not the rocket's frontal area.

| Mach | NACA section pressure Cd | UARC | Difference |
| --- | --- | --- | --- |
| 1.35 | 0.0160 | 0.01610846 | +0.6779% |
| 1.60 | 0.0116 | 0.01156658 | −0.2881% |

The regression tolerance is 1%, allowing for the rounded/approximate reference.
This verifies only the 2D shock/expansion calculation. The 6% reference section
is outside the complete model's 5% finite-fin thickness limit; that limit is
unchanged. These two theoretical checks do not establish measured finite-fin
drag accuracy at any Mach number.

**Separate experimental nose comparison:** the three supersonic circle-symbol
readings in NACA RM L53K17 Fig. 5, described above, are not used for calibration.
For nose length/diameter 3, the actual compiled flight-pressure path gives:

| Mach | Approximate experimental nose pressure Cd | UARC | Difference |
| --- | --- | --- | --- |
| 1.24 | 0.135 | 0.13348 | −1.13% |
| 1.44 | 0.118 | 0.11658 | −1.21% |
| 1.96 | 0.103 | 0.09653 | −6.28% |

Readings have about ±0.005 Cd uncertainty; nose-pressure separation has further
experimental/theoretical contributions. The test allows 0.012 absolute Cd,
including model discrepancy. Three graph readings do not establish a general
6.28% error bound. They check only a fineness-3 nose below Mach 2, not total drag
or experimental accuracy up to Mach 3.

**Transonic and whole-vehicle status:** the Mach 0.8–1.15 cone values are
calibration inputs. Reproducing them is not independent experimental validation.
[NACA Report 1242](https://ntrs.nasa.gov/citations/19930090996) provides a separate
transonic cone-cylinder experiment, but its 20°/25°/30° cone semiangles are
outside this model's length/diameter 3–10 envelope. It is not counted as a matched
validation case. [NASA TR R-100](https://ntrs.nasa.gov/citations/19630004995)
collects many free-flight measurements; the inspected configurations have
different nose/tail or fin geometry, and include data from the existing
calibration experiment. Its published totals are not treated as like-for-like
validation without matching those quantities and configurations.
[NACA RM L56C13](https://ntrs.nasa.gov/citations/19930089113) was also checked
for supersonic finite-wing data. Its hexagonal/NACA 65A sections and swept or
delta planforms are not the supported sharp double-wedge fin section. Moreover,
its wing-plus-interference coefficients use exposed wing area. They are not
compared directly to UARC's body-area fin-pressure coefficients.

Consequently, **transonic total Cd0, finite-fin pressure, powered base drag and
whole-rocket high-speed drag remain independently unvalidated**. The GUI and
design report disclose this. Neither successful trajectory integration nor
agreement with an ideal cone table certifies these components. Improving this
status requires a separate matched-geometry/transonic and finite-fin dataset;
the current model must not be retuned to its own calibration data and then
described as validated.

### Extended audit (2026-10-28)

The accessible primary sources listed below were inspected for geometry,
coefficient definition, reference area, Mach/Reynolds conditions, boundary-layer
state, supports and whether a value was measured, calculated or used to fit this
model. A source being downloadable does not make it a compatible benchmark.
The supported geometry was not broadened to obtain apparent validation.
The NASA SP-3004 5°/Mach 2.5 reference was rechecked against the scan and its
transcription corrected to **0.03058576**; no runtime constant was tuned.

**Additional independent base-flow measurement:** Herrin & Dutton (1994),
[*Supersonic Base Flow Experiments in the Near Wake of a Cylindrical Afterbody*](https://doi.org/10.2514/3.11953),
*AIAA Journal* 32(1), 77–83, printed p. 79 / PDF p. 3, Fig. 3 and Eq. 1.
The original article was obtained and inspected, including the pressure-profile
figure. The measured **area-averaged** base pressure coefficient is −0.102.
For the closed base, on its own frontal area, `Cd_base = −Cp_base = 0.102`.
This uses the paper's integrated value, not a single radial pressure tap.
The upstream-supported cylinder has diameter 63.5 mm, no fins/jet/downstream
sting, nominal unit Reynolds number 52 million/m, and turbulent approach flow.
Measured approach Mach is 2.46 ±1%; the pressure-derived value is 2.44.

| Comparison | UARC base Cd | Difference from 0.102 |
| --- | --- | --- |
| Measured nominal Mach 2.46 | 0.10162602 | −0.3667% |
| Pressure-derived Mach 2.44 | 0.10245902 | +0.4500% |
| Mach 2.46 ±1% endpoints | 0.10061982–0.10265254 | Mach sensitivity only |

The close match supports **one coasting cylindrical-base condition**. It does
not establish a general 0.37% accuracy bound. The compiled nose/body is not a
reconstruction of the experiment's annular supply nozzle: only its local base
component is compared. UARC ignores base boundary-layer thickness, size and
Reynolds effects. The quoted Mach uncertainty is not pressure uncertainty; the
article's LDV velocity error estimates must not be relabelled as pressure error.
The regression checks agreement with the rounded nominal coefficient and its
Mach sensitivity, without asserting a statistical confidence interval.

**Numerical domain and convergence checks:** from `backend/`, run
`uv run python scripts/validate_aerodynamics.py`.
The retained output is [validation/drag_audit.json](validation/drag_audit.json).
This uses the real design compiler and validates the resulting geometry;
it neither bypasses fin limits nor queries the network.

- **67,725 evaluations:** five nose fineness ratios (3/4/6/8/10), no fins or
  three rectangular/four trapezoidal fins at the allowed 5% thickness limit,
  Mach 0–3 every 0.01, diameter Reynolds numbers 0/1e3/1e5/1e7/1e9, and
  equivalent sand-grain roughness 0/1/100 micrometres. Components were finite
  and nonnegative, and assembled drag was positive. Independent Mach/Re
  extremes include nonphysical combinations; this is a numerical stress test.
- At 180 cone-table midpoints, the largest sampled interpolation difference
  from the direct Taylor–Maccoll solve was **0.16085%** of nose pressure Cd
  (absolute 0.00021750), at nose fineness 3 and Mach 1.225. This is a sampled
  numerical difference, not an experimental error or a global bound.
- Eight-strip fin integration was compared with 64 strips at taper ratios
  1/0.4/0.1/0.01 and Mach 1.2/1.5/2/3. The largest difference was **4.14199%**
  of the fin-pressure term, absolute body-area Cd **0.0000057122**, at taper
  0.01 and Mach 1.2. Eight strips therefore have a known numerical limitation
  for extremely tapered fins even within the current schema. The 64-strip
  calculation is a convergence comparison, not measured finite-wing truth.
  Missing finite-span/body interactions are additional, unquantified errors.

All **160 backend tests** passed in this audit, including 13 compressible-drag
tests. Ruff lint/format checks passed for the audit script and relevant Python
files. These counts describe the checked working tree, not a released version.

The new closed-base reference test supplements the independent cone/wedge
checks and the actual 3-/6-DOF flights, weather/Reynolds callbacks, serialized
pressure tables, spawn workers, saved-run replay and out-of-range rejection
tests described above. Passing software tests establishes those behaviors,
not whole-vehicle aerodynamic accuracy. Friction/form-factor formula checks
and the OpenRocket subsonic comparisons also remain distinct from independent
matched-surface experimental validation.

**Accessible sources that cannot presently establish the missing accuracy:**

| Primary source | Inspected evidence | Blocker / useful next application |
| --- | --- | --- |
| [NACA TN 3819 (Love, 1957)](https://ntrs.nasa.gov/citations/19930084517) | Fig. 18 collects measured unfinned-cylinder base pressures; Fig. 19 varies afterbody length, Mach 1.62/1.93/2.41 | Base pressure depends on approach flow and afterbody length. Fig. 19 uses a 15° cone half-angle and a transition strip, outside UARC's nose domain. Compilation curves are not fresh independent measurements; these data are not a matched whole-body benchmark. They prevent generalizing from the single Herrin–Dutton match. |
| [NACA RM L9A12 (Lina, 1949)](https://ntrs.nasa.gov/citations/19930085867) | Zero-lift transonic drag, Fig. 9, Mach 0.66–1.12, reflected AR 4, Re about 0.36–0.8 million | Sharp double-wedge section is **6%** thick; complete UARC fin model allows ≤5%. Endplate and boundary-layer conditions matter. Useful for a future supported 6% finite-fin model; not current finite-fin validation. |
| [NACA RM A8I20 (Walker & Berggren, 1948)](https://ntrs.nasa.gov/citations/19930090356) | 5%-thick double-wedge triangular wing, AR 2, Mach 0.50–0.975 and 1.09–1.49 | Zero tip chord, large sweep and spanwise varying physical thickness are unsupported. No measurement at Mach 1. It cannot validate the current sonic join or trapezoidal strip model. |
| [NACA TN 3794 (Katzen & Kaattari, 1956)](https://ntrs.nasa.gov/citations/19930084518) | Separate body, six wings and combinations; Mach 1.50/2.02, body-length Re 5.5 million; geometry Table I | **8%** thick triangular wings, large sweep, and a different forebody. Wing/combination coefficients use wing area while body coefficients use base area. Useful to develop interference/transition modeling; subtracting raw coefficients would be invalid. |
| [NACA RM A8L16 (Perkins & Canning, 1949)](https://ntrs.nasa.gov/citations/19930085516) | Supported 5% rectangular double-wedge section, Mach 1.53, AR 3.5, Re 1.25 million | Measurements target downstream downwash/wake, not an integrated zero-lift drag reference. Matching section thickness alone is insufficient. |
| [NACA RM L9D12 (Sandahl et al., 1949)](https://ntrs.nasa.gov/citations/19930085881) | Free-flight rectangular/swept-wing drag and aileron effectiveness | Double-wedge wings are **9%** thick, with control deflections/rolling; outside current geometry and zero-incidence assumptions. |
| [NACA TN 2100 (Vincenti, 1950)](https://ntrs.nasa.gov/citations/19930082906) | Theory/experiment wing comparisons; Fig. 9 separates boundary-layer/pressure contributions | Included 5% double-wedge drag cases are triangular, and some measured flows are transitional. Useful finite-wing/transition evidence; not a rectangular-fin pressure validation. |
| [NACA RM E57E06 (Baughman & Kochendorfer, 1957)](https://ntrs.nasa.gov/citations/19930089763) | Fig. 23(a), Mach 1.91, jet Mach 1, identical base/nozzle geometry at different jet pressure ratios | Current powered correction has no jet pressure/temperature/Mach inputs. For boattail 5.63°, base/jet diameter 1.40, measured Cp_base changes approximately from **−0.10 at Pj/p0≈4.7 to +0.10 at ≈16.4** (graph readings about ±0.01). The same area cannot explain both values. These boattail cases are outside UARC geometry, so no direct relative Cd error is asserted. Mach 3.12 cases are also outside its Mach limit. |
| [NASA CR-149989 (Andrews & Cooper, 1974)](https://ntrs.nasa.gov/citations/19760024194) | Extensive afterbody/base-pressure data, Mach 0.9/1.2/1.46/3.48, varying plume properties | Cone-ogive-cylinder and strut/nozzle geometry differ; pressure ratio, temperature, simulant gas and support effects need to be represented. Mach 3.48 is unsupported. Report obtained; all 735 pages have **not** been individually digitized. |
| [NACA RM L55G28a (Rumsey, 1955)](https://ntrs.nasa.gov/citations/19930088905) | Free-flight cone-cylinder with four fins; geometry Fig. 1, total drag to Mach 6.9 | Nose tip bluntness, non-double-wedge/rounded leading edges, spanwise varying fin thickness and exposed instrumentation differ. Much of the measured range exceeds Mach 3. A geometric surrogate is not the tested rocket. |
| [NACA TR-1386](https://ntrs.nasa.gov/citations/19930091022) | Fineness-3 nose flight results, including Fig. 7(a) | Some curves are **foredrag**, including friction, not nose pressure. The experiment overlaps the supersonic circles already checked in RM L53K17; do not count it as another independent experiment or compare foredrag directly to Cp. |
| [NACA TR-1036 (Chapman & Perkins, 1951)](https://ntrs.nasa.gov/citations/19930091091) | Laminar/turbulent and roughness/support effects at Mach 1.5 | Most bodies have ogive/parabolic forebodies; the cone test has 10° half-angle and laminar flow. Neither matches the current fully turbulent slender-cone complete model. |
| [CALLISTO first wind-tunnel data (2019)](https://www.eucass.eu/doi/EUCASS2019-0350.pdf) | Measured launch-vehicle forces/moments, Mach 0.5–2.5 | Diameter changes, landing hardware, fins and support/base geometry differ. The 2019 IAC follow-up focuses on normal-force/fin/roll behavior; it is not an additional Cd reference. |
| [Tsentis et al. (2026)](https://doi.org/10.1007/s13272-026-00994-8) | Full article accessible; powered transonic base-pressure experiment | Tangent-ogive/cavity/nozzle geometry and **16.5% tunnel blockage** differ. Raw data require an author request. Their reported <1.6% CFD/experiment discrepancy belongs to their model, not UARC. |

The previously examined Report 1242, TR R-100 and RM L56C13 retain the blockers
described above. TR R-100's many configurations were **partly inspected**, not
exhaustively digitized; no claim is made to have excluded every possible match.
No CFD was run or substituted for a physical experiment in this audit.

**Useful material not obtained as quantitative source data:**

| Source | Access status on 2026-10-28 | What it could resolve |
| --- | --- | --- |
| Dupuis, *Aeroballistic Range and Wind Tunnel Tests of the Basic Finner Reference Projectile from Subsonic to High Supersonic Velocities*, DRDC Valcartier TM 2002-136 | Bibliographic trail found, original report not retrieved; legacy catalogue request failed. This is not proof that the report is unavailable publicly. Original geometry, cant, area convention and axial/drag data remain to be checked. | Matched finned-vehicle validation, after confirming compatibility; secondary CFD curves are not replacements for its measurements. |
| [Drew & Jenn (1990), AIAA 90-0280](https://doi.org/10.2514/6.1990-280) | Publisher full text not retrieved; [university-hosted PDF](https://mae-nas.eng.usu.edu/MAE_6530_Web/launch_design/Drew_Jenn.1990-280.pdf) timed out / could not be fetched. Indexed fragments are insufficient for implementing the complete method. | Arbitrary-moldline/transonic pressure method and its actual validation conditions. Some cited measurements overlap RM L53K17; independent data must be distinguished from calibration. |
| Tsentis et al. (2026), underlying experimental dataset | **Article obtained; raw dataset not public in the article.** Data-availability statement says to request it from the corresponding author. No request was sent. | Pressure distributions/uncertainty for powered base flow, after matching the tunnel and model rather than treating it as free flight. |

Remaining unvalidated physics includes independent transonic nose-fineness
scaling and joins; measured finite-fin pressure and wing/body interference;
matched roughness/transition/wall-temperature friction; powered plume/base
interaction; incidence/induced drag and hardware; and total-vehicle drag and
trajectory accuracy. The very-tapered-fin quadrature discrepancy is a **known
numerical limitation**, not an unknown measurement error. The supported Mach
0–3 range still describes computation, not experimentally established accuracy
over every geometry and condition.

### External subsonic benchmark

OpenRocket 24.12 is treated as a useful, credible subsonic engineering benchmark.
Differences from it require investigation; they are not evidence that UARC is
more accurate. A one-off comparison runs the installed OpenRocket program via
its public API outside this repository. No OpenRocket calculation implementation
is stored in UARC. These are comparisons between models, not wind-tunnel errors.

Both programs use zero incidence, no motor, the same reference area `πR²`,
288.15 K / 101325 Pa and identical diameter-based Reynolds numbers. UARC uses
smooth surfaces; OpenRocket uses polished finish (roughness does not control
these cases). Dimensions below are metres; the cylinder length excludes the nose.

| Case | Diameter | Nose length | Cylinder length | Fins |
| --- | --- | --- | --- | --- |
| Finless | 0.08 | 0.32 | 0.88 | None |
| Four-fin student example | 0.12 | 0.48 | 2.52 | 4; root 0.30, tip 0.12, span 0.18, leading-edge sweep offset 0.10, thickness 0.004 |

| Case | Mach | UARC coast Cd0 | OpenRocket coast Cd0 | Relative difference |
| --- | --- | --- | --- | --- |
| Finless | 0.1 | 0.32176 | 0.32442 | −0.82% |
| Finless | 0.3 | 0.29728 | 0.30073 | −1.15% |
| Finless | 0.7 | 0.32391 | 0.32895 | −1.53% |
| Four-fin student example | 0.1 | 0.55638 | 0.50564 | +10.03% |
| Four-fin student example | 0.3 | 0.49110 | 0.46093 | +6.55% |
| Four-fin student example | 0.7 | 0.48794 | 0.52227 | −6.57% |

The four-fin case shares the outer dimensions but **not an identical airfoil
definition**: OpenRocket uses its generic `AIRFOIL` section, whereas UARC assumes
a sharp symmetric double wedge. Friction, profile-pressure and interference
assumptions differ. At Mach 0.3, for example, UARC's friction is 0.35441 versus
0.30912 in OpenRocket, while base drag is 0.13170 in both. Further improvement
needs independent finite-fin/profile data, not tuning constants to cancel those
differences. Finless agreement does not validate the fin model.

At Mach 3 the same four-fin case gives 0.29671 versus 0.50071 (−40.74%); this
large difference remains unresolved. OpenRocket also emits its supersonic body
accuracy warning in this comparison. Neither that warning nor the different
sections establishes which total is correct. UARC's finite-fin/sweep and
transonic approximations still need matched-section experimental validation;
the Mach 0–3 envelope is a supported computation range, not a general accuracy
claim. Use measured/imported curves when quantitative high-speed drag is needed.

## Existing subsonic model (`subsonic_v1`): equations and sources

All coefficients use `A_ref = π R²`, the full body cross-section. The returned
coefficient is zero-incidence **axial** Cd0; RocketPy applies it to body-axis drag.
It is not the complete drag coefficient at arbitrary incidence.

1. **Skin friction:** NACA Report 793, Theodorsen & Regier (1944), Appendix C,
   printed p. 382, collects the plate-average smooth and fully rough relations:

   `Cf_smooth = 0.455 / (log10(Re_L))^2.58`

   `Cf_rough = [1.89 + 1.62 log10(L/ks)]^(-2.5)`

   [Original NASA-hosted report](https://ntrs.nasa.gov/citations/20050241738).
   UARC uses `max(Cf_smooth, Cf_rough)` as an approximate envelope, not a detailed
   hydraulically transitional roughness model. With ks=0 the rough branch is
   disabled. `Re_L` is floored at 10,000 for finite numerical behavior at launch
   and near apogee; this is regularization, **not low-Re validation**. No laminar
   transition or compressibility correction is inferred.

2. **Body form correction:** Gregorek, *Aerodynamic Drag of Model Rockets*,
   Estes TR-11 (1970), printed pp. 14–15, Eq. 1:

   `FF_body = 1 + 60/(L_total/D)^3 + 0.0025 L_tube/D`

   UARC applies this to the true outer wetted area, replacing the report's
   approximate conical area factor. Cylinders use `2πRL`; noses use frustum-strip
   integration of the same outer profile used for mass and rendering. This
   adaptation does not establish shape-specific pressure-drag accuracy for each
   nose family. Every body patch uses the **full nose-to-base length** for Re,
   so splitting a tube does not artificially restart its boundary layer.

3. **Streamlined fins:** TR-11, printed p. 18, Eq. 11:

   `Cd_fin = Cf_fin (1 + 2t/c) 2n S_fin / A_ref`

   `c` is mean aerodynamic chord; exposed trapezoid or ellipse areas are analytic.
   Fin Re uses its own chord, not the rocket length. The thickness correction
   assumes a streamlined section. Square leading/trailing edges are unsupported.
   Eq. 12's fin/body interference contribution is **not** implemented; the
   current design schema does not describe embedded fin planforms or fillets.

4. **Body base drag:** TR-11, printed pp. 15–16, Eqs. 2–3:

   `Cd_base_off = 0.029 / sqrt(Cd_forebody)`

   `Cd_base_on = Cd_base_off [1 - (R_nozzle/R_body)^2]^(3/2)`

   `Cd_forebody` is body skin friction with its form correction, excluding fins
   and base drag. Coasting uses the full base. During motor operation the nozzle
   opening reduces the equivalent exposed base diameter. This is an empirical
   plume/base approximation; it does not resolve jet pressure or nozzle hardware.
   Without a motor, the on/off estimates coincide.

   [Original TR-11 scan](https://www.oldrocketplans.com/pubs/Estes/estTR-11/TR-11.pdf).

The report separates skin friction, form-factor additions and base drag. Total
Cd0 is their sum. There is no fitted match to another simulator's results.

## Weather, preview and numerical domain

RocketPy 1.13's seven-input drag callback supplies instantaneous Mach and
`Re_D = ρ V D / μ`. UARC converts this to `Re_L = Re_D L / D` for each surface.
Thus the selected weather profile, local altitude, temperature, pressure and
relative airspeed affect drag during flight. No forecast is fetched merely to
refresh a geometry preview.

The GUI table is a reproducible **reference** calculation at 288.15 K and
101325 Pa, with ideal dry air (`R=287.05287`, `γ=1.4`) and Sutherland viscosity
`μ=1.458e-6 T^1.5/(T+110.4)`. It is not the launch site's forecast or a constant
Re used for simulation. Mach-only calls to RocketPy's native convenience drag
function have no Re information; use the seven-input function for quantitative
diagnostics. UARC's preview supplies its own explicit Re.

The implemented envelope is deliberately restricted:

- Mach 0–0.7. A faster flight **fails visibly**; coefficients are not silently
  extrapolated across the transonic regime. Supersonic/manual curves remain usable.
- One sharp nose, nose length/diameter ≥ 2 and overall length/diameter ≥ 5.
- Contiguous, equal-radius cylindrical tubes with a flush nose. Gaps, overlaps,
  radius steps, tails and boat-tails require manual curves.
- Thin, uncanted trapezoidal or elliptical fins, attached wholly to the tubes,
  thickness/MAC ≤ 0.1, assumed streamlined. Fin sweep affects the geometric
  placement check but no separate swept-edge pressure model is provided.
- A nozzle flush with the aft body plane and smaller than the body diameter.
- Per-part **equivalent sand-grain ks**, with ks < characteristic length/100.
  Positive Ra or legacy model heights are rejected, not converted. Missing finish
  means a disclosed smooth-surface assumption, not a measured smooth finish.

Angle-of-attack drag, separated flow, fin/body interference, launch guides,
exposed hardware, fin leading/trailing-edge pressure drag and compressibility
drag rise are omitted. This can underpredict drag, especially toward the upper
Mach limit. Use independent measurements for serious flight prediction and a
validated higher-speed model before extending the domain.
