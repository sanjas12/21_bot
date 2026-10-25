"""Release version decisions and updates without publishing anything."""

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "release_version",
    Path(__file__).resolve().parents[1] / "scripts/release_version.py",
)
assert SPEC is not None and SPEC.loader is not None
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


class ReleaseVersionTests(unittest.TestCase):
    def test_auto_prioritizes_breaking_changes(self):
        for message, expected in (
            ("fix: bug", "1.2.4"),
            ("feat(calendar): today", "1.3.0"),
            ("feat: calendar\n\nBREAKING CHANGE: schema", "2.0.0"),
            ("fix(api)!: remove field", "2.0.0"),
        ):
            with self.subTest(message=message):
                self.assertEqual(
                    release.next_version("1.2.3", "auto", message), expected
                )

    def test_manual_rejects_invalid_or_older_versions(self):
        for version in ("1.2.3", "1.0.0", "v2.0.0", "2.0.0-rc1", "02.0.0"):
            with self.subTest(version=version), self.assertRaises(ValueError):
                release.next_version("1.2.3", version)
        self.assertEqual(release.next_version("1.2.3", "2.0.0"), "2.0.0")

    def test_write_changes_only_project_version(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pyproject.toml"
            source = '[project]\nname = "bot"\nversion = "1.2.3" # keep\n[tool.other]\nversion = "9.0.0"\n'
            path.write_text(source, encoding="utf-8")
            with (
                patch.object(release, "Path", return_value=path),
                patch.object(
                    release.sys, "argv", ["release_version.py", "write", "1.2.4"]
                ),
            ):
                release.main()
            self.assertEqual(
                path.read_text(encoding="utf-8"), source.replace("1.2.3", "1.2.4")
            )
