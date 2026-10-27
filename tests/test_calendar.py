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

from date_picker import picker  # noqa: E402
from main import MENU, MyBot  # noqa: E402
from notebook import Store, due_reminders, occurrences  # noqa: E402
from release_updates import release_message  # noqa: E402


def event(starts="2030-01-31T10:00:00", repeat="monthly", timezone="Europe/Moscow"):
    return {
        "title": "Встреча",
        "starts": starts,
        "repeat": repeat,
        "timezone": timezone,
        "visibility": "private",
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
        for text in [
            MENU[0],
            "Встреча",
            "31.01.2030 10:00",
            "Ежемесячно",
            "За час",
            "Общее (по умолчанию)",
        ]:
            self.app.handle(self.message(text))
        saved = Store(self.path).events(1)
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["repeat"], "monthly")
        self.assertEqual(saved[0]["reminder"], 60)

    def test_release_notification_persists_and_is_not_repeated(self):
        self.store.ensure_user(1)
        message = release_message("v0.0.4", "Добавлен просмотр на сегодня")
        self.store.queue_release("v0.0.4", message)
        self.app.deliver_release_updates()
        self.api.send_message.assert_called_once_with(1, message)
        self.store = Store(self.path)
        self.app.store = self.store
        self.store.ensure_user(2)
        self.store.queue_release("v0.0.4", message)
        self.app.deliver_release_updates()
        self.assertEqual(self.api.send_message.call_count, 1)
        self.store.queue_release("v0.0.5", "Следующий релиз")
        self.assertEqual(len(self.store.pending_releases()), 2)

    def test_failed_release_delivery_retries_independently(self):
        for uid in (1, 2):
            self.store.ensure_user(uid)
        self.store.queue_release("v0.0.4", "Изменения")
        self.api.send_message.side_effect = [RuntimeError("offline"), None]
        self.app.deliver_release_updates()
        pending = self.store.pending_releases()
        self.assertEqual([row["user_id"] for row in pending], [1])
        self.api.send_message.side_effect = None
        self.app.deliver_release_updates()
        self.assertEqual(self.store.pending_releases(), [])

    def test_blocked_user_does_not_retry_release_forever(self):
        self.store.ensure_user(1)
        self.store.queue_release("v0.0.4", "Изменения")
        error = RuntimeError("blocked")
        error.error_code = 403
        self.api.send_message.side_effect = error
        self.app.deliver_release_updates()
        self.assertEqual(self.store.pending_releases(), [])

    def test_release_snapshot_without_users_does_not_notify_new_users(self):
        self.store.queue_release("v0.0.4", "Изменения")
        self.store.ensure_user(1)
        self.store.queue_release("v0.0.4", "Изменения")
        self.assertEqual(self.store.pending_releases(), [])

    def test_release_message_is_plain_text_and_fits_telegram_limit(self):
        message = release_message("v0.0.4", "😀" * 5000)
        self.assertLess(len(message.encode("utf-16-le")) // 2, 4096)
        self.assertIn("Полный список", message)
        self.assertIn("Исправления", release_message("v0.0.4", ""))

    def test_changelog_command_sends_complete_history(self):
        root = Path(self.temp.name)
        (root / "docs").mkdir()
        content = "# История\n\n## 0.0.4\n\n- Новое\n\n## 0.0.3\n\n- Старое\n"
        (root / "docs" / "CHANGELOG.md").write_text(
            content, encoding="utf-8", newline="\n"
        )
        received = []
        self.api.send_document.side_effect = lambda uid, history, **kw: received.append(
            (uid, history.read())
        )
        with patch("main.ROOT", root):
            self.app.handle(self.message("/changelog"))
        self.assertEqual(received, [(1, content.encode("utf-8"))])

    def test_edit_all_fields_and_confirm(self):
        eid = self.store.add(1, event(), 60)
        self.app.handle(self.message(f"/edit {eid}"))
        for text in ("Текст", "Изменённый текст", "Дата и время"):
            self.app.handle(self.message(text))
        self.click_date("day", "2030-03-10")
        self.click_date("hour", "16")
        self.click_date("minute", "25")
        self.assertEqual(self.app.drafts[1]["step"], "edit_fields")
        for text in ("Повтор", "Еженедельно", "Напоминание", "За день"):
            self.app.handle(self.message(text))
        self.assertEqual(self.store.get(1, eid)["title"], "Встреча")
        self.app.handle(self.message("Сохранить изменения"))
        row = Store(self.path).get(1, eid)
        self.assertEqual(row["title"], "Изменённый текст")
        self.assertEqual(row["starts"], "2030-03-10T16:25:00")
        self.assertEqual(row["repeat"], "weekly")
        self.assertEqual(row["reminder"], 1440)

    def test_edit_cancel_preserves_original_and_foreign_event_is_denied(self):
        eid = self.store.add(1, event(), 60)
        original = dict(self.store.get(1, eid))
        for text in (f"/edit {eid}", "Текст", "Не сохранять", "/cancel"):
            self.app.handle(self.message(text))
        self.assertEqual(dict(self.store.get(1, eid)), original)
        self.app.handle(self.message(f"/edit {eid}", uid=2))
        self.assertNotIn(2, self.app.drafts)

    def test_edit_title_does_not_resend_delivered_reminder(self):
        eid = self.store.add(1, event("2030-01-01T10:00:00", "once"), 60)
        now = utc("2030-01-01T06:00:00")
        self.app.remind_once(now)
        for text in (f"/edit {eid}", "Текст", "Новое название", "Сохранить изменения"):
            self.app.handle(self.message(text))
        self.assertEqual(list(due_reminders(self.store, now)), [])

    def test_edit_reschedules_reminder(self):
        eid = self.store.add(1, event("2030-01-01T10:00:00", "once"), 60)
        self.app.remind_once(utc("2030-01-01T06:00:00"))
        for text in (
            f"/edit {eid}",
            "Дата и время",
            "01.01.2030 12:00",
            "Сохранить изменения",
        ):
            self.app.handle(self.message(text))
        self.assertEqual(
            list(due_reminders(self.store, utc("2030-01-01T06:00:00"))), []
        )
        due = list(due_reminders(self.store, utc("2030-01-01T08:00:00")))
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0][1], utc("2030-01-01T09:00:00"))

    def test_edit_cannot_restore_deleted_event(self):
        eid = self.store.add(1, event(), 60)
        self.app.handle(self.message(f"/edit {eid}"))
        self.store.delete(1, eid)
        self.app.handle(self.message("Сохранить изменения"))
        self.assertIsNone(self.store.get(1, eid))
        self.assertNotIn(1, self.app.drafts)

    def test_stale_edit_does_not_overwrite_newer_change(self):
        eid = self.store.add(1, event(), 60)
        self.app.handle(self.message(f"/edit {eid}"))
        current = dict(self.store.get(1, eid))
        self.assertTrue(
            self.store.update(
                1, eid, {**current, "title": "Другая правка", "original": current}
            )
        )
        self.app.handle(self.message("Сохранить изменения"))
        self.assertEqual(self.store.get(1, eid)["title"], "Другая правка")

    def click_date(self, action, value="", uid=1, token=None):
        token = token or self.app.drafts[uid]["picker_token"]
        message = self.message("", uid)
        message.message_id = 42
        self.app.callback(
            SimpleNamespace(
                id="callback",
                message=message,
                from_user=message.from_user,
                data=f"date:{token}:{action}:{value}",
            )
        )

    def test_interactive_date_full_flow(self):
        for text in (MENU[0], "Событие из календаря"):
            self.app.handle(self.message(text))
        self.click_date("month", "2030-02-01")
        self.click_date("day", "2030-02-28")
        self.click_date("hour", "14")
        self.click_date("minute", "35")
        self.assertEqual(self.app.drafts[1]["step"], "repeat")
        self.app.handle(self.message("Однократно"))
        self.app.handle(self.message("За час"))
        self.app.handle(self.message("Общее (по умолчанию)"))
        self.assertEqual(self.store.events(1)[0]["starts"], "2030-02-28T14:35:00")

    def test_old_calendar_cannot_change_new_draft(self):
        for text in (MENU[0], "Первое"):
            self.app.handle(self.message(text))
        old_token = self.app.drafts[1]["picker_token"]
        for text in ("/cancel", MENU[0], "Второе"):
            self.app.handle(self.message(text))
        self.click_date("day", "2030-02-28", token=old_token)
        self.assertEqual(self.app.drafts[1]["picker_stage"], "day")
        self.assertNotIn("day", self.app.drafts[1])

    def test_calendar_back_and_cancel(self):
        for text in (MENU[0], "Отменить"):
            self.app.handle(self.message(text))
        self.click_date("day", "2030-02-28")
        self.click_date("hour", "10")
        self.click_date("back", "hour")
        self.assertEqual(self.app.drafts[1]["picker_stage"], "hour")
        self.click_date("back", "day")
        self.click_date("cancel")
        self.assertNotIn(1, self.app.drafts)
        self.assertEqual(self.store.events(1), [])

    def test_calendar_leap_year_and_past_days(self):
        today = utc("2028-02-15").date()
        _, markup = picker("day", "token", today)
        values = [button.callback_data for row in markup.keyboard for button in row]
        self.assertIn("date:token:day:2028-02-29", values)
        self.assertNotIn("date:token:day:2028-02-14", values)
        self.assertTrue(all(len(value.encode()) <= 64 for value in values))

    def test_invalid_date_and_cancel(self):
        for text in [MENU[0], "Встреча", "31.02.2030 10:00"]:
            self.app.handle(self.message(text))
        self.assertEqual(self.app.drafts[1]["step"], "date")
        self.app.handle(self.message("/cancel"))
        self.assertNotIn(1, self.app.drafts)
        self.assertEqual(self.store.events(1), [])

    def test_creation_defaults_to_public_and_private_can_be_selected(self):
        for text in (MENU[0], "Общее", "31.01.2030 10:00", "Однократно", "За час"):
            self.app.handle(self.message(text))
        self.assertEqual(self.app.drafts[1]["visibility"], "public")
        self.assertEqual(self.app.drafts[1]["step"], "visibility")
        self.app.handle(self.message("Общее (по умолчанию)"))
        public = self.store.events(1)[0]
        self.assertEqual(public["visibility"], "public")
        for text in (
            MENU[0],
            "Личная запись",
            "31.01.2030 10:00",
            "Однократно",
            "За час",
            "Личное",
        ):
            self.app.handle(self.message(text))
        self.assertEqual(len(self.store.events(1)), 2)
        self.assertEqual(
            [row["id"] for row in self.store.visible_events(2)], [public["id"]]
        )

    def test_shared_visibility_does_not_grant_edit_or_delete(self):
        eid = self.store.add(1, {**event(), "visibility": "public"}, 60)
        self.assertEqual(self.store.visible_events(2)[0]["id"], eid)
        self.assertIsNone(self.store.get(2, eid))
        self.assertFalse(self.store.delete(2, eid))
        self.app.begin_edit(2, eid)
        self.assertNotIn(2, self.app.drafts)

    def test_shared_reminders_track_each_recipient(self):
        self.store.ensure_user(2)
        eid = self.store.add(
            1, {**event("2030-01-01T10:00:00", "once"), "visibility": "public"}, 60
        )
        now = utc("2030-01-01T06:00:00")
        self.app.remind_once(now)
        self.assertEqual(
            {call.args[0] for call in self.api.send_message.call_args_list}, {1, 2}
        )
        self.assertTrue(self.store.sent(eid, utc("2030-01-01T07:00:00"), 2))
        self.api.send_message.reset_mock()
        self.app.remind_once(now)
        self.api.send_message.assert_not_called()

    def test_failed_shared_delivery_does_not_block_other_users(self):
        self.store.ensure_user(2)
        self.store.add(
            1, {**event("2030-01-01T10:00:00", "once"), "visibility": "public"}, 60
        )
        now = utc("2030-01-01T06:00:00")
        self.api.send_message.side_effect = lambda uid, *a, **kw: (
            (_ for _ in ()).throw(OSError()) if uid == 1 else None
        )
        with self.assertLogs("main", level="ERROR"):
            self.app.remind_once(now)
        self.api.send_message.reset_mock()
        self.api.send_message.side_effect = None
        self.app.remind_once(now)
        self.assertEqual(
            [call.args[0] for call in self.api.send_message.call_args_list], [1]
        )

    def test_changing_shared_event_to_private(self):
        eid = self.store.add(1, {**event(), "visibility": "public"}, 60)
        for text in (f"/edit {eid}", "Доступ", "Личное", "Сохранить изменения"):
            self.app.handle(self.message(text))
        self.assertEqual(self.store.visible_events(2), [])
        self.assertEqual(self.store.recipients(self.store.get(1, eid)), [1])

    def test_legacy_events_remain_private_and_delivery_is_preserved(self):
        eid = self.store.add(1, event(), 60)
        start = utc("2030-01-31T07:00:00")
        with self.store.connect() as db:
            db.execute("ALTER TABLE events DROP COLUMN visibility")
            db.execute("INSERT INTO reminders VALUES (?,?)", (eid, start.isoformat()))
        reopened = Store(self.path)
        self.assertEqual(reopened.get(1, eid)["visibility"], "private")
        self.assertEqual(reopened.visible_events(2), [])
        self.assertTrue(reopened.sent(eid, start, 1))

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

    def test_today_uses_full_local_day_and_visibility(self):
        self.store.set_timezone(1, "Asia/Yekaterinburg")
        for title, starts in (
            ("Вчера", "2030-01-01T18:59:59"),
            ("Полночь", "2030-01-01T19:00:00"),
            ("Вечер", "2030-01-02T18:59:59"),
            ("Завтра", "2030-01-02T19:00:00"),
        ):
            self.store.add(1, {**event(starts, "once", "UTC"), "title": title}, -1)
        for title, visibility in (("Общее", "public"), ("Чужое", "private")):
            self.store.add(
                2,
                {
                    **event("2030-01-01T20:00:00", "daily", "UTC"),
                    "title": title,
                    "visibility": visibility,
                },
                -1,
            )
        with patch("main.datetime") as clock:
            clock.now.return_value = utc("2030-01-01T23:00:00")
            self.app.handle(self.message("📋 Сегодня"))
        rows = self.app.pages[1][1]
        self.assertEqual(len(rows), 3)
        self.assertIn("Полночь", rows[0])
        self.assertIn("Общее", rows[1])
        self.assertIn("Вечер", rows[2])

    def test_today_can_be_empty(self):
        self.app.handle(self.message("📋 Сегодня"))
        self.assertEqual(self.app.pages[1][1], [])
        self.assertIn("Событий пока нет.", self.api.send_message.call_args.args[1])

    def test_tomorrow_uses_local_day_across_new_year_and_visibility(self):
        self.store.set_timezone(1, "Asia/Yekaterinburg")
        for title, starts in (
            ("Сегодня", "2030-12-31T18:59:59"),
            ("Полночь", "2030-12-31T19:00:00"),
            ("Вечер", "2031-01-01T18:59:59"),
            ("Послезавтра", "2031-01-01T19:00:00"),
        ):
            self.store.add(1, {**event(starts, "once", "UTC"), "title": title}, -1)
        for title, visibility in (("Общее", "public"), ("Чужое", "private")):
            self.store.add(
                2,
                {
                    **event("2030-12-30T20:00:00", "daily", "UTC"),
                    "title": title,
                    "visibility": visibility,
                },
                -1,
            )
        with patch("main.datetime") as clock:
            clock.now.return_value = utc("2030-12-31T18:00:00")
            self.app.handle(self.message("📌 Завтра"))
        rows = self.app.pages[1][1]
        self.assertEqual(len(rows), 3)
        self.assertIn("01.01.2031 00:00 — Полночь", rows[0])
        self.assertIn("Общее", rows[1])
        self.assertIn("Вечер", rows[2])

    def test_tomorrow_dst_day_ends_at_local_midnight(self):
        self.store.set_timezone(1, "Europe/Berlin")
        for starts in (
            "2030-03-30T22:59:59",
            "2030-03-30T23:00:00",
            "2030-03-31T21:59:59",
            "2030-03-31T22:00:00",
        ):
            self.store.add(1, event(starts, "once", "UTC"), -1)
        with patch("main.datetime") as clock:
            clock.now.return_value = utc("2030-03-30T12:00:00")
            self.app.handle(self.message("📌 Завтра"))
        rows = self.app.pages[1][1]
        self.assertEqual(len(rows), 2)
        self.assertIn("31.03.2030 00:00", rows[0])
        self.assertIn("31.03.2030 23:59", rows[1])

    def test_tomorrow_can_be_empty(self):
        self.app.handle(self.message("📌 Завтра"))
        self.assertEqual(self.app.pages[1][1], [])
        self.assertIn("Событий пока нет.", self.api.send_message.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
