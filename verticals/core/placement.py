"""Parent/child vertical placement invariant shared by create, schedule and reparent."""

from __future__ import annotations

from verticals.core import vertical as vertical_mod
from verticals.core.errors import ValidationError


def validate_child_vertical(
    *, child_vertical: str | None, parent_vertical: str | None, child_id: str, parent_id: str
) -> None:
    """A parked child is below every scale. Otherwise its scale may equal its parent's or sit
    lower in the commitment ladder, never above it. A parked parent is below every scheduled
    child, so a scheduled child cannot be newly placed under one."""
    if child_vertical is None:
        return
    if parent_vertical is None or vertical_mod.rank(child_vertical) > vertical_mod.rank(parent_vertical):
        raise ValidationError(
            f"goal {child_id!r} at vertical {child_vertical!r} cannot be placed above parent "
            f"{parent_id!r} at vertical {parent_vertical!r}",
            field="vertical",
            child_id=child_id,
            child_vertical=child_vertical,
            parent_id=parent_id,
            parent_vertical=parent_vertical,
        )
