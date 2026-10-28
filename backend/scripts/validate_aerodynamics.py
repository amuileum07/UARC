"""Offline numerical audit, not a whole-rocket aerodynamic certification.

Run from backend/: uv run python scripts/validate_aerodynamics.py
Published cone/wedge/nose references and flight/replay checks are also exercised
by tests/test_compressible_drag.py. Source conditions: docs/AERODYNAMICS.md.
"""

import json
from math import atan, isfinite
from pathlib import Path

import numpy as np

from app.aerodynamics import drag_coefficients
from app.compressible_drag import cone_pressure, wedge_pressure_drag
from app.design import compile_design
from app.schemas import RocketDesign
from app.schemas.aerodynamics import DragGeometry

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "design.json"


def geometry(fineness, fin=None):
    """Use the real design compiler and its geometry validation, in SI units."""
    payload = json.loads(EXAMPLE.read_text())
    payload["automatic_drag"] = {"model": "compressible_v1"}
    payload["motor"] = None
    payload["components"] = payload["components"][: 3 if fin else 2]
    nose = payload["components"][1]["surface"]
    nose.update(kind="conical", length=0.05 * fineness, position=0.6 + 0.05 * fineness)
    nose.pop("haack_c")
    if fin:
        count, tip, thickness = fin
        payload["components"][2]["thickness"] = thickness
        payload["components"][2]["surface"].update(
            n=count, tip_chord=tip, sweep_length=(0.12 - tip) / 2
        )
    config, _ = compile_design(RocketDesign.model_validate(payload))
    return config.rocket.automatic_drag


def herrin_dutton_comparison():
    """Compare only the closed cylindrical base, using its own frontal area.

    Herrin & Dutton (1994), AIAA J. 32(1), 77–83, p. 79 / PDF p. 3,
    Fig. 3 and accompanying text: area-average Cp_base=-0.102; Eq. 1 uses
    local approach dynamic pressure. LDV Mach=2.46 ±1%; pressure-derived
    Mach=2.44. Diameter=63.5 mm; nominal unit Re=52e6/m. No downstream sting,
    fins or jet. Cd_base=-Cp_base; no annular-area correction is appropriate.
    No independent pressure-measurement uncertainty is stated in that passage.
    The LDV velocity uncertainty must not be substituted for pressure uncertainty.
    UARC's base correlation ignores size, Re and the boundary-layer profile;
    the compiled forebody is not a reconstruction of the annular supply nozzle.
    """
    body = geometry(6)
    observed = 0.102
    calculated = drag_coefficients(body, 2.46, 52e6 * 0.0635).base_off
    interval = [
        drag_coefficients(body, mach, 52e6 * 0.0635).base_off
        for mach in (2.46 * 1.01, 2.46 * 0.99)
    ]
    return {
        "source": "https://doi.org/10.2514/3.11953",
        "quantity": "coasting closed-cylinder base Cd, not total Cd",
        "mach": 2.46,
        "reference": observed,
        "calculated": calculated,
        "difference_percent": 100 * (calculated / observed - 1),
        "prediction_at_mach_uncertainty_endpoints": interval,
        "prediction_at_pressure_derived_mach_2_44": drag_coefficients(
            body, 2.44, 52e6 * 0.0635
        ).base_off,
        "pressure_measurement_uncertainty": None,
        "scope": "One base-flow condition; not general base or whole-rocket validation.",
    }


def numerical_sweep():
    """Finite sampled domain/stress check; not experimental validation."""
    evaluated = 0
    largest_nose = {"relative_percent": 0.0}
    largest_fin = {"relative_percent": 0.0}
    largest_reference = {"relative_percent": 0.0}
    machs = np.linspace(0, 3, 301)
    reynolds = (0, 1e3, 1e5, 1e7, 1e9)
    roughnesses = (0, 1e-6, 1e-4)
    for fineness in (3, 4, 6, 8, 10):
        for fin in (None, (3, 0.12, 0.006), (4, 0.05, 0.0025)):
            compiled = geometry(fineness, fin)
            for roughness in roughnesses:
                raw = compiled.model_dump(mode="json")
                for surface in raw["surfaces"]:
                    surface["roughness_m"] = roughness
                body = DragGeometry.model_validate(raw)
                for mach in machs:
                    for re_d in reynolds:
                        values = drag_coefficients(body, float(mach), re_d)
                        components = (
                            values.skin_friction,
                            values.form,
                            values.nose_pressure,
                            values.fin_pressure,
                            values.base_off,
                            values.base_on,
                        )
                        if not all(isfinite(x) and x >= 0 for x in components):
                            raise AssertionError((fineness, fin, roughness, mach, re_d))
                        if not 0 < values.total_on <= values.total_off:
                            raise AssertionError("Invalid assembled drag")
                        evaluated += 1
        # Check between stored pressure nodes, where interpolation can differ
        # from the direct ODE; these values are never used as empirical data.
        body = geometry(fineness)
        for mach in np.linspace(1.225, 2.975, 36):
            exact = cone_pressure(float(mach), atan(1 / (2 * fineness)))
            frozen = drag_coefficients(body, float(mach), 1e6).nose_pressure
            difference = abs(frozen / exact - 1) * 100
            if difference > largest_nose["relative_percent"]:
                largest_nose = {
                    "relative_percent": difference,
                    "absolute_cd": abs(frozen - exact),
                    "nose_fineness": fineness,
                    "mach": float(mach),
                }
    # Compare the production eight-strip rule to a 64-strip rule for the SAME
    # 2D theory. This detects integration error, not missing finite-wing physics.
    for taper in (1, 0.4, 0.1, 0.01):
        tip = 0.12 * taper
        body = geometry(6, (4, tip, 0.05 * tip))
        fin = body.compressible.fins[0]
        for mach in (1.2, 1.5, 2, 3):
            references = []
            for strips in (64, 128):
                nodes, weights = np.polynomial.legendre.leggauss(strips)
                chords = (0.12 + tip) / 2 + nodes * (tip - 0.12) / 2
                integral = sum(
                    float(weight * chord)
                    * wedge_pressure_drag(mach, float(fin.thickness_m / chord))
                    for weight, chord in zip(weights, chords, strict=True)
                )
                references.append(
                    fin.count * fin.span_m / (2 * np.pi * 0.025**2) * integral
                )
            reference, refined = references
            convergence = abs(reference / refined - 1) * 100
            if convergence > largest_reference["relative_percent"]:
                largest_reference = {
                    "relative_percent": convergence,
                    "absolute_cd": abs(reference - refined),
                    "taper": taper,
                    "mach": mach,
                }
            calculated = drag_coefficients(body, mach, 1e6).fin_pressure
            difference = abs(calculated / reference - 1) * 100
            if difference > largest_fin["relative_percent"]:
                largest_fin = {
                    "relative_percent": difference,
                    "absolute_cd": abs(calculated - reference),
                    "taper": taper,
                    "mach": mach,
                }
    return {
        "coefficient_evaluations": evaluated,
        "nose_fineness": [3, 4, 6, 8, 10],
        "fins": "none; 3 rectangular (5% thick); 4 trapezoidal (5% at tip)",
        "mach": {"min": 0, "max": 3, "step": 0.01},
        "diameter_reynolds": reynolds,
        "sand_grain_roughness_m": roughnesses,
        "nose_interpolation_max_sampled_error": largest_nose,
        "fin_8_vs_64_strip_max_sampled_error": largest_fin,
        "fin_64_vs_128_strip_max_sampled_difference": largest_reference,
        "scope": "Sampled numerical stress/convergence checks, not physical accuracy. "
        "Independent Mach/Re extremes include nonphysical combinations.",
    }


if __name__ == "__main__":
    print(
        json.dumps(
            {
                "experimental_base_comparison": herrin_dutton_comparison(),
                "numerical_sweep": numerical_sweep(),
                "whole_rocket_experimental_validation": False,
            },
            indent=2,
            allow_nan=False,
        )
    )
