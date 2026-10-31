"""Bounded error reports from the local desktop frontend."""

from typing import Annotated, Literal

from pydantic import Field

from app.schemas.common import EngineConfig


class FrontendError(EngineConfig):
    kind: Literal["error", "unhandledrejection", "react", "renderer", "resource"]
    message: Annotated[str, Field(min_length=1, max_length=4096)]
    stack: Annotated[str, Field(max_length=8192)] = ""
    source: Annotated[str, Field(max_length=2048)] = ""
    component_stack: Annotated[str, Field(max_length=4096)] = ""
