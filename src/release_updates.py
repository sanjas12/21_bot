"""Queue release notes after successful deployment; never contact Telegram here."""

import base64
import sys
from pathlib import Path

from notebook import Store


def release_message(version, notes):
    notes = notes.strip() or "Исправления и улучшения работы бота."
    # Telegram counts UTF-16 units: even emoji fit in one message at this size.
    if len(notes) > 1400:
        notes = notes[:1400] + "\n… Полный список изменений доступен на GitHub."
    return f"🚀 Бот обновлён до {version}\n\nЧто изменилось:\n{notes}"


def main():
    version, encoded = sys.argv[1:3]
    notes = base64.b64decode(encoded, validate=True).decode("utf-8")
    root = Path(__file__).resolve().parent.parent
    Store(root / "data" / "calendar.sqlite3").queue_release(
        version, release_message(version, notes)
    )


if __name__ == "__main__":
    main()
