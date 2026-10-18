"""Offline tests: python -m unittest discover -s tests -v."""

import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from main import MENU, MyBot  # noqa: E402
from notebook import Store, due_reminders, occurrences  # noqa: E402


def event(starts="2030-01-31T10:00:00", repeat="monthly", timezone="Europe/Moscow"):
    return {
        "title": "Встреча",
        "starts": starts,
        "repeat": repeat,
        "timezone": timezone,
    }


def utc(value):
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


class RecurrenceTests(unittest.TestCase):
    def test_month_end_does_not_drift(self):
        dates = list(occurrences(event(), utc("2030-01-01"), utc("2030-05-01")))
        self.assertEqual([d.day for d in dates], [31, 28, 31, 30])

    def test_leap_day_returns_in_leap_year(self):
        dates = list(
            occurrences(
                event("2028-02-29T12:00:00", "yearly"),
                utc("2028-01-01"),
                utc("2033-01-01"),
            )
        )
        self.assertEqual([d.day for d in dates], [29, 28, 28, 28, 29])

    def test_daily_preserves_local_time_across_dst(self):
        zone = ZoneInfo("Europe/Berlin")
        dates = list(
            occurrences(
                event("2030-03-30T10:00:00", "daily", zone.key),
                utc("2030-03-30"),
                utc("2030-04-02"),
            )
        )
        self.assertEqual([d.astimezone(zone).hour for d in dates], [10, 10, 10])
        self.assertEqual([d.hour for d in dates], [9, 8, 8])

    def test_weekly_and_exclusive_end(self):
        dates = list(
            occurrences(
                event("2030-01-01T10:00:00", "weekly"),
                utc("2030-01-01T07:00:00"),
                utc("2030-01-15T07:00:00"),
            )
        )
        self.assertEqual([d.day for d in dates], [1, 8])

    def test_once_does_not_repeat(self):
        self.assertEqual(
            len(
                list(
                    occurrences(
                        event(repeat="once"), utc("2030-01-01"), utc("2031-01-01")
                    )
                )
            ),
            1,
        )


class CalendarTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "calendar.sqlite3"
        self.store = Store(self.path)
        with patch("main.telebot.TeleBot") as factory:
            self.app = MyBot("test", self.store)
            self.api = factory.return_value

    def message(self, text, uid=1):
        return SimpleNamespace(
            text=text,
            from_user=SimpleNamespace(id=uid),
            chat=SimpleNamespace(id=uid, type="private"),
        )

    def test_creation_and_persistence(self):
        for text in [MENU[0], "Встреча", "31.01.2030 10:00", "Ежемесячно", "За час"]:
            self.app.handle(self.message(text))
        saved = Store(self.path).events(1)
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["repeat"], "monthly")
        self.assertEqual(saved[0]["reminder"], 60)

    def test_invalid_date_and_cancel(self):
        for text in [MENU[0], "Встреча", "31.02.2030 10:00"]:
            self.app.handle(self.message(text))
        self.assertEqual(self.app.drafts[1]["step"], "date")
        self.app.handle(self.message("/cancel"))
        self.assertNotIn(1, self.app.drafts)
        self.assertEqual(self.store.events(1), [])

    def test_ownership_and_delete_confirmation(self):
        eid = self.store.add(1, event(), 60)
        self.assertIsNone(self.store.get(2, eid))
        self.assertFalse(self.store.delete(2, eid))
        self.app.handle(self.message(f"/delete {eid}"))
        self.assertIsNotNone(self.store.get(1, eid))
        call = SimpleNamespace(
            id="call",
            data=f"delete:{eid}",
            from_user=SimpleNamespace(id=1),
            message=self.message(""),
        )
        self.app.callback(call)
        self.assertIsNone(self.store.get(1, eid))

    def test_reminder_not_resent_after_restart(self):
        eid = self.store.add(1, event("2030-01-01T10:00:00", "once"), 60)
        now = utc("2030-01-01T06:00:00")
        self.assertEqual(len(list(due_reminders(self.store, now))), 1)
        self.app.remind_once(now)
        self.api.send_message.assert_called_once()
        self.assertEqual(list(due_reminders(Store(self.path), now)), [])
        self.assertTrue(self.store.delete(1, eid))

    def test_failed_delivery_can_retry(self):
        self.store.add(1, event("2030-01-01T10:00:00", "once"), 60)
        now = utc("2030-01-01T06:00:00")
        self.api.send_message.side_effect = OSError("offline")
        with self.assertLogs("main", level="ERROR"):
            self.app.remind_once(now)
        self.assertEqual(len(list(due_reminders(self.store, now))), 1)
        self.api.send_message.side_effect = None
        self.app.remind_once(now)
        self.assertEqual(list(due_reminders(self.store, now)), [])

    def test_creation_after_reminder_deadline_delivers_immediately(self):
        start = datetime.now(UTC) + timedelta(days=1)
        self.store.add(
            1, event(start.replace(tzinfo=None).isoformat(), "once", "UTC"), 10080
        )
        self.assertEqual(len(list(due_reminders(self.store, datetime.now(UTC)))), 1)

    def test_no_reminder_and_stale_events(self):
        self.store.add(1, event("2030-01-01T10:00:00", "once"), -1)
        self.store.add(1, event("2029-01-01T10:00:00", "once"), 60)
        self.assertEqual(
            list(due_reminders(self.store, utc("2030-01-01T06:00:00"))), []
        )

    def test_timezone_and_user_isolation_in_view(self):
        self.store.set_timezone(1, "Asia/Yekaterinburg")
        self.assertEqual(Store(self.path).timezone(1), "Asia/Yekaterinburg")
        starts = (
            (datetime.now(UTC) + timedelta(days=1)).replace(tzinfo=None).isoformat()
        )
        self.store.add(1, event(starts, "once", "UTC"), -1)
        self.store.add(2, {**event(starts, "once", "UTC"), "title": "Чужая запись"}, -1)
        for period in (1, 2, 3):
            self.app.show_events(1, period)
            self.assertEqual(len(self.app.pages[1][1]), 1)
            self.assertNotIn("Чужая запись", self.app.pages[1][1][0])

    def test_maximum_emoji_title_fits_telegram_limit(self):
        self.app.pages[1] = ("token", ["😀" * 500] * 4, "Europe/Moscow")
        self.app.render_page(1, "token", 0)
        text = self.api.send_message.call_args.args[1]
        self.assertLessEqual(len(text.encode("utf-16-le")) // 2, 4096)


if __name__ == "__main__":
    unittest.main()
