"""Offline material facts and references shared by the desktop library and importer."""

import json
from pathlib import Path


def material_catalog() -> dict:
    """Return a fresh JSON value; saved designs keep their own editable densities."""
    return json.loads(
        Path(__file__).with_name("materials.json").read_text(encoding="utf-8")
    )
