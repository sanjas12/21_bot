"""Generate cumulative release history from local Git commits and tags."""

import re
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from changelog import release_notes  # noqa: E402

HEADER = "# История изменений\n\n"
GROUPS = {
    "feat": "Новые возможности",
    "fix": "Исправления",
    "docs": "Документация",
    "other": "Прочие изменения",
}


def git(*args):
    return subprocess.check_output(["git", *args], encoding="utf-8").strip()


def section(version, previous, target, released):
    span = f"{previous}..{target}" if previous else target
    subjects = git("log", "--no-merges", "--reverse", "--format=%s", span).splitlines()
    groups = {name: [] for name in GROUPS}
    for subject in subjects:
        match = re.match(r"(\w+)(?:\(([^)]+)\))?(!)?:\s*(.*)", subject)
        kind, scope, breaking, text = (
            match.groups() if match else ("other", None, None, subject)
        )
        if kind == "bump":
            continue
        if not text.strip():
            continue
        text = f"{scope}: {text}" if scope else text
        if breaking:
            text = "Несовместимое изменение: " + text
        groups[kind if kind in GROUPS else "other"].append(text)
    body = []
    for kind, title in GROUPS.items():
        if groups[kind]:
            body.append(
                f"### {title}\n\n" + "\n".join(f"- {text}" for text in groups[kind])
            )
    return (
        f"## {version} ({released})\n\n"
        + ("\n\n".join(body) or "- Обновление версии проекта.")
        + "\n\n"
    )


def historical_sections():
    versions = {}
    for tag in git("tag", "--merged", "HEAD").splitlines():
        if re.fullmatch(r"v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", tag):
            versions[tuple(map(int, tag.removeprefix("v").split(".")))] = tag
    sections = []
    previous = ""
    for _, tag in sorted(versions.items()):
        released = git("show", "-s", "--format=%cs", f"{tag}^{{commit}}")
        sections.insert(0, section(tag.removeprefix("v"), previous, tag, released))
        previous = tag
    return "".join(sections)


def update(path, version=None, previous=""):
    source = (
        path.read_text(encoding="utf-8")
        if path.exists()
        else HEADER + historical_sections()
    )
    if version:
        if not re.fullmatch(
            r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", version
        ):
            raise ValueError("Expected MAJOR.MINOR.PATCH")
        try:
            release_notes(source, version)
        except ValueError:
            pass
        else:
            raise ValueError(f"Changelog already contains {version}")
        entry = section(version, previous, "HEAD", date.today().isoformat())
        # Preserve every existing section, including hand-written notes.
        first = re.search(r"(?m)^## ", source)
        position = first.start() if first else len(source)
        source = source[:position].rstrip() + "\n\n" + entry + source[position:]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source.rstrip() + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    update(
        Path("docs/CHANGELOG.md"),
        sys.argv[1] if len(sys.argv) > 1 else None,
        sys.argv[2] if len(sys.argv) > 2 else "",
    )
