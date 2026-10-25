"""Check release history generation and the notes used by the bot."""

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from changelog import release_notes  # noqa: E402

SPEC = importlib.util.spec_from_file_location(
    "update_changelog",
    Path(__file__).resolve().parents[1] / "scripts/update_changelog.py",
)
assert SPEC is not None and SPEC.loader is not None
generator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generator)


class ChangelogTests(unittest.TestCase):
    def test_bot_reads_only_the_exact_release(self):
        source = "# История\n\n## 0.0.40 (2030-01-02)\n\nЧужой релиз\n\n## 0.0.4 (2030-01-01)\n\n### Новое\n\n- Сегодня\n"
        self.assertEqual(release_notes(source, "v0.0.4"), "### Новое\n\n- Сегодня")
        with self.assertRaises(ValueError):
            release_notes(source, "0.0.5")

    def test_new_section_preserves_existing_handwritten_history(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "CHANGELOG.md"
            original = (
                "# История\n\nВведение\n\n## 0.0.4 (2030-01-01)\n\n- Ручное описание\n"
            )
            path.write_text(original, encoding="utf-8")
            with patch.object(
                generator,
                "git",
                return_value="feat(calendar): Сегодня\nfix: ошибка\nbump: release 0.0.4",
            ) as git:
                generator.update(path, "0.0.5", "v0.0.4")
            git.assert_called_once_with(
                "log", "--no-merges", "--reverse", "--format=%s", "v0.0.4..HEAD"
            )
            result = path.read_text(encoding="utf-8")
            self.assertIn("- Ручное описание", result)
            notes = release_notes(result, "0.0.5")
            self.assertIn("calendar: Сегодня", notes)
            self.assertIn("### Исправления", notes)
            self.assertNotIn("bump:", notes)
            with self.assertRaises(ValueError):
                generator.update(path, "0.0.5", "v0.0.4")
            self.assertEqual(path.read_text(encoding="utf-8"), result)

    def test_bootstrap_history_covers_each_tag_range(self):
        def fake_git(*args):
            if args[0] == "tag":
                return "v0.0.4\nv0.0.3\nnot-a-release"
            if args[0] == "show":
                return "2030-01-01"
            return "feat: Начало" if args[-1] == "v0.0.3" else "fix: Починка"

        with patch.object(generator, "git", side_effect=fake_git) as git:
            source = generator.historical_sections()
        self.assertIn("Начало", release_notes(source, "0.0.3"))
        self.assertIn("Починка", release_notes(source, "0.0.4"))
        self.assertNotIn("Начало", release_notes(source, "0.0.4"))
        git.assert_any_call(
            "log", "--no-merges", "--reverse", "--format=%s", "v0.0.3..v0.0.4"
        )
