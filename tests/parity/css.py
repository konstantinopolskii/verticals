"""Helpers for assertions against computed CSS values."""

from __future__ import annotations


def split_css_list(value: str) -> list[str]:
    """Split a computed CSS list without splitting commas inside functions or strings."""
    items: list[str] = []
    start = 0
    depth = 0
    quote: str | None = None
    escaped = False

    for index, character in enumerate(value):
        if escaped:
            escaped = False
            continue
        if character == "\\":
            escaped = True
            continue
        if quote is not None:
            if character == quote:
                quote = None
            continue
        if character in {'"', "'"}:
            quote = character
        elif character == "(":
            depth += 1
        elif character == ")":
            depth = max(0, depth - 1)
        elif character == "," and depth == 0:
            items.append(value[start:index].strip())
            start = index + 1

    items.append(value[start:].strip())
    return items
