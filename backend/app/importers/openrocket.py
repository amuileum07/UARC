"""Import a single axial OpenRocket stage using its documented XML format.

Unsupported physical features fail explicitly. Extend these mappings alongside
reference fixtures rather than silently dropping geometry or guessing settings.
"""

import gzip
import io
import json
import math
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from app.schemas import OpenRocketImport, OpenRocketOptions, RocketDesign
from app.storage import MAX_PAYLOAD_BYTES

MAX_ARCHIVE_BYTES = 8 * 1024**2
OUTER = {"nosecone", "bodytube", "transition"}
TUBES = {
    "bodytube",
    "innertube",
    "tubecoupler",
    "centeringring",
    "bulkhead",
    "engineblock",
}
FINS = {"trapezoidfinset", "ellipticalfinset"}


def _text(node, name, default=None):
    value = node.findtext(name, default)
    if value is None:
        raise ValueError(f"<{node.tag}> requires <{name}>.")
    return value.strip()


def _number(node, name, default=None):
    value = float(_text(node, name, default))
    if not math.isfinite(value):
        raise ValueError(f"<{name}> must be finite.")
    return value


def _xml(source: Path):
    with source.open("rb") as stream:
        data = stream.read(MAX_ARCHIVE_BYTES + 1)
    if len(data) > MAX_ARCHIVE_BYTES:
        raise ValueError("OpenRocket archive exceeds 8 MiB.")
    try:
        if zipfile.is_zipfile(io.BytesIO(data)):
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                entries = archive.infolist()
                matches = [entry for entry in entries if entry.filename == "rocket.ork"]
                if len(entries) > 128 or len(matches) != 1:
                    raise ValueError(
                        "Archive must contain exactly one rocket.ork and at most 128 entries."
                    )
                if matches[0].file_size > MAX_PAYLOAD_BYTES:
                    raise ValueError("OpenRocket XML exceeds 2 MiB.")
                # Never extract archive paths or read embedded executable content.
                with archive.open(matches[0]) as stream:
                    data = stream.read(MAX_PAYLOAD_BYTES + 1)
        elif data.startswith(b"\x1f\x8b"):
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
                data = stream.read(MAX_PAYLOAD_BYTES + 1)
        if len(data) > MAX_PAYLOAD_BYTES:
            raise ValueError("OpenRocket XML exceeds 2 MiB.")
        text = data.decode("utf-8-sig")
        if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
            raise ValueError("XML document types and entities are not accepted.")
        parser = ET.XMLPullParser(events=("start", "end"))
        root, depth, count = None, 0, 0
        for start in range(0, len(text), 8192):
            parser.feed(text[start : start + 8192])
            for event, element in parser.read_events():
                if event == "start":
                    depth += 1
                    count += 1
                    if root is None:
                        root = element
                    if depth > 32 or count > 4096:
                        raise ValueError(
                            "OpenRocket XML is too deeply nested or has too many elements."
                        )
                else:
                    depth -= 1
        parser.close()
    except (ET.ParseError, UnicodeError, zipfile.BadZipFile, EOFError) as error:
        raise ValueError(f"Invalid OpenRocket file: {error}") from error
    if root is None or root.tag != "openrocket":
        raise ValueError("Expected an <openrocket> document.")
    version = root.get("version", "").split(".")
    if (
        len(version) != 2
        or version[0] != "1"
        or not version[1].isdigit()
        or int(version[1]) > 11
    ):
        raise ValueError("Supported OpenRocket format versions are 1.0 through 1.11.")
    return root


def _length(node):
    if node.tag in FINS:
        return _number(node, "rootchord")
    return _number(
        node,
        "packedlength"
        if node.tag in {"masscomponent", "parachute", "shockcord"}
        else "length",
    )


def _position(node, parent_start, parent_length, length, previous_end, default):
    offset = node.find("axialoffset")
    legacy = node.find("position")
    if offset is None:
        offset = legacy
    method = (
        default if offset is None else offset.get("method", offset.get("type", default))
    )
    value = 0.0 if offset is None else float(offset.text or "0")
    if not math.isfinite(value):
        raise ValueError("Axial offsets must be finite.")
    if (
        legacy is not None
        and offset is not legacy
        and (
            legacy.get("type", default) != method or float(legacy.text or "0") != value
        )
    ):
        raise ValueError("Conflicting axialoffset and legacy position fields.")
    origins = {
        "absolute": 0.0,
        "top": parent_start,
        "middle": parent_start + (parent_length - length) / 2,
        "bottom": parent_start + parent_length - length,
        "after": previous_end,
    }
    if method not in origins:
        raise ValueError(f"Unsupported axial positioning method: {method}.")
    return origins[method] + value


def _guard(node):
    for key in ("overridecg", "overridecd", "overridesubcomponents"):
        if node.find(key) is not None:
            raise ValueError(f"<{node.tag}> uses unsupported <{key}>.")
    for key in (
        "overridesubcomponentsmass",
        "overridesubcomponentscg",
        "overridesubcomponentscd",
        "flipped",
    ):
        if _text(node, key, "false") != "false":
            raise ValueError(f"<{node.tag}> uses unsupported <{key}>.")
    if _number(node, "radialposition", "0") != 0:
        raise ValueError(
            "Off-axis components are not supported by the axial design model."
        )
    if node.tag not in FINS and _number(node, "instancecount", "1") != 1:
        raise ValueError(
            "Repeated or clustered components must be expanded before import."
        )
    if _text(node, "clusterconfiguration", "single") != "single":
        raise ValueError("Clustered motor tubes are not supported.")


def import_openrocket(source: Path, options: OpenRocketOptions) -> OpenRocketImport:
    root = _xml(source)
    rocket = root.find("rocket")
    stages = [] if rocket is None else list(rocket.findall("subcomponents/*"))
    if len(stages) != 1 or stages[0].tag != "stage":
        raise ValueError(
            "Import requires exactly one axial <stage>; boosters and pods are unsupported."
        )
    _guard(rocket)
    _guard(stages[0])
    if (
        rocket.find("overridemass") is not None
        or stages[0].find("overridemass") is not None
    ):
        raise ValueError(
            "Assembly mass overrides must be entered explicitly after import."
        )
    outer = list(stages[0].findall("subcomponents/*"))
    if not 1 <= len(outer) <= 64 or any(node.tag not in OUTER for node in outer):
        raise ValueError(
            "Stage components must be nose cones, body tubes, or conical transitions."
        )
    placements = []
    end = 0.0
    for node in outer:
        length = _length(node)
        if length <= 0:
            raise ValueError("Component lengths must be positive.")
        start = _position(node, 0.0, 0.0, length, end, "after")
        placements.append((node, start, length))
        end = start + length
    total_length = max(start + length for _, start, length in placements)
    materials, components = {}, []
    warnings = [
        "UARC mass and aerodynamic approximations apply; compare imported mass/CG with OpenRocket.",
        "Motor/thrust, atmosphere, launch settings, and body drag use the explicit import options; OpenRocket simulations are not imported.",
    ]

    def material(node, kind="bulk", density=None):
        entry = node.find("material")
        if entry is None or entry.get("type", "bulk") != kind:
            raise ValueError(f"<{node.tag}> requires a {kind} material with a density.")
        value = float(entry.get("density", "nan")) if density is None else density
        name = (entry.text or "Imported material").strip()
        key = f"material_{len(materials)}"
        materials[key] = {"name": name, "density": value}
        return key

    def radius(node, name, fallback=None):
        text = _text(node, name)
        if text == "auto" or text.startswith("auto "):
            if fallback is None or fallback <= 0:
                raise ValueError(
                    f"Cannot resolve automatic <{name}>; set an explicit radius in OpenRocket."
                )
            return fallback
        value = float(text)
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"<{name}> must be positive and finite.")
        return value

    def explicit_radius(node, name):
        text = _text(node, name, "auto")
        return None if text.startswith("auto") else radius(node, name)

    # Resolve chains of automatic outer radii from adjacent explicit end radii.
    # At most 64 components: a simple bounded relaxation keeps the rules readable.
    fore, aft = [], []
    for node in outer:
        fore.append(
            0.0
            if node.tag == "nosecone"
            else explicit_radius(
                node, "radius" if node.tag == "bodytube" else "foreradius"
            )
        )
        aft.append(
            explicit_radius(node, "radius" if node.tag == "bodytube" else "aftradius")
        )
    for _ in range(len(outer)):
        for index, node in enumerate(outer):
            if node.tag == "bodytube":
                if fore[index] is None:
                    candidate = aft[index - 1] if index else None
                    if candidate is None and index + 1 < len(outer):
                        candidate = fore[index + 1]
                    fore[index] = aft[index] = candidate
                continue
            if fore[index] is None:
                fore[index] = aft[index - 1] if index else None
            if aft[index] is None:
                aft[index] = fore[index + 1] if index + 1 < len(outer) else None
    if any(value is None for value in fore + aft):
        raise ValueError(
            "Automatic body radii could not be resolved; set explicit radii in OpenRocket."
        )

    def add(node, start, length, parent_radius, parent_inner, outer_radii=None):
        _guard(node)
        kind = node.tag
        base = {"id": f"part_{len(components)}", "name": _text(node, "name", kind)}
        if len(components) >= 64:
            raise ValueError("Imported designs support at most 64 components.")
        mass_override = node.findtext("overridemass")
        if mass_override is not None:
            base["mass_override"] = float(mass_override)
        if kind in TUBES:
            r = (
                outer_radii[1]
                if outer_radii
                else radius(node, "outerradius", parent_inner)
            )
            if kind == "bulkhead":
                thickness = r
            elif kind == "centeringring":
                thickness = r - _number(node, "innerradius")
            else:
                thickness = (
                    r
                    if _text(node, "filled", "false") == "true"
                    else _number(node, "thickness")
                )
            base.update(
                component_type="body_tube",
                material=material(node),
                position=total_length - start - length,
                length=length,
                outer_radius=r,
                thickness=thickness,
            )
            components.append(base)
            inner = r - thickness
        elif kind in {"nosecone", "transition"}:
            r0, r1 = outer_radii
            shape = _text(node, "shape", "conical")
            if _text(node, "shapeclipped", "false") == "true":
                raise ValueError("Clipped transition/nose profiles are unsupported.")
            if any(
                _number(node, name, "0") != 0
                for name in ("aftshoulderlength", "foreshoulderlength")
            ):
                raise ValueError(
                    "Nose/transition shoulders must be modelled explicitly before import."
                )
            surface = {
                "position": total_length - start,
                "rocket_radius": max(r0, r1),
                "length": length,
            }
            if kind == "transition":
                if shape != "conical" or min(r0, r1) <= 0:
                    raise ValueError(
                        "Only conical transitions with positive end radii are supported."
                    )
                surface.update(surface_type="tail", top_radius=r0, bottom_radius=r1)
            else:
                families = {
                    "conical": "conical",
                    "ogive": "ogive",
                    "ellipsoid": "elliptical",
                    "parabolic": "parabolic",
                    "haack": "haack",
                    "power": "powerseries",
                }
                if shape not in families:
                    raise ValueError(f"Unsupported nose shape: {shape}.")
                surface.update(
                    surface_type="nose", kind=families[shape], base_radius=r1
                )
                if shape in {"haack", "power"}:
                    surface["haack_c" if shape == "haack" else "power"] = _number(
                        node, "shapeparameter", "0" if shape == "haack" else "0.5"
                    )
                elif (
                    shape in {"ogive", "parabolic"}
                    and _number(node, "shapeparameter", "1") != 1
                ):
                    raise ValueError(
                        "Only tangent ogives and full parabolic noses are supported."
                    )
            thickness = (
                min(r for r in (r0, r1) if r > 0)
                if _text(node, "filled", "false") == "true"
                else _number(node, "thickness")
            )
            base.update(
                component_type="surface",
                material=material(node),
                thickness=thickness,
                surface=surface,
            )
            components.append(base)
            inner = max(r0, r1) - thickness
            r = max(r0, r1)
        elif kind in FINS:
            if parent_radius is None:
                raise ValueError("Fins require a cylindrical parent tube.")
            if (
                _number(node, "tabheight", "0") != 0
                or _number(node, "filletradius", "0") != 0
            ):
                raise ValueError(
                    "Fin tabs and fillets are unsupported; model their mass explicitly."
                )
            if _text(node, "crosssection", "square") != "square":
                raise ValueError("Only square-section fin plates are supported.")
            surface = {
                "surface_type": "trapezoidal_fins"
                if kind == "trapezoidfinset"
                else "elliptical_fins",
                "position": total_length - start,
                "rocket_radius": parent_radius,
                "n": int(_text(node, "fincount", "3")),
                "root_chord": length,
                "span": _number(node, "height"),
                "cant_angle": _number(node, "cant", "0"),
            }
            if kind == "trapezoidfinset":
                surface.update(
                    tip_chord=_number(node, "tipchord"),
                    sweep_length=_number(node, "sweeplength"),
                )
            base.update(
                component_type="surface",
                material=material(node),
                thickness=_number(node, "thickness"),
                surface=surface,
            )
            components.append(base)
            r, inner = None, None
        elif kind in {"masscomponent", "shockcord", "parachute"}:
            packed_radius = radius(node, "packedradius", parent_inner)
            position = total_length - start - length / 2
            if kind == "parachute":
                if node.find("deploymentconfiguration") is not None:
                    raise ValueError(
                        "Per-flight parachute deployment configurations are unsupported."
                    )
                event = _text(node, "deployevent", "ejection")
                trigger = options.parachute_trigger
                if trigger is None:
                    if event == "apogee":
                        trigger = "apogee"
                    elif event == "altitude":
                        trigger = _number(node, "deployaltitude")
                    else:
                        raise ValueError(
                            f"Deployment event {event!r} requires an explicit parachute_trigger import option."
                        )
                area = math.pi * (_number(node, "diameter") / 2) ** 2
                surface_material = node.find("material")
                if surface_material is None:
                    raise ValueError("Parachute requires a surface material.")
                areal_density = float(surface_material.get("density", "nan"))
                # OpenRocket records kg/m², not fabric thickness. Preserve areal
                # mass using a documented 1 mm equivalent layer, editable later.
                thickness = 0.001
                key = material(node, "surface", areal_density / thickness)
                line = node.find("linematerial")
                line_count = int(_text(node, "linecount", "0"))
                if not 0 <= line_count <= 10_000:
                    raise ValueError(
                        "Parachute line count must be between 0 and 10000."
                    )
                if line_count and (line is None or line.get("type") != "line"):
                    raise ValueError("Parachute lines require a line material.")
                line_length = _text(node, "linelength", "0")
                line_length = (
                    1.5 * _number(node, "diameter")
                    if line_length.startswith("auto")
                    else float(line_length)
                )
                line_density = (
                    float(line.get("density", "nan")) if line is not None else 0.0
                )
                if (
                    not math.isfinite(line_length)
                    or line_length < 0
                    or (
                        line_count
                        and (not math.isfinite(line_density) or line_density <= 0)
                    )
                ):
                    raise ValueError(
                        "Parachute line length/density must be physically valid."
                    )
                line_mass = line_count * line_length * line_density
                cd = _text(node, "cd", "auto")
                base.update(
                    component_type="parachute",
                    material=key,
                    position=position,
                    attachment_position=position,
                    canopy_area=area,
                    thickness=thickness,
                    line_mass=line_mass,
                    packed_radius=packed_radius,
                    packed_length=length,
                    deployment={
                        "name": base["name"],
                        "radius": _number(node, "diameter") / 2,
                        "drag_coefficient": 0.8 if cd == "auto" else float(cd),
                        "trigger": trigger,
                        "lag": _number(node, "deploydelay", "0"),
                    },
                )
                warnings.append(
                    "Parachute surface density uses an equivalent 1 mm fabric layer; attachment position is the packed CG, not an imported anchor."
                )
            else:
                if kind == "shockcord":
                    entry = node.find("material")
                    if entry is None or entry.get("type") != "line":
                        raise ValueError("Shock cord requires a line material.")
                    cord_length = _number(node, "cordlength")
                    line_density = float(entry.get("density", "nan"))
                    if (
                        cord_length <= 0
                        or not math.isfinite(line_density)
                        or line_density <= 0
                    ):
                        raise ValueError("Shock cord length/density must be positive.")
                    mass = cord_length * line_density
                else:
                    mass = _number(node, "mass")
                base.update(
                    component_type="mass",
                    position=position,
                    mass=float(base.pop("mass_override", mass)),
                    radius=packed_radius,
                    length=length,
                )
            components.append(base)
            r, inner = None, None
        else:
            raise ValueError(f"Unsupported OpenRocket component: <{kind}>.")
        for child in node.findall("subcomponents/*"):
            child_length = _length(child)
            if child_length <= 0:
                raise ValueError("Component lengths must be positive.")
            default = "bottom" if child.tag in FINS else "top"
            child_start = _position(
                child, start, length, child_length, start + length, default
            )
            if kind not in {"bodytube", "innertube", "tubecoupler"}:
                raise ValueError(
                    "Nested components currently require a cylindrical tube parent."
                )
            add(child, child_start, child_length, r, inner)

    for index, (node, start, length) in enumerate(placements):
        add(node, start, length, None, None, (fore[index], aft[index]))
    if (
        rocket.find("motorconfiguration") is not None
        or rocket.find(".//motormount") is not None
    ):
        warnings.append(
            "OpenRocket motor database selections were not imported; supply a UARC motor with its thrust curve."
        )
    payload = options.model_dump(mode="json", exclude={"parachute_trigger"})
    payload.update(
        name=_text(rocket, "name", "Imported OpenRocket design"),
        materials=materials,
        components=components,
    )
    design = RocketDesign.model_validate_json(json.dumps(payload))
    return OpenRocketImport(design=design, warnings=warnings)
