"""Shared building blocks for every agent contract."""
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints


class Contract(BaseModel):
    """Base for all agent I/O. extra='forbid' => the model cannot smuggle in
    undeclared fields; unknown keys fail validation and trigger a correction."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


HexColor = Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]
Slug = Annotated[str, StringConstraints(pattern=r"^(/|/[a-z0-9]+(-[a-z0-9]+)*(/[a-z0-9]+(-[a-z0-9]+)*)*)$")]
TaskKey = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{1,40}$")]
SectionId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=60)]
ShortText = Annotated[str, StringConstraints(min_length=1, max_length=400)]


def _lin(c: int) -> float:
    v = c / 255
    return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4


def luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def wcag_contrast(a: str, b: str) -> float:
    """WCAG 2.x contrast ratio between two #rrggbb colors (1.0 - 21.0)."""
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)
