"""Portable, versioned JSON designs with a dedicated .uarc extension."""

import re
from ntpath import isreserved
from pathlib import Path

from app.design import compile_design
from app.schemas import RocketDesign
from app.storage import MAX_PAYLOAD_BYTES, atomic_json


def design_filename(name: str) -> str:
    """Keep Unicode names while producing a portable single filename."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', "_", name).strip(" .")
    if name.lower().endswith(".uarc"):
        name = name[:-5]
    name = name.encode("utf-8")[:240].decode("utf-8", errors="ignore").rstrip(" .")
    if isreserved(name + ".uarc"):
        name = "_" + name
    return (name or "rocket") + ".uarc"


def validate_design_file(payload: bytes | str) -> RocketDesign:
    if (
        len(payload.encode("utf-8") if isinstance(payload, str) else payload)
        > MAX_PAYLOAD_BYTES
    ):
        raise ValueError("설계 파일은 2 MiB 이하여야 합니다.")
    design = RocketDesign.model_validate_json(payload)
    # External curve files are not portable; freeze their numeric samples first.
    external = {
        "thrust_source",
        "power_off_drag",
        "power_on_drag",
        "liquid_mass",
        "gas_mass",
        "pressure",
        "temperature",
        "wind_u",
        "wind_v",
        "atmosphere_file",
    }

    def check(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in external and isinstance(item, str):
                    raise ValueError(
                        "외부 파일을 참조하는 설계는 수치 표·기상 스냅샷으로 변환한 뒤 내보내세요."
                    )
                check(item)
        elif isinstance(value, list):
            for item in value:
                check(item)

    check(design.model_dump(mode="json"))
    compile_design(design)
    return design


def read_design_file(path: Path) -> dict:
    with path.open("rb") as stream:
        payload = stream.read(MAX_PAYLOAD_BYTES + 1)
    return validate_design_file(payload).model_dump(mode="json")


def write_design_file(path: Path, payload: str) -> Path:
    design = validate_design_file(payload)
    if path.suffix.lower() != ".uarc":
        path = path.with_suffix(".uarc")
    atomic_json(path, design.model_dump(mode="json"), overwrite=False)
    return path
