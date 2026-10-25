"""Read a single release section from the project changelog."""

import re


def release_notes(source, version):
    version = version.removeprefix("v")
    headings = list(re.finditer(r"(?m)^## (.+)$", source))
    for index, heading in enumerate(headings):
        if re.match(rf"\[?v?{re.escape(version)}(?:\]|\s|$)", heading[1]):
            end = (
                headings[index + 1].start()
                if index + 1 < len(headings)
                else len(source)
            )
            return source[heading.end() : end].strip()
    raise ValueError(f"Release {version} is missing from docs/CHANGELOG.md")
