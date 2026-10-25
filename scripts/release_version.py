"""Read, calculate and update the single project release version (Python 3.11+)."""

import re
import subprocess
import sys
import tomllib
from pathlib import Path


def parse_version(value):
    if not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", value):
        raise ValueError("Version must be MAJOR.MINOR.PATCH without a prefix")
    return tuple(map(int, value.split(".")))


def next_version(current, kind, messages=""):
    major, minor, patch = parse_version(current)
    if kind == "auto":
        if re.search(r"(?m)^\w+(?:\([^\n]*\))?!:|^BREAKING[ -]CHANGE:", messages):
            kind = "major"
        elif re.search(r"(?m)^feat(?:\([^\n]*\))?:", messages):
            kind = "minor"
        else:
            kind = "patch"
    values = {
        "patch": (major, minor, patch + 1),
        "minor": (major, minor + 1, 0),
        "major": (major + 1, 0, 0),
    }
    if kind in values:
        return ".".join(map(str, values[kind]))
    if parse_version(kind) <= (major, minor, patch):
        raise ValueError("New version must be greater than the current version")
    return kind


def main():
    path = Path("pyproject.toml")
    source = path.read_text(encoding="utf-8")
    current = tomllib.loads(source)["project"]["version"]
    command = sys.argv[1]
    if command == "current":
        print(current)
        return
    if command == "next":
        ref = sys.argv[3] if len(sys.argv) > 3 else ""
        messages = subprocess.check_output(
            ["git", "log", "--format=%B", *([f"{ref}..HEAD"] if ref else [])],
            encoding="utf-8",
        )
        print(next_version(current, sys.argv[2], messages))
    elif command == "write":
        version = next_version(current, sys.argv[2])
        # Only change [project].version, preserving comments and other tables.
        source, count = re.subn(
            r'(?ms)(^\[project\]\s*\n(?:(?!^\[).)*?^version\s*=\s*")[^"]+("[^\n]*)',
            lambda match: match[1] + version + match[2],
            source,
            count=1,
        )
        if count != 1 or tomllib.loads(source)["project"]["version"] != version:
            raise ValueError("Cannot update project version")
        path.write_text(source, encoding="utf-8", newline="\n")
    else:
        raise ValueError("Unknown command")


if __name__ == "__main__":
    main()
