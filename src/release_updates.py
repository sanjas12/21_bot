"""Queue release notes after successful deployment; never contact Telegram here."""

import sys
from pathlib import Path

from changelog import release_notes
from notebook import Store


def release_message(version, notes):
    notes = notes.strip() or "Исправления и улучшения работы бота."
    # Telegram counts UTF-16 units: even emoji fit in one message at this size.
    if len(notes) > 1400:
        notes = notes[:1400] + "\n… Полный список изменений доступен на GitHub."
    return f"🚀 Бот обновлён до {version}\n\nЧто изменилось:\n{notes}"


def main():
    version = sys.argv[1]
    root = Path(__file__).resolve().parent.parent
    notes = release_notes(
        (root / "docs" / "CHANGELOG.md").read_text(encoding="utf-8"), version
    )
    Store(root / "data" / "calendar.sqlite3").queue_release(
        version, release_message(version, notes)
    )


if __name__ == "__main__":
    main()
