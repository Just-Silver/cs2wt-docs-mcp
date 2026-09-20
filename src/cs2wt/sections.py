"""Extract a single section from converted Markdown."""

from __future__ import annotations

import re

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$", re.MULTILINE)


def _headings(markdown: str) -> list[tuple[int, int, str]]:
    return [
        (m.start(), len(m.group(1)), m.group(2))
        for m in _HEADING.finditer(markdown)
    ]


def extract_section(markdown: str, section: str) -> str | None:
    """Return the section (heading + body + subsections), or None."""
    headings = _headings(markdown)
    if not headings:
        return None

    target = section.strip().lower()
    match: tuple[int, int] | None = None

    for start, level, text in headings:
        if text.strip().lower() == target:
            match = (start, level)
            break

    if match is None and target:
        for start, level, text in headings:
            if target in text.lower():
                match = (start, level)
                break

    if match is None:
        return None

    start, level = match
    end = len(markdown)
    for s, lvl, _ in headings:
        if s > start and lvl <= level:
            end = s
            break
    return markdown[start:end].strip()